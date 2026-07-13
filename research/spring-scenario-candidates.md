# Spring Boot/Java scenario candidates

**Status:** Provisional research note; none of these candidates is suite-qualified
**Reviewed:** 2026-07-12
**Purpose:** Candidate evidence for [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20)

## Recommendation

Provisionally reserve these four Public Suite cells. The selection uses four distinct permissively licensed repository lineages, so it remains below the accepted maximum of two Scenarios per lineage.

| Workload Family | Difficulty | Provisional repository snapshot | Candidate concept |
| --- | --- | --- | --- |
| Defect diagnosis and repair | Standard | Spring Data Examples [`083ff1c38c9c77339828accf106f2c8f4b8bb511`](https://github.com/spring-projects/spring-data-examples/tree/083ff1c38c9c77339828accf106f2c8f4b8bb511) | Repair a seeded selective-update transaction-boundary defect that can commit an orphan child after optimistic-lock rejection. |
| Bounded feature implementation | Challenging | Spring Petclinic [`51045d1648dad955df586150c1a1a6e22ef400c2`](https://github.com/spring-projects/spring-petclinic/tree/51045d1648dad955df586150c1a1a6e22ef400c2) | Add a clinic-wide upcoming-visits schedule with date filtering, pagination, stable ordering, and owner/pet context. |
| Test generation and hardening | Standard | Spring Modulith [`c4f6d51365bdb7f943327392a9cd4e828a58af0f`](https://github.com/spring-projects/spring-modulith/tree/c4f6d51365bdb7f943327392a9cd4e828a58af0f) | Harden Moments passage-of-time tests across locale week-years, shifted quarters, leap dates, and time-zone boundaries. |
| Repository evolution | Standard | Spring Boot RealWorld [`ee17e31aafe733d98c4853c8b9a74d7f2f6c924a`](https://github.com/gothinkster/spring-boot-realworld-example-app/tree/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a) | Replace deprecated adapter-based Spring Security configuration with component-based configuration while preserving the HTTP/JWT contract. |

These are authoring targets, not qualified Scenario Packages. Each remains subject to baseline-failure, Reference Solution, repeatability, licensing, common-profile, and no-download gates.

## Public candidates

### 1. Spring Data selective-update transaction atomicity repair — Standard

**First-party evidence.** Apache-2.0 [license](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/LICENSE); relevant custom update transaction in [`PartyHatRepositoryImpl`](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/jdbc/howto/selectiveupdate/src/main/java/example.springdata/jdbc/howto/selectiveupdate/PartyHatRepositoryImpl.java), aggregate/version behavior in [`Minion`](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/jdbc/howto/selectiveupdate/src/main/java/example.springdata/jdbc/howto/selectiveupdate/Minion.java) and [`MinionRepository`](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/jdbc/howto/selectiveupdate/src/main/java/example.springdata/jdbc/howto/selectiveupdate/MinionRepository.java), current integration tests in [`SelectiveUpdateApplicationTests`](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/jdbc/howto/selectiveupdate/src/test/java/example/springdata/jdbc/howto/selectiveupdate/SelectiveUpdateApplicationTests.java), local [schema](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/jdbc/howto/selectiveupdate/src/main/resources/schema.sql), and module [`pom.xml`](https://github.com/spring-projects/spring-data-examples/blob/083ff1c38c9c77339828accf106f2c8f4b8bb511/jdbc/howto/selectiveupdate/pom.xml).

**Professionally bounded brief concept.** Under a stale aggregate version, granting a child item reports an optimistic-lock failure but can leave that child committed. Restore atomic success/failure behavior without changing the public repository contract: success inserts exactly one child and advances the version; a stale write persists neither operation.

**Seed mechanism.** A content-addressed project-original patch introduces a separate `REQUIRES_NEW` child-insert boundary while retaining the outer version-checked update. The resulting tree, seed patch, H2 schema, Maven closure, and image are digest pinned. The brief describes observable atomicity, not transaction annotations or the seeded classes.

**Hidden verifier shape.** Use local H2, deterministic transaction barriers, and two stale aggregate instances. Assert the expected optimistic-lock exception, unchanged version, and absence of an orphan child after failure; assert one child and one version increment after success; cover repeated calls, rollback-only behavior, and unrelated selective updates. Existing module tests form the regression group. No timing race or external database is required.

**Exposure caveat.** The example and its existing optimistic-lock tests are public. A bounded first-party issue/PR search found no matching transaction-boundary task, but that is not proof of no analogue or model exposure. The exact propagation seed and verifier are project-original.

**Qualification blockers.** Prove the barriers are deterministic, the seed is not reducible to restoring an explicitly revealed token, the H2 transaction model represents the declared behavior, the seeded baseline fails acceptance while regressions remain valid, and the Reference Solution produces the same score vector twice under `standard-v1`.

### 2. Spring Petclinic upcoming-visits schedule — Challenging

**First-party evidence.** Apache-2.0 [license](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/LICENSE.txt); owner persistence and pagination in [`OwnerRepository`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/main/java/org/springframework/samples/petclinic/owner/OwnerRepository.java), aggregate relationships in [`Owner`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/main/java/org/springframework/samples/petclinic/owner/Owner.java), [`Pet`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/main/java/org/springframework/samples/petclinic/owner/Pet.java), and [`Visit`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/main/java/org/springframework/samples/petclinic/owner/Visit.java), MVC conventions in [`OwnerController`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/main/java/org/springframework/samples/petclinic/owner/OwnerController.java), current controller tests in [`OwnerControllerTests`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/test/java/org/springframework/samples/petclinic/owner/OwnerControllerTests.java), view conventions in [`ownersList.html`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/src/main/resources/templates/owners/ownersList.html), and Maven identity in [`pom.xml`](https://github.com/spring-projects/spring-petclinic/blob/51045d1648dad955df586150c1a1a6e22ef400c2/pom.xml).

**Professionally bounded brief concept.** Add a clinic-wide upcoming-visits page. Staff can select an inclusive start/end date, page through results, and see visit date/description plus owner and pet identity. Invalid ranges return a field-level error; equal-date visits use a declared stable tie order; empty results remain a successful page. Creating or editing visits is out of scope.

**Seed mechanism.** The exact clean snapshot is the baseline; absence of the capability makes acceptance fail. Scenario-owned deterministic H2 fixtures create multiple owners, pets, and visits around page and date boundaries. The Developer Brief states behavior and route discoverability but not repository query shape, controller class, or template structure.

**Hidden verifier shape.** Run repository integration tests and MockMvc/HTML assertions against fixed H2 fixtures. Check inclusive boundaries, invalid and missing ranges, stable ordering, pagination metadata/links, owner/pet association, empty results, and unchanged owner/visit workflows. A production build alone cannot satisfy acceptance.

**Exposure caveat.** Petclinic is highly exposed and its MVC/JPA conventions are public. A bounded first-party search found no matching upcoming-schedule issue, but the repository and common scheduling patterns may be familiar. The exact brief, fixtures, and verifier are project-original; no training claim is made.

**Qualification blockers.** Freeze route, default date range, tie ordering, maximum page size, and H2 query semantics; verify the task requires genuine repository/controller/view coordination and fits Challenging; run two fresh Reference Solution qualifications; audit bundled assets and Maven closure; exclude every disclosed legacy pilot repair from the task.

### 3. Spring Modulith Moments test hardening — Standard

**First-party evidence.** Apache-2.0 [license](https://github.com/spring-projects/spring-modulith/blob/c4f6d51365bdb7f943327392a9cd4e828a58af0f/LICENSE); passage-of-time logic in [`Moments`](https://github.com/spring-projects/spring-modulith/blob/c4f6d51365bdb7f943327392a9cd4e828a58af0f/spring-modulith-moments/src/main/java/org/springframework/modulith/moments/support/Moments.java), locale/zone/quarter configuration in [`MomentsProperties`](https://github.com/spring-projects/spring-modulith/blob/c4f6d51365bdb7f943327392a9cd4e828a58af0f/spring-modulith-moments/src/main/java/org/springframework/modulith/moments/support/MomentsProperties.java), current [`MomentsUnitTests`](https://github.com/spring-projects/spring-modulith/blob/c4f6d51365bdb7f943327392a9cd4e828a58af0f/spring-modulith-moments/src/test/java/org/springframework/modulith/moments/support/MomentsUnitTests.java), and module [`pom.xml`](https://github.com/spring-projects/spring-modulith/blob/c4f6d51365bdb7f943327392a9cd4e828a58af0f/spring-modulith-moments/pom.xml).

**Professionally bounded brief concept.** Add maintainable tests for existing passage-of-time event behavior across locale-specific week-year boundaries, leap dates, shifted fiscal quarters, configured zones, daylight-saving transitions, and multi-boundary positive shifts. Do not change production behavior.

**Seed mechanism.** The clean snapshot is the seed condition: existing tests cover ordinary cases but not the declared boundary matrix. The Submission is restricted to test sources; verifier-only mutants and exact hidden dates are absent from the agent workspace.

**Hidden verifier shape.** Run submitted tests against clean production code, then against a fixed non-equivalent mutation matrix: calendar year instead of locale week-based year, default instead of configured locale/zone, off-by-one month/quarter/year boundaries, incorrect negative-shift emission, and skipped multi-boundary events. Require declared mutant kills plus the clean targeted module suite; do not score raw test count or coverage percentage.

**Exposure caveat.** The source and existing tests publicly reveal most APIs and ordinary expectations, including prior issue-linked cases. The boundary matrix and mutants are project-original. Public source exposure is disclosed without inferring model training.

**Qualification blockers.** Independently prove every mutant is non-equivalent and survives the retained baseline, pin timezone data and clocks, cap targeted Maven runtime, reject production edits at handoff, and require two identical Reference Solution verifier runs.

### 4. Spring Security component-configuration migration — Standard

**First-party evidence.** MIT [license](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/LICENSE); deprecated adapter-based rules and JWT filter ordering in [`WebSecurityConfig`](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/src/main/java/io/spring/api/security/WebSecurityConfig.java), filter behavior in [`JwtTokenFilter`](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/src/main/java/io/spring/api/security/JwtTokenFilter.java), protected/public endpoint tests in [`CurrentUserApiTest`](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/src/test/java/io/spring/api/CurrentUserApiTest.java) and [`ListArticleApiTest`](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/src/test/java/io/spring/api/ListArticleApiTest.java), and Spring Boot 2.6/Security dependency identity in [`build.gradle`](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/build.gradle) plus the pinned [Gradle wrapper](https://github.com/gothinkster/spring-boot-realworld-example-app/blob/ee17e31aafe733d98c4853c8b9a74d7f2f6c924a/gradle/wrapper/gradle-wrapper.properties).

**Professionally bounded brief concept.** Replace `WebSecurityConfigurerAdapter` inheritance with component-based Spring Security configuration supported by the pinned dependency line. Preserve stateless sessions, CSRF/CORS behavior, JWT filter position, unauthorized status, public GraphQL and registration/login routes, authenticated feed access, public read routes, and authenticated mutation routes.

**Seed mechanism.** The exact snapshot is the baseline: acceptance requires removal of the deprecated adapter path and preservation of behavior. The pre-provisioned Gradle distribution and resolved dependency closure are digest pinned; no version upgrade or measured download is required.

**Hidden verifier shape.** Compile against the pinned dependencies; start the local MockMvc security context; exercise OPTIONS/CORS, anonymous and authenticated requests across every declared route class, invalid/valid JWT behavior, stateless repeated requests, and filter ordering. Inspect the produced classes/dependency graph only to verify removal of the adapter inheritance; behavioral checks remain primary.

**Exposure caveat.** The deprecated adapter and standard `SecurityFilterChain` migration pattern are widely public. A bounded first-party issue search found no exact repository migration, but the solution shape is likely familiar. This candidate measures repository-safe migration and regression preservation, not novelty.

**Qualification blockers.** Confirm the component-based API is supported by the pinned Spring Security version, freeze the exact route matrix and CORS semantics, create a dependency lock or equivalent content-addressed provisioning closure, prove the clean baseline fails only the evolution acceptance group, and replace the candidate if it becomes a mechanical one-file rewrite with insufficient repository reasoning.

## Private Suite slot contracts only

No exact private repository, ref, brief, seed, verifier content, package identity, or solution is selected or disclosed here.

| Private Spring Boot/Java slot | Difficulty | Public contract |
| --- | --- | --- |
| Defect diagnosis and repair | Challenging | A seeded behavioral defect requiring cross-layer diagnosis, deterministic hidden acceptance, and preserved regressions; no Public Suite lineage. |
| Bounded feature implementation | Standard | A small repository-integrated Spring behavior with deterministic persistence/API or MVC acceptance and no build-only success; no Public Suite lineage. |
| Test generation and hardening | Standard | Tests-only strengthening of existing behavior with a bounded hidden adequacy check and strict production-change boundaries; no Public Suite lineage. |
| Repository evolution | Challenging | A bounded framework, dependency, schema, API, or configuration migration with explicit compatibility outcomes and offline behavioral verification; no Public Suite lineage. |

The eventual private manifest must keep at most two Scenarios per lineage and at most one per lineage in a Workload Family. Exact material belongs only in the access-controlled manifest and Private Suite Commitment. Spring Data Examples, Spring Petclinic, Spring Modulith, and Spring Boot RealWorld are forbidden private lineages.

## Rejected Public candidates

- The disclosed PetValidator and Owner search repairs are rejected because they belong to the historical pilot/Legacy Calibration boundary and would leak their answers.
- A Spring Petclinic single-controller or validation mutation was rejected as too close to the disclosed pilot's local bug-fix shape for the initial measured suite.
- A whole-repository Spring Boot 2-to-3 or `javax`-to-`jakarta` migration of Spring Boot RealWorld was rejected as too broad for Standard under `standard-v1`; only the already-supported component-security seam is retained.
- Spring Modulith's full Jackson 2 compatibility removal was rejected because release-policy and cross-module compatibility scope were not proven Standard-sized.
- Spring Batch and the broader Spring Modulith monorepo were rejected for the initial slice where a targeted module command and bounded verifier could not yet be established more credibly than the selected alternatives.

## Policy and scenario-origin basis

- **Adopted:** pinned first-party source/license evidence and each repository's test/build conventions are retained as provenance. Apache-2.0 or MIT terms govern redistribution.
- **Adapted:** exposure review, Reference Solution solvability, and adversarial anti-hardcoding checks are adapted from established benchmark methodology, specialized to deterministic hidden Check Groups and hermetic Spring tests.
- **Project-original:** all four scenario concepts, seeds, hidden verifier projections, difficulty assignments, lineage allocation, Public/Private boundary, and private slot contracts are local. None is represented as a Terminal-Bench or other external benchmark task.

## Caveats

No seed patch, hidden verifier, dependency closure, Reference Solution, runtime estimate, or three-harness qualification run exists yet. Repository heads and licenses were verified from first-party GitHub and local exact-commit clones on 2026-07-12. Bounded issue searches found no exact upstream task for the four concepts, but absence from that search is not proof of no public analogue or no model exposure. The Petclinic feature and Security migration are the highest-risk difficulty classifications and must be replaced or reclassified only through the accepted same-cell qualification process.