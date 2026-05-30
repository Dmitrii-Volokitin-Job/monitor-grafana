# Contributing

Thanks for your interest in contributing! This project follows standard GitHub
flow — fork, branch, PR.

## Ground rules

- **Be kind.** See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- **Open an issue first** for non-trivial changes so we can align on direction
  before you spend time on the PR.
- **Small, focused PRs** merge faster than big ones. Split a feature + refactor
  + style cleanup into separate PRs.
- **No regressions in tests or dashboards.** Run the test suites locally
  before pushing (see below). CI runs the same suites on every PR.

## Dev environment

```bash
git clone https://github.com/your-org/monitor-grafana.git
cd monitor-grafana
cp .env.example .env

# Bring up the local stack
docker compose up -d
# Wait ~30 s; check it works:
curl -fs http://localhost:9119/sd/healthz
curl -fs http://localhost:3000/api/health
```

The admin UI lives at `http://localhost:9119/admin/` — log into Grafana at
`http://localhost:3000` first (`admin/admin`), then the cookie carries you in.

## Running tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r monitor_exporter/requirements.txt -r requirements-test.txt

pytest tests/unit              # ~1 s, mocks DB + Grafana — run this on every change
pytest tests/dashboards        # ~1 s, validates dashboards/*.json against PromQL + schema
pytest tests/live --live       # ~20 s, requires `docker compose up`
```

Add a unit test for every bug you fix and every feature you add — a regression
shouldn't be able to come back unnoticed.

## Code style

- **Python**: PEP 8, type hints on public functions. We don't enforce a
  specific formatter; just match the surrounding style.
- **Jinja templates**: 2-space indent, Bootstrap 5 classes, htmx where it
  improves UX without bloat.
- **SQL migrations**: idempotent (`IF NOT EXISTS`, `INSERT IGNORE`,
  `ON DUPLICATE KEY UPDATE`). Numbered `0N-name.sql` under `docker/init-db/`.
  Files run in alphabetic order — pick a number that satisfies your deps.
- **Comments**: explain *why*, not *what*. The code shows what.

## What needs help

Good first issues are labelled `good-first-issue` in GitHub. Areas where
contributions are especially welcome:

- More **dashboard variations** (per-team, per-service-type, per-region).
- **Additional version-detection strategies** for common application
  frameworks (e.g. Quarkus, FastAPI, Django).
- **Better cloud starters** under `deployments/aws/` and `deployments/gcp/`.
- **Translations** of the admin UI templates.
- **Alert rules** for additional probe types.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) if you can:

```
feat(admin-ui): add bulk-enable button for systems
fix(sd-endpoints): handle NULL system_group without 500
docs(runbook): clarify exporter-down failure mode
```

The first line should fit in 72 characters. Reference the issue in the body:
`Closes #123`.

## Submitting a PR

1. Fork the repo and create a feature branch (`git checkout -b feat/my-thing`).
2. Make your changes; keep commits logical.
3. Run the test suites listed above; fix any failures.
4. Push your branch and open a PR against `main`.
5. CI runs the test suites + dashboard validators. A maintainer will review
   within a few days.

## Reporting security issues

**Don't** open a public issue for security bugs. See
[docs/SECURITY.md](docs/SECURITY.md) for the disclosure process.
