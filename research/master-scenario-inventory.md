# Inventory the master-branch benchmark scenarios

**Status:** Final inventory  
**Inventory timestamp:** 2026-07-11T17:02:06Z  
**Authoritative source snapshot:** repository `master` at [`efb243da54cc77d3a250a1cae9cd4ca5ac7d2714`](https://github.com/MihaiA24/model-benchmarking/tree/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714)  
**Map:** [Design a real-world CLI benchmark for coding-agent harnesses](https://github.com/MihaiA24/model-benchmarking/issues/13)  
**Ticket:** [Inventory the master-branch benchmark scenarios](https://github.com/MihaiA24/model-benchmarking/issues/15)

## Answer

The `master` branch contains **11 historical single-file model-completion tasks** across four ecosystems: five bug fixes and six features. Nine borrow real open-source application code from Spring Petclinic or RealWorld/Conduit; two use a tracked Chinook SQLite database. They are useful source material for the new benchmark, but **none is a drop-in autonomous CLI scenario** under the accepted Harbor, isolation, verifier, or provenance contracts.

The reusable unit is the task idea plus selected mutation and verifier intent—not the current runner, trial records, baseline materialization, or evidence package. The existing tasks call a model API directly with one file, overwrite that file with the response, and verify in the same host-side copied directory. A future harness CLI would instead inspect and edit a complete immutable evaluated repository inside a fresh agent environment and submit a host-derived patch to a separate verifier.

This inventory does not select the initial portfolio. That decision remains with [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20).

## Scenario inventory

| Scenario | Ecosystem and workload | Repository realism | Current checks | Current isolation and provenance | Reuse boundary and material gap |
|---|---|---|---|---|---|
| `bug1-petvalidator` | Spring Boot/Java bug fix: reject whitespace-only pet names by restoring `hasText` semantics. | A one-line defect in Spring Petclinic application code. The model receives only `PetValidator.java`, not an autonomous repository workspace. | Maven compile, then the complete `PetControllerTests` class. The intended failing cases are documented, but no verifier asset is tracked with this repository. | A local ignored `baselines/petclinic` directory is copied per attempt without `.git` or `target`. Documentation names clean/buggy short commits, but the baseline origin and full commits are not recoverable from this repository. | Strong candidate idea and targeted regression intent. Rebuild from a pinned upstream snapshot; move acceptance and regressions into a separate verifier; record the seed patch as a versioned task input. |
| `bug2-ownercontroller` | Spring Boot/Java bug fix: redirect only when owner search returns exactly one result. | A one-line controller defect in Spring Petclinic. The model receives only `OwnerController.java`. | Maven compile, then the complete `OwnerControllerTests` class. | Shares the same untracked, manually reconstructed Petclinic baseline as `bug1-petvalidator`. | Strong candidate idea. It needs the same immutable baseline, hidden verifier, seed-patch identity, and clean-reset conversion as the other Petclinic bug. |
| `sb-feat1-name-length` | Spring Boot/Java feature: reject pet names longer than 50 characters with `tooLong`. | Uses Petclinic, but a separate local baseline is manually created by adding the requested test. The prompt discloses the test shape and restricts the edit to one method. | Maven compile, then only `PetControllerTests#processCreationFormWithTooLongName`. No broader regression or boundary tests are declared. | The ignored `baselines/petclinic-feat1` directory is cloned from a rolling upstream default and modified manually; no exact evaluated-repository commit or mutation digest is recorded. | Candidate easy-feature stratum, not ready-made evidence. Pin the repository, version the public instruction separately from hidden checks, and add regression and boundary coverage. |
| `ng-bug1-missing-input` | Angular/TypeScript compile repair: restore `@Input()` to `ArticleListComponent.config`. | Seeded into the RealWorld Angular app, but the task is an explicitly described one-token decorator restoration. The model receives one component file. | `npm run build` only; `test_ok` is set equal to `build_ok`. | A rolling clone of `gothinkster/angular-realworld-example-app` is copied per attempt while a shared baseline `node_modules` directory is junction-linked into every workdir. The source commit and dependency-tree digest are absent. | Reusable only as a very easy compile-repair candidate. Build success is not a functional verifier; package it with an immutable repository/dependency image and hidden template/behavior regression checks. |
| `ng-feat1-reading-time` | Angular/TypeScript feature: implement `getReadingTime(body)` after the runner seeds a template call. | The seed touches a real article-preview component, but the requested algorithm is fully specified and remains a one-file completion. | `npm run build` only. No test proves whitespace handling, rounding, the minimum, or rendered output. | Same rolling Angular baseline and shared mutable dependency junction as the other Angular tasks. | Preserve the feature concept only. It needs hidden unit and rendered-component checks; build-only status cannot represent functional correctness. |
| `ng-feat2-service-search` | Angular/TypeScript service feature: add `search(query)` using `GET /articles?q=...`. | Seeded by inserting an interface into the RealWorld service. The repository is realistic, but no evidence establishes that the upstream RealWorld API supports the invented `q` contract. | `npm run build` only. No HTTP request/response behavior or application integration is exercised. | Same unpinned Angular baseline and shared dependency junction. | Requires realism validation before portfolio selection, then hidden `HttpClient` behavior and regression checks. Compilation alone is insufficient. |
| `re-bug1-favorite-count` | React/Redux JavaScript bug fix: update `favoritesCount` with `favorited`. | A reducer defect seeded into the legacy RealWorld React/Redux application; the model receives only `articleList.js`. | Full app build plus one injected targeted Jest reducer test. | A rolling clone of `gothinkster/react-redux-realworld-example-app` is copied while a shared baseline `node_modules` directory is junction-linked. The injected test is placed in the same writable workdir. | Strong candidate idea and useful focused test. Pin the old application and dependencies, keep public checks distinct from hidden regressions, and verify surrounding reducer behavior. |
| `re-feat1-reading-time` | JavaScript utility feature: implement a new `getReadingTime(body)` function. | The runner creates both a stub and four tests under `src/utils`, but does not integrate the utility into the RealWorld UI. This is effectively a micro greenfield exercise inside a real repository. | Full app build plus four targeted Jest cases covering empty/short, 200, 400, and 600 words. | Same unpinned React baseline and shared dependency junction; the injected tests live in the agent-side copy under a future CLI interpretation. | Reusable as a small utility stratum, not as evidence of feature integration. Move acceptance checks to the verifier and decide whether portfolio breadth needs such a low-integration task. |
| `re-feat2-author-filter` | React/Redux feature: add a `FILTER_BY_AUTHOR` reducer case. | Uses an existing reducer, but tests only the reducer transformation; no action creator, UI flow, restoration semantics, or API interaction is involved. | Full app build plus one injected targeted reducer test. | Same unpinned React baseline and shared dependency junction. | Preserve as possible state-management source material, but do not describe it as end-to-end integration. A retained version needs a precise behavior contract and hidden regression checks. |
| `data-bug1-sales-genre` | Python/pandas/SQLite bug fix: correct the `Track`→`InvoiceLine` join and return the top five genres by units sold. | A real relational schema and a tracked 1,007,616-byte Chinook database are used, but the dataset source version and license are not recorded. The model receives only one Python file. | `py_compile`, then a pandas frame equality check against `expected/top_genres.csv`. | The complete tracked data baseline is copied per attempt. Its database SHA-256 is `7651ba378ac2fcd0dfc3c66fb101f7a7eed3ba39a612ec642b96e20702061f15`, but the expected answer is inside that copy; it would be visible to an autonomous CLI. | Strong data-task idea. Pin and license the dataset, move expected output into the separate verifier, and add anti-hardcoding/semantic checks where practical. |
| `data-feat1-customer-ranking` | Python/pandas/SQLite feature: write a window-function query ranking customers by country. | Uses Chinook but is a single placeholder query rather than a broader data pipeline. | `py_compile`, then comparison of `Country`, `CustomerId`, `TotalPurchases`, and `Rank` against expected output. Required `FirstName` and `LastName` values are only checked for column presence, not correctness. | Same copied tracked baseline; the full expected CSV is agent-visible under a future CLI interpretation. Dataset source/license are absent. | Useful SQL/window-function idea after verifier repair. Hide expected data, validate every required field, define tie/order behavior, and prevent answer-file leakage. |

Task definitions and current checks are embedded in [`poc_harness.py`](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/poc_harness.py#L27-L56), [`run_springboot.py`](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_springboot.py#L41-L94), [`run_angular.py`](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_angular.py#L42-L126), [`run_react.py`](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_react.py#L42-L184), and [`run_data.py`](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_data.py#L42-L82).

## Cross-scenario findings

### Workload coverage

- The inventory has five bug fixes and six features, but no test-generation, repository-scale investigation, dependency upgrade, multi-service, migration, performance, security-hardening, or substantive multi-file implementation scenario.
- Most tasks are deliberately easy and heavily specify the implementation. Several prompts identify the exact missing token, method, endpoint, SQL join, or expected test code.
- Nine tasks borrow real open-source repositories, but none uses company code. “Real-world” currently means familiar framework context, not demonstrated representativeness of the organization's daily work.
- All 11 model calls are single-turn, single-file completions. They do not exercise navigation, tool choice, planning, test execution, iterative repair, context management, or any other harness behavior that the new benchmark exists to compare.

### Check strength

- Spring and React have targeted test evidence, but the checks run after the response is written in the same copied workdir; there is no separate verifier or hidden acceptance layer.
- Angular has only compilation evidence. [`run_angular.py`](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_angular.py#L183-L221) explicitly aliases `test_ok` to `build_ok`.
- Data has deterministic expected-output checks, the strongest current oracle shape, but those expected files are part of the copied baseline and one verifier omits required name values from equality comparison.
- No task declares dimensional scores, protected paths, submission allowlists, verifier limits, negative tests for hardcoding/test tampering, or a distinction between acceptance and regression checks.

### Isolation

The historical runner does provide one useful invariant: it deletes and recopies a workdir for each `(task, model, run)`. That prevents source edits from one attempt from directly becoming the next attempt's baseline.

It is not hermetic execution under the accepted benchmark contract:

- trials execute directly on the developer host, inherit the host environment, and have no fresh home, container, worker profile, resource controls, or network policy;
- Angular and React junction-link the same writable `node_modules` tree into every trial ([Angular copy path](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_angular.py#L159-L167), [React copy path](https://github.com/MihaiA24/model-benchmarking/blob/efb243da54cc77d3a250a1cae9cd4ca5ac7d2714/run_react.py#L217-L224));
- checks execute inside the model-edited workdir rather than in a fresh verifier environment;
- subprocess checks have no lifecycle, process-tree, resource, or integrity controls;
- expected outputs and injected tests are not separated from the evaluated repository; and
- the system under evaluation is an API model response, not an untrusted autonomous CLI stock profile.

The copy-per-attempt pattern can inform migration tests, but Harbor must own the replacement lifecycle. The current Python runners must not become a second sandbox or verifier implementation.

### Provenance

Provenance is the largest reuse blocker:

- Spring, Angular, and React baselines are ignored by Git. Setup instructions clone rolling default branches; they do not record full upstream commits, source archives, dependency lock digests, clean-tree digests, or image digests. The two short Spring commit labels in `CLAUDE.md` have no repository identity in this project and are not sufficient evaluated-repository provenance.
- The Chinook database is tracked and therefore recoverable from the `master` commit; its SQLite integrity check returned `ok`, with 25 genres, 3,503 tracks, and 2,240 invoice lines. Its upstream source, version, and license remain undocumented.
- Scenario instructions are recoverable from the runner scripts at the pinned `master` commit, but trials carry no scenario version or instruction digest.
- Results record task, model slug, repetition number, build/test booleans, token counts, rounded cost, latency, and a local workdir string. They do not record repository/task/verifier/runner digests, harness identity, provider endpoint, immutable model revision, request settings as effective at the provider, worker profile, timestamps, pair/block identity, process evidence, check logs, final patch, or bundle digests.
- Model slugs and price tables are mutable declarations embedded independently in four scripts. Historical rows cannot prove that two calls using one slug reached immutable identical model weights or pricing metadata.

[Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) should treat these fields as pilot input examples, not as a schema to preserve.

## Existing benchmark assets

| Asset group | What exists on `master` | Evidenced state | Reuse disposition |
|---|---|---|---|
| Runner scripts | One direct-OpenRouter Python runner per stack, the original Petclinic runner, a data repair runner, a Windows-only four-window launcher, and CSV merge/generation utilities. | Task prompts, seed patches, API calls, workdir creation, checks, usage extraction, and cost arithmetic are mixed in each script. | Do not reuse as the execution architecture. Mine frozen instruction text, mutation snippets, and verifier commands while implementing them through Harbor tasks and the experiment coordinator. |
| Evaluated-repository baselines | Tracked Chinook data package; ignored local Spring, Angular, and React clones reconstructed from documentation. | Only Chinook bytes are present in the canonical tree. | Chinook can seed a new immutable package after source/license verification. Rebuild all application baselines from explicit full commits and digested dependencies. |
| Verifier assets | Two tracked pandas verifiers and expected CSVs; frontend tests embedded as runner strings; Spring tests exist only in external baselines. | The data verifiers are readable and deterministic but agent-visible; React checks are generated into the workdir; Angular has no functional verifier. | Extract verifier intent, then place versioned checks and private data exclusively in separate verifier packages. |
| Machine metrics | `metrics_all.csv` and anonymized metrics contain 363 rows: 11 models × 11 tasks × 3 repetitions. Observed statuses are 303 build/test passes, 44 build/test failures, 15 build-pass/test-fail outcomes, and one error. | The consolidated table is complete by condition count, but lacks the provenance and raw evidence needed to establish reproducible trials. | Preserve as historical pilot data only. Do not pool it with the new CLI benchmark. |
| Raw and applied outputs | The canonical `results/` tree tracks 80 `_raw_response.txt` files across nine tasks; ignored workdirs, applied source trees, diffs, and most check logs are absent. | The 363 metric rows do not each have a canonical raw evidence bundle. | Do not treat these as complete trial evidence. New trials require the host-derived patch, raw process/proxy/verifier evidence, and a sealed manifest. |
| Blind human-review package | 121 blind response copies, one selected response per `(model, task)`, a 121-row scoring CSV, Google Forms data/build scripts, rubric, instructions, and framework index. | The generator prefers a passing lowest-numbered run, so the package is a curated representative-response layer rather than a full repetition sample. The alias-to-model mapping is intentionally ignored and absent from the public tree. | Reuse the rubric and operational patterns only after the statistical protocol defines trial sampling and blinding. Keep the private mapping in the canonical access-controlled evidence set. |
| Presentation | A standalone HTML executive presentation and result-interpretation prompt. | Derived from historical metrics and review workflow. | Presentation structure may inspire the later report prototype; its numerical claims are pilot-only and must not flow into new benchmark evidence. |

## Downstream routing

No new Wayfinder ticket is required. The inventory sharpens existing lanes:

- [Define the scenario package and authoring protocol](https://github.com/MihaiA24/model-benchmarking/issues/19) owns immutable evaluated-repository and dependency identity, versioned seed mutations and instructions, public/private check separation, sidecar/data packaging, hidden verifier assets, and migration rules for any retained task idea.
- [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20) owns which ideas survive, their difficulty and workload balance, whether upstream sample apps are representative enough, and whether weakly integrated tasks are replaced.
- [Define the run ledger and provenance schema](https://github.com/MihaiA24/model-benchmarking/issues/21) owns the missing trial, repository, task, verifier, harness, model/provider, worker, usage, disposition, and artifact identities.
- [Set the benchmark architecture and reuse boundary](https://github.com/MihaiA24/model-benchmarking/issues/24) should enforce the architectural conclusion here: Harbor owns execution and verification; project code may import scenario source material and historical reporting ideas but must not preserve the duplicated per-stack runner lifecycle.

## Verification and evidence limits

- Inspected the complete tracked `master` tree at `efb243da54cc77d3a250a1cae9cd4ca5ac7d2714`, all scenario runner definitions, data baselines/verifiers, consolidated metrics, raw-response inventory, human-review generators/assets, setup documentation, and relevant Git history.
- Python bytecode compilation succeeded for every tracked Python file in an isolated detached `master` worktree.
- The Chinook SQLite integrity check returned `ok`; its table counts and database SHA-256 are recorded above.
- The seeded data verifiers could not execute in the audit environment because `pandas` is not installed. No dependency was installed for this read-only inventory. Their logic and expected assets were inspected directly; no claim is made that the checks were re-executed successfully.
- The external Spring, Angular, and React baselines are intentionally absent from `master`; their historical source bytes, dependency state, and tests could not be reconstructed exactly and are classified as provenance gaps rather than inferred.
- The audit used a temporary detached worktree and changed no `master` files. The only persistent repository change is this inventory asset on the Wayfinder branch; the pre-existing untracked `.serena/` directory was not touched.
