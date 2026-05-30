---
name: monitoring:add-alert-rule
description: Add a Prometheus/Alertmanager alerting rule
branch: Develop (default if no branch-specific skill exists)
---

# Add Alert Rule

## When to Use
When defining a new alerting condition.

## Pattern
In `alerting/` rules file:
```yaml
groups:
  - name: monitor-alerts
    rules:
      - alert: <AlertName>
        expr: <prometheus_expression>
        for: 5m
        labels:
          severity: warning  # or critical
          team: monitor
        annotations:
          summary: "Brief description"
          description: "{{ $labels.instance }} - detailed info with {{ $value }}"
```

## Common Expressions
```yaml
# Service down
expr: up{job="app-api"} == 0

# High error rate
expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1

# High latency
expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 2

# Certificate expiring
expr: monitor_cert_expiry_days < 30
```

## Severity Levels
- `critical` — Immediate attention, pages on-call
- `warning` — Should be investigated soon
- `info` — Informational, no action needed
