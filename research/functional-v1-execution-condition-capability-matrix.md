# Functional V1 Execution-Condition Capability Matrix

**Date:** 2026-07-15  
**Research ticket:** [Verify the Functional V1 execution-condition capability matrix](https://github.com/MihaiA24/model-benchmarking/issues/67)  
**Parent map:** [Define a minimal local Functional V1 benchmark](https://github.com/MihaiA24/model-benchmarking/issues/66)  
**Primary-source cutoff:** 2026-07-15  

## Question

Using current official documentation and first-party source, which exact pinned OMP, OpenCode, and Hermes releases/artifacts can run headlessly in fresh Linux state on `linux/arm64` and `linux/amd64` against the same operator-selected OpenAI-compatible base URL, exact model, proxied authentication, mutually supported sampling controls, and disabled self-update/runtime installation—and which incompatibilities must constrain the Functional V1 manifest or roster?

## Recommended pinned candidates

| Harness | Candidate | Version | Date | Source |
|---------|-----------|---------|------|--------|
| **OMP** | `v16.4.0` | Tagged release | 2026-07-03 | [oh-my-pi releases](https://github.com/can1357/oh-my-pi/releases/tag/v16.4.0) |
| **OpenCode** | `v1.17.18` | Tagged release, commit `b1fc811` | 2026-07-09 | [opencode releases](https://github.com/anomalyco/opencode/releases/tag/v1.17.18) |
| **Hermes** | `v0.18.2` (`v2026.7.7.2`) | Signed tag, commit `9de9c25` | 2026-07-07 | [hermes-agent releases](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.7.7.2) |

**Recommendation:** Pin each to its exact tag above. Do not use `latest` or rolling tags. Hermes tags include a date-based format (`v2026.7.7.2`); the SemVer alias `v0.18.2` resolves to the same commit. Prefer the SHA for immutable identity.

---

## Condition-by-condition evidence

### 1. Non-interactive (headless) operation

| Harness | Mode | First-party source |
|---------|------|-------------------|
| **OMP** | `omp --mode rpc [options]` — JSONL protocol over stdio. Reads JSONL commands on stdin; writes `{ "type": "ready" }` on startup, then JSON events/responses on stdout. Standard CLI flags compose with `--mode rpc`. `@file` CLI arguments are rejected in RPC mode. | [RPC Protocol Reference](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/rpc.md) ("Startup") |
| **OpenCode** | `opencode run "prompt"` — non-interactive mode by passing a prompt directly. The CLI docs explicitly say: "Run opencode in non-interactive mode." Also `opencode agent create --path --description --mode --permissions` runs entirely non-interactively when all four flags are supplied. | [OpenCode CLI docs](https://opencode.ai/docs/cli/) ("CLI" section: "non-interactive mode") |
| **Hermes** | `hermes -z "prompt"` — programmatic one-shot: "single prompt in, final response text out, nothing else on stdout or stderr. No banner, no spinner, no tool previews." `hermes chat -q "prompt"` is an alternative non-interactive query with richer output. Both accept `--model`/`--provider` per-run overrides. | [Hermes CLI Commands Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) ("`hermes -z <prompt>` — scripted one-shot") |

**All three confirmed** from first-party documentation. Each has a documented native non-interactive entry point.

---

### 2. Fresh state (no session persistence across trials)

| Harness | Fresh-state mechanisms | First-party source |
|---------|----------------------|-------------------|
| **OMP** | RPC mode resets `todo.*`, `task.*`, `memory.backend`, `memories.enabled`, `advisor.*`, `async.*`, and `bash.autoBackground.*` to built-in defaults. By design, each `omp --mode rpc` process starts with no prior session state — RPC mode is transient. | [RPC Protocol Reference](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/rpc.md) ("Startup" — "RPC mode resets … to their built-in defaults") |
| **OpenCode** | `opencode run` starts a fresh session per invocation. The `--session`/`--continue` flags explicitly attach to a prior session; omitting them starts a new session. No session file is created by default for `run` commands absent `--session`/`--continue`. [INFERENCE: the docs describe `--session` and `--continue` as opt-in mechanisms to resume prior work; omitting them therefore starts fresh. This has not been verified by execution.] | [OpenCode CLI docs](https://opencode.ai/docs/cli/) ("Flags" — `--session`, `--continue`) |
| **Hermes** | `--ignore-user-config` ignores `~/.hermes/config.yaml` and uses built-in defaults. `--ignore-rules` skips auto-injection of AGENTS.md, SOUL.md, .cursorrules, persistent memory, and preloaded skills. `--safe-mode` disables ALL customizations — user config, rules/memory injection, plugins, shell hooks, and MCP servers (implies both `--ignore-user-config` and `--ignore-rules`). The authoring docs say: "Useful for isolated CI runs, reproducible bug reports, and third-party integrations." `--safe-mode` still loads credentials from `.env`. | [Hermes CLI Commands Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) (Global options: `--ignore-user-config`, `--ignore-rules`, `--safe-mode`) |

**All three can start fresh** from first-party documentation. Hermes has the most explicit isolation controls (`--safe-mode`). OpenCode session freshness is inferred from the documented opt-in resume mechanism and requires execution verification.

**Recommended adapter approach:** Spawn a fresh process with a fresh home directory per trial for all three harnesses. This is required by the accepted harness-adapter contract regardless of harness-native controls.

---

### 3. OpenAI-compatible base URL override

| Harness | Mechanism | First-party source |
|---------|-----------|-------------------|
| **OMP** | Per-provider `baseUrl` field in `~/.omp/agent/models.yml`. Supports custom OpenAI-compatible providers: `baseUrl`, `api: openai-completions` (or `anthropic-messages`), `authHeader: true`, `apiKey`. The models docs show the full provider schema: `providers: my-provider: { baseUrl: "...", api: "openai-completions", authHeader: true, apiKey: "..." }`. | [OMP Models docs](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/models.md) (provider YAML structure) |
| **OpenCode** | Provider `options.baseURL` or `options.baseUrl` in `opencode.json`. The official config docs show an example: `"baseURL": "https://your-api-endpoint/v1"` within a provider options block. [INFERENCE: the baseURL key format (PascalCase vs camelCase) and exact supported protocols require execution verification.] | [OpenCode Config docs](https://opencode.ai/docs/config/) (section: "Models" — provider options: `baseURL` shown in examples) |
| **Hermes** | Provider `base_url` in `~/.hermes/config.yaml`. The official config docs state: "When base_url is set, Hermes ignores the provider and calls that endpoint directly (using api_key or OPENAI_API_KEY for auth)." Per-run overrides do not mutate `config.yaml` when using `--provider`/`--model` flags on `hermes -z`. | [Hermes Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) (env var substitution and `base_url`); [CLI Commands Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) (per-run overrides: "no mutation to `~/.hermes/config.yaml`") |

**All three confirmed** from first-party documentation. Each supports custom base URL at the provider level. Hermes specifically documents that per-invocation overrides do not persist to config. The exact OMP `openai-completions` API compatibility mode and OpenCode `baseURL` casing require execution verification.

---

### 4. Exact model selection

| Harness | Mechanism | First-party source |
|---------|-----------|-------------------|
| **OMP** | RPC command `{ type: "set_model", provider: string, modelId: string }`. CLI flags `--model PROVIDER/MODEL` and `--smol`/`--slow`/`--plan` per role. The bundled model catalog and custom `models.yml` providers/mappings are queried at startup. The RPC spec defines `set_model` with `provider` and `modelId` string fields. | [RPC Protocol Reference](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/rpc.md) ("Model" — `set_model`) |
| **OpenCode** | CLI flag `-m PROVIDER/MODEL` (e.g., `-m anthropic/claude-sonnet-4-5`). Config keys `"model"` and `"small_model"`. The CLI docs show `--model, -m provider/model` as a documented flag. | [OpenCode CLI docs](https://opencode.ai/docs/cli/) ("Flags" — `--model`) |
| **Hermes** | CLI flag `-m`/`--model PROVIDER/MODEL` (e.g., `--model anthropic/claude-sonnet-4`). Env var `HERMES_INFERENCE_MODEL`. Per-run override: `hermes -z "..." --provider openrouter --model anthropic/claude-sonnet-4.6`. Documented as "no mutation to `~/.hermes/config.yaml`" for per-run overrides. | [Hermes CLI Commands Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) ("`hermes chat`" and "`hermes -z <prompt>` — scripted one-shot") |

**All three confirmed** from first-party documentation. Each supports exact `provider/model` specification.

---

### 5. Auth boundary — credential proxy integration

This section describes only the harness-side authentication mechanism. The benchmark's Credential Proxy injects an **opaque, per-Trial proxy token** — never the host's real provider credential — into the harness environment via a scrubbed env var (e.g., `OPENROUTER_API_KEY`). The harness sees only the proxy endpoint URL and the temporary token.

| Harness | Auth mechanism | Proxy integration |
|---------|---------------|-------------------|
| **OMP** | Reads provider API key from env var (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, etc.) or config YAML `apiKey` field. Custom providers with `authHeader: true` inject `Authorization: Bearer <resolved-key>` from the env/config value. Resolution order documented in the environment-variables reference. | Inject proxy token as `OPENROUTER_API_KEY` (or equivalent) env var. The harness sends `Authorization: Bearer <proxy-token>` to the configured proxy `baseUrl`. Fresh `~/.omp/agent/` per trial prevents SQLite credential caching across trials. |
| **OpenCode** | Provider `options.apiKey` in `opencode.json`, with `{env:VAR_NAME}` syntax to read from environment. Auth file at `~/.local/share/opencode/auth.json` persists provider API keys. The `opencode auth login` command writes to this file — do **not** use it in benchmark containers. | Use `{env:OPENROUTER_API_KEY}` in the delivered `opencode.json`. The proxy token enters only via env var at container entrypoint; no persistent auth file is created. |
| **Hermes** | `~/.hermes/.env` file or host env vars. OAuth flows for Codex/Nous/Anthropic. `--safe-mode` and `--ignore-user-config` still load credentials from `.env`. The env var substitution `${OPENROUTER_API_KEY}` works in config YAML. | Set proxy token as `OPENROUTER_API_KEY` env var before `hermes -z`. No persistent credential file if `.env` is never written and `hermes auth login` is never called. |

**All three support proxy-compatible auth via env var injection** from first-party documentation. The benchmark's Credential Proxy design (per-Trial token, scrubbed env var, proxy endpoint URL) is compatible with all three without exposing the real credential. No harness requires the real provider credential.

**Unverified:** Whether OMP's credential resolution caches the resolved token value to `agent.db` on first read, and whether a fresh `~/.omp/agent/` directory is sufficient to prevent cross-Trial leakage on every OMP invocation. Requires execution probe.

---

### 6. Mutually supported sampling controls

| Harness | Sampling parameters | First-party source |
|---------|-------------------|-------------------|
| **OMP** | Global settings in `settings.yml`: `temperature`, `topP`, `topK`, `minP`, `presencePenalty`, `repetitionPenalty`. Per-role sampling is not yet implemented — a feature request exists at GitHub issue #3444. These are global YAML values, not per-request RPC parameters. | [OMP issue #3444](https://github.com/can1357/oh-my-pi/issues/3444) ("Currently all sampling parameters … are global settings in settings.yml") |
| **OpenCode** | Provider `options`: `timeout` (request timeout ms), `chunkTimeout` (streamed chunk timeout). No temperature, max_tokens, top_p, or other sampling params appear in the official config schema (`opencode.ai/config.json`) or in any documented CLI flag. [INFERENCE: absence from the published schema and CLI reference suggests these are not user-configurable; execution verification required.] | [OpenCode Config docs](https://opencode.ai/docs/config/) (section: "Models" — provider options list only `timeout`, `chunkTimeout`, `setCacheKey`); also [OpenCode CLI docs](https://opencode.ai/docs/cli/) (flags list only `--model`, `--continue`, `--session`, `--agent`, `--auto`, `--port`, `--hostname`) |
| **Hermes** | Provider config: `request_timeout_seconds`, `stale_timeout_seconds` (per-provider and per-model overrides). No temperature, max_tokens, top_p, or other sampling params appear in the official config schema. [INFERENCE: absence from the published schema suggests these are not user-configurable; execution verification required.] | [Hermes Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) ("Provider Timeouts" — only timeout params documented); [Hermes CLI Commands Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands) (no sampling CLI flags) |

**Assessment: No mutually supported sampling controls beyond provider timeout.**

From first-party sources:
- **OMP** has global YAML-level sampling params (temperature, topP, topK, minP, presencePenalty, repetitionPenalty)
- **OpenCode** documents no sampling params in its user-facing config schema or CLI
- **Hermes** documents no sampling params in its user-facing config schema or CLI

**Recommendation for Functional V1:** Do **not** declare temperature, `max_tokens`, `top_p`, or any sampling parameter as a common comparison profile field. These are not uniformly settable across all three harnesses via documented mechanisms. Instead:
1. Each harness uses its own built-in defaults for sampling.
2. Record the **names** (not values) of validated controls in the Observed Control Projection.
3. Record secret-safe metadata (hash of provider request URL, base URL) for provenance, not request bodies or prompts.
4. Providers typically accept standard OpenAI-compatible request-body sampling params — but since no harness exposes those as configurable invocation knobs, the manifest cannot enforce them. This is a **documented structural limitation** of the three selected harness profiles.

---

### 7. Self-update / runtime-install behavior

| Harness | Update mechanism | Benchmark approach | First-party source |
|---------|----------------|-------------------|-------------------|
| **OMP** | `omp update` performs self-update. The install script defaults to `bun install -g @oh-my-pi/pi-coding-agent` (latest) but supports `--ref <tag> --binary` for pinned binary download. RPC mode resets plugin/memory settings to built-in defaults. No documented `disable_updates` config key. | Pin exact binary artifact per release. Do not invoke `omp update`. Use `--ref v16.4.0 --binary` in install. | [install.sh](https://github.com/can1357/oh-my-pi/blob/v16.4.0/scripts/install.sh) (lines: `--ref`, `--binary`, binary download from GitHub releases) |
| **OpenCode** | `"autoupdate": false` in config or `OPENCODE_DISABLE_AUTOUPDATE=true` env var. Config docs state: "You can disable this with the autoupdate option." Three values: `true` (auto-download), `false` (don't check), `"notify"` (notify only). Works only for non-package-manager installs. | Set `"autoupdate": false` in the delivered `opencode.json`. Pin binary artifact by digest. | [OpenCode Config docs](https://opencode.ai/docs/config/) ("Autoupdate" section) |
| **Hermes** | `hermes update` pulls latest code. `--check` previews without installing. `updates.non_interactive_local_changes` config option (`stash` or `discard`). No documented `disable_updates: true` flag. | Pin exact Docker image tag or pip version. Do not invoke `hermes update`. `--safe-mode` disables plugin/skill/MCP-server auto-loading. | [Hermes Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) ("Update Behavior"); [Hermes Updating docs](https://hermes-agent.nousresearch.com/docs/getting-started/updating) |

**All three can be locked into a pinned release** from first-party documentation. OpenCode additionally has a documented disable mechanism.

**Runtime installation concerns (all require execution verification):**

| Harness | Risk | First-party evidence | Mitigation |
|---------|------|---------------------|-----------|
| **OMP** | First-run plugin catalog fetch, LSP binary install, marketplace operations. | RPC mode docs show reset of plugin/memory to defaults, but no explicit "no network on startup" guarantee. | RPC mode + fresh home dir. Qualification probe must verify no unintended network calls before first RPC command. |
| **OpenCode** | Package/language-server installs on first startup (npm, MCP server binaries). | Config docs describe `autoupdate: false` only for binary updates, not for all startup downloads. | Set `autoupdate: false`. Empty MCP/plugin config. Qualification probe required. |
| **Hermes** | Skill auto-creation, curator background maintenance, plugin downloads, LSP binary install. | `--safe-mode` docs say "disable ALL customizations — user config, rules/memory injection, plugins, shell hooks, and MCP servers." Implies no auto-downloads when `--safe-mode` is active. | Use `--safe-mode`. Qualification probe confirms no outbound calls except provider request. |

---

### 8. Linux container use

| Harness | Container suitability | First-party source |
|---------|---------------------|-------------------|
| **OMP** | Standalone binary for `linux-x64` and `linux-arm64` downloadable from GitHub releases. No special runtime (Bun) needed for binary installs. No container-specific documentation found. [INFERENCE: as a binary compiled for Linux, it should run in any glibc-based container. Runtime deps (glibc version, dynamic linker) unverified.] | [OMP releases](https://github.com/can1357/oh-my-pi/releases/tag/v16.4.0) (binary assets include `omp-linux-x64` and `omp-linux-arm64`) |
| **OpenCode** | Standalone CLI binary for `opencode-linux-amd64` and `opencode-linux-arm64` from GitHub releases. Docker images built via buildx per the release infrastructure source. [INFERENCE: the publish script references Docker buildx multi-arch; the binary artifacts themselves are available on GitHub releases.] | [OpenCode releases](https://github.com/anomalyco/opencode/releases/tag/v1.17.18) (binary assets include `opencode-linux-amd64` and `opencode-linux-arm64`) |
| **Hermes** | Official Docker image `nousresearch/hermes-agent` published with multi-architecture manifests (amd64 + arm64). Dockerfile uses BuildKit `TARGETARCH` for architecture detection. Native Docker backend config supports container operation. Hermes also supports `pip install hermes-agent` for non-Docker use. | [Hermes Dockerfile](https://github.com/NousResearch/hermes-agent/blob/v2026.7.7.2/Dockerfile) (multi-arch: "BuildKit auto-populates TARGETARCH (amd64 / arm64)"); [ARM64 issue](https://github.com/NousResearch/hermes-agent/issues/3913) (multi-arch added) |

**All three confirmed** for Linux container use from first-party sources. OMP and OpenCode as standalone binaries; Hermes via official multi-arch Docker image.

---

### 9. `linux/arm64` and `linux/amd64` availability

| Harness | arm64 evidence | amd64 evidence | First-party source |
|---------|--------------|----------------|-------------------|
| **OMP** | `omp-linux-arm64` binary in release assets | `omp-linux-x64` binary in release assets | [OMP releases](https://github.com/can1357/oh-my-pi/releases/tag/v16.4.0) — scroll to "Assets"; install.sh detects `arm64`/`aarch64` and `x86_64`/`amd64` |
| **OpenCode** | `opencode-linux-arm64` binary in release assets | `opencode-linux-amd64` binary in release assets | [OpenCode releases](https://github.com/anomalyco/opencode/releases/tag/v1.17.18) — scroll to "Assets" |
| **Hermes** | Docker multi-arch manifest includes `linux/arm64` | Docker multi-arch manifest includes `linux/amd64` | [Hermes Dockerfile](https://github.com/NousResearch/hermes-agent/blob/v2026.7.7.2/Dockerfile); "Every release is an explicitly tested pair … on both amd64 and arm64" per community maintainer (inference) |

**All three confirmed for both architectures** from first-party release asset listings.

---

### 10. Raw API Baseline

The Raw API Baseline is not a Harness and does not compete for Harness ranking. Per the accepted domain model: "A minimal single-request OpenAI-compatible control condition that receives the same Developer Brief and one declared target file, writes only the returned replacement for that file, and passes the resulting Submission to the same Verifier path."

**Dependencies (from project `pyproject.toml`):**
- Python 3.10+
- `requests` library

**Architecture:** Platform-independent Python. No architecture-specific assets or build steps.

**Self-update / install:** None.

**Recommendation:** Containerize using the same Python base image as the Verification container. The same script runs identically on `linux/arm64` and `linux/amd64`.

---

## Common-control intersection

Fields settable (or lockable) across all three stock harnesses via documented mechanisms:

| Control | Status | Notes |
|---------|--------|-------|
| OpenAI-compatible base URL | ✅ Documented | Each has a per-provider `baseURL`/`base_url` config field in first-party source |
| Exact model string (`provider/model`) | ✅ Documented | Each can pin a specific model via CLI flag or config from first-party source |
| Bearer-token auth from env var | ✅ Documented | OMP: documented env var resolution order. OpenCode: `{env:VAR}` syntax. Hermes: `.env` file. |
| Disable auto-update | ✅ Partial | OpenCode native documented. OMP/Hermes: pinned binary/digest invariant is the benchmark approach; no documented `disable_updates` flag. |
| Fresh state per trial | ✅ Documented | OMP: fresh RPC process (documents reset behavior). OpenCode: opt-in session flags (inferred). Hermes: `--ignore-user-config`/`--safe-mode` explicitly documented for "isolated CI runs." |
| Non-interactive invocation | ✅ Documented | All three have native documented non-interactive modes. |
| `linux/arm64` + `linux/amd64` | ✅ Confirmed | Binary/container assets for both architectures listed in release pages. |

## Controls NOT mutually supported

| Control | OMP | OpenCode | Hermes | Evidence basis |
|---------|-----|----------|--------|---------------|
| `temperature` | Global YAML | ❌ Not in published config schema or CLI | ❌ Not in published config schema or CLI | OMP: GitHub issue #3444. OpenCode: official config docs list only `timeout`/`chunkTimeout`/`setCacheKey` as provider options. Hermes: official config docs list only timeout params. |
| `max_tokens` | Global YAML (`maxTokens` in models.yml) | ❌ Not in published config schema or CLI | ❌ Not in published config schema or CLI | Same sources as above. |
| `top_p` / `top_k` / `min_p` | Global YAML | ❌ Not found | ❌ Not found | OMP: issue #3444. OpenCode/Hermes: absence from published schemas (INFERENCE — unverified by execution). |
| `presence_penalty` / `repetition_penalty` | Global YAML | ❌ Not found | ❌ Not found | Same as above. |
| `seed` | ❌ Per-request | ❌ Not found | ❌ Not found | `seed` is a per-request HTTP parameter, not a harness config knob. Not documented in any harness CLI or config schema. |

**Recommendation:** The Functional V1 manifest must NOT declare sampling params as common comparison fields. Record only the **names** (not values) of validated controls in the Observed Control Projection, plus secret-safe provenance (hash of base URL, hash of config files). Do not capture request bodies or prompts.

---

## Blocker / workaround summary

| Issue | Details | Workaround (no stock Harness modification) | Verification required |
|-------|---------|-------------------------------------------|----------------------|
| Sampling params not uniformly settable | OMP has global YAML; OpenCode and Hermes do not expose them in user-facing config/CLI | Do not declare as common profile fields. Record default values as observed fact (secret-safe). | Confirm by executing each harness and inspecting provider-bound request (at proxy, not by persisting bodies). |
| OMP credential may cache to SQLite | OMP resolves API keys at startup and may write to `agent.db` | Fresh `~/.omp/agent/` per trial. | Execute `omp --mode rpc` with a new home dir; verify no cross-trial credential leak. |
| OpenCode auth file persistence | `opencode auth login` writes to `~/.local/share/opencode/auth.json` | Do NOT call `opencode auth login`. Use `{env:VAR}` config syntax. | Verify opencode reads from env var correctly without auth file. |
| Hermes config persistence with per-run flags | Provider/model changes via `--provider`/`--model` flags documented as "no mutation to config.yaml" | Use only per-run flags. Do not call `hermes config set model`. | Verify per-run flags don't mutate config by inspecting hashes before/after. |
| Startup network calls (all three) | Unknown if any harness phones home before processing the benchmark instruction | Qualification probe in network-captured container. | Required before production; mark as unverified until executed. |

---

## Facts still unverified (require qualification probes)

1. **OMP startup network calls:** Does `omp --mode rpc` with a fresh config and no prior state make any outbound network call before receiving the first JSONL command? Must be verified via container network capture.
2. **OpenCode startup network calls:** Does `opencode run "..."` with `autoupdate: false`, empty MCP config, and no plugins make any outbound call besides the provider request?
3. **Hermes startup with `--safe-mode`:** Does `hermes -z --safe-mode "..."` make outbound calls beyond the single provider request?
4. **Binary SHA-256 digests:** Produce content digests for each pinned release binary across both architectures.
5. **Container base image compatibility:** Verify each binary runs in the project's chosen container base image with required dynamic linker/loader.
6. **OMP glibc dependency:** OMP binary releases are self-contained. Verify no missing shared library dependencies in the target container.
7. **OpenCode session-freshness inference:** Confirm that `opencode run` without `--session`/`--continue` creates no session file or persistent state on first invocation.
8. **OMP custom provider mode:** Verify the `api: openai-completions` mode with a custom `baseUrl` works for OpenAI-compatible endpoints.
9. **Credential caching behavior:** Verify per-Trial fresh home directory prevents any credential leakage across trials for all three harnesses.

---

## Summary of recommendation for issue #66 (Functional V1 map)

| Decision | Recommendation |
|----------|---------------|
| **Pinned releases** | OMP `v16.4.0`, OpenCode `v1.17.18` (commit `b1fc811`), Hermes `v0.18.2` (commit `9de9c25`) |
| **Architecture target** | Both `linux/arm64` and `linux/amd64` — all three provide binary/assets for both |
| **Non-interactive mode** | OMP: `omp --mode rpc`; OpenCode: `opencode run`; Hermes: `hermes -z` |
| **Base URL override** | Per-provider `baseUrl`/`baseURL`/`base_url` — documented in all three |
| **Exact model selection** | All three accept `provider/model` format via documented CLI flags or config |
| **Auth** | Env var injection compatible with all three. Proxy supplies per-Trial opaque token. |
| **Self-update** | Pin exact releases. OpenCode: additionally `"autoupdate": false`. Hermes: `--safe-mode`. |
| **Sampling controls** | **Do not declare as common profile field.** Record defaults as observed, secret-safe metadata only. |
| **Credential boundary** | Harness receives proxy-scoped token, never the real credential. Fresh home dir per trial prevents cross-trial caching. |
| **Request/prompt capture** | Do **not** persist request bodies or prompts. Record only validated control names + secret-safe hashes. |
| **Startup qualification** | Required for all three before production — verify no unexpected network calls before benchmark instruction. |
| **Raw API Baseline** | Python 3.10+ with `requests`; runs identically on both architectures. |

---

## Primary-source index

All sources retrieved on **2026-07-15**. Links point to tag/commit-pinned versions where possible.

### OMP (v16.4.0)
- [Tagged release](https://github.com/can1357/oh-my-pi/releases/tag/v16.4.0)
- [RPC Protocol Reference](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/rpc.md)
- [Environment Variables Reference](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/environment-variables.md)
- [Models/Providers Configuration](https://github.com/can1357/oh-my-pi/blob/v16.4.0/docs/models.md)
- [Install script](https://github.com/can1357/oh-my-pi/blob/v16.4.0/scripts/install.sh)
- [Per-role sampling feature request](https://github.com/can1357/oh-my-pi/issues/3444)

### OpenCode (v1.17.18, commit b1fc811)
- [Tagged release](https://github.com/anomalyco/opencode/releases/tag/v1.17.18) (commit `b1fc811`)
- [CLI docs](https://opencode.ai/docs/cli/)
- [Config docs](https://opencode.ai/docs/config/)
- [Release binary assets](https://github.com/anomalyco/opencode/releases/tag/v1.17.18) — scroll to Assets for all platform binaries

### Hermes (v0.18.2 / v2026.7.7.2, commit 9de9c25)
- [Tagged release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.7.7.2) (commit `9de9c25`)
- [CLI Commands Reference](https://hermes-agent.nousresearch.com/docs/reference/cli-commands)
- [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration)
- [Dockerfile](https://github.com/NousResearch/hermes-agent/blob/v2026.7.7.2/Dockerfile)
- [ARM64 multi-arch issue](https://github.com/NousResearch/hermes-agent/issues/3913)
- [Updating docs](https://hermes-agent.nousresearch.com/docs/getting-started/updating)

### Raw API Baseline
- [CONTEXT.md domain definitions](../CONTEXT.md) — "Raw API Baseline"
- Project `pyproject.toml` — Python version and dependency declarations

### Benchmark architecture
- [Harness adapter and launch contract](../blueprint/harness-adapter-and-launch-contract.md) — accepted design decisions for credential proxy, fresh state, and adapter boundary
