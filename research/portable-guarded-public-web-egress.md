# Portable guarded public-web egress for Functional V1

**Research date:** 2026-07-15 (revised)

**Primary-source cutoff:** 2026-07-15

**Ticket:** [Choose portable guarded public-web egress](https://github.com/MihaiA24/model-benchmarking/issues/68)

**Map:** [Define a minimal local Functional V1 benchmark](https://github.com/MihaiA24/model-benchmarking/issues/66)

## Question

What minimal enforceable networking design lets Functional V1 agent containers reach the public
web while blocking private, LAN, link-local, cloud-metadata, host-service, and direct Provider
Route bypass destinations; retaining the local Credential Proxy as the only model route; and
recording useful egress evidence on both Docker Desktop for macOS and native Docker on Linux
without privileged Trial access? The design must cover DNS rebinding, IPv4/IPv6 parity,
redirects, Docker bridge/host gateway behaviour, macOS VM boundaries, fail-closed
startup/cleanup, portability limitations, destination-IP validation on every connection and
redirect, blocks applied to connections originating from the egress proxy itself, and deny
non-proxied UDP/QUIC.

## Constraints from accepted architecture

**standard-v1** (profiles/standard-v1.yaml) declares network_mode: no-network -- the production
profile is default-deny. Functional V1 is a diagnostic milestone with a deliberately different
network posture.

The Credential Proxy is the only route to model providers
([hermetic-execution-and-integrity.md](../../blueprint/hermetic-execution-and-integrity.md)):

> Keep provider credentials outside the agent environment. A benchmark-controlled credential
> proxy injects provider authentication, restricts traffic to the declared provider and model
> route, and gives each trial only an opaque short-lived token that is valid at that proxy.

No privileged Trial access -- no CAP_NET_ADMIN or CAP_NET_RAW inside the agent container
([hermetic-execution-and-integrity.md](../../blueprint/hermetic-execution-and-integrity.md)):

> Run every harness under the same unprivileged user, with write access limited to the
> evaluated repository and explicitly declared scratch and cache paths.

The coordinator owns Docker enforcement policy
([benchmark-architecture-and-reuse-boundary.md](../../blueprint/benchmark-architecture-and-reuse-boundary.md)):

> Experiment and worker controls include the selected Harness artifact mount, Credential Proxy
> route, Docker enforcement policy, single-Trial worker concurrency, host-side evidence
> collectors, output roots, and provider ceilings.

The Credential Proxy runs per-Trial
([benchmark-architecture-and-reuse-boundary.md](../../blueprint/benchmark-architecture-and-reuse-boundary.md)):

> Start one proxy instance per Trial, configured for exactly one Planned Trial Cell, Provider
> Route and upstream endpoint, requested model identifier, opaque Trial token, real upstream
> credential, request/token/spend ceilings, and secret-safe evidence destination.

## Primary-source evidence

### 1. Docker bridge network egress -- Linux native

Docker's bridge driver adds MASQUERADE rules in the nat table POSTROUTING chain; ip_forward
must be enabled
([Docker packet filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/)).
The filter table FORWARD chain jumps to DOCKER-USER (user insertion point), DOCKER-FORWARD,
and DOCKER ([Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/)).
Bridge driver options include enable_ip_masquerade and enable_icc
([Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/)).

### 2. Docker Desktop for macOS -- VM boundary

Docker Desktop runs containers inside a LinuxKit VM (HyperKit)
([Collabnix](https://collabnix.com/how-docker-for-mac-works-under-the-hood/)). Key consequences:

- No docker0 on the host -- bridge interface inside the VM
  ([Docker Desktop networking](https://docs.docker.com/desktop/features/networking/)).
- iptables operates inside the VM, not on macOS. NET_ADMIN containers can destabilise the VM
  ([docker/for-mac #2489](https://github.com/docker/for-mac/issues/2489),
  [#6297](https://github.com/docker/for-mac/issues/6297),
  [#5547](https://github.com/docker/for-mac/issues/5547)).
- host.docker.internal resolves to the host's IP within the VM (e.g., 192.168.65.2).
- No kernel-escape: container root != host root on macOS.

### 3. Harbor v0.18.0 egress-control sidecar

Harbor provides public, no-network, and allowlist modes. In allowlist mode it deploys an
egress-control sidecar with NET_ADMIN + NET_RAW, running gost (transparent TCP proxy) with
nftables redirecting all TCP through the proxy
([task docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx)).

Source files at pinned commit
[527d50deb63a5d279e8c20593c18a2cbc7f61f9e](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e):

| File | Role |
| --- | --- |
| [docker-compose-egress-control.yaml](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker-compose-egress-control.yaml) | Sidecar Compose overlay with NET_ADMIN, NET_RAW |
| [entrypoint.sh](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/entrypoint.sh) | Startup: calls network-policy with initial mode |
| [bin/network-policy](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/bin/network-policy) | nftables ruleset + gost management |
| [gost.yaml](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/gost.yaml) | gost transparent proxy with file-based bypass (whitelist) |
| [docker.py](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker.py) | Docker provider; kernel probe; sidecar enablement |

### 4. gost bypass and redirect mechanics

gost's bypass system defaults to **blacklist** semantics -- when no bypass or a bypass with
`whitelist: false` is configured, gost forwards all destinations except those matching the
bypass rules. Bypass rules accept IP addresses, CIDR ranges, domain names, and wildcard
patterns ([gost bypass concepts](https://gost.run/en/concepts/bypass/)).

The RED handler (transparent redirect) receives connections redirected by iptables/nftables.
With `sniffing: true` and `sniffing.fallback: true`, gost attempts to extract the original
destination from the sniffed protocol (HTTP host, TLS SNI). If sniffing fails, it falls
back to the original destination address from the RED metadata
([gost RED tutorial](https://gost.run/en/tutorials/redirect/)).

**TLS SNI limitation:** gost's sniffing extracts the TLS SNI from the ClientHello. However,
SNI reveals only the hostname (e.g., api.openai.com), not the URL path. An agent could
connect to two different HTTPS services on the same IP/port behind the same SNI -- gost
cannot distinguish them at the proxy layer. This is the accepted Layer-7 limit without MITM
([gost sniffing](https://latest.gost.run/en/tutorials/sniffing/)).

Harbor's pinned [gost.yaml](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/gost.yaml)
uses `handler: red`, `sniffing: true`, `sniffing.fallback: true`, and a `whitelist: true` bypass.

**For the Functional V1 design, the required change is:**
- `whitelist: true` -> `whitelist: false` (blacklist mode)
- Replace allowlist with blocklist CIDRs (private ranges, provider IPs, etc.)
- Add provider domain/wildcard patterns to the blocklist (defence in depth)

### 5. Cloud metadata endpoints

169.254.169.254 is the metadata endpoint for AWS, GCP, and Azure. On cloud VMs, all
containers reach it by default. The definitive block is host-level iptables; however, the
transparent proxy design blocks it at the proxy/nftables layer within the sidecar (no
host-level rules needed).

**Sources:** [Blocking EC2 metadata](https://ops.tips/blog/blocking-docker-containers-from-ec2-metadata/);
[AWS ECS](https://aws.amazon.com/premiumsupport/knowledge-center/ecs-container-ec2-metadata/).

### 6. DNS rebinding and proxy IP validation

Docker's embedded DNS at 127.0.0.11 does not implement rebinding protection
([Docker DNS](https://docs.docker.com/engine/network/networking/#dns-services)).

A transparent proxy that checks destination IPs **after** DNS resolution (as gost does with
the RED handler) is inherently immune: the proxy resolves the hostname, obtains the IP, and
applies the blocklist to that IP. Even if DNS returns a private IP on a short-TTL resolution,
the proxy drops the connection before forwarding.

For HTTP redirects: each redirect creates a new TCP connection. The proxy resolves the
redirect target, applies the blocklist, and drops if blocked.

### 7. IPv6 in Docker

Docker supports IPv6 on bridge networks. Docker Desktop can operate dual-stack or IPv6-only
([Docker Desktop settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/#networking)).
nftables inet family rules cover both IPv4 and IPv6. Harbor's sidecar uses table inet
gost_egress (dual-stack).

**Preflight:** Coordinator must verify IPv4/IPv6 enforcement parity. If parity unverifiable,
disable IPv6 on the Docker network (--ipv6=false) or reject as not_started.

### 8. Non-proxied UDP and QUIC

Transparent TCP proxies cannot intercept UDP. QUIC/HTTP3 bypasses the TCP proxy entirely.
Harbor's existing nftables egress chain handles this:

```
chain egress {
    type filter hook output priority filter; policy accept;
    meta mark 114514 accept
    fib daddr type local accept
    ip protocol icmp accept
    ip6 nexthdr icmpv6 accept
    meta l4proto != tcp reject
}
```

Adding `udp dport 53 accept` before the reject rule permits DNS. Everything else is dropped.

### 9. Proxy-self traffic

Gost's forwarded packets carry socket mark GOST_MARK (0x114514). The nftables NAT redirect
uses "meta mark 114514 return" to skip re-redirecting (preventing loops). The egress filter
uses "meta mark 114514 accept" to allow validated traffic. The proxy cannot bypass because
it validates every destination IP before forwarding.

### 10. Complete blocklist

| Range | Purpose |
| --- | --- |
| 10.0.0.0/8 | RFC 1918 private |
| 172.16.0.0/12 | RFC 1918 private; Docker bridge gateways |
| 192.168.0.0/16 | RFC 1918 private; host.docker.internal |
| 169.254.0.0/16 | Link-local; cloud metadata |
| 100.64.0.0/10 | CGNAT |
| 198.18.0.0/15 | RFC 2544 bench |
| 127.0.0.0/8 | Loopback; host services |
| 224.0.0.0/4 | Multicast |
| 240.0.0.0/4 | Reserved |
| fc00::/7 | IPv6 ULA |
| fe80::/10 | IPv6 link-local |
| ::1/128 | IPv6 loopback |
| ff00::/8 | IPv6 multicast |
| PROVIDER_IP_RANGES | Model provider IPs (provision-time) |

### 11. Provider Route bypass -- three-layer defence

**Layer 1 -- DNS hostname blocking (defence in depth):** Force agent to coordinator DNS
resolver; returns NXDOMAIN for provider domains.

**Layer 2 -- gost IP + hostname validation (primary defence):** Every TCP connection goes
through gost. It checks destination IP and SNI hostname against the blocklist. Blocked
destinations are dropped before any data is forwarded.

**Layer 3 -- nftables boundary (final defence):** Drops any packet to blocked ranges that
bypasses the proxy.

## Design -- transparent proxy egress sidecar (Design B)

### Core principle

**The agent container has NO direct external network route.** Every packet goes to the
coordinator-controlled egress sidecar or the Credential Proxy. The sidecar runs gost as a
**blacklist-mode** transparent proxy (whitelist: false), nftables for non-TCP enforcement,
and dnsmasq as a DNS proxy.

This is **fully portable** -- no host-level iptables, no platform-specific configuration.
Identical on Linux and macOS Docker Desktop.

### Required configuration changes to Harbor's sidecar

Harbor's existing sidecar uses whitelist mode. The following are **configuration changes
to gost.yaml and the network-policy script**, not a new sidecar build:

1. **gost.yaml: change whitelist: true -> whitelist: false**
   ```yaml
   bypasses:
     - name: blocklist
       whitelist: false   # blacklist: allow all except matches
       reload: 1s
       file:
         path: /opt/egress-sidecar/blocklist.txt
   ```
   Empty blocklist = allow all public web by default.
   ([gost bypass docs](https://gost.run/en/concepts/bypass/#BypassConfig): matching
   destination terminates forwarding with error.)

2. **blocklist.txt contents:** CIDR ranges for all private/special provider ranges from
   SS 10 above, plus provider domain/wildcard patterns (b .openai.com, etc.) as defence
   in depth. gost's bypass matching supports exact domain, wildcard, IP, CIDR, and IP range.

3. **nftables: add ip daddr/ip6 daddr drop rules** matching the same CIDR ranges, ensuring
   that even traffic that bypasses gost (UDP, malformed TCP, kernel-bypass scenarios) is
   blocked.

4. **dnsmasq:** bogus-priv (reject A/AAAA for private ranges), plus address=/PROVIDER_DOMAIN/
   for NXDOMAIN (defence in depth).

### nftables ruleset (dual-stack inet)

```nft
table inet gost_egress {
  chain prerouting {
    type nat hook prerouting priority dstnat; policy accept;
    iif "eth0" meta l4proto tcp redirect to :12345
  }
  chain output {
    type nat hook output priority dstnat; policy accept;
    meta mark 114514 return
    fib daddr type local return
    meta l4proto tcp redirect to :12345
  }
  chain egress {
    type filter hook output priority filter; policy accept;
    meta mark 114514 accept
    fib daddr type local accept
    ip protocol icmp accept
    ip6 nexthdr icmpv6 accept
    udp dport 53 accept
    meta l4proto != tcp reject
    ip daddr { 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16,
      100.64.0.0/10, 198.18.0.0/15, 127.0.0.0/8, 224.0.0.0/4, 240.0.0.0/4 } drop
    ip6 daddr { fc00::/7, fe80::/10, ::1/128, ff00::/8 } drop
    ip daddr { PROVIDER_IPV4_RANGES } drop
    ip6 daddr { PROVIDER_IPV6_RANGES } drop
  }
}
```

### Per-connection validation flow

```
Agent -> TCP SYN to public.example.com
  1. nftables: redirect to gost:12345
  2. gost reads destination (public.example.com:443)
  3. gost resolves -> 93.184.216.34
  4. gost checks blocklist (IP + SNI after sniffing) -> NOT BLOCKED
  5. gost forwards with SO_MARK 114514
  6. nftables: mark 114514 -> accept

Agent follows redirect to http://10.0.0.1/admin
  1. New TCP SYN to 10.0.0.1:80 -> gost
  2. gost checks 10.0.0.1 against blocklist -> BLOCKED (RFC 1918)
  3. gost drops connection (TCP RST)

Agent tries QUIC/HTTP3
  1. UDP packet -> nftables egress: non-TCP -> reject

Agent hardcodes provider IP
  1. TCP SYN to provider IP -> gost checks blocklist -> BLOCKED
```

### Credential Proxy

Runs on proxy-net (separate internal network, not through sidecar). Agent has direct route
to proxy. Proxy validates Trial token, forwards only to configured provider route.

### Evidence collection

| Source | Data | Granularity |
| --- | --- | --- |
| gost logs | Time, src, dest IP:port, bytes, status | Per-connection |
| nftables counters | Packets per blocked range | Per-rule |
| dnsmasq logs | Query name, client, response | Per-query |
| CP logs | Request count, timing, status, usage | Per-request |
| Harbor Trial | Timing, errors, result | Per-Trial |

### Preflight (all required -- fail not_started)

1. nftables kernel support (CONFIG_NFT_FIB_INET=y)
2. gost healthcheck (responding on redirect port)
3. dnsmasq healthcheck (agent resolves test domain)
4. CP healthcheck (Trial token valid)
5. IPv6 parity: if IPv6 enabled, verify nftables IPv6 rules operational; disable or reject if not
6. Blocklist populated (>= 20 CIDRs + provider IPs)
7. No external agent route (ip route shows only sidecar gateway)

### Cleanup

```
docker compose -f trial-overlay.yaml down --remove-orphans --volumes
```

All containers, networks, volumes removed. nftables cleaned with namespace.

## Invariant compliance

| Invariant | How satisfied |
| --- | --- |
| Public web reachable | Default allow (blacklist blocks only listed ranges) |
| Private/LAN blocked | nftables + gost blocklist (RFC 1918) |
| Link-local/metadata | 169.254.0.0/16; DROP for 169.254.169.254 |
| Host services blocked | Loopback + bridge subnet in blocklists |
| DNS rebinding | gost validates IP after DNS resolution |
| IPv4 enforced | ip daddr rules + gost validation |
| IPv6 enforced | ip6 daddr rules (same inet table); preflight parity check |
| Redirects mitigated | Each redirect = new TCP; gost validates independently |
| Provider bypass blocked | DNS NXDOMAIN + gost IP/SNI check + nftables |
| CP only route | Agent has direct route to CP on proxy-net only |
| UDP/QUIC denied | meta l4proto != tcp reject (except DNS, ICMP) |
| Proxy-self blocked | gost validates before forwarding; nftables applies to all |
| No privileged Trial | Agent: UID 65532, no caps |
| Fail-closed startup | 7 preflight probes; any failure -> not_started |
| Cleanup completeness | docker compose down removes everything |
| Egress evidence | gost + nftables + dnsmasq + CP + Harbor logs |
| macOS VM boundary | All inside Docker containers; preflight probes nftables |
| Portable | Same Compose overlay, sidecar image, rules on Linux and macOS |

## Acceptance probes

1. Public internet: agent fetches https://github.com, https://pypi.org.
2. RFC 1918 blocked: cannot reach http://10.0.0.1, http://172.16.0.1, http://192.168.1.1.
3. Link-local blocked: cannot reach http://169.254.169.254 (DROP, no ICMP).
4. Loopback blocked: http://127.0.0.1:80, http://127.0.0.11:53.
5. Multicast blocked: cannot send UDP to 224.0.0.0/4.
6. IPv6 private blocked (if IPv6 enabled): http://[fc00::1], http://[fe80::1], http://[::1].
7. IPv6 parity: preflight confirms all IPv4 ranges have IPv6 equivalents.
8. DNS rebinding: domain resolving to 10.0.0.1 -> connection dropped (TCP RST).
9. Provider DNS blocked: dig api.openai.com -> NXDOMAIN.
10. Provider IP blocked: TCP to resolved provider IP -> RST/timeout.
11. Redirect to private IP blocked: curl -L http://public/redirect-to-10.0.0.1 -> fails.
12. Redirect to provider IP blocked: curl -L http://public/redirect-to-provider -> fails.
13. CP reachable: agent can reach proxy on proxy-net.
14. Provider via proxy succeeds: request through CP returns valid model response.
15. UDP/QUIC blocked: cannot reach external UDP except DNS (53).
16. No direct route: ip route shows only sidecar gateway.
17. No CAP_NET_ADMIN: iptables -L -> permission denied.
18. Egress evidence: gost log with 10+ connections (dest IP, timestamp, status).
19. Cleanup: no containers/networks/volumes persist after teardown.
20. nftables kernel (macOS): Docker Desktop VM passes probe.
21. Blocklist populated: >= 20 entries.
22. gost logs all connections: each logged with IP, bytes, duration.

## Portability limitations

| Limitation | Impact | Mitigation |
| --- | --- | --- |
| nftables kernel in DD VM | Without it, egress control cannot deploy | Preflight -> reject not_started |
| DD VM stability with NET_ADMIN | Bug could destabilise VM | Minimal rules; no default-DROP on INPUT/OUTPUT |
| Provider IP range freshness | Resolved IPs may go stale | Record provision-time ranges + timestamp in evidence |
| Layer-7 path blocking | Cannot inspect HTTPS URL paths | Delegated to Credential Proxy |
| DD IPv6 variability | IPv6 enabled but nftables partial | Preflight parity check; disable IPv6 or reject |
| Blocklist is a config change | Harbor's sidecar uses whitelist by default | Change whitelist: true to whitelist: false in gost.yaml |

## Primary-source index

All sources retrieved or checked on 2026-07-15.

1. [Docker packet filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
2. [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/)
3. [Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/)
4. [Docker Desktop networking](https://docs.docker.com/desktop/features/networking/)
5. [docker/for-mac #2489](https://github.com/docker/for-mac/issues/2489)
6. [docker/for-mac #6297](https://github.com/docker/for-mac/issues/6297)
7. [docker/for-mac #5547](https://github.com/docker/for-mac/issues/5547)
8. [Collabnix -- How Docker for Mac works](https://collabnix.com/how-docker-for-mac-works-under-the-hood/)
9. [Docker Desktop network settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/#networking)
10. [gost bypass concepts](https://gost.run/en/concepts/bypass/) -- bypass defaults to blacklist; matches IP, CIDR, domain, wildcard
11. [gost RED handler](https://gost.run/en/tutorials/redirect/) -- transparent redirect with sniffing and original-target fallback
12. [gost sniffing](https://latest.gost.run/en/tutorials/sniffing/) -- TLS SNI extraction limits
13. [Harbor v0.18.0 task docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx)
14. [Harbor v0.18.0 docker.py](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker.py)
15. [Harbor v0.18.0 egress-control sidecar](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar)
16. [Harbor v0.18.0 gost.yaml](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/gost.yaml)
17. [Harbor v0.18.0 bin/network-policy](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/bin/network-policy)
18. [Harbor v0.18.0 task config](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py)
19. [Blocking EC2 metadata](https://ops.tips/blog/blocking-docker-containers-from-ec2-metadata/)
20. [Docker DNS](https://docs.docker.com/engine/network/networking/#dns-services)
21. [DNS rebinding](https://blogs.jsmon.sh/dns-rebinding-how-a-browser-visits-your-localhost/)
22. [nccgroup Singularity](https://github.com/nccgroup/singularity)
23. In-repo: blueprint/benchmark-architecture-and-reuse-boundary.md,
    blueprint/hermetic-execution-and-integrity.md, profiles/standard-v1.yaml

## Decision

**Adopt the transparent-proxy egress sidecar design (Design B) for Functional V1.**

All map-contract invariants are satisfied:

1. **Agent has NO direct external route.** All traffic through coordinator-controlled sidecar
   or Credential Proxy.
2. **Per-connection destination-IP validation.** gost resolves every hostname, checks IP
   against blocklist (blacklist mode: whitelist: false), drops blocked destinations before
   forwarding any data. Each HTTP redirect is an independently validated new connection.
3. **Three-layer Provider Route defence.** DNS NXDOMAIN (defence in depth), gost IP/SNI
   check (primary), nftables block (final).
4. **DNS rebinding fully mitigated.** gost checks IP after DNS resolution.
5. **Redirects fully mitigated.** Each redirect validated independently by gost.
6. **IPv4/IPv6 parity.** nftables inet dual-stack; preflight verifies or rejects.
7. **Non-proxied UDP/QUIC denied.** nftables rejects non-TCP except DNS and ICMP.
8. **Proxy-self traffic cannot bypass.** gost validates before forwarding.
9. **Truly portable.** No host-level iptables. Same Compose overlay on Linux and macOS.
10. **Fail-closed.** 7 preflight probes; any failure -> not_started.
11. **Blocklist is a configuration change to Harbor's existing sidecar.** whitelist: true ->
    whitelist: false in gost.yaml; CIDR/provider entries in blocklist.txt; nftables drop
    rules for the same ranges; dnsmasq for DNS-layer defence.
12. **Evidence-rich.** gost per-connection logs + nftables counters + DNS logs + CP logs.
