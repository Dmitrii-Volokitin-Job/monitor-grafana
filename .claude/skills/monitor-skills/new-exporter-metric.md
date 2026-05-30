---
name: monitoring:new-exporter-metric
description: Add a Prometheus metric to a Python custom exporter
branch: Develop (default if no branch-specific skill exists)
---

# Add Exporter Metric

## When to Use
When exposing a new metric from the custom Python exporter.

## Pattern
```python
from prometheus_client import Gauge, Counter, Histogram

# Gauge (current value)
monitor_service_status = Gauge(
    'monitor_service_status',
    'Service availability status (1=up, 0=down)',
    ['service', 'environment']
)

# Counter (cumulative)
monitor_requests_total = Counter(
    'monitor_requests_total',
    'Total requests processed',
    ['method', 'endpoint']
)

# Usage in collector
def collect_metrics():
    monitor_service_status.labels(service='api', environment='prod').set(1)
    monitor_requests_total.labels(method='POST', endpoint='/v1/subscribers').inc()
```

## Location
- `monitor_exporter/` — Main Monitor exporter
- `custom_exporter/` — Additional custom exporters

## Conventions
- Prefix metrics with `monitor_`
- Use labels for dimensions (service, environment, method)
- Gauge for status, Counter for totals, Histogram for latencies
