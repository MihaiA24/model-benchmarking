#!/usr/bin/env python3
"""Regression tests for benchmark env/model fallback behavior."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

import benchmark.util as util
from benchmark.adapters.raw_api import ApiCallResult, FormatError, RawApiAdapter, extract_code
from benchmark.checks import run_checks
from benchmark.models import opencode_go_model_id, opencode_go_selector
from benchmark.runner import default_adapter_model
from gen_plantilla import load_review_rows, metric_test_ok, pick_run
from generate_fair_comparison import denominator_warning, failure_rows, wilson_interval
from merge_metrics import normalize
from rescore_results import fair_row, row_key


class EnvFallbackTests(unittest.TestCase):
    def test_benchmark_env_reads_opencode_keys_from_dotenv(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / ".env").write_text("OPENCODE_API_KEY=from-dotenv\n", encoding="utf-8")

            with patch.object(util, "REPO_ROOT", tmp_path), patch.dict(os.environ, {}, clear=True):
                env = util.benchmark_env()

        self.assertEqual(env["OPENCODE_API_KEY"], "from-dotenv")
        self.assertEqual(env["OPENCODE_GO_API_KEY"], "from-dotenv")

    def test_provider_model_with_go_equivalent_maps_to_opencode_go(self) -> None:
        self.assertEqual(opencode_go_model_id("deepseek/deepseek-v4-flash"), "deepseek-v4-flash")
        self.assertEqual(opencode_go_selector("minimax-m3"), "opencode-go/minimax-m3")
        self.assertEqual(opencode_go_selector("minimax/minimax-m3"), "opencode-go/minimax-m3")
        self.assertEqual(default_adapter_model("opencode", "deepseek/deepseek-v4-flash"), "opencode-go/deepseek-v4-flash")
        self.assertEqual(default_adapter_model("raw_api", "deepseek/deepseek-v4-flash"), "deepseek/deepseek-v4-flash")

    def test_unsupported_provider_model_does_not_silently_remap(self) -> None:
        self.assertEqual(opencode_go_model_id("z-ai/glm-4.7"), "")
        self.assertEqual(opencode_go_selector("z-ai/glm-4.7"), "")
        self.assertEqual(default_adapter_model("opencode", "z-ai/glm-4.7"), "z-ai/glm-4.7")

    def test_merge_normalizes_legacy_opencode_go_fallback_rows(self) -> None:
        row = normalize({
            "harness": "raw_api",
            "model": "minimax/minimax-m3",
            "telemetry_note": "opencode_go_chat_api_usage; cost_from_price_table",
        })

        self.assertEqual(row["adapter_model"], "opencode-go/minimax-m3")
        self.assertEqual(row["provider_backend"], "opencode-go")
        self.assertEqual(row["api_backend"], "opencode_go_chat")
        self.assertEqual(row["pricing_model"], "opencode-go/minimax-m3")


    def _api_result(self, pricing_model: str) -> ApiCallResult:
        return ApiCallResult(
            text="text",
            in_tokens=1,
            out_tokens=2,
            latency_s=0.1,
            telemetry_note="note",
            provider_backend="opencode-go" if pricing_model.startswith("opencode-go/") else "deepseek",
            api_backend="opencode_go_chat" if pricing_model.startswith("opencode-go/") else "openrouter_chat",
            pricing_model=pricing_model,
        )

    def test_raw_api_falls_back_to_opencode_go_when_openrouter_missing(self) -> None:
        adapter = RawApiAdapter()
        with (
            patch("benchmark.adapters.raw_api.read_openrouter_key", return_value=""),
            patch("benchmark.adapters.raw_api.read_opencode_key", return_value="go-key"),
            patch.object(adapter, "_call_opencode_chat", return_value=self._api_result("opencode-go/deepseek-v4-flash")) as call_opencode,
        ):
            result = adapter._call_api(model="deepseek/deepseek-v4-flash", user_msg="prompt", timeout_s=1)

        self.assertEqual(result.pricing_model, "opencode-go/deepseek-v4-flash")
        self.assertEqual(call_opencode.call_args.kwargs["model_id"], "deepseek-v4-flash")

    def test_raw_api_uses_chat_endpoint_for_minimax_fallback(self) -> None:
        adapter = RawApiAdapter()
        with (
            patch("benchmark.adapters.raw_api.read_openrouter_key", return_value=""),
            patch("benchmark.adapters.raw_api.read_opencode_key", return_value="go-key"),
            patch.object(adapter, "_call_opencode_chat", return_value=self._api_result("opencode-go/minimax-m3")) as call_opencode,
        ):
            result = adapter._call_api(model="minimax/minimax-m3", user_msg="prompt", timeout_s=1)

        self.assertEqual(result.pricing_model, "opencode-go/minimax-m3")
        self.assertEqual(call_opencode.call_args.kwargs["model_id"], "minimax-m3")

    def test_raw_api_prefers_openrouter_when_openrouter_present(self) -> None:
        adapter = RawApiAdapter()
        with (
            patch("benchmark.adapters.raw_api.read_openrouter_key", return_value="openrouter-key"),
            patch("benchmark.adapters.raw_api.read_opencode_key", return_value="go-key"),
            patch.object(adapter, "_call_openrouter", return_value=self._api_result("deepseek/deepseek-v4-flash")) as call_openrouter,
            patch.object(adapter, "_call_opencode_chat") as call_opencode,
        ):
            result = adapter._call_api(model="deepseek/deepseek-v4-flash", user_msg="prompt", timeout_s=1)

        self.assertEqual(result.pricing_model, "deepseek/deepseek-v4-flash")
        self.assertEqual(call_openrouter.call_args.kwargs["model"], "deepseek/deepseek-v4-flash")
        call_opencode.assert_not_called()


class RawApiExtractionTests(unittest.TestCase):
    def test_extract_code_ignores_think_snippets_and_uses_final_block(self) -> None:
        response = """<think>
