# MiniMax M3 tiered-pricing audit — OpenCode Go — 2026-07-23

**Decision:** **Do not start the paid three-model Campaign from the current handoff.** The actual handoff catalog has not drifted, but its qualification did not validate either MiniMax M3's model-specific transport or its tier/cache pricing shape. Official OpenCode Go billing documentation publishes flat MiniMax M3 rates, while the official Models.dev raw catalog publishes a doubled `>512,000`-input-token tier for the same `opencode-go/minimax-m3` entry. Public primary sources do not resolve which rule the Go billing service actually applies. The supported documented MiniMax route is Anthropic Messages, while the qualified implementation forces OpenAI Chat Completions. A no-spend repair and requalification can proceed; a provider completion cannot safely proceed.

**Spend statement:** This audit made **no credentialed request, no model-completion request, and no paid/provider request**. It fetched public documentation, public source history, the public Models.dev catalog, and the public handoff evidence only. Tests, linters, and formatters were not run.

## Scope and investigated versions

| Item | Audited identity/version | Observation time |
|---|---|---|
| Qualified benchmark checkout | `50909cba08088d0cb9fe8d99761a5a13ece9346a` | handoff evidence sealed 2026-07-23 |
| Actual handoff qualification | `dry-launch-qualification:sha256:4f5fc161d699e63a1492c062ad2a6a305f958a0ddca0884006329c525a2c4a70` | catalog retrieved `2026-07-23T06:28:24.575171Z`; qualification sealed `2026-07-23T06:33:23.445461Z` |
| Actual handoff/current catalog | SHA-256 `0fde178efd91764a20ae11948d9c26cdaad216a76efcd48590904962b77bb48e` | re-fetched and hashed `2026-07-23T07:08:24Z` |
| Older committed qualification | catalog SHA-256 `630eeb477845971d1fdfcf8d3c00a517eb0152c3c648c256388ddeb98d516e5f` | retrieved `2026-07-23T01:53:17.362168Z`; sealed `2026-07-23T02:01:10.809167Z` |
| Models.dev source | `dev` at `4a14b64ce3970c7e681f00e05899c638f044b7d5` | commit time `2026-07-23T03:36:15Z`; still branch head when audited |
| OpenCode Go docs source | `go.mdx` at `411eff73f026d4950c07947c4d983788cb615baa` | latest change to that file before and through the handoff; live page says “Last updated: Jul 22, 2026” |
| Qualified route | `https://opencode.ai/zen/go/v1` | manifest and handoff qualification |
| Qualified flat Pricing Record | `$0.30/M` input; `$1.20/M` output | `functional-v1-minimax-m3.yaml` |

## Correction: which qualification is the handoff

### Observed facts

