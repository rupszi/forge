"""Tests for the plugin system: connectors, skills, LLM adapters, lethal trifecta.

These cover the v0.1.0 skeleton — the registries, manifest validation,
refused-capability gates, and the lethal-trifecta gate. The full sandbox
runtime (subprocess + rlimit + egress filter) gets its own test file
once Sprint 6 lands the live plumbing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from forge_plugin_api import (
    Connector,
    GenerationRequest,
    GenerationResult,
    LLMAdapter,
    Tool,
    ToolResult,
)

from daemon.connectors import ConnectorRegistry, load_connector
from daemon.connectors.registry import ConnectorEntry, ConnectorManifest
from daemon.llms import load_llm
from daemon.llms.registry import LLMManifest
from daemon.skills import is_blocked_combination, load_skill
from daemon.skills.lethal_trifecta import BUILTIN_PROFILES, CapabilityProfile
from daemon.skills.registry import SkillManifest

# ---- Manifest refusal gates ----


def test_connector_refuses_shell_in_exec():
    with pytest.raises(ValueError, match="shell"):
        ConnectorManifest(name="bad", version="0.1.0", description="d", exec=["bash", "echo"])


def test_connector_refuses_wildcard_network():
    with pytest.raises(ValueError, match="wildcard"):
        ConnectorManifest(name="bad", version="0.1.0", description="d", network=["*"])


def test_connector_refuses_system_path():
    with pytest.raises(ValueError, match="system path"):
        ConnectorManifest(name="bad", version="0.1.0", description="d", filesystem=["/etc/passwd"])


def test_skill_refuses_shell_in_exec():
    with pytest.raises(ValueError, match="shell"):
        SkillManifest(name="bad", version="0.1.0", exec=["sh"])


def test_skill_refuses_root_filesystem():
    with pytest.raises(ValueError, match="system path"):
        SkillManifest(name="bad", version="0.1.0", filesystem=["/"])


def test_llm_refuses_no_network():
    """LLM adapter with no network capability is meaningless — must declare endpoint."""
    with pytest.raises(ValueError, match="network capability"):
        LLMManifest(name="bad", version="0.1.0", network=[], family="x")


def test_llm_refuses_no_family():
    """family is required for cross-family-evaluator routing (ADR-006)."""
    with pytest.raises(ValueError, match="family"):
        LLMManifest(name="bad", version="0.1.0", network=["https://x.com"], family="")


# ---- Lethal-trifecta gate ----


def test_trifecta_blocks_private_untrusted_egress():
    profiles = [
        CapabilityProfile(reads_private=True, reads_untrusted=False, writes_external=False),
        CapabilityProfile(reads_private=False, reads_untrusted=True, writes_external=False),
        CapabilityProfile(reads_private=False, reads_untrusted=False, writes_external=True),
    ]
    reason = is_blocked_combination(profiles)
    assert reason is not None
    assert "lethal-trifecta" in reason


def test_trifecta_allows_two_legs_only():
    """Private + egress without untrusted = OK (e.g., posting your own data)."""
    profiles = [
        CapabilityProfile(reads_private=True, reads_untrusted=False, writes_external=True),
    ]
    assert is_blocked_combination(profiles) is None


def test_trifecta_allows_untrusted_alone():
    profiles = [
        CapabilityProfile(reads_private=False, reads_untrusted=True, writes_external=False),
    ]
    assert is_blocked_combination(profiles) is None


def test_trifecta_empty_profiles_allowed():
    assert is_blocked_combination([]) is None


def test_builtin_profiles_have_known_keys():
    """Sanity: at least the headline integrations are pre-classified."""
    for key in ("github_mcp", "vercel_mcp", "supabase_mcp", "sendgrid", "web_research"):
        assert key in BUILTIN_PROFILES


def test_builtin_combination_real_world_block():
    """vercel_mcp (private + egress) + web_research (untrusted) trips the gate."""
    reason = is_blocked_combination(
        [BUILTIN_PROFILES["vercel_mcp"], BUILTIN_PROFILES["web_research"]]
    )
    assert reason is not None


# ---- Connector registry ----


def test_connector_registry_register_and_get():
    reg = ConnectorRegistry()
    manifest = ConnectorManifest(name="x", version="0.1.0", description="d")
    entry = ConnectorEntry(manifest=manifest, plugin_path=Path("/tmp/x"))
    reg.register(entry)
    assert reg.get("x") is entry
    assert reg.get("missing") is None


def test_connector_registry_enable_disable():
    reg = ConnectorRegistry()
    manifest = ConnectorManifest(name="x", version="0.1.0", description="d")
    entry = ConnectorEntry(manifest=manifest, plugin_path=Path("/tmp/x"))
    reg.register(entry)

    assert entry.enabled is False
    assert reg.enable("x") is True
    assert entry.enabled is True
    assert reg.disable("x") is True
    assert entry.enabled is False

    # Non-existent connector
    assert reg.enable("missing") is False
    assert reg.disable("missing") is False


def test_connector_registry_list_separates_enabled():
    reg = ConnectorRegistry()
    a = ConnectorEntry(
        manifest=ConnectorManifest(name="a", version="0.1.0", description="a"),
        plugin_path=Path("/tmp/a"),
        enabled=True,
    )
    b = ConnectorEntry(
        manifest=ConnectorManifest(name="b", version="0.1.0", description="b"),
        plugin_path=Path("/tmp/b"),
        enabled=False,
    )
    reg.register(a)
    reg.register(b)

    all_ = reg.list_all()
    assert [e.manifest.name for e in all_] == ["a", "b"]  # sorted

    enabled = reg.list_enabled()
    assert [e.manifest.name for e in enabled] == ["a"]


# ---- Loaders raise on missing files ----


def test_load_connector_raises_on_missing_dir(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_connector(tmp_path / "does-not-exist")


def test_load_connector_raises_on_missing_manifest(tmp_path):
    p = tmp_path / "plugin"
    p.mkdir()
    with pytest.raises(FileNotFoundError, match=r"manifest\.toml"):
        load_connector(p)


def test_load_skill_raises_on_missing_skill_md(tmp_path):
    p = tmp_path / "skill"
    p.mkdir()
    (p / "manifest.toml").write_text("[plugin]\nname='s'\nversion='0.1.0'\n")
    with pytest.raises(FileNotFoundError, match=r"SKILL\.md"):
        load_skill(p)


def test_load_skill_round_trip(tmp_path):
    """End-to-end: write manifest+SKILL.md, load, verify capabilities + hash."""
    p = tmp_path / "csv-cleaner"
    p.mkdir()
    (p / "SKILL.md").write_text("# CSV Cleaner\n\nUse this when ...")
    (p / "manifest.toml").write_text("""
