# Terminal-Bench 2.1 portfolio-methodology comparison

**Status:** Verified research note
**Reviewed:** 2026-07-11
**Purpose:** Evidence for [Select the initial scenario portfolio](https://github.com/MihaiA24/model-benchmarking/issues/20)

## Answer

Terminal-Bench 2.1 does **not** define or use a two-band `Standard`/`Challenging` portfolio policy. The benchmark stores author-supplied `easy`, `medium`, or `hard` metadata and expert/junior time estimates on individual tasks. The Terminal-Bench paper separately reports a post-hoc empirical `Easy`/`Medium`/`Hard` categorization derived from agent pass rates. The project-owned `Standard`/`Challenging` rule in this benchmark is therefore neither copied from nor directly aligned with Terminal-Bench 2.1.

That distinction is intentional: this project assigns its portfolio band before measured Harness Trials from structural task evidence and prohibits relabeling from observed Harness success. The band balances the finite portfolio; it is not a primary analysis stratum or a post-hoc model-performance category.

## Verified Terminal-Bench methodology

### Portfolio and submission coverage

- The Terminal-Bench paper reports 229 crowd-sourced tasks from 93 contributors, with author-provided expert and junior completion estimates; 89 were selected for Terminal-Bench 2.0 using author difficulty plus quality assessment by three experienced reviewers.
- The reviewed Terminal-Bench 2.1 repository commit contains 89 task manifests. The official 2.1 release describes a corrective revision that fixes 28 tasks rather than a newly difficulty-stratified subset.
- Official leaderboard submissions must run the unmodified dataset, cover every task, and provide at least five Trials per task. There is no sampled Standard/Challenging layer.

### Difficulty

At reviewed commit [`816d3988d95426329f14e5eba23cb7fd8bfb04f7`](https://github.com/harbor-framework/terminal-bench-2-1/tree/816d3988d95426329f14e5eba23cb7fd8bfb04f7), task metadata demonstrates all three author-facing labels:

- [`fix-git`](https://github.com/harbor-framework/terminal-bench-2-1/blob/816d3988d95426329f14e5eba23cb7fd8bfb04f7/tasks/fix-git/task.toml): `easy`, expert estimate 5 minutes, junior estimate 20 minutes;
- [`mteb-retrieve`](https://github.com/harbor-framework/terminal-bench-2-1/blob/816d3988d95426329f14e5eba23cb7fd8bfb04f7/tasks/mteb-retrieve/task.toml): `medium`, 15 and 45 minutes; and
- [`configure-git-webserver`](https://github.com/harbor-framework/terminal-bench-2-1/blob/816d3988d95426329f14e5eba23cb7fd8bfb04f7/tasks/configure-git-webserver/task.toml): `hard`, 15 and 60 minutes.

The paper's separate **empirical difficulty** uses selected frontier-model pass rates: `Easy` at least 66.7%, `Medium` from 33.3% through 66.7%, and `Hard` below 33.3%. Those labels describe observed model performance and must not be imported as pre-trial portfolio labels here.

### Quality and contamination controls

The paper describes specificity review, oracle/reference solvability, integrity and anti-cheating checks, automated and LLM checks, model Trials, adversarial exploit-agent testing, and manual audits. These are useful qualification precedents, although this benchmark keeps its already accepted deterministic verifier and Reference Solution contracts rather than copying Terminal-Bench's complete process.

Terminal-Bench places the Big-Bench/Terminal-Bench canary string in repository files to aid training-corpus decontamination. Its paper also states that all tasks are public, that it has no private held-out test set, and that canaries cannot prevent intentional contamination. The canary is therefore disclosure evidence, not proof that a model has never seen a task. This benchmark's separate Private Suite and access-controlled task assets provide a stronger held-out boundary, while still requiring exposure searches and later invalidation when leakage is discovered.

## Consequences for this benchmark

1. Keep the accepted project-owned `Standard`/`Challenging` bands and pre-trial structural assignment.
2. Do not infer or revise a Scenario's band from measured Harness pass rates.
3. Preserve human time estimates and structural difficulty evidence as useful review metadata, without treating them as calibrated outcome labels.
4. Retain the accepted independent review, Reference Solution, anti-hardcoding, and deterministic qualification gates.
5. Treat canaries as optional provenance markers only; do not substitute them for the Public/Private split, access controls, exposure review, or suite invalidation policy.

## Primary sources

- [Official Terminal-Bench 2.1 release](https://www.tbench.ai/news/terminal-bench-2-1)
- [Terminal-Bench 2.1 repository at reviewed commit](https://github.com/harbor-framework/terminal-bench-2-1/tree/816d3988d95426329f14e5eba23cb7fd8bfb04f7)
- [Dataset manifest](https://github.com/harbor-framework/terminal-bench-2-1/blob/816d3988d95426329f14e5eba23cb7fd8bfb04f7/tasks/dataset.toml)
- [Leaderboard submission requirements](https://github.com/harbor-framework/terminal-bench-2-1/blob/816d3988d95426329f14e5eba23cb7fd8bfb04f7/leaderboard/SUBMIT.md#L32-L42)
- [Terminal-Bench paper, arXiv v1](https://arxiv.org/html/2601.11868v1), especially task construction, quality control, empirical difficulty, limitations, and benchmark-reporting sections
- [Official task-wizard difficulty and canary implementation](https://github.com/harbor-framework/terminal-bench/blob/d28711d0da2675d0bb1d56de45ae5df6082438a3/terminal_bench/cli/wizard.py#L580-L636)

## Evidence limits

The official 2.1 release says 28 tasks were fixed, while some first-party repository prose has described 26 modified tasks. This note relies on the release page for the 28-task claim and does not use the discrepancy to infer portfolio behavior. Terminal-Bench's task quality process is evidence for useful checks, not proof that its broad terminal-task population is representative of this benchmark's three professional ecosystems and four Workload Families.
