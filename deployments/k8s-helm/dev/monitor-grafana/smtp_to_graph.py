"""
smtp_to_graph — accepts SMTP on the pod's loopback, forwards each message
to the Microsoft Graph API. Lets Grafana (which only speaks SMTP) deliver
mail through a tenant that has SMTP AUTH disabled.

Reads three env vars for the OAuth2 client-credentials flow:
  TENANT_ID, CLIENT_ID, CLIENT_SECRET (from the grafana-graph-secret Secret)

Reads two env vars for behaviour:
  FROM_ADDRESS    sender mailbox (the Application Access Policy must allow it)
  LISTEN_PORT     SMTP listen port (default 2525, loopback only)

Health/metrics: HTTP server on :8080 (/healthz, /metrics).
"""
from __future__ import annotations

import asyncio
import email
import logging
import os
import sys
import time
from email.message import Message
from typing import Iterable

import httpx
import msal
from aiosmtpd.controller import Controller
from prometheus_client import Counter, Histogram, start_http_server

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
AUTHORITY_TMPL = "https://login.microsoftonline.com/{tenant}"

log = logging.getLogger("smtp_to_graph")

# Prometheus metrics — query patterns documented in the helm chart README.
SENT = Counter(
    "smtp_to_graph_messages_total",
    "Messages submitted to Graph, by outcome",
    ["result"],
)
SEND_LATENCY = Histogram(
    "smtp_to_graph_send_duration_seconds",
    "Time spent sending one message via Graph",
)
TOKEN_REFRESH = Counter(
    "smtp_to_graph_token_refreshes_total",
    "Number of times MSAL acquired a fresh access token",
)


def _required(var: str) -> str:
    val = os.environ.get(var, "").strip()
    if not val:
        log.error("missing required env var %s", var)
        sys.exit(1)
    return val


def _addresses(msg: Message, header: str) -> list[str]:
    raw = msg.get_all(header, [])
    return [
        addr.strip()
        for entry in raw
        for addr in entry.replace(",", ";").split(";")
        if addr.strip()
    ]


class GraphSender:
    """Thin wrapper around MSAL + Graph. Single instance, shared by handler.

    MSAL's ConfidentialClientApplication eagerly performs OIDC tenant
    discovery in its constructor, which means a bad tenant/network/creds
    state at pod-start crashes the sidecar before the SMTP listener and
    health endpoint are up. Lazy-init the MSAL app on first send so the
    sidecar stays observable (healthz/metrics) even when Microsoft is
    temporarily unreachable or creds are wrong — operators can then
    diagnose via /metrics and logs instead of CrashLoopBackOff.
    """

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, from_address: str):
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._from_address = from_address
        self._app: msal.ConfidentialClientApplication | None = None

    def _msal_app(self) -> msal.ConfidentialClientApplication:
        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                client_id=self._client_id,
                client_credential=self._client_secret,
                authority=AUTHORITY_TMPL.format(tenant=self._tenant_id),
            )
        return self._app

    def _access_token(self) -> str:
        # MSAL maintains its own in-memory cache; we trust it and just call
        # acquire_token_for_client every time. If the cache has a fresh token
        # it returns it without a network call. token_source tells us whether
        # we actually hit the IdP.
        result = self._msal_app().acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise RuntimeError(
                f"MSAL token acquisition failed: {result.get('error')}: "
                f"{result.get('error_description')}"
            )
        if result.get("token_source") == "identity_provider":
            TOKEN_REFRESH.inc()
            log.info("acquired fresh access token (expires in %ss)", result.get("expires_in"))
        return result["access_token"]

    def send(self, raw_message: bytes, envelope_recipients: Iterable[str]) -> None:
        # Parse the SMTP DATA payload into a typed Message so we can extract
        # subject, content-type, and recipients (with the SMTP envelope
        # taking precedence for routing).
        msg = email.message_from_bytes(raw_message)
        subject = msg.get("Subject", "(no subject)")
        # Prefer the SMTP envelope for routing — that's what Grafana actually
        # asked us to deliver to. Fall back to header parsing only if empty.
        to_addrs = list(envelope_recipients) or _addresses(msg, "To")
        cc_addrs = _addresses(msg, "Cc")

        body_html, body_text = _extract_body(msg)
        body_kind = "HTML" if body_html else "Text"
        body_content = body_html or body_text or ""

        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_kind, "content": body_content},
                "toRecipients": [{"emailAddress": {"address": a}} for a in to_addrs],
            },
            "saveToSentItems": False,
        }
        if cc_addrs:
            payload["message"]["ccRecipients"] = [
                {"emailAddress": {"address": a}} for a in cc_addrs
            ]

        url = f"{GRAPH_BASE}/users/{self._from_address}/sendMail"
        # Wrap token + HTTP call in one try/except so any failure mode (MSAL
        # token error, network blip, Graph 4xx/5xx) increments the failure
        # metric exactly once. Success branch handles the increment in line;
        # any exception path lands in the except below.
        try:
            token = self._access_token()
            with SEND_LATENCY.time():
                r = httpx.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    timeout=30.0,
                )
            if r.status_code != 202:
                log.error(
                    "Graph rejected message: HTTP %s — %s", r.status_code, r.text[:500]
                )
                r.raise_for_status()
            SENT.labels(result="success").inc()
            log.info("delivered to %s subject=%r", to_addrs, subject)
        except Exception:
            SENT.labels(result="failure").inc()
            raise


