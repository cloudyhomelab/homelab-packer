# smart-exporter

SMART data from moria's disks into Prometheus. TrueNAS is configured by hand; `compose.yaml` is the
source of truth for the app.

- `smartctl_exporter` reads every disk's SMART data once a minute. A disk in standby is skipped,
  not woken.
- Alloy pushes the metrics to Prometheus with `instance="moria"`.

## Install or update

1. Apps → Discover Apps → ⋮ → Install via YAML (to update: Apps → `smart-exporter` → Edit)
2. Name: `smart-exporter`
3. Paste `compose.yaml` and save

## Check

- Apps → `smart-exporter`: both containers running
- Container logs of `alloy`: no remote-write errors
- Grafana → Homelab → SMART: one row per disk