[plugin]
name = "csv-cleaner"
version = "0.2.0"
description = "Cleans CSV files"

[skill]
when_to_use = "When the user asks to dedupe CSV"
entry_script = "scripts/clean.py"

[capabilities]
filesystem = ["${WORKTREE}"]
network = []
exec = []
secrets_read = []

[limits]
memory_mb = 256
cpu_seconds = 30
wall_seconds = 60
""")
    (p / "scripts").mkdir()
    (p / "scripts" / "clean.py").write_text("# placeholder\n")

    entry = load_skill(p)
    assert entry.manifest.name == "csv-cleaner"
    assert entry.manifest.version == "0.2.0"
    assert entry.manifest.memory_mb == 256
    assert entry.manifest.cpu_seconds == 30
    assert entry.skill_md.startswith("# CSV Cleaner")
    assert len(entry.manifest_sha256) == 64  # SHA-256 hex
    assert entry.enabled is False  # default disabled


def test_load_llm_round_trip(tmp_path):
    p = tmp_path / "cohere"
    p.mkdir()
    (p / "manifest.toml").write_text("""
[plugin]
name = "cohere"
version = "0.1.0"

[capabilities]
network = ["https://api.cohere.com"]
secrets_read = ["COHERE_API_KEY"]

[llm]
provider = "cohere"
family = "cohere"
default_model = "command-r"
api_key_env = "COHERE_API_KEY"
""")
    entry = load_llm(p)
    assert entry.manifest.provider == "cohere"
    assert entry.manifest.family == "cohere"
    assert entry.manifest.network == ["https://api.cohere.com"]
    assert entry.enabled is False


# ---- Public API surface ----


def test_tool_decorator_attaches_metadata():
    @Tool(name="my_tool", side_effects="external", idempotent=True)
    async def some_method(self):
        return ToolResult(ok=True)

    meta = some_method._forge_tool_meta  # type: ignore[attr-defined]
    assert meta["name"] == "my_tool"
    assert meta["side_effects"] == "external"
    assert meta["idempotent"] is True


def test_connector_lists_decorated_tools():
    class Sample(Connector):
        name = "sample"

        @Tool(name="t1", side_effects="readonly")
        async def t1(self):
            return ToolResult(ok=True)

        @Tool(name="t2", side_effects="external")
        async def t2(self):
            return ToolResult(ok=True)

        async def not_a_tool(self):
            return None

    tools = Sample._list_tools()
    names = sorted(t["name"] for t in tools)
    assert names == ["t1", "t2"]


def test_llm_adapter_default_unsupported():
    """Subclasses must override generate; defaults are conservative for tools/json."""
    adapter = LLMAdapter(secrets={})
    assert adapter.supports_tools("any") is False
    assert adapter.supports_json_mode("any") is False


def test_generation_request_and_result_dataclass():
    req = GenerationRequest(
        model="x",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.0,
    )
    assert req.model == "x"
    res = GenerationResult(text="hello", tokens_in=10, tokens_out=2)
    assert res.text == "hello"
    assert res.stop_reason == "stop"
