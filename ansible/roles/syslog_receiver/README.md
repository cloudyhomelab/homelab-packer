# syslog_receiver

Receives syslog in the host's Alloy and ships it to Loki through `loki.write.central`, which the
`observability` role defines. Opening the listener ports in the firewall is left to the playbook.

- `instance`: the message's hostname, or the sender's address when the message has none
- `service_name`: the syslog app name
- `level`: the syslog severity; `informational` becomes `info`, as in the journal

## pf filterlog

Lines from the app `filterlog` (pf firewall log, e.g. OPNsense) are parsed:

- Labels: `action`, `interface` (renamed through `syslog_receiver_filterlog_interfaces`),
  `direction`
- Structured metadata: `rule`, `rule_id`, `proto`, `src`, `dst`, `src_port`, `dst_port`,
  `tcp_flags`
- Counter `loki_process_custom_filterlog_entries_total` with the stream labels, scraped from
  Alloy's own `/metrics` into Prometheus
