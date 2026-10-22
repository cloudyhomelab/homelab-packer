# observability

Grafana Alloy pushes host metrics and systemd unit states to Prometheus remote-write, and the
journal to Loki. The journal is kept on disk, capped by `observability_journal_max_use`.

## Variables

Required:

```yaml
observability_prometheus_url: https://prometheus.example/api/v1/write
observability_loki_url: https://loki.example/loki/api/v1/push
```

The endpoints need not exist when a host boots: Alloy retries until they do.
