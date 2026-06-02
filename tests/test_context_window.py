"""Context-window sizing: presets, RAM-safe ceiling, num_ctx resolution."""

from __future__ import annotations

import pytest

from daemon import context_window as cw


@pytest.fixture(autouse=True)
def _reset_setting():
    cw.set_setting("auto")
    yield
    cw.set_setting("auto")


class TestModelMax:
    def test_known_model(self):
        assert cw.model_max("llama3.1:8b") == 128_000

    def test_unknown_defaults_32k(self):
        assert cw.model_max("mystery-model") == 32_000


class TestRamSafeCeiling:
    def test_small_model_big_ceiling(self):
        # An 8B on 48 GB should allow a large context (tens of thousands+).
        ceiling = cw.ram_safe_ceiling("llama3.1:8b", ram_budget_gb=36.0)
        assert ceiling >= 32_000

    def test_big_model_smaller_ceiling(self):
        small = cw.ram_safe_ceiling("qwen2.5-coder:32b", ram_budget_gb=36.0)
        big = cw.ram_safe_ceiling("qwen2.5-coder:7b", ram_budget_gb=36.0)
        assert small < big

    def test_tiny_ram_floors_at_4k(self):
        assert cw.ram_safe_ceiling("qwen2.5-coder:32b", ram_budget_gb=20.0) >= 4096

    def test_never_exceeds_model_max(self):
        ceiling = cw.ram_safe_ceiling("qwen2.5-coder:7b", ram_budget_gb=48.0)
        assert ceiling <= cw.model_max("qwen2.5-coder:7b")


class TestResolveNumCtx:
    def test_auto_picks_largest_preset_within_ceiling(self):
        cw.set_setting("auto")
        n = cw.resolve_num_ctx("llama3.1:8b", ram_budget_gb=36.0)
        assert n in cw.PRESETS
        assert n <= cw.ram_safe_ceiling("llama3.1:8b", 36.0)

    def test_explicit_value_clamped_to_ceiling(self):
        cw.set_setting(131072)
        n = cw.resolve_num_ctx("qwen2.5-coder:32b", ram_budget_gb=24.0)
        assert n <= cw.ram_safe_ceiling("qwen2.5-coder:32b", 24.0)

    def test_explicit_value_honored_when_safe(self):
        cw.set_setting(16384)
        n = cw.resolve_num_ctx("llama3.1:8b", ram_budget_gb=36.0)
        assert n == 16384

    def test_floor_4k(self):
        cw.set_setting(100)
        assert cw.resolve_num_ctx("qwen2.5-coder:7b", ram_budget_gb=36.0) >= 4096


class TestPresets:
    def test_includes_large_windows(self):
        assert 262144 in cw.PRESETS  # 256K
        assert 524288 in cw.PRESETS  # 512K
        assert 1048576 in cw.PRESETS  # 1M
        assert 2097152 in cw.PRESETS  # 2M

    def test_human_labels(self):
        assert cw._human(262144) == "256K"
        assert cw._human(1048576) == "1M"
        assert cw._human(2097152) == "2M"

    def test_large_presets_disabled_on_small_model(self):
        # qwen2.5-coder:7b maxes at 32K → the big windows are flagged as
        # exceeding the model, so the UI greys them out (not hidden).
        opts = cw.options_for("qwen2.5-coder:7b", ram_budget_gb=36.0)
        for tokens in (262144, 1048576, 2097152):
            p = next(x for x in opts["presets"] if x["tokens"] == tokens)
            assert p["exceeds_model"] is True

    def test_large_preset_available_for_long_context_model(self):
        # llama-4-scout advertises a 10M window, so 1M is within the model max
        # (RAM may still gate it, but it's not flagged as exceeding the model).
        opts = cw.options_for("llama-4-scout", ram_budget_gb=36.0)
        one_m = next(x for x in opts["presets"] if x["tokens"] == 1048576)
        assert one_m["exceeds_model"] is False


class TestOptionsFor:
    def test_options_mark_fit_and_model_max(self):
        opts = cw.options_for("qwen2.5-coder:7b", ram_budget_gb=36.0)
        assert opts["model_max"] == 32_000
        assert "ceiling" in opts and "auto" in opts
        # Presets above the model's 32K max are flagged.
        big = next(p for p in opts["presets"] if p["tokens"] == 131072)
        assert big["exceeds_model"] is True
        # Each preset carries a KV-cache GB estimate.
        assert all("kv_gb" in p for p in opts["presets"])


class TestSetting:
    def test_set_auto_and_int(self):
        cw.set_setting("auto")
        assert cw.get_setting() == "auto"
        cw.set_setting(32768)
        assert cw.get_setting() == 32768

    def test_invalid_setting_rejected(self):
        with pytest.raises(ValueError):
            cw.set_setting("huge")


class TestWsHandlers:
    async def _send(self, msg, tmp_db):
        import json

        from daemon import ws_server
        from daemon.budget import BudgetController

        return await ws_server._handle_message(
            object(), json.dumps(msg), tmp_db, None, BudgetController()
        )

    @pytest.mark.asyncio
    async def test_context_options_handler(self, tmp_db):
        resp = await self._send({"type": "context.options", "model": "llama3.1:8b"}, tmp_db)
        assert resp["type"] == "context_options"
        assert resp["model_max"] == 128_000
        assert len(resp["presets"]) == len(cw.PRESETS)

    @pytest.mark.asyncio
    async def test_set_context_handler(self, tmp_db):
        resp = await self._send(
            {"type": "set_context", "value": 16384, "model": "llama3.1:8b"}, tmp_db
        )
        assert resp["type"] == "context_set"
        assert resp["setting"] == 16384
        assert resp["resolved"] == 16384

    @pytest.mark.asyncio
    async def test_set_context_invalid(self, tmp_db):
        resp = await self._send({"type": "set_context", "value": "massive"}, tmp_db)
        assert resp["type"] == "error"
