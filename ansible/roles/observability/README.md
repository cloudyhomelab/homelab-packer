# observability

Grafana Alloy pushes host metrics and systemd unit states to Prometheus remote-write, and the
journal to Loki. The journal is kept on disk, capped by `observability_journal_max_use`.

Alloy loads every `*.alloy` file in `/etc/alloy` as one configuration. Another role adds components
by dropping its own file there (mode `0640`, group `alloy`); component names must be unique across
files, and `prometheus.remote_write.central` is available to forward metrics to.

## Variables

Required:

```yaml
observability_prometheus_url: https://prometheus.example/api/v1/write
observability_loki_url: https://loki.example/loki/api/v1/push
```

The endpoints need not exist when a host boots: Alloy retries until they do.
