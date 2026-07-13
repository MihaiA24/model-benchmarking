# Python data-engineering scenario candidates

**Status:** Provisional research note; none of these candidates is suite-qualified
**Reviewed:** 2026-07-12
**Purpose:** Candidate evidence for “Select the initial scenario portfolio”

## Recommendation

Provisionally reserve exactly these four Public Suite cells. The selection uses three Apache-2.0 repository lineages: DVC twice, Kedro once, and Dagster once. Thus no lineage supplies more than two scenarios or more than one scenario in a Workload Family.

| Workload Family | Difficulty | Provisional repository snapshot | Candidate concept |
| --- | --- | --- | --- |
| Defect diagnosis and repair | Standard | Kedro [`d3b46f3b69876674de99c254133d86d0564c612b`](https://github.com/kedro-org/kedro/tree/d3b46f3b69876674de99c254133d86d0564c612b) | Repair seeded dataset-factory precedence and interpolation behavior. |
| Bounded feature implementation | Standard | DVC [`f74c1c0e709de61f571905802bc0c75035dc6ef2`](https://github.com/treeverse/dvc/tree/f74c1c0e709de61f571905802bc0c75035dc6ef2) | Add a scriptable “parameter changes found” exit-status mode to `dvc params diff`. |
| Test generation and hardening | Challenging | Dagster [`d0688548c9d62209e08d8f8697524df07b27639c`](https://github.com/dagster-io/dagster/tree/d0688548c9d62209e08d8f8697524df07b27639c) | Harden multi-dimensional partition-mapping tests against boundary and composition regressions. |
| Repository evolution | Standard | DVC [`f74c1c0e709de61f571905802bc0c75035dc6ef2`](https://github.com/treeverse/dvc/tree/f74c1c0e709de61f571905802bc0c75035dc6ef2) | Retire the ConfigObj-backed configuration codec while preserving DVC configuration behavior. |

These are scenario-package authoring leads, not approval to freeze them. Each must still satisfy the accepted no-op, Reference Solution, repeatability, independent-review, common-profile, and no-download gates.

## Common synthetic-fixture contract

Every candidate uses package-owned `pydata-fixture-v1`. Its canonical generator, schema, scale/distribution parameters, invariants, and canonical-serialization rules are versioned and locked. A fixture seed is the unsigned 64-bit prefix of `SHA-256("<scenario-id>|pydata-fixture-v1|<role>|<ordinal>")`; `role=visible` and ordinal `0` produce one realistic agent-visible example, while verifier-only roles and ordinals are frozen in the package lock but absent from the Scenario Baseline. Every generated fixture records its SHA-256 digest. Hidden suites vary seeds and declared edge regimes rather than relying on one hardcodeable example.

## Public Suite candidates

### 1. Kedro dataset-factory precedence repair — Standard

**First-party evidence.** Apache-2.0 [license](https://github.com/kedro-org/kedro/blob/d3b46f3b69876674de99c254133d86d0564c612b/LICENSE.md); relevant [catalog resolver](https://github.com/kedro-org/kedro/blob/d3b46f3b69876674de99c254133d86d0564c612b/kedro/io/catalog_config_resolver.py), [catalog integration](https://github.com/kedro-org/kedro/blob/d3b46f3b69876674de99c254133d86d0564c612b/kedro/io/data_catalog.py), [resolver tests](https://github.com/kedro-org/kedro/blob/d3b46f3b69876674de99c254133d86d0564c612b/tests/io/test_catalog_config_resolver.py), [catalog tests](https://github.com/kedro-org/kedro/blob/d3b46f3b69876674de99c254133d86d0564c612b/tests/io/test_data_catalog.py), and [packaging/test metadata](https://github.com/kedro-org/kedro/blob/d3b46f3b69876674de99c254133d86d0564c612b/pyproject.toml).

**Professionally bounded brief concept.** A production catalog containing overlapping factory templates sometimes selects a generic dataset definition instead of the intended specific definition. Restore deterministic resolution, placeholder interpolation, explicit-entry behavior, and user catch-all fallback without prescribing the implementation or naming the seeded location.

**Scenario and fixture seed.** A declared project-original seed patch introduces a multi-path precedence defect while leaving ordinary single-pattern cases green. `kedro-factory-precedence-v1` feeds the common generator with weighted specific/generic/catch-all templates, nested config values, explicit names, and nonmatching names; hidden regimes include equal-specificity ordering, multiple placeholders, tuple-like opaque values, and malformed placeholders.

**Hidden verifier shape.** In a separate verifier environment, construct generated `CatalogConfigResolver`/`DataCatalog` cases using only local `MemoryDataset`-compatible definitions. Compare resolved type/config and catalog lookup against an independent small oracle; require acceptance for overlapping patterns and regressions for explicit entries, credential-free interpolation, error behavior, and input non-mutation. Build/import success alone earns no acceptance.

**Exposure caveat.** The resolver algorithm and substantial public tests already reveal intended sorting and fallback behavior, and this note discloses the task concept. The exact seed patch, hidden fixtures, and Reference Solution are project-original and not an upstream issue/patch, but no claim can be made about model training exposure.

**Qualification blockers.** Authoring must prove that the seeded baseline fails only required acceptance groups, existing regressions remain green, the brief does not make the resolver file obvious, the defect is not reducible to trivial token restoration, all three harnesses finish under `standard-v1`, and the Reference Solution passes two fresh locked verifier runs identically.

### 2. DVC `params diff` change-detection mode — Standard

**First-party evidence.** Apache-2.0 [license](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/LICENSE); relevant [CLI command](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/dvc/commands/params.py), [repository diff API](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/dvc/repo/params/diff.py), [functional diff tests](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/tests/func/params/test_diff.py), and [packaging/test metadata](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/pyproject.toml).

**Professionally bounded brief concept.** CI users need an opt-in `dvc params diff` mode that preserves normal human/JSON/Markdown output but returns a documented nonzero status when tracked parameter values differ. No difference remains success; invalid revisions and load failures retain their existing error semantics. The option spelling and exact exit code must be frozen during authoring, not improvised during trials.

**Scenario and fixture seed.** A declared project-original seed patch adds only a visible parser/help stub and no implementation. `dvc-params-diff-status-v1` generates local Git histories plus YAML parameter trees; hidden regimes cover nested numeric/string/list changes, additions/deletions, unchanged values with `--all`, targets, workspace dirtiness, JSON/Markdown modes, and missing/corrupt files.

**Hidden verifier shape.** Materialize fresh local repositories, invoke the stock CLI as a subprocess, and assert status, stdout/stderr schema, and unchanged existing output for generated histories. Acceptance covers changed/unchanged behavior in each declared output mode; regression covers revision errors, load errors, targeted diffs, and the Python API result. No network remote is configured.

**Exposure caveat.** DVC’s command, output formats, and nearby tests are public and strongly guide repository navigation. The requested mode is project-original rather than copied from a reviewed upstream issue or patch, so there is no known public solution; this does not establish absence from model training data.

**Qualification blockers.** Freeze conflict semantics for `--all`, load errors, and JSON; verify the parser stub does not reveal implementation; confirm no existing option already provides equivalent behavior; prove the hidden CLI oracle is portable; and qualify runtime, Reference Solution repeatability, and all three stock harnesses offline.

### 3. Dagster multi-partition mapping test hardening — Challenging

**First-party evidence.** Apache-2.0 [license](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/LICENSE); relevant [multi-mapping base](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/python_modules/dagster/dagster/_core/definitions/partitions/mapping/multi/base.py), [multi-to-multi mapping](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/python_modules/dagster/dagster/_core/definitions/partitions/mapping/multi/multi_to_multi.py), [time-window mapping](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/python_modules/dagster/dagster/_core/definitions/partitions/mapping/time_window.py), existing [multi-partition tests](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/python_modules/dagster/dagster_tests/asset_defs_tests/partition_mapping_tests/test_multipartition_partition_mapping.py), package [metadata](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/python_modules/dagster/pyproject.toml), and package [lock](https://github.com/dagster-io/dagster/blob/d0688548c9d62209e08d8f8697524df07b27639c/python_modules/dagster/uv.lock).

**Professionally bounded brief concept.** Add maintainable executable tests that protect existing multi-dimensional partition mapping behavior when mapped and implicit dimensions are composed across static, dynamic, daily, and weekly definitions. Cover reverse mapping, required-but-nonexistent keys, offset boundaries, and validation errors. Production behavior must not change.

**Scenario and fixture seed.** The Scenario Baseline removes a bounded subset of overlapping tests, not production code. `dagster-multipartition-hardening-v1` generates two-dimensional definitions and selected subsets; hidden regimes vary cardinality, mapping direction, unmapped dimensions, empty/all subsets, dynamic membership, daily/weekly boundaries, offsets, and a pinned daylight-saving timezone database case.

**Hidden verifier shape.** Enforce a test-only Submission path. First run submitted tests against the clean pinned implementation. Then, one at a time, apply a locked set of verifier-only non-equivalent mutants in dimension composition, reverse direction, missing-key propagation, and time-window boundaries; each required mutant must be killed by the submitted tests while the clean source remains green. Mutation IDs have equal group weight, not raw test-count weight.

**Exposure caveat.** Dagster already publishes extensive nearby partition tests, so patterns and expected APIs are exposed; hidden generated cases and mutants provide the actual discrimination. The hardening brief and mutation set are project-original, not an adopted upstream patch. Model training exposure is unknowable.

**Qualification blockers.** Independently prove every mutant is behaviorally non-equivalent, not already killed by the retained baseline, and representative rather than syntactic; cap runtime under `standard-v1`; pin timezone data; reject production edits at handoff; and show the Reference Solution kills the same locked mutant set twice in fresh verifier environments.

### 4. DVC configuration-codec migration — Standard

**First-party evidence.** The same pinned Apache-2.0 DVC snapshot supplies the [license](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/LICENSE), ConfigObj-backed [configuration implementation](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/dvc/config.py), [unit tests](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/tests/unit/test_config.py), [functional CLI tests](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/tests/func/test_config.py), and [packaging metadata declaring `configobj`](https://github.com/treeverse/dvc/blob/f74c1c0e709de61f571905802bc0c75035dc6ef2/pyproject.toml).

**Professionally bounded brief concept.** Remove DVC’s runtime dependency on ConfigObj and migrate its repository/global/local configuration codec to a maintained in-repository or standard-library-backed boundary. Preserve observable section naming, case normalization, layered precedence, path handling, validation, CLI get/set/list behavior, and deterministic writes; dependency removal alone is not success.

**Scenario and fixture seed.** A project-original seed patch pins the replacement dependency environment, marks `configobj` unavailable, and leaves the current codec failing at runtime. `dvc-config-codec-migration-v1` generates INI-like DVC configuration layers with named remotes/machines/databases, booleans, URLs, relative/absolute paths, quoting, mixed case, empty sections, Unicode, and malformed input.

**Hidden verifier shape.** Run generated read/edit/write/read cycles and CLI get/set/list operations across repo and local layers, comparing normalized semantic results and declared canonical output against a format oracle. Regression covers validation messages by class, path round trips, remote section names, precedence, and package import with ConfigObj absent. An offline installed-package smoke run exercises behavior; a successful wheel build by itself cannot pass.

**Exposure caveat.** Existing ConfigObj calls and public expected config bytes expose the current boundary. The replacement migration is project-original and not a replay of a reviewed upstream patch, but common library-migration patterns may be familiar and model training exposure cannot be determined.

**Qualification blockers.** Build a compatibility corpus before freezing exact preservation requirements; determine whether comments, duplicate keys/sections, interpolation, and whitespace are supported or explicitly out of contract; prove the task remains Standard-sized and localized; verify licensing of any replacement; generate a fully pinned offline environment; and require two identical Reference Solution verifier vectors. Reclassify or reject if compatibility work crosses the Standard band.

## Private Suite slot contracts only

No exact private repository, ref, brief, seed, verifier content, package identity, or solution is selected or disclosed here.

| Private Python data-engineering slot | Difficulty | Public contract |
| --- | --- | --- |
| Defect diagnosis and repair | Standard | A professionally plausible seeded data/pipeline behavior defect with bounded investigation; deterministic hidden synthetic acceptance plus unchanged regression behavior; no Public Suite lineage. |
| Bounded feature implementation | Challenging | A repository-integrated data-engineering capability requiring coordinated changes across more than one established boundary; deterministic synthetic acceptance/regression checks under `standard-v1`; no Public Suite lineage. |
| Test generation and hardening | Standard | Tests-only strengthening of existing data behavior with a bounded hidden adequacy check and clean-source regression run; production changes prohibited unless a separately approved minimal testability seam is declared; no Public Suite lineage. |
| Repository evolution | Standard | A bounded dependency/API/schema/configuration migration that preserves declared data behavior and compatibility; behavioral verification beyond build success; no Public Suite lineage. |

Within the Private Suite, the eventual manifest must still use at most two scenarios per lineage and at most one per lineage in a Workload Family. Exact material belongs only in the access-controlled manifest and pre-trial content-addressed commitment.

## Rejected public candidates

- **Great Expectations: group-aware monotonic expectation feature.** Rejected for the initial Standard feature cell: the pinned tree’s expectation model, schema snapshots, and engine surfaces make a credible Pandas/Spark/SQL-neutral feature broader than Standard without further slicing ([core expectations](https://github.com/fivetran/great_expectations/tree/e1679d13d7f14d20bfbfc71fa010ba0bece0e6c9/great_expectations/expectations/core), [schema tests](https://github.com/fivetran/great_expectations/blob/e1679d13d7f14d20bfbfc71fa010ba0bece0e6c9/tests/expectations/core/test_core_model_schemas.py), [Apache-2.0 license](https://github.com/fivetran/great_expectations/blob/e1679d13d7f14d20bfbfc71fa010ba0bece0e6c9/LICENSE)).
- **Great Expectations: native Pydantic-v2 expectation-model migration.** Rejected as a Standard evolution candidate: the pin deliberately routes Pydantic 2 through `pydantic.v1`, while more than 50 core models have frozen Draft-7 schema artifacts; migration blast radius and compatibility policy are unresolved ([compatibility layer](https://github.com/fivetran/great_expectations/blob/e1679d13d7f14d20bfbfc71fa010ba0bece0e6c9/great_expectations/compatibility/pydantic.py), [schema test](https://github.com/fivetran/great_expectations/blob/e1679d13d7f14d20bfbfc71fa010ba0bece0e6c9/tests/expectations/core/test_core_model_schemas.py), [packaging configuration](https://github.com/fivetran/great_expectations/blob/e1679d13d7f14d20bfbfc71fa010ba0bece0e6c9/pyproject.toml)).
- **DVC remote-transfer repair.** Rejected despite professional realism because measured acceptance would tend to depend on mutable remote/storage behavior or a large protocol emulator; the selected DVC tasks are fully local.
- **Dagster partition-mapping production repair.** Rejected for this cell because a planted production defect plus the existing broad tests risks either trivial localization or an oversized cross-mapping repair. The tests-only mutant-backed candidate better matches the accepted Challenging test-hardening slot.
- **Sales-by-genre repair.** Rejected from measured selection because its intent is already disclosed and reserved for the non-measured Legacy Calibration Suite; it is not reused or disguised here.

## Policy and scenario-origin basis

- **Adopted:** commit-pinned first-party source/license evidence and upstream repository test/packaging conventions are retained as provenance; Apache-2.0 terms govern redistribution. No exact scenario or solution is adopted from an upstream issue or patch.
- **Adapted:** exposure review, oracle/reference solvability, and adversarial anti-hardcoding checks are adapted from the established benchmark evidence summarized in [the Terminal-Bench 2.1 comparison](terminal-bench-2.1-methodology.md), but specialized to deterministic hidden Check Groups and synthetic fixtures.
- **Project-original:** the four exact scenario concepts and seed mutations, `Standard`/`Challenging` assignments, synthetic generator/seed/digest contract, lineage allocation, Public/Private matrix, private slot boundary, and pre-trial commitment are local policies from the [working portfolio record](../blueprint/initial-scenario-portfolio.md). None should be represented as a Terminal-Bench standard.

## Caveats

Repository commits were resolved from first-party Git remotes and reviewed through pinned GitHub/raw files on 2026-07-12. Great Expectations and DVC now resolve under the first-party GitHub owners `fivetran` and `treeverse`, respectively; that ownership movement is an exposure/provenance fact, not evidence of a distinct code lineage. No candidate package, seed patch, verifier, fixture digest, Reference Solution, runtime estimate, or three-harness qualification run exists yet. The DVC configuration migration is the highest-risk provisional choice and must be replaced if its compatibility corpus exceeds the Standard band.