The public handoff [Gist](https://gist.github.com/MihaiA24/b5dd749d2ed763f263684135b86d8937) identifies qualification `4f5fc161…`, checkout `50909cba…`, catalog retrieval at `06:28:24Z`, catalog SHA `0fde178e…`, zero external requests, and zero external cost. This is the qualification named by `.integration-worktree/.benchmark-cache/PAID-CAMPAIGN-HANDOFF.md`.

The tracked [older qualification artifact](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/artifacts/qualification/functional-v1/dry-launch-qualification.json) records the earlier `01:53:17Z` retrieval and catalog SHA `630eeb47…`. Its record identity is `dry-launch-qualification:sha256:dd9e03fe5a5d83beaad5b6e8e570f59c11e1a94f4b0c795702ee78291f0a921a`; it is **not** the handoff identity.

The catalog fetched at `07:08:24Z` hashed to `0fde178e…`, exactly the handoff catalog hash. Therefore **there is no observed catalog drift from the actual handoff qualification to this audit**. The difference between `630e…` and `0fde…` is a difference between an older committed artifact and the later handoff artifact, not evidence that the handoff catalog changed.

## 1. Models.dev and OpenCode Go history

### Models.dev `opencode-go/minimax-m3`

Observed source history:

1. Models.dev PR [#2774](https://github.com/anomalyco/models.dev/pull/2774), merged `2026-06-24T16:14:58Z`, says verbatim: “add a pricing tier for MiniMax M3 contexts above 512k tokens” and “set input, output, and cache-read prices to 2x the base rates.” Its commit is [`d77f5969…`](https://github.com/anomalyco/models.dev/commit/d77f5969759714194b5d1de4aa2c6a6b4858bf97).
2. Commit [`56873935…`](https://github.com/anomalyco/models.dev/commit/5687393566252ded4618a0eff5d26f23a29e3b77) on 2026-06-30/07-01 restored the Go rates from `$0.10/$0.40/$0.02` to `$0.30/$1.20/$0.06` and doubled the tier to `$0.60/$2.40/$0.12`.
3. The entry's last later edit was a display-name change on 2026-07-02. No commit after that changed this file through Models.dev source head `4a14b64…`, including the interval after both qualification timestamps.
4. At qualification-era source revision `4a14b64…`, the provider-specific [TOML entry](https://github.com/anomalyco/models.dev/blob/4a14b64ce3970c7e681f00e05899c638f044b7d5/providers/opencode-go/models/minimax-m3.toml#L14-L34) contains exactly:

   ```toml
   [cost]
   input = 0.3
   output = 1.2
   cache_read = 0.06

   [[cost.tiers]]
   tier = { size = 512_000 }
   input = 0.6
   output = 2.4
   cache_read = 0.12
   ...
   [provider]
   npm = "@ai-sdk/anthropic"
   ```

5. The live [`api.json`](https://models.dev/api.json) at `07:08:24Z` had the handoff SHA `0fde178e…` and its exact `opencode-go.models.minimax-m3` object included:

   ```json
   {
     "provider": {"npm": "@ai-sdk/anthropic"},
     "limit": {"context": 1000000, "output": 131072},
     "cost": {
       "input": 0.3,
       "output": 1.2,
       "cache_read": 0.06,
       "tiers": [{
         "input": 0.6,
         "output": 2.4,
         "cache_read": 0.12,
         "tier": {"type": "context", "size": 512000}
       }],
       "context_over_200k": {"input": 0.6, "output": 2.4, "cache_read": 0.12}
     }
   }
   ```

6. The rendered [Models.dev OpenCode Go provider page](https://models.dev/providers/opencode-go/) shows MiniMax M3 as `1,000,000` context, `131,072` output, and only `$0.30 / $1.20`; it does not render the nested tier. Thus the rendered page and raw API present materially different pricing detail.

### Meaning of `context_over_200k` in Models.dev

The raw field name is a compatibility artifact, not the threshold. The qualification-era [schema](https://github.com/anomalyco/models.dev/blob/4a14b64ce3970c7e681f00e05899c638f044b7d5/packages/core/src/schema.ts#L72-L111) defines an exact context tier with `tier.type = "context"` and an integer `tier.size`. The [generator](https://github.com/anomalyco/models.dev/blob/4a14b64ce3970c7e681f00e05899c638f044b7d5/packages/core/src/generate.ts#L230-L276) says verbatim:

> `context_over_200k is a legacy compatibility field. It intentionally`
> `includes higher thresholds; cost.tiers carries the exact threshold.`

It emits `context_over_200k` for a sole context tier whose size is **at least** 200,000. For MiniMax M3 the exact threshold is therefore `512,000`, not `200,000`.

### OpenCode Go route-specific docs

The qualification-era official Go docs source is the stable [`411eff73…` permalink](https://github.com/anomalyco/opencode/blob/411eff73f026d4950c07947c4d983788cb615baa/packages/web/src/content/docs/go.mdx#L83-L153); the same material is on the live [OpenCode Go docs](https://opencode.ai/docs/go/). It states that Go's limits are dollar-valued (`$12`/5-hour, `$30`/week, `$60`/month). Its price table lists MiniMax M3 once, with flat `$0.30` input, `$1.20` output, and `$0.06` cached-read rates. The same table explicitly splits Qwen3.7 Plus and Qwen3.6 Plus into `≤256K` and `>256K` rows. It does **not** split MiniMax M3.

OpenCode originally added M3 on 2026-05-31 with `$0.60/$2.40/$0.12`; commit [`1772e8ee…`](https://github.com/anomalyco/opencode/commit/1772e8ee6e794d1241dac6fa10d28e708f53b881) changed it on 2026-06-08 to the current flat `$0.30/$1.20/$0.06`. Subsequent edits through the July 22 source revision retained that row while adding/updating other models and explicit tiers.

The official [endpoint table](https://github.com/anomalyco/opencode/blob/411eff73f026d4950c07947c4d983788cb615baa/packages/web/src/content/docs/go.mdx#L185-L208) specifies MiniMax M3 as:

```text
model minimax-m3 → https://opencode.ai/zen/go/v1/messages → @ai-sdk/anthropic
```

That endpoint has been present since the model was introduced in commit [`c5737983…`](https://github.com/anomalyco/opencode/commit/c57379833e3f25967c03653482fc3131b3068c04). No official source found in this audit documents `https://opencode.ai/zen/go/v1/chat/completions` as a supported MiniMax M3 Go endpoint. Absence is not proof that an undocumented compatibility route cannot exist; without a credentialed probe or public server source, `chat/completions` support is **unresolved**. The documented contract is `/messages`.

## 2. Did the sealed catalog bytes contain the tier?

### Actual handoff SHA `0fde178e…`: yes

**Observed fact:** the public catalog fetched during this audit is byte-identified by the same SHA-256 as the actual handoff catalog. Its MiniMax M3 object contains both `cost.tiers` and `cost.context_over_200k`. Under the qualification's SHA-256 identity convention, the handoff bytes therefore contained those fields.

### Older committed SHA `630eeb47…`: exact bytes not recovered

**Observed fact:** the older qualification stores the digest and selected projections, not the response body. The collector [reads `catalog_bytes`, hashes them, and writes only the digest plus `_manifest_catalog_entry` projections](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/dry_launch_qualification.py#L162-L204). The projection records only base input/output costs. No retained catalog body with SHA `630e…` was found. A digest alone cannot recover or prove a nested field.

**Inference, strongly supported but not byte-proven:** `630e…` likely also contained the tier. The provider-specific tier entered source on June 24, exact base/tier rates were restored by July 1, and the entry did not change after July 2; the older retrieval was July 23. However, because the exact response bytes were not sealed and deployment state was not independently reconstructed to a matching whole-document hash, this remains an inference rather than an observed fact.

## 3. What triggers the tier, and does OpenCode Go bill it?

### Direct MiniMax API semantics: `>512k` input tokens

MiniMax's official [pay-as-you-go pricing](https://platform.minimax.io/docs/guides/pricing-paygo.md) labels the bands verbatim as `≤ 512k input tokens` and `> 512k input tokens`. For standard service, the latter doubles all three published rates from `$0.30/$1.20/$0.06` to `$0.60/$2.40/$0.12`. Therefore, for the direct MiniMax API:

- the discriminator is **input-token count**, not output tokens and not input-plus-output total;
- the threshold is **strictly greater than 512k**, not greater than 200k;
- when the higher band applies, its row supplies higher input, output, and cache-read rates.

MiniMax's official [Anthropic-compatible cache documentation](https://platform.minimax.io/docs/api-reference/anthropic-api-compatible-cache.md) defines:

```text
total_input_tokens = cache_read_input_tokens
                   + cache_creation_input_tokens
                   + input_tokens
```

and explains that `input_tokens` alone is only the uncached portion after the last breakpoint.

**Inference:** the direct MiniMax `>512k input tokens` discriminator is per request and uses that request's total input, including cached-read and cache-creation input. The docs separately define total input this way, but the pricing page does not explicitly repeat the formula beside the tier, so cached-token threshold treatment is not quoted as a standalone billing rule. No source supports a Campaign-cumulative or conversation-lifetime discriminator.

### OpenCode Go billing: conflicting public primary sources

- **Evidence for flat Go billing:** OpenCode's route-specific Go docs define limits in dollar value and publish one flat MiniMax row; they explicitly show tiers for models whose Go pricing is tiered. The rendered Models.dev provider page also shows only the flat pair.
- **Evidence for tiered Go billing:** the provider-specific Models.dev source, PR #2774, and raw API explicitly attach the `512,000` doubled tier to `opencode-go/minimax-m3`. This is not merely the provider-agnostic MiniMax model file.
- **Missing authority:** no public OpenCode Go billing-service implementation or route-specific statement was found that explains the discrepancy. No paid/credentialed request was made, and a single billed response would not safely establish every threshold/cache case anyway.

**Conclusion:** whether OpenCode Go actually debits the doubled tier is **unresolved in public primary sources**. The official Go docs are the more route-specific customer billing statement and support the flat interpretation, but the official raw catalog contradicts them. It is unsafe to make a `$25` launch decision by silently choosing either source.

## 4. Can the committed flat Pricing Record faithfully derive provider cost?

**No, not for the complete published contract.** It is faithful only under the unproven assumptions that Go bills flat, no separately priced cache tokens need accounting, and returned `input_tokens` already includes every billable input token.

Observed implementation facts at qualified commit `50909cba…`:

1. The [MiniMax manifest](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/functional-v1-minimax-m3.yaml#L3-L20) seals only base URL, model, flat input/output rates, and a flat Pricing Record identity. It has no tier threshold, tier rates, cache-read rate, or token-composition rule.
2. [`PricingRecord.cost_usd`](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L62-L103) computes only `input_tokens × flat_input_rate + output_tokens × flat_output_rate`.
3. The response observer [accepts `prompt_tokens`/`input_tokens` and `completion_tokens`/`output_tokens`](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L270-L351), but not `cache_read_input_tokens` or `cache_creation_input_tokens`. When a Pricing Record exists, `_accounted_cost` derives the flat cost and does not use a provider-reported `cost` value.
4. The [catalog validator](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/dry_launch_qualification.py#L102-L150) compares only `cost.input`, `cost.output`, and the top-level provider `api` base URL. It ignores `cost.tiers`, `context_over_200k`, `cache_read`, and the model-level `provider.npm`.
5. Its live-route check [HEADs only the base URL](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/dry_launch_qualification.py#L85-L99); any HTTP status from 100 through 599 is accepted. The handoff recorded 404. This proves reachability, not model/endpoint compatibility.

The cache omission is material even if Go is flat: MiniMax's Anthropic usage example reports uncached `input_tokens`, `cache_read_input_tokens`, and `cache_creation_input_tokens` separately. The current derived-cost path would not price the latter two fields.

## 5. Independent transport blind spot

The official OpenCode docs and model-specific Models.dev entry agree on Anthropic Messages. The qualification does not:

- the sealed OpenCode condition [locks `@ai-sdk/openai-compatible`](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/opencode.py#L98-L119);
- the Credential Proxy [allows only `/chat/completions`](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L93-L103) and rejects other paths at [request validation](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L541-L556);
- the Raw API condition [hard-codes `/chat/completions`](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/raw_api.py#L162-L211); and
- the no-spend qualification used a loopback deterministic provider, so its successful cells did not exercise the live `/messages` contract.

Thus the dry launch proves the four clients can talk to the local OpenAI-shaped substitute. It does not prove that any MiniMax M3 Campaign cell can use the documented Go endpoint or parse its Anthropic usage/cache fields.

## 6. Budget effect

The Campaign rule requires a sealed worst-case bound plus one in-flight response overshoot to remain within `$25`. Using the handoff catalog limits, `375,000` provider-token stop per cell, 16 cells per model, and the existing conservative bound (all stop tokens at the more expensive input/output rate, then one full-context input plus `output_limit - 1` output as final-response overshoot) gives:

| 16-cell Run | Flat-rate bound |
|---|---:|
| DeepSeek V4 Flash | `$5.64031552` |
| Hy3 | `$4.64735072` |
| MiniMax M3 | `$14.51656320` |
| **Campaign total** | **`$24.80422944`** |
| **Slack** | **`$0.19577056`** |

These are arithmetic bounds, not observed spend. The MiniMax calculation is:

```text
16 × ((375,000 × $1.20
       + 1,000,000 × $0.30
       + 131,071 × $1.20) / 1,000,000)
= $14.51656320
```

**Conservative implication:** if the doubled band must be used for the MiniMax bound, its bound is `$29.03312640` and the three-model total is `$39.32079264`, far over `$25`. The public sources do not justify spending against the very small `$0.19577056` flat-rate margin while tier applicability and cache accounting remain unresolved.

## 7. Handoff/requalification decision

### What does not invalidate the handoff

The actual handoff catalog hash is still current. Therefore do **not** claim that post-handoff catalog drift invalidated qualification `4f5fc161…`. The older `630e…` artifact is not the handoff.

### What does block launch

Qualification `4f5fc161…` is insufficient for MiniMax M3 because it accepted a catalog containing unvalidated tier/cache/model-provider fields and exercised only an OpenAI-shaped loopback route, while both official route sources select Anthropic Messages. The artifact remains cryptographically intact; it simply does not establish the contract needed for a paid MiniMax run.

The tracked Campaign instructions say that any source, lock, manifest, pricing, worker, or qualification change resets qualification, and that a committed-input or pricing change invalidates qualification and completed Campaign Runs ([`docs/pending-worker-runs.md`, lines 38–63](https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/docs/pending-worker-runs.md#L38-L63)). Correcting the transport and extending pricing/catalog validation necessarily changes one or more of those sealed inputs.

**Required disposition:**

1. **Stop before every paid Campaign request.** Do not run even the first model under a handoff whose required third-model bound/transport is unresolved.
2. Obtain a first-party OpenCode clarification or public billing contract for whether Go MiniMax M3 uses the `>512k total-input` band and how cached tokens are returned/debited.
3. Model the documented `/messages` transport and Anthropic usage fields for MiniMax, or obtain an equally authoritative statement that the current `/chat/completions` shape is supported for this model.
4. Extend the Pricing Record and validator to seal every applicable tier/cache rule and the model-specific transport, or explicitly seal a documented flat-Go exception.
5. Re-run the complete no-spend qualification and publish a new identity before any paid request. Under the handoff rule, any already completed Campaign Runs would have to restart after such a committed correction.

## Answers to the audit questions

| Question | Answer | Status |
|---|---|---|
| Did the tier exist in the actual handoff catalog? | Yes: the identical-hash `0fde…` bytes expose `cost.tiers` and `context_over_200k`. | Observed |
| Did it exist in older `630e…` bytes? | Probably, based on source history, but the bytes were not retained and the digest is not reversible. | **Unresolved; inference only** |
| Is it really an “over 200k” tier? | No. `context_over_200k` is a legacy alias; exact threshold is `512,000`. | Observed |
| What triggers MiniMax's direct tier? | `>512k input tokens`; not output or input+output. Cache docs define total input as cached-read + cache-creation + uncached input. Per-request/total-input threshold use is the best-supported interpretation. | Observed, with cache-trigger interpretation labeled inference |
| Does OpenCode Go bill the tier? | Public sources conflict: Go docs say flat; provider-specific raw catalog says tiered. No public billing implementation resolves it. | **Unresolved** |
| Can the flat Pricing Record faithfully derive all provider cost? | No: it cannot represent tiers or cache rates/token fields and ignores provider-reported cost when the record is present. | Observed |
| Is `/chat/completions` supported for Go MiniMax M3? | Not documented. Both official route sources specify `/messages` with `@ai-sdk/anthropic`; no paid probe was made. | **Unresolved; documented route differs** |
| Did catalog drift invalidate the real handoff? | No; current hash equals the handoff hash. | Observed |
| Must the work requalify before paid launch? | Yes. Fixing the unvalidated pricing/transport contract changes sealed source/manifest/pricing/qualification inputs, and the current artifact does not prove the live MiniMax path. | Conclusion from observed handoff rule and blind spots |
| Can a no-spend campaign safely proceed? | Only no-spend investigation, repair, and dry qualification. The paid three-model Campaign must not start. | **No-go for paid requests** |

## Primary-source URL inventory

Every URL used as evidence in this note:

- Handoff qualification Gist: https://gist.github.com/MihaiA24/b5dd749d2ed763f263684135b86d8937
- Older committed qualification: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/artifacts/qualification/functional-v1/dry-launch-qualification.json
- Live Models.dev API: https://models.dev/api.json
- Rendered Models.dev OpenCode Go page: https://models.dev/providers/opencode-go/
- Models.dev M3 source at qualification-era head: https://github.com/anomalyco/models.dev/blob/4a14b64ce3970c7e681f00e05899c638f044b7d5/providers/opencode-go/models/minimax-m3.toml#L14-L34
- Models.dev tier PR: https://github.com/anomalyco/models.dev/pull/2774
- Models.dev tier commit: https://github.com/anomalyco/models.dev/commit/d77f5969759714194b5d1de4aa2c6a6b4858bf97
- Models.dev price-restoration commit: https://github.com/anomalyco/models.dev/commit/5687393566252ded4618a0eff5d26f23a29e3b77
- Models.dev cost schema: https://github.com/anomalyco/models.dev/blob/4a14b64ce3970c7e681f00e05899c638f044b7d5/packages/core/src/schema.ts#L72-L111
- Models.dev compatibility-field generator: https://github.com/anomalyco/models.dev/blob/4a14b64ce3970c7e681f00e05899c638f044b7d5/packages/core/src/generate.ts#L230-L276
- Live OpenCode Go docs: https://opencode.ai/docs/go/
- Qualification-era OpenCode Go docs source: https://github.com/anomalyco/opencode/blob/411eff73f026d4950c07947c4d983788cb615baa/packages/web/src/content/docs/go.mdx#L83-L208
- OpenCode M3 flat-price update: https://github.com/anomalyco/opencode/commit/1772e8ee6e794d1241dac6fa10d28e708f53b881
- OpenCode M3 introduction/endpoint commit: https://github.com/anomalyco/opencode/commit/c57379833e3f25967c03653482fc3131b3068c04
- MiniMax direct pay-as-you-go pricing: https://platform.minimax.io/docs/guides/pricing-paygo.md
- MiniMax Anthropic cache/token semantics: https://platform.minimax.io/docs/api-reference/anthropic-api-compatible-cache.md
- Qualified MiniMax manifest: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/functional-v1-minimax-m3.yaml#L3-L20
- Qualification catalog validator: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/dry_launch_qualification.py#L85-L204
- Flat Pricing Record/cost observer: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L62-L103 and https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L270-L351
- Credential Proxy route allowlist: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/credential_proxy.py#L541-L556
- Locked OpenCode provider shape: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/opencode.py#L98-L119
- Raw API route: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/src/model_benchmark/runtime/raw_api.py#L162-L211
- Campaign/requalification rule: https://github.com/MihaiA24/model-benchmarking/blob/50909cba08088d0cb9fe8d99761a5a13ece9346a/docs/pending-worker-runs.md#L38-L63
