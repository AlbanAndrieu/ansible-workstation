# Workstation DNS split-zone reconciliation (opt-in)

Source of truth: `ansible-workstation` task
`tasks/network_split_dns.yml`. pfSense upstream DoT and private Unbound zone
belong to `AlbanAndrieu/nabla-compose` PR #274.

## Observation

2026-10-24: `nmcli device reapply eno1` succeeded but
`resolvectl dns eno1` remained `9.9.9.9 149.112.112.112`.
`dig @172.17.0.1 sample.int.albandrieu.com` returned
`172.17.0.24`, while NSS `getent` did not resolve the name.
The active link resolver must be reconciled; changing profile fields
alone does not prove DNS is correct.

## Security and activation

Default is `workstation_split_dns_enabled: false`. Opt in only for the
home workstation after confirming SSH/console rollback access, active
NetworkManager profile, and pfSense health. This changes IPv4 DNS for
the *active profile*, not the global resolver. No secrets and no system
restarts beyond `nmcli device reapply`. If Quad9 remains effective,
the task fails rather than claiming success.

Example play variables (explicit opt-in):

```yaml
workstation_split_dns_enabled: true
workstation_split_dns_interface: eno1
workstation_split_dns_resolver: 172.17.0.1
workstation_split_dns_domain: int.albandrieu.com
```

Client -> pfSense DNS in this phase is normal UDP/TCP port 53 on the
trusted LAN; pfSense -> Quad9 can be strict DoT on TCP 853 when separately
validated. Do not call this 'encrypted end to end'. DNSOverTLS opportunistic
on the workstation can silently downgrade to cleartext. Workstation
strict DoT to a local pfSense certificate should be a distinct opt-in
profile once a valid trusted certificate and split routing are available.

Check after applying:

```bash
nmcli -f GENERAL.CONNECTION,IP4.DNS device show eno1
resolvectl dns eno1
resolvectl domain eno1
getent ahostsv4 sample.int.albandrieu.com
dig @172.17.0.1 sample.int.albandrieu.com A
```

Do not treat an update to the profile as success without these checks.