```java
if (!StringUtils.hasLength(name)) {
    errors.rejectValue("name", REQUIRED, REQUIRED);
}
```
</think>
```java
package example;

class PetValidator {}
```
"""

        self.assertEqual(extract_code(response).strip(), "package example;\n\nclass PetValidator {}")

    def test_extract_code_uses_last_visible_block(self) -> None:
        response = """Example:
```sql
JOIN InvoiceLine il ON t.TrackId = il.InvoiceLineId
```
Final answer:
```python
print("fixed")
```
"""

        self.assertEqual(extract_code(response).strip(), 'print("fixed")')

    def test_extract_code_reports_format_error_for_missing_block(self) -> None:
        with self.assertRaisesRegex(FormatError, "format_error"):
            extract_code("No fenced code here")


class CheckRunnerTests(unittest.TestCase):
    def test_run_checks_skips_test_command_when_build_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            marker = tmp_path / "test-ran"
            task = SimpleNamespace(
                build_cmd=[sys.executable, "-c", "import sys; sys.exit(1)"],
                test_cmd=[sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"],
                test_ok_equals_build=False,
            )

            self.assertEqual(run_checks(tmp_path, task, timeout_s=5), (False, False))
            self.assertFalse(marker.exists())


class RescoreResultTests(unittest.TestCase):
    def test_fair_row_applies_posthoc_rescore_result(self) -> None:
        metrics = {"harness": "raw_api", "task": "bug1-petvalidator", "model": "minimax/minimax-m3", "run": "1", "build_ok": "False", "test_ok": "False"}
        audit = {"category": "harness.raw_api_extraction_mismatch", "suggested_disposition": "posthoc_rescore_candidate", "notes": ""}
        rescore = {row_key(metrics): {"rescored_build_ok": "True", "rescored_test_ok": "True", "rescore_workdir": "/tmp/rescore"}}

        row = fair_row(metrics, audit, rescore)

        self.assertEqual(row["fair_status"], "posthoc_rescore_pass")
        self.assertEqual(row["fair_build_ok"], "True")
        self.assertEqual(row["fair_test_ok"], "True")
        self.assertEqual(row["fair_included"], "True")

    def test_fair_row_excludes_infra(self) -> None:
        metrics = {"harness": "raw_api", "task": "ng-bug1-missing-input", "model": "minimax/minimax-m3", "run": "1", "build_ok": "False", "test_ok": "False"}
        audit = {"category": "infra.angular_missing_ng", "suggested_disposition": "exclude_infra", "notes": "missing ng"}

        row = fair_row(metrics, audit, {})

        self.assertEqual(row["fair_status"], "excluded_infra")
        self.assertEqual(row["fair_included"], "False")


class HumanReviewGeneratorTests(unittest.TestCase):
    def test_pick_run_prefers_fair_status_over_raw_status(self) -> None:
        chosen = pick_run([
            {"run": "1", "build_ok": "True", "test_ok": "True", "fair_build_ok": "False", "fair_test_ok": "False"},
            {"run": "2", "build_ok": "False", "test_ok": "False", "fair_build_ok": "True", "fair_test_ok": "True"},
        ])

        self.assertEqual(chosen["run"], "2")
        self.assertEqual(metric_test_ok(chosen), "True")

    def test_load_review_rows_excludes_infra_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            metrics = Path(tmp) / "metrics_fair.csv"
            metrics.write_text(
                "harness,task,model,run,test_ok,fair_test_ok,fair_included,fair_status\n"
                "raw_api,t1,m1,1,False,False,False,excluded_infra\n"
                "raw_api,t2,m1,1,False,True,True,posthoc_rescore_pass\n",
                encoding="utf-8",
            )

            rows = load_review_rows(metrics, include_excluded=False)

        self.assertEqual([row["task"] for row in rows], ["t2"])


class FairComparisonOutputTests(unittest.TestCase):
    def test_wilson_interval_and_denominator_warning(self) -> None:
        low, high = wilson_interval(25, 25)

        self.assertGreater(low, 0.8)
        self.assertEqual(high, 1.0)
        self.assertIn("low_n", denominator_warning(25))

    def test_failure_rows_uses_posthoc_rescore_workdir(self) -> None:
        with TemporaryDirectory() as tmp:
            rescore_workdir = Path(tmp) / "rescore"
            original_workdir = Path(tmp) / "original"
            rescore_workdir.mkdir()
            original_workdir.mkdir()
            (rescore_workdir / "_test_output.txt").write_text("FAIL: rescore evidence\n", encoding="utf-8")
            (original_workdir / "_test_output.txt").write_text("FAIL: stale evidence\n", encoding="utf-8")
            df = pd.DataFrame([
                {
                    "harness": "raw_api",
                    "task": "re-feat2-author-filter",
                    "model": "minimax/minimax-m3",
                    "run": "1",
                    "fair_failed": True,
                    "fair_status": "posthoc_rescore_fail",
                    "fair_notes": "",
                    "workdir": str(original_workdir),
                    "transcript_path": "",
                }
            ])
            rows = failure_rows(df, {("raw_api", "re-feat2-author-filter", "minimax/minimax-m3", "1"): {"rescore_workdir": str(rescore_workdir)}})

        self.assertIn("rescore evidence", rows[0]["evidence_excerpt"])
        self.assertIn("rescore", rows[0]["evidence_file"])


if __name__ == "__main__":
    unittest.main()