def _extract_body(msg: Message) -> tuple[str, str]:
    """Return (html, text) — either may be empty."""
    html, text = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            if ctype == "text/html" and not html:
                html = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
            elif ctype == "text/plain" and not text:
                text = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
    else:
        body = msg.get_payload(decode=True) or b""
        body_str = body.decode(msg.get_content_charset() or "utf-8", errors="replace")
        if msg.get_content_type() == "text/html":
            html = body_str
        else:
            text = body_str
    return html, text


class GraphSMTPHandler:
    def __init__(self, sender: GraphSender):
        self._sender = sender

    async def handle_DATA(self, server, session, envelope):
        # aiosmtpd contract: return 250 on success, 5xx on permanent failure.
        try:
            self._sender.send(envelope.content, envelope.rcpt_tos)
        except Exception:
            log.exception("send failed")
            return "550 Could not forward to Graph"
        return "250 Message queued for Graph delivery"


def _start_health_server(port: int) -> None:
    # prometheus_client.start_http_server gives us /metrics for free; we just
    # need to also serve a tiny /healthz on the same port.
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler signature)
            if self.path == "/healthz":
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"ok\n")
            elif self.path == "/metrics":
                payload = generate_latest()
                self.send_response(200)
                self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt, *args):  # silence default access log
            return

    srv = HTTPServer(("0.0.0.0", port), Handler)
    Thread(target=srv.serve_forever, name="health-http", daemon=True).start()
    log.info("health/metrics server listening on 0.0.0.0:%d", port)


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    tenant_id = _required("TENANT_ID")
    client_id = _required("CLIENT_ID")
    client_secret = _required("CLIENT_SECRET")
    from_address = _required("FROM_ADDRESS")
    listen_port = int(os.environ.get("LISTEN_PORT", "2525"))
    health_port = int(os.environ.get("HEALTH_PORT", "8080"))

    sender = GraphSender(tenant_id, client_id, client_secret, from_address)
    handler = GraphSMTPHandler(sender)

    _start_health_server(health_port)

    # Bind to loopback only — sidecar is reachable only from inside the pod,
    # never via Service. The pod-network namespace is shared between Grafana
    # and the sidecar, so 127.0.0.1 is enough.
    controller = Controller(handler, hostname="127.0.0.1", port=listen_port)
    controller.start()
    log.info("SMTP listener started on 127.0.0.1:%d (from=%s)", listen_port, from_address)

    # aiosmtpd's Controller runs its own thread; the main thread parks here.
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        log.info("shutting down")
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
