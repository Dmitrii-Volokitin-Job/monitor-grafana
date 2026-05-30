---
name: monitoring:new-dashboard
description: Create a new Grafana dashboard JSON definition
branch: Develop (default if no branch-specific skill exists)
---

# Create Grafana Dashboard

## When to Use
When adding a new monitoring dashboard.

## Steps
1. Create JSON file in `dashboards/<dashboard-name>.json`
2. Define panels with Prometheus queries
3. Add variables for dynamic filtering

## Panel Pattern
```json
{
  "panels": [
    {
      "title": "Request Rate",
      "type": "graph",
      "targets": [
        {
          "expr": "rate(http_requests_total{service=\"app-api\"}[5m])",
          "legendFormat": "{{method}} {{path}}"
        }
      ]
    }
  ]
}
```

## Conventions
- Use Prometheus as datasource
- Add template variables for environment/service filtering
- Export from Grafana UI and save as provisioned dashboard
