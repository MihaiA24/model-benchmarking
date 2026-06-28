#!/usr/bin/env python3
"""Regression tests for benchmark env/model fallback behavior."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import benchmark.util as util
from benchmark.adapters.raw_api import RawApiAdapter
from benchmark.models import opencode_go_model_id, opencode_go_selector
from benchmark.runner import default_adapter_model


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
        self.assertEqual(opencode_go_selector("minimax/minimax-m3"), "opencode-go/minimax-m3")
        self.assertEqual(default_adapter_model("opencode", "deepseek/deepseek-v4-flash"), "opencode-go/deepseek-v4-flash")
        self.assertEqual(default_adapter_model("raw_api", "deepseek/deepseek-v4-flash"), "deepseek/deepseek-v4-flash")

    def test_unsupported_provider_model_does_not_silently_remap(self) -> None:
        self.assertEqual(opencode_go_model_id("z-ai/glm-4.7"), "")
        self.assertEqual(opencode_go_selector("z-ai/glm-4.7"), "")
        self.assertEqual(default_adapter_model("opencode", "z-ai/glm-4.7"), "z-ai/glm-4.7")

    def test_raw_api_falls_back_to_opencode_go_when_openrouter_missing(self) -> None:
        adapter = RawApiAdapter()
        with (
            patch("benchmark.adapters.raw_api.read_openrouter_key", return_value=""),
            patch("benchmark.adapters.raw_api.read_opencode_key", return_value="go-key"),
            patch.object(adapter, "_call_opencode_chat", return_value=("text", 1, 2, 0.1, "note")) as call_opencode,
        ):
            result = adapter._call_api(model="deepseek/deepseek-v4-flash", user_msg="prompt", timeout_s=1)

        self.assertEqual(result, ("text", 1, 2, 0.1, "note"))
        self.assertEqual(call_opencode.call_args.kwargs["model_id"], "deepseek-v4-flash")

    def test_raw_api_uses_chat_endpoint_for_minimax_fallback(self) -> None:
        adapter = RawApiAdapter()
        with (
            patch("benchmark.adapters.raw_api.read_openrouter_key", return_value=""),
            patch("benchmark.adapters.raw_api.read_opencode_key", return_value="go-key"),
            patch.object(adapter, "_call_opencode_chat", return_value=("text", 1, 2, 0.1, "note")) as call_opencode,
        ):
            result = adapter._call_api(model="minimax/minimax-m3", user_msg="prompt", timeout_s=1)

        self.assertEqual(result, ("text", 1, 2, 0.1, "note"))
        self.assertEqual(call_opencode.call_args.kwargs["model_id"], "minimax-m3")

    def test_raw_api_prefers_openrouter_when_openrouter_present(self) -> None:
        adapter = RawApiAdapter()
        with (
            patch("benchmark.adapters.raw_api.read_openrouter_key", return_value="openrouter-key"),
            patch("benchmark.adapters.raw_api.read_opencode_key", return_value="go-key"),
            patch.object(adapter, "_call_openrouter", return_value=("text", 1, 2, 0.1, "note")) as call_openrouter,
            patch.object(adapter, "_call_opencode_chat") as call_opencode,
        ):
            result = adapter._call_api(model="deepseek/deepseek-v4-flash", user_msg="prompt", timeout_s=1)

        self.assertEqual(result, ("text", 1, 2, 0.1, "note"))
        self.assertEqual(call_openrouter.call_args.kwargs["model"], "deepseek/deepseek-v4-flash")
        call_opencode.assert_not_called()


if __name__ == "__main__":
    unittest.main()
