# Security policy

## Reporting a vulnerability

If you find a security issue, please **do not** open a public GitHub issue.
Instead, email the maintainers privately and we will coordinate a fix.

Include enough detail for us to reproduce:

- A short summary of the issue
- The affected version / commit hash
- Steps to reproduce
- Impact assessment (what an attacker could do)

We aim to acknowledge within 72 hours and to ship a fix within 14 days for
high-severity issues. We will credit you in the release notes unless you ask
us not to.

## Supported versions

Only the latest release on the `main` branch receives security fixes. If you
are running an older tag, please upgrade before reporting issues.

## How this project handles secrets

  tokens, admin UI signing keys, and SMTP credentials are all read from
  environment variables at runtime. The committed `.env.example` shows the
  variable names; `.env` itself is gitignored.
- **Helm values files contain only placeholders.** Real values are injected
  via the K8s Secret objects (`monitor-tokens`, `monitor-db-secrets`,
  `grafana-secret`) or passed at install time with `--set`.
- **Admin UI auth piggy-backs on Grafana.** There is no separate password
  store for the admin UI — every request validates the inbound
  `grafana_session` cookie against Grafana's `/api/user`.
- **Datasource passwords** never live in the `datasource` table itself. The
  table stores the *name* of the env var Grafana should read; the actual value
  is supplied to the Grafana container at runtime.

## Pre-publish checklist (for first-time contributors fork-and-publishing)

If you are forking this repo and publishing your own copy, scan for leaked
secrets before pushing:

```bash
# 1. Look for plaintext passwords / tokens in tracked files
git grep -InE 'password\s*[:=]\s*["'\'']?[A-Za-z0-9!@#$%^&*_-]{8,}'  \
        -- '*.yml' '*.yaml' '*.env*' '*.sql'

# 2. Common token prefixes
git grep -InE 'glpat[_-]|glptt[_-]|sq[upap]_|AKIA[0-9A-Z]{16}|gh[pousr]_'

# 3. Internal hostnames / private IPs you forgot to scrub
git grep -InE 'corp|internal|\b10\.|\b172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.'

# 4. If history contains secrets, rewrite it before publishing:
#    https://github.com/newren/git-filter-repo
```

A single committed credential — even one removed in the next commit — is
permanently in the git history. Use `git filter-repo` or BFG to scrub it
before any push to a public remote.

## Threat model

This project is a monitoring stack — it reads metrics, it does not run user
workloads. The threat surface is therefore narrow:

| Surface | What an attacker could do | Mitigation |
|---|---|---|
| Admin UI (`:9119/admin/*`) | Add malicious monitored targets, change probe URLs to exfiltrate via SSRF | Grafana session auth (Editor role); UI is intended for internal-only exposure |
| HTTP-SD endpoints (`:9119/sd/*`) | Discover internal hosts via the target list | Bind to internal network; no auth by design (Prometheus needs to poll it) |
| Exporter `/metrics` (`:9116`) | Read all probe results | Internal network only |
| Grafana | Standard Grafana threat model | Follow [Grafana hardening guide](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/) |
| Postgres | Read/write the catalog | Standard DB hardening |

If you expose any of these to the public internet, you are operating outside
this project's intended threat model — put a reverse proxy with strong auth
in front of everything.
