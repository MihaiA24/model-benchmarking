# Harbor post-stop Submission capture proof

This standalone project proves that pinned Harbor can stop the evaluated `main`
service before a trusted sidecar captures a Trial-local repository, collect only
the sidecar-produced handoff, and pass that handoff to a separate verifier.
It does not patch Harbor, import Harbor lifecycle internals, or give the evaluated
service access to the collector image or output directory.

## Run the proof

From the repository root, with a working Docker daemon:

```sh
uv run --project proofs/harbor-submission-capture --frozen pytest -q proofs/harbor-submission-capture/tests --maxfail=1
```

The command intentionally fails rather than skips when Docker is unavailable.
A successful full run atomically writes and immediately verifies:

- `artifacts/proof-report.json`
- `artifacts/cases/*.json`
- `artifacts/sha256sums.txt`

Focused test runs do not overwrite those authoritative full-suite artifacts.
The report is deterministic: it contains no timestamps, temporary paths, trial
UUIDs, or race-dependent patch bytes.
The canonical full-suite invocation removes prior success artifacts before
collection starts and again on any test, collection, or publication failure.

## Supported Harbor seam

Harbor is locked to commit
`527d50deb63a5d279e8c20593c18a2cbc7f61f9e` (`0.18.0`). The proof composes
public task and Compose configuration already supported at that commit:

1. `[verifier].environment_mode = "separate"` selects a fresh verifier
   environment.
2. `[[verifier.collect]]` runs the collector command in the named `capture`
   sidecar.
3. Service-scoped `artifacts` download only `/capture/capture.json` and
   `/capture/submission.patch` from that sidecar.
4. In a single-step trial with a separate verifier, Harbor automatically asks
   phased artifact collection to stop `main` before sidecar evidence is read.
5. Harbor downloads main artifacts, stops `main`, runs sidecar collection, and
   then starts the separate verifier.

First-party evidence at the pinned commit:

- [`single_step.py` lines 38-52](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/single_step.py#L38-L52)
  derives the stop-before-sidecars behavior from separate-verifier mode.
- [`trial.py` lines 918-967](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/trial/trial.py#L918-L967)
  implements phased main/sidecar collection and stops `main` first.
- [`config.py` lines 563-590](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/src/harbor/models/task/config.py#L563-L590)
  defines separate-verifier mode and public collect hooks.
- [`test_single_step_trial.py` lines 99-129](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/tests/unit/test_single_step_trial.py#L99-L129)
  asserts the order `download:main`, `stop:main`, `download:sidecar`.
- The upstream [`sidecar-artifacts` task](https://github.com/harbor-framework/harbor/blob/527d50deb63a5d279e8c20593c18a2cbc7f61f9e/examples/tasks/sidecar-artifacts/task.toml)
  demonstrates service-scoped artifacts, a sidecar collect hook, and a separate
  verifier without lifecycle patches.

There is no public `stop_main_before_sidecars` task key at this Harbor commit.
That flag is an internal argument selected automatically by the supported
single-step + separate-verifier composition above.

## Trust boundary

The evaluated `main` service owns the writable `/workspace` volume. Every case
asserts that `/tests` and `/capture` are absent from that service, proving the
Harness never receives verifier assets or a route to collector output. The capture
sidecar receives only `/input:ro`, has no network, drops all Linux capabilities,
and enables `no-new-privileges`. Its collector and baseline are root-owned and
read-only to UID `65532`; only its private `/capture` directory is writable to
that UID. `main` has no mount or channel to `/capture`.

The verifier is built independently from `tests/Dockerfile`. Harbor transfers
only the two declared sidecar artifacts into it. Verifier assertions fail if the
mutable workspace, solution, agent-home marker, or undeclared files cross that
boundary.

`/capture` intentionally uses the sidecar's private writable container layer,
not tmpfs. Real-Docker testing showed the hook could write tmpfs successfully,
but Harbor's subsequent Compose copy could not retrieve those files. The
private layer remains inaccessible to `main`, while root-owned collector inputs
remain immutable to the non-root sidecar process.

## Cases

| Case | Expected disposition |
| --- | --- |
| Normal patch | Accepted normalized patch; separate verifier receives no agent-home data |
| No-op | Accepted explicit no-op with an empty patch |
| Malicious path | Rejected as an undeclared path; no patch collected |
| Symlink | Rejected without dereferencing; no patch collected |
| Special file | Rejected; no patch collected |
| Oversized file | Rejected by the byte limit; no patch collected |
| Racing descendant | `main` and descendant stop before a stable two-snapshot capture |
| Missing capture | Both artifacts remain missing and verifier reward remains zero |

## Scope and limitations

- This proves the Harbor lifecycle/configuration seam, not a production-ready
  Submission format implementation.
- The demonstration patch normalizer accepts only bounded UTF-8 regular,
  non-executable files allowed by `policy.json`, with paths restricted to the
  patch-safe ASCII set `[A-Za-z0-9._/-]`. It deliberately rejects binary,
  non-UTF-8, control-character/unsafe paths, symlink, hard-link, special-file,
  unsafe-mode, undeclared-path, and limit violations. Missing final newlines are
  represented with standard Git patch markers.
- The stop-before-capture guarantee exercised here is the pinned single-step,
  separate-verifier path. Other Harbor modes require their own proof before use.
- Harbor artifact downloads are best-effort. Therefore acceptance must gate on
  the capture record, artifact manifest, verifier result, and sealed proof—not
  merely on a successful Harbor CLI exit code.
- Race-case bytes are intentionally nondeterministic; the proof asserts lifecycle
  order, bounded output, and stability after stop rather than a fixed race count.
