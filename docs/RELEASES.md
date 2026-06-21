# Release process

How to cut a new release of monitor-grafana. Single source of truth — keep
this in sync with whatever the chart, README, and CI expect.

## Versioning

Semantic Versioning (`MAJOR.MINOR.PATCH`):

| Bump | When |
|---|---|
| `PATCH` (0.0.X) | Bug fixes; doc-only changes that don't alter behaviour. |
| `MINOR` (0.X.0) | Backwards-compatible additions (new system_type, new probe, new dashboard). |
| `MAJOR` (X.0.0) | Breaking changes — schema migrations, removed env vars, renamed probe metrics, removed dashboards. |

Pre-1.0.0: minor and patch may both ship breaking changes; once at 1.0.0 the
contract above is binding.

## Files that carry the version

Bump all four in lockstep:

| File | Field |
|---|---|
| `VERSION` | the raw version string (single line) |
| `deployments/k8s-helm/dev/monitor-grafana/Chart.yaml` | `version:` and `appVersion:` |
| `CHANGELOG.md` | new `## [X.Y.Z] - YYYY-MM-DD` section under `## [Unreleased]` |

## Cutting a release — step by step

```bash
# 0. Tree must be clean and tests green
git status
pytest tests/unit tests/dashboards tests/config tests/db/test_schema.py -q   # expect 302/302+

# 1. Bump the four files above
NEW=0.1.0
TODAY=$(date +%Y-%m-%d)
echo "$NEW" > VERSION
sed -i.bak -E "s/^version: .*/version: $NEW/; s/^appVersion: .*/appVersion: \"$NEW\"/" \
  deployments/k8s-helm/dev/monitor-grafana/Chart.yaml
rm deployments/k8s-helm/dev/monitor-grafana/Chart.yaml.bak

# 2. Roll the CHANGELOG: convert [Unreleased] into [$NEW] - $TODAY
#    (manual edit — keep an empty [Unreleased] header above)

# 3. Commit + push
git add -A
git commit -m "release: v$NEW"
git push origin main develop

# 4. Tag + push the tag
git tag -a "v$NEW" -m "Release v$NEW"
git push origin "v$NEW"

# 5. Create the GitHub Release. Body = the CHANGELOG section for this version.
gh release create "v$NEW" \
  --title "v$NEW" \
  --notes-file <(awk "/^## \\[$NEW\\]/,/^## \\[/{ if(/^## \\[/ && !/^## \\[$NEW\\]/) exit; print }" CHANGELOG.md)

# 6. Smoke-check the release page
gh release view "v$NEW"
```

## What goes in the CHANGELOG entry

Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — group items
under: `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`.

Mention the **why**, not just the **what**. Example:

```markdown
### Fixed
- SSL `monitor:ssl_days_until_expiry` recording rule now sources from both
  `probe_ssl_earliest_cert_expiry` (blackbox) and `ssl_cert_not_after`
  (ssl_exporter) instead of just the first — previously the
  `ssl_certificates` job's certs never appeared in the rule output.
```

## Hotfix releases

For an urgent fix off an already-published tag:

```bash
git checkout -b hotfix/X.Y.Z v<previous>
# … fix …
# bump VERSION to next PATCH, CHANGELOG entry, commit, tag v0.0.(X+1)
git push origin hotfix/X.Y.Z v0.0.X
gh release create v0.0.X --title "v0.0.X" --notes-file <(awk …) --target hotfix/X.Y.Z
```

Then merge the hotfix back into `main` / `develop` so future releases inherit it.

## What NOT to release

- Working-tree edits that aren't committed.
- Releases without a CHANGELOG entry — GitHub Release body would be empty.
- Releases that don't pass `pytest tests/unit tests/dashboards tests/config tests/db/test_schema.py`.
- Releases that touched the SQL seed without mirroring into
  `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-db-init.yaml`.
  (The `test_helm_chart_schema_matches_canonical_columns` test catches
  schema drift; seed-content drift between the two copies is currently a
  manual check.)

## Pre-release / RC tags

For release candidates use the `vX.Y.Z-rc.N` suffix and pass `--prerelease`
to `gh release create`. RCs are not auto-published to chart repositories.

## Release history (this file as a quick index)

| Version | Date | Notes |
|---|---|---|
| **0.0.1** | 2026-05-31 | First OSS release. Postgres backend, admin UI, HTTP-SD, real-data demo seed, two intentional SSL negatives (badssl.com), bundled demo target containers via `COMPOSE_PROFILES=full` / `demoTargets.enabled`, full live test suite. |

See `CHANGELOG.md` for the per-version detail.
