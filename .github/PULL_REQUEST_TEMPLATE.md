<!-- Thanks for opening a PR! -->

## What changed

<!-- One sentence summary. -->

## Why

<!-- The user-facing problem this solves, or the issue this closes. -->

Closes #

## How it was tested

<!-- pytest output, screenshots of dashboards, curl against /sd, etc. -->

```
pytest tests/unit tests/dashboards
```

## Checklist

- [ ] Tests added or updated (unit + dashboard validators where applicable)
- [ ] Docs updated (README / runbook / CLAUDE.md / CHANGELOG.md)
- [ ] No new committed secrets (run `git grep -InE 'password|token|key'`)
- [ ] Helm chart mirrored — if you changed Python or templates, they're also
      copied into `deployments/k8s-helm/dev/monitor-grafana/`
- [ ] If you added a new probe type / system_type:
  - [ ] form partial under `monitor_exporter/templates/`
  - [ ] entry in `REQUIRED_FIELDS` (admin_ui.py)
  - [ ] entry in `_load_db_targets` (exporter.py) if it has a custom check
  - [ ] mapper in `sd_endpoints.py` if it goes through Blackbox
  - [ ] seed row in `docker/init-db/07-seed-systems.sql`
