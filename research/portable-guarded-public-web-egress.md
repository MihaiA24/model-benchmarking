# Portable guarded public-web egress for Functional V1

**Research date:** 2026-07-15
**Primary-source cutoff:** 2026-07-15
**Ticket:** [Choose portable guarded public-web egress](https://github.com/MihaiA24/model-benchmarking/issues/68)
**Map:** [Define a minimal local Functional V1 benchmark](https://github.com/MihaiA24/model-benchmarking/issues/66)

## Question

What minimal enforceable networking design lets Functional V1 agent containers reach the public
web while blocking private, LAN, link-local, cloud-metadata, host-service, and direct Provider
Route bypass destinations; retaining the local Credential Proxy as the only model route; and
recording useful egress evidence on both Docker Desktop for macOS and native Docker on Linux
without privileged Trial access?

## Constraints from accepted architecture

The current [`standard-v1`](/Users/mihai/code/nter/model-benchmarking/profiles/standard-v1.yaml) profile
declares `network_mode: no-network` for both agent and verifier — production profile is default-deny.
Functional V1 is a diagnostic milestone with a deliberately different network posture:

> **Functional V1**: The diagnostic milestone in which one trusted local operator executes the fixed
> comparison conditions through the selected Legacy Calibration Suite slice and obtains verified
> Result Bundles without making a statistically defensible ranking claim.

The Credential Proxy must remain the only route to model providers
([hermetic-execution-and-integrity.md](/Users/mihai/code/nter/model-benchmarking/blueprint/hermetic-execution-and-integrity.md)).
No privileged Trial access (no `CAP_NET_ADMIN` inside the agent container, no host-network mode
for the agent). The coordinator already owns "Docker enforcement policy"
([benchmark-architecture-and-reuse-boundary.md](/Users/mihai/code/nter/model-benchmarking/blueprint/benchmark-architecture-and-reuse-boundary.md)).

## Primary-source evidence

### 1. Docker bridge network egress mechanics (Linux native)

Docker's bridge driver adds MASQUERADE rules in the `nat` table `POSTROUTING` chain for every
Docker subnet. Containers reach the internet through source NAT; the host kernel's `ip_forward`
must be enabled. In the `filter` table, Docker inserts rules in the `FORWARD` chain that jump to
`DOCKER-USER`, `DOCKER-FORWARD`, and `DOCKER` chains, and sets the default FORWARD policy to DROP.

```text
iptables -t nat -A POSTROUTING -s 172.17.0.0/16 ! -o docker0 -j MASQUERADE
iptables -A FORWARD -i docker0 ! -o docker0 -j ACCEPT
iptables -A FORWARD -o docker0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

**Source:** Docker official docs — [Packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/),
[Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/),
[Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/).

### 2. The DOCKER-USER chain

Docker creates the `DOCKER-USER` chain in the `filter` table as a user-defined insertion point
for custom iptables rules. Rules in `DOCKER-USER` are processed **before** Docker's own rules
in `DOCKER-FORWARD` and `DOCKER`. This is the recommended seam for restricting container egress:

```console
# Block all external source IPs except a specific subnet
iptables -I DOCKER-USER -i ext_if ! -s 192.0.2.0/24 -j DROP
```

**Source:** [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/).

### 3. Docker Desktop for macOS — architectural differences

Docker Desktop runs containers inside a LinuxKit VM using HyperKit, not directly on macOS.
This has critical consequences for network enforcement:

- **No `docker0` bridge on the host** — the bridge interface exists only inside the VM
  ([Docker Desktop networking docs](https://docs.docker.com/desktop/features/networking/networking-how-tos/)).
- **iptables rules operate inside the VM** — they affect the VM's kernel, not macOS.
  A container with `--network host` and `NET_ADMIN` can destabilise the entire Docker Desktop VM
  by blocking the VM's own networking. Even a single dropped OUTPUT rule can bring the VM down
  ([docker/for-mac #2489](https://github.com/docker/for-mac/issues/2489),
  [#6297](https://github.com/docker/for-mac/issues/6297),
  [#5547](https://github.com/docker/for-mac/issues/5547)).
- **`host.docker.internal`** resolves to the macOS host from inside the VM
  ([Docker Desktop networking how-tos](https://docs.docker.com/desktop/features/networking/networking-how-tos/)).
- **All inbound connections** pass through `com.docker.backend` on macOS, which handles port
  forwarding into the VM. The macOS host firewall cannot filter container-originated traffic
  because it originates inside the VM.
- **No kernel access:** Container root is not host root on macOS. Any firewall enforcement
  must happen inside the VM through Docker's mechanisms.

**Sources:** [Docker Desktop networking](https://docs.docker.com/desktop/features/networking/);
[Collabnix — How Docker for Mac works](https://collabnix.com/how-docker-for-mac-works-under-the-hood/);
[Docker Desktop crash with iptables (Medium)](https://medium.com/@chinmayshringi4/docker-bug-docker-desktop-crash-on-macos-understanding-the-host-network-iptables-bug-3d3fc2884149).

### 4. Harbor v0.18.0 network policy implementation

Harbor v0.18.0 provides three `network_mode` values: `public`, `no-network`, `allowlist`.

- **`public`:** default; standard Docker bridge networking — full unrestricted egress.
- **`no-network`:** sets `network_mode: none` on the main container via a Compose overlay.
- **`allowlist`:** deploys an egress-control sidecar container with `NET_ADMIN` and `NET_RAW`
  capabilities. The sidecar runs **gost** (transparent proxy) with **nftables** rules that
  redirect all TCP through the proxy, which checks destinations against a file-based allowlist.
  Non-TCP traffic is rejected; local and ICMP traffic are permitted.

Key source files (pinned commit
[`527d50deb63a5d279e8c20593c18a2cbc7f61f9e`](https://github.com/harbor-framework/harbor/tree/527d50deb63a5d279e8c20593c18a2cbc7f61f9e)):

- [`docker-compose-egress-control.yaml`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker-compose-egress-control.yaml)
- [`entrypoint.sh`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/entrypoint.sh)
- [`bin/network-policy`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/bin/network-policy)
- [`gost.yaml`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/gost.yaml)
- [`docker.py`](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker.py)

Critical limitations:

1. Egress control is **only enabled when the kernel supports nftables `fib` lookups on `inet`
   families** — a probe runs before every Trial. If the probe fails, egress control silently
   falls back to public mode.
2. Egress control is **disabled for Windows containers** (Linux containers only).
3. The `allowlist` mode is a **positive allowlist** — only explicitly listed destinations pass.
   There is no "allow-public-web-block-private" mode.
4. **DNS rebinding is not mitigated** at the nftables layer (gost's whitelist-based allowlist
   mode is immune, but the general redirect path is not).

**Source:** [Harbor task structure docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx),
Harbor v0.18.0 source at the pinned commit.

### 5. Cloud metadata endpoints

All three major cloud providers expose instance metadata at `169.254.169.254`:

- **AWS:** `http://169.254.169.254/latest/meta-data/` — IAM role credentials.
- **GCP:** `http://169.254.169.254/computeMetadata/v1/` — service account tokens.
- **Azure:** `http://169.254.169.254/metadata/instance` — managed identity tokens.

On a cloud VM running Docker, **all containers can reach the metadata endpoint by default**
because it is a link-local address routed through the host. The only reliable container-side
block is host-level iptables:

```console
iptables --insert DOCKER-USER --destination 169.254.169.254 --jump REJECT
```

IMDSv2 (AWS) with a hop limit of 1 blocks containers at the instance level, but this is
cloud-specific and not portable to all environments.

**Sources:** [Blocking EC2 metadata from Docker (ops.tips)](https://ops.tips/blog/blocking-docker-containers-from-ec2-metadata/);
[AWS ECS knowledge center](https://aws.amazon.com/premiumsupport/knowledge-center/ecs-container-ec2-metadata/);
[GCP metadata security advisory](https://github.com/louislam/uptime-kuma/security/advisories/GHSA-qjxc-h5jf-c7rj).

### 6. DNS rebinding

Docker's embedded DNS resolver at `127.0.0.11` performs container-name resolution and forwards
external queries to configured upstream resolvers. It **does not implement DNS rebinding
protection** — it returns any A/AAAA record from the upstream, including records pointing to
private IP ranges.

An attacker-controlled domain can be configured with a short TTL that alternates between a
public IP and a private IP. If an agent makes a TCP connection after a resolution that returns
the private IP, it can reach internal services.

Harbor's `allowlist` mode is immune (gost checks the destination hostname before resolution),
but `public` mode has no such protection.

**Sources:** [Docker embedded DNS](https://docs.docker.com/engine/network/networking/#dns-services);
[DNS rebinding explanation](https://blogs.jsmon.sh/dns-rebinding-how-a-browser-visits-your-localhost/);
[nccgroup Singularity framework](https://github.com/nccgroup/singularity).

### 7. IPv6 in Docker

Docker supports IPv6 for bridge networks via `--ipv6`. Docker Desktop can operate in dual-stack
or IPv6-only mode. Harbor's egress-control sidecar nftables ruleset uses `inet` (dual-stack)
families, covering both IPv4 and IPv6 when the kernel supports it. IPv6 link-local (`fe80::/10`)
and ULA (`fc00::/7`) ranges must be blocked alongside their IPv4 equivalents.

**Sources:** [Docker bridge IPv6 docs](https://docs.docker.com/engine/network/drivers/bridge/#use-ipv6-in-a-user-defined-bridge-network);
[Docker Desktop network settings](https://docs.docker.com/desktop/settings-and-maintenance/settings/#networking).

### 8. Link-local and special-purpose address ranges

| Range | Purpose | Rationale |
| --- | --- | --- |
| `10.0.0.0/8` | RFC 1918 private | LAN reachability |
| `172.16.0.0/12` | RFC 1918 private | LAN reachability |
| `192.168.0.0/16` | RFC 1918 private | LAN reachability |
| `169.254.0.0/16` | Link-local | Cloud metadata (`169.254.169.254`); DHCP autoconfiguration |
| `100.64.0.0/10` | CGNAT | Carrier-grade NAT — may alias internal infra |
| `198.18.0.0/15` | Benchmark testing | RFC 2544 — used by some cloud vendors internally |
| `127.0.0.0/8` | Loopback | Host services; DNS rebinding target |
| `224.0.0.0/4` | Multicast | Local subnet discovery |
| `240.0.0.0/4` | Reserved | Future use |
| `fc00::/7` | IPv6 ULA | IPv6 private addressing |
| `fe80::/10` | IPv6 link-local | IPv6 local subnet |
| `::1/128` | IPv6 loopback | IPv6 host services |
| `ff00::/8` | IPv6 multicast | IPv6 local subnet discovery |

The Docker bridge subnet itself (`172.17.0.0/16`) is covered by the RFC 1918 rules.

### 9. Provider Route bypass

The accepted architecture places model-provider credentials behind the Credential Proxy. To
prevent direct Provider Route bypass:

- Model provider API endpoints (e.g., `api.openai.com`, `api.anthropic.com`) must be resolved
  and their IP ranges blocked.
- The Credential Proxy must be reachable from the agent container via a stable address.
- The agent must have only an opaque Trial token, not the real credential.

The proxy runs per-Trial:
> Start one proxy instance per Trial, configured for exactly one Planned Trial Cell, Provider
> Route and upstream endpoint, requested model identifier, opaque Trial token, real upstream
> credential, request/token/spend ceilings, and secret-safe evidence destination.

**Source:** [benchmark-architecture-and-reuse-boundary.md](/Users/mihai/code/nter/model-benchmarking/blueprint/benchmark-architecture-and-reuse-boundary.md).

## Viable designs

### Design A — Host iptables DOCKER-USER rules (Linux) + Harbor sidecar (macOS)

**How it works:**

1. Use Harbor's `network_mode = "public"` — baseline unrestricted egress.
2. Before each Trial, the coordinator installs **DOCKER-USER chain rules** on Linux, or deploys
   an **egress-control sidecar with custom nftables rules** on macOS (extending Harbor's existing
   infrastructure), implementing the same blocklist.
3. The blocklist covers all private, link-local, metadata, multicast, CGNAT, reserved, and
   model-provider IP ranges (from the table in §8), plus model-provider API ranges resolved at
   provision time.
4. After each Trial, the coordinator removes the rules / tears down the sidecar.
5. Egress evidence is collected from iptables/nftables log targets and conntrack.

**Platform coverage:**

| Platform | Enforcement mechanism | Works? | Notes |
| --- | --- | --- | --- |
| Linux, native Docker | `iptables -I DOCKER-USER` + `ip6tables` | Yes | Standard supported seam. Per-Trial rules. |
| macOS, Docker Desktop | Extended Harbor sidecar with custom nftables | Yes | Runs inside VM. Requires nftables kernel support. |
| macOS, Docker Desktop (no nftables) | Fallback limited | Partial | Without sidecar, enforcement is weaker — preflight must reject. |
| All platforms | Credential Proxy reachability | Yes | Proxy runs on host/published port. |

**Strengths:** Simple, well-understood mechanism; no proxy overhead; per-Trial cleanup; works
without modifying Harbor source.

**Weaknesses:** DNS rebinding not mitigated; macOS requires sidecar approach with kernel-support
dependency; IPv6 coverage varies; no built-in egress evidence capture (needs LOG targets).

### Design B — Transparent proxy with blocklist (extended Harbor sidecar)

**How it works:**

1. Extend the Harbor egress-control sidecar to implement a **"restricted-public" mode**:
   - All TCP is redirected through the gost transparent proxy.
   - The proxy checks resolved destination IPs against a blocklist.
   - gost records each connection for evidence.
   - nftables rules block non-TCP traffic to private ranges.
   - A DNS response filter rejects A/AAAA records resolving to blocked ranges.
2. The coordinator deploys the sidecar overlay when controlled public access is needed.
3. The Credential Proxy is deployed outside the sidecar's network namespace with a bypass mark.

**Platform coverage:**

| Platform | Works? | Notes |
| --- | --- | --- |
| Linux, native Docker | Yes | Sidecar runs as Docker Compose service. |
| macOS, Docker Desktop | Yes | Same sidecar inside VM. Requires nftables for REDIRECT. |
| macOS (no nftables) | Partial | gost redirection needs nftables or iptables REDIRECT. HTTP_PROXY env-var fallback weaker. |

**Strengths:** DNS rebinding mitigated; rich egress evidence; consistent across platforms; no
host-level iptables needed; future-proof for protocol-aware filtering.

**Weaknesses:** Performance overhead (every TCP connection proxied); non-TCP/UDP bypasses proxy;
HTTPS CONNECT reveals only SNI (not full URL path); more infrastructure to maintain.

### Design C — DNS-only filtering + iptables (lightest, weakest)

**How it works:**

1. Run a validating DNS proxy (unbound with `private-address` or dnsmasq with `bogus-priv`)
   that rejects DNS responses with private IP addresses.
2. Combine with DOCKER-USER iptables rules (Design A) for IP-level defense in depth.

**Platform coverage:**

| Platform | DNS proxy | iptables | Combined |
| --- | --- | --- | --- |
| Linux | `--dns` flag or embedded DNS replacement | DOCKER-USER | Full |
| macOS | Custom DNS container as sidecar | Sidecar nftables needed | Partial |

**Strengths:** Lightweight; prevents DNS rebinding at source.

**Weaknesses:** Agent can hardcode IPs (bypasses DNS filtering); does not block model provider
bypass alone; no egress evidence from DNS alone; two mechanisms needed for full coverage.

## Comparative analysis

| Criterion | Design A (iptables) | Design B (proxy) | Design C (DNS+iptables) |
| --- | --- | --- | --- |
| Blocks private/LAN ranges | Linux: DOCKER-USER. macOS: sidecar nftables | Via proxy IP check + nftables | Via iptables |
| Blocks link-local/metadata | Same mechanism | Same mechanism | Same mechanism |
| Blocks host services | Block 127.0.0.0/8, host bridge IP | Blocked ranges + proxy check | Blocked ranges |
| Prevents DNS rebinding | Not mitigated | Proxy checks resolved IP | DNS proxy rejects private records |
| Blocks Provider Route bypass | Block provider API IP ranges | Block in proxy + iptables | Block provider API IP ranges |
| Retains Credential Proxy as only route | Allow proxy IP, block API IPs | Allow proxy via bypass mark | Allow proxy IP, block API IPs |
| Egress evidence | Requires iptables LOG or conntrack | gost logs all connections | DNS query logs only |
| Works on Linux native Docker | Yes | Yes | Yes |
| Works on macOS Docker Desktop | Requires sidecar nftables | Same sidecar, same config | DNS proxy works; IP needs sidecar |
| No privileged Trial access | Rules on host (outside agent) | Sidecar has NET_ADMIN (not agent) | DNS proxy has no special caps |
| Fail-closed on startup | Verify rules before Trial | Verify sidecar healthy before Trial | Verify DNS proxy before Trial |
| Cleanup completeness | Must flush rules even on failure | Compose down removes sidecar | Must flush rules even on failure |
| Performance overhead | None (line-rate) | Every connection proxied | Minimal (DNS caching) |
| Implementation effort | Medium | High | Low |
| Portability outside Docker | Not portable | Proxy works anywhere; nftables doesn't | Not portable |

## DNS rebinding — assessment for Functional V1

Functional V1 is a local diagnostic run on a developer's machine or dedicated benchmark worker.
The agent container runs as an **unprivileged user** (UID 65532 in standard-v1) with no
`NET_ADMIN` or `NET_RAW` capabilities. The Credential Proxy holds the only valuable credential
— the agent has only an opaque Trial token. Compromising a host service on `127.0.0.1` yields
nothing of value. The dedicated worker host has no personal SSH keys, repositories, or browser
sessions.

For Functional V1, DNS rebinding is a **low-severity concern**:
- No valuable secrets are accessible on localhost or LAN.
- The agent is already unprivileged.
- The Credential Proxy validates the Trial token before forwarding.

For production benchmarks the risk is similarly low when the worker host follows the
[hermetic execution convention](https://github.com/MihaiA24/model-benchmarking/blob/master/blueprint/hermetic-execution-and-integrity.md#worker-host-isolation)
(no personal credentials, no SSH agent, no cloud metadata).

**Recommendation:** Accept DNS rebinding risk for Functional V1 without dedicated mitigation.
The iptables/nftables private-range blocks prevent actual data exfiltration even in a
rebinding scenario. Add a DNS validation proxy only if later evidence shows rebinding is
used against the Credential Proxy or to probe host services.

## Recommendation for Functional V1

**Adopt Design A — Host iptables DOCKER-USER rules (Linux) + Harbor egress-control sidecar with
custom nftables (macOS Docker Desktop).**

### Coordinator responsibilities

The project-owned coordinator (`runtime` module) is already responsible for "Docker enforcement
policy." The following additions are needed:

#### Pre-Trial network setup

**On Linux (native Docker):**
```python
# Install DOCKER-USER rules before Trial
iptables_rules = [
    "-I DOCKER-USER -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT",
    "-I DOCKER-USER -d <CREDENTIAL_PROXY_IP> -j ACCEPT",
    "-I DOCKER-USER -d 10.0.0.0/8 -j REJECT",
    "-I DOCKER-USER -d 172.16.0.0/12 -j REJECT",
    "-I DOCKER-USER -d 192.168.0.0/16 -j REJECT",
    "-I DOCKER-USER -d 169.254.0.0/16 -j DROP",   # DROP not REJECT for metadata
    "-I DOCKER-USER -d 100.64.0.0/10 -j REJECT",
    "-I DOCKER-USER -d 198.18.0.0/15 -j REJECT",
    "-I DOCKER-USER -d 127.0.0.0/8 -j REJECT",
    "-I DOCKER-USER -d 224.0.0.0/4 -j REJECT",
    "-I DOCKER-USER -d 240.0.0.0/4 -j REJECT",
    # Model provider IP ranges resolved at provision time
    "-I DOCKER-USER -d <PROVIDER_IP_RANGE> -j REJECT",
]
# ip6tables rules for IPv6
ip6tables_rules = [
    "-I DOCKER-USER -d fc00::/7 -j REJECT",
    "-I DOCKER-USER -d fe80::/10 -j REJECT",
    "-I DOCKER-USER -d ::1/128 -j REJECT",
    "-I DOCKER-USER -d ff00::/8 -j REJECT",
]
```

Rules are injected via subprocess calls to `iptables`/`ip6tables`. On failure, the Trial must
not start (disposition: `not_started`).

**On macOS (Docker Desktop):**
The coordinator deploys an egress-control sidecar via Docker Compose overlay, extending Harbor's
existing pattern. The sidecar runs gost as a transparent proxy that allows all destinations,
with nftables rules implementing the same blocklist. All agent-service TCP is routed through
the sidecar's network namespace. The sidecar logs all connections for evidence.

#### Post-Trial cleanup

**On Linux:**
```python
subprocess.run(["iptables", "-F", "DOCKER-USER"], check=False)
subprocess.run(["ip6tables", "-F", "DOCKER-USER"], check=False)
```

**On macOS:** Docker Compose `down --remove-orphans` removes the sidecar and its nftables rules
are automatically cleaned up with the network namespace.

#### Credential Proxy reachability

- **On Linux:** The proxy runs on the host. The agent reaches it via the Docker bridge gateway
  IP on a published port. DOCKER-USER rules explicitly allow this destination.
- **On macOS:** The proxy runs as a separate Docker Compose service on the same Docker network,
  reachable by service name. Alternatively, use `host.docker.internal` with a published port.

#### Egress evidence collection

| Evidence source | Data captured | Platform |
| --- | --- | --- |
| iptables/nftables logs | Blocked destination IPs, protocols, packet counts | Linux / macOS |
| conntrack table | Active and terminated connections | Linux (macOS: inside VM) |
| Credential Proxy logs | Request count, timing, status, usage | Both |
| Harbor Trial Result JSON | Timing, errors, result metadata | Both |
| Sidecar gost logs | All proxied connections | macOS (optional on Linux) |

#### Startup and cleanup failure handling

| Failure mode | Disposition | Action |
| --- | --- | --- |
| iptables rules cannot be installed | `not_started` | Do not launch Trial |
| Credential Proxy cannot start | `not_started` | Do not launch Trial |
| Sidecar fails healthcheck | `not_started` | Do not launch Trial |
| Harbor Trial fails mid-execution | As per existing rules | Cleanup rules/sidecar in `finally` |
| Cleanup fails | Infrastructure event | Log warning; mark worker for inspection |
| Rules persist after cleanup | Quarantine worker | Block further Trials on this worker |

### Acceptance probes

The following probes must pass before Functional V1 may claim guarded public-web egress:

1. **Public internet reachability:** Agent container can fetch `https://github.com`,
   `https://pypi.org`, `https://docs.python.org` (HTTP/1.1 and HTTP/2).
2. **Private range blocked:** Cannot connect to `http://10.0.0.1:80`,
   `http://172.16.0.1:80`, `http://192.168.1.1:80`.
3. **Link-local blocked:** Cannot connect to `http://169.254.169.254:80`
   or any `169.254.x.x` address.
4. **Loopback blocked:** Cannot connect to `http://127.0.0.1:80` or `http://127.0.0.11:53`.
5. **Multicast blocked:** Cannot send UDP packets to `224.0.0.0/4`.
6. **IPv6 private blocked (if IPv6 enabled):** Cannot connect to `http://[fc00::1]:80`
   or `http://[fe80::1]:80`.
7. **Credential Proxy reachable:** Agent can reach the proxy at its configured address.
8. **Provider Route blocked:** Cannot reach the model provider API endpoint directly
   (e.g., `https://api.openai.com/v1`).
9. **Provider Route via proxy succeeds:** Request through proxy succeeds and returns data.
10. **No CAP_NET_ADMIN in agent:** Agent runs as UID 65532 and `iptables -L` fails with
    permission denied.
11. **Egress evidence recorded:** After Trial, coordinator retrieves a log of at least 10
    outbound connections with destination IP, timestamp, and protocol.
12. **Cleanup removes rules:** After teardown, a connection to a private IP from a fresh test
    container succeeds (rules were Trial-specific, not permanent).
13. **Sidecar kernel support (macOS):** Docker Desktop passes the nftables kernel probe,
    enabling the egress-control sidecar.

## Portability limitations

| Capability | Linux (Docker) | macOS (Docker Desktop) | Notes |
| --- | --- | --- | --- |
| Host-level iptables DOCKER-USER | Full | Not available | macOS has no host iptables |
| Container-level iptables | Yes (no-op without CAP_NET_ADMIN) | Same as Linux | Ineffective without capabilities |
| Harbor egress-control sidecar | Full | Requires nftables kernel support | VM must have `CONFIG_NFT_FIB_INET=y` |
| Transparent TCP proxy (gost) | Full | Requires nftables for REDIRECT | Without nftables, use env-var proxy |
| DNS rebinding protection | Via DNS proxy container | Same (runs in container) | Works identically |
| IPv6 enforcement | ip6tables/nftables | Depends on VM kernel | Some Docker Desktop versions have limited IPv6 nftables |
| Egress evidence from host | iptables LOG + conntrack | Must use sidecar logs | No host-level visibility on macOS |
| Credential Proxy deployment | Host process or container | Container on shared network | Both work |
| Non-TCP enforcement (UDP, ICMP) | iptables covers all | nftables covers TCP+UDP; ICMP explicit | ICMP may be needed for PMTU discovery |

### What is NOT enforceable portably

These gaps must be explicitly accepted for Functional V1:

1. **Host-level iptables logging on macOS.** All egress evidence must come from inside the VM.
2. **Docker Desktop VM stability with iptables.** Granting `NET_ADMIN` to the sidecar is
   necessary but carries VM stability risk. Mitigated by giving `NET_ADMIN` only to the
   coordinator-controlled sidecar, never to the agent.
3. **nftables kernel support in Docker Desktop.** The sidecar requires `CONFIG_NFT_FIB_INET=y`.
   Without it, the coordinator must reject the Trial as `not_started`.
4. **IPv6 enforcement consistency.** Docker Desktop IPv6 varies by version and host network.
5. **DNS server control.** Docker's embedded DNS at `127.0.0.11` cannot be replaced. Custom
   filtering must run as an additional resolver via Docker Compose `dns` option.
6. **Layer-7 filtering without MITM.** Without TLS interception (prohibited), only destination
   IP and SNI are visible. Route-level blocking requires the Credential Proxy.

## Evidence gap register

| Gap | Impact | Mitigation for Functional V1 |
| --- | --- | --- |
| DNS rebinding not mitigated | Agent could probe host services | Low severity (no secrets on worker host); acceptable |
| UDP protocol bypass (QUIC/HTTP3) | Could reach private UDP endpoints | nftables blocks UDP to private ranges; QUIC rare for model providers |
| Sidecar kernel support on macOS | Without nftables, no enforcement | Preflight detects and rejects; documented limitation |
| Provider IP ranges change | Blocklist becomes stale | Resolve at provision time; record resolved IPs |
| IPv6 Docker Desktop variation | Coverage may be partial | Probe IPv6 at preflight; block what's detectable |

## Primary-source index

All sources retrieved or checked on **2026-07-15**.

1. [Docker packet filtering and firewalls](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
2. [Docker with iptables](https://docs.docker.com/engine/network/firewall-iptables/)
3. [Bridge network driver](https://docs.docker.com/engine/network/drivers/bridge/)
4. [Docker Desktop networking how-tos](https://docs.docker.com/desktop/features/networking/networking-how-tos/)
5. [Docker Desktop networking overview](https://docs.docker.com/desktop/features/networking/)
6. [docker/for-mac issue #2489](https://github.com/docker/for-mac/issues/2489)
7. [docker/for-mac issue #6297](https://github.com/docker/for-mac/issues/6297)
8. [docker/for-mac issue #5547](https://github.com/docker/for-mac/issues/5547)
9. [Collabnix — How Docker for Mac works](https://collabnix.com/how-docker-for-mac-works-under-the-hood/)
10. [Docker Desktop crash with iptables (Medium)](https://medium.com/@chinmayshringi4/docker-bug-docker-desktop-crash-on-macos-understanding-the-host-network-iptables-bug-3d3fc2884149)
11. [Harbor v0.18.0 task structure docs](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/docs/content/docs/tasks/index.mdx)
12. [Harbor v0.18.0 docker-compose-egress-control.yaml](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker-compose-egress-control.yaml)
13. [Harbor v0.18.0 sidecar entrypoint.sh](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/entrypoint.sh)
14. [Harbor v0.18.0 bin/network-policy](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/bin/network-policy)
15. [Harbor v0.18.0 gost.yaml](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/harbor-docker-egress-control-sidecar/gost.yaml)
16. [Harbor v0.18.0 Docker provider docker.py](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/environments/docker/docker.py)
17. [Harbor v0.18.0 network task config models](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py)
18. [Blocking EC2 metadata from Docker (ops.tips)](https://ops.tips/blog/blocking-docker-containers-from-ec2-metadata/)
19. [AWS ECS knowledge center](https://aws.amazon.com/premiumsupport/knowledge-center/ecs-container-ec2-metadata/)
20. [GCP metadata advisory (GHSA)](https://github.com/louislam/uptime-kuma/security/advisories/GHSA-qjxc-h5jf-c7rj)
21. [Docker DNS services](https://docs.docker.com/engine/network/networking/#dns-services)
22. [DNS rebinding (jsmon.sh)](https://blogs.jsmon.sh/dns-rebinding-how-a-browser-visits-your-localhost/)
23. [nccgroup Singularity framework](https://github.com/nccgroup/singularity)
24. [Docker Desktop settings — networking](https://docs.docker.com/desktop/settings-and-maintenance/settings/#networking)
25. In-repo blueprints: `blueprint/benchmark-architecture-and-reuse-boundary.md`,
    `blueprint/hermetic-execution-and-integrity.md`

## Decision

**Accept Design A for Functional V1**, with the following explicit scope:

- The coordinator installs iptables DOCKER-USER rules on Linux to block private, link-local,
  metadata, multicast, CGNAT, loopback, reserved ranges, and model-provider IP ranges.
- The coordinator deploys an egress-control sidecar with custom nftables on macOS Docker Desktop
  implementing the same blocklist, extending Harbor's existing infrastructure.
- DNS rebinding is accepted without dedicated mitigation for Functional V1.
- Egress evidence is collected from iptables/nftables logs (Linux), sidecar/gost logs (macOS),
  Credential Proxy logs, and Harbor-native result data.
- Preflight detects missing enforcement capability and rejects the Trial as `not_started`.
- Cleanup removes all rules/sidecar even on failure.
- IPv4-only enforcement is acceptable initially, with IPv6 rules added when the worker is
  confirmed to have IPv6 connectivity.
- Provider IP ranges are resolved at provision time and recorded in the Provisioning Manifest.
- The Credential Proxy is deployed per-Trial and explicitly allowed through enforcement rules.
