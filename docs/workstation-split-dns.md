# Workstation DNS split-zone reconciliation (opt-in)

Source of truth: `ansible-workstation` task
`tasks/network_split_dns.yml`. pfSense upstream DoT and private Unbound zone
belong to `AlbanAndrieu/nabla-compose` PR #274.

## 2026-11-25: Quad9 stopped serving France — DNS outage

Root cause: Quad9 withdrew from France on 2026-11-24 (court-ordered
blocking). From the Free public IP, `9.9.9.9`, `9.9.9.10`, `9.9.9.11` and
`149.112.112.112` time out on UDP/53, refuse TCP/53 and DoT, and DoH answers
`403`, while ICMP, Cloudflare and Google still answer. The workstation
global DNS (`/etc/systemd/resolved.conf`, set by `tasks/services.yml`),
its `FallbackDNS` (`files/etc/systemd/resolved.conf.d/99-workstation.conf`)
and Pi-hole's upstreams (AdGuard `:553` over Quad9 DoH, then `9.9.9.9`, in
nabla-compose `apps/pihole/compose.yml`) all depended on Quad9. Pi-hole still
answers `*.int.albandrieu.com` but times out on public names.

Journal evidence: `DNSSEC validation failed … no-signature` ran at about
8,000/h since 2026-11-18 (Pi-hole, `DefaultRoute=yes` on `eno1`, returns
unsigned answers; Quad9 answered instead), then about 45,000/h from
2026-11-24 09:00, when no signed path was left.

Manual workarounds on 2026-11-25 (not in Git): R7000 DHCP DNS reduced to
the Freebox `192.168.1.254` around 19:59; `Wired eno1` replaced by
`Profile 1` (netplan, `ipv6.method disabled`) around 20:06; at 21:10 a
global Cloudflare DoT drop-in `/etc/systemd/resolved.conf.d/10-dns-over-tls.conf`
and `ipv4.ignore-auto-dns yes`. Public names resolve again, but
`*.int.albandrieu.com` no longer does (Maven through `nexus.int` fails) and
IPv6 is off on `eno1`.

**Fix applied on 2026-11-25 around 22:00 (operator chose Cloudflare):**

- `/etc/systemd/resolved.conf.d/99-workstation.conf` (captured in
  `files/etc`): Cloudflare `1.1.1.1`/`1.0.0.1` over strict DoT, same
  fallback, `DNSSEC=yes`. The 21:10 drop-in is folded into it and kept as
  `/etc/systemd/10-dns-over-tls.conf.bak-20261125`; `resolved.conf` Quad9
  lines replaced too (backup `resolved.conf.bak-20261125`).
- Profile renamed back to `Wired eno1` (the NTA dispatcher only acts on
  that name): `ipv4.dns 172.17.0.24`, `~int.albandrieu.com`,
  `ignore-auto-dns`, `ipv6.method auto` and `connection.dns-over-tls no`,
  since the global strict DoT also applied to the LAN link and Pi-hole has
  no DoT. `tasks/network_split_dns.yml` now sets that last field;
  `--check` on the host: `ok=9 changed=0`.
- Verified: NTA `int.albandrieu.com` back on `eno1`, `nexus.int` → 200,
  public names authenticated over DoT.
- `tasks/services.yml` `dns_new` (hide-location) is now Cloudflare.

Still open: `eno1` stays `DefaultRoute=yes`, so public queries also hit
Pi-hole and log `no-signature`; the R7000 no longer sends IPv6 router
advertisements (its LAN link-local `fe80::120c:6bff:fe62:128e` is silent),
so `eno1` only has a link-local address; Pi-hole/AdGuard/Gluetun upstreams
live in nabla-compose.

## 2026-11-18: pfSense retired

The Netgate 1100 no longer boots and was removed; the Freebox is back in
router mode. The private-zone resolver is now Pi-hole on TrueNAS
(`172.17.0.24`), the global `systemd-resolved` DNS is Quad9, and the
`Wired eno1` profile was recreated. Details, remaining steps and the
`nmcli` commands: [architecture, section 0](homelab-split-dns-architecture.md).

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
workstation_split_dns_resolver: 172.17.0.24
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
dig @172.17.0.24 sample.int.albandrieu.com A
```

Do not treat an update to the profile as success without these checks.
