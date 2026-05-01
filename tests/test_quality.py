"""Quality tests: code structure, imports, consistency."""

import importlib
import os

import pytest


class TestModuleImports:
    """Verify all modules import cleanly."""

    MODULES = [
        "daemon.config",
        "daemon.models",
        "daemon.db",
        "daemon.budget",
        "daemon.scanner.project",
        "daemon.scanner.claude_code",
        "daemon.scanner.tools",
        "daemon.memory.knowledge",
        "daemon.memory.episodic",
        "daemon.memory.procedural",
        "daemon.memory.research",
        "daemon.memory.retriever",
        "daemon.memory.learner",
        "daemon.agents.classifier",
        "daemon.agents.planner",
        "daemon.agents.generator",
        "daemon.agents.evaluator",
        "daemon.agents.researcher",
        "daemon.agents.reviewer",
        "daemon.executors.ollama",
        "daemon.executors.claude_code",
        "daemon.executors.batch",
        "daemon.scheduler",
        "daemon.worktree",
        "daemon.ws_server",
        "daemon.cli",
    ]

    @pytest.mark.parametrize("module", MODULES)
    def test_module_imports(self, module):
        importlib.import_module(module)


class TestFileStructure:
    """Verify expected files exist."""

    EXPECTED_FILES = [
        "daemon/__init__.py",
        "daemon/config.py",
        "daemon/models.py",
        "daemon/db.py",
        "daemon/budget.py",
        "daemon/scheduler.py",
        "daemon/worktree.py",
        "daemon/ws_server.py",
        "daemon/cli.py",
        "daemon/main.py",
        "daemon/scanner/__init__.py",
        "daemon/scanner/project.py",
        "daemon/scanner/claude_code.py",
        "daemon/scanner/tools.py",
        "daemon/memory/__init__.py",
        "daemon/memory/knowledge.py",
        "daemon/memory/episodic.py",
        "daemon/memory/procedural.py",
        "daemon/memory/research.py",
        "daemon/memory/retriever.py",
        "daemon/memory/learner.py",
        "daemon/agents/__init__.py",
        "daemon/agents/classifier.py",
        "daemon/agents/planner.py",
        "daemon/agents/generator.py",
        "daemon/agents/evaluator.py",
        "daemon/agents/researcher.py",
        "daemon/agents/reviewer.py",
        "daemon/executors/__init__.py",
        "daemon/executors/ollama.py",
        "daemon/executors/claude_code.py",
        "daemon/executors/batch.py",
        "daemon/requirements.txt",
        "setup.sh",
        "LICENSE",
    ]

    @pytest.mark.parametrize("filepath", EXPECTED_FILES)
    def test_file_exists(self, filepath):
        assert os.path.exists(filepath), f"Missing: {filepath}"


class TestDependencies:
    """Verify only httpx and websockets are required."""

    def test_requirements_minimal(self):
        with open("daemon/requirements.txt") as f:
            content = f.read()
        lines = [
            l.strip() for l in content.strip().split("\n") if l.strip() and not l.startswith("#")
        ]
        # Should only have httpx and websockets
        assert len(lines) == 2
        deps = [l.split(">=")[0].split("==")[0].strip() for l in lines]
        assert "httpx" in deps
        assert "websockets" in deps


class TestConfigConsistency:
    def test_model_costs_complete(self):
        from daemon.config import MODEL_COSTS

        # Anthropic-tier keys must be present (used by budget downgrade cascade
        # and by users on the BYO-API-key path).
        required = {"opus", "sonnet", "haiku", "ollama"}
        assert required.issubset(set(MODEL_COSTS.keys())), (
            f"Missing required cost keys: {required - set(MODEL_COSTS.keys())}"
        )

    def test_ollama_is_free(self):
        from daemon.config import MODEL_COSTS

        assert MODEL_COSTS["ollama"]["input"] == 0.0
        assert MODEL_COSTS["ollama"]["output"] == 0.0

    def test_open_weight_models_are_free(self):
        # ADR-003: Forge's default open-weight model lineup is self-hosted via
        # Ollama, so all marginal cost is 0.0. Users on paid endpoints
        # (OpenRouter / Together) override per-call via the executor.
        from daemon.config import MODEL_COSTS

        for model in ("qwen3-coder-next", "qwen3.6:27b", "deepseek-v4-flash", "gpt-oss:20b"):
            assert model in MODEL_COSTS, f"missing cost entry for default model {model}"
            assert MODEL_COSTS[model]["input"] == 0.0
            assert MODEL_COSTS[model]["output"] == 0.0

    def test_budget_default_reasonable(self):
        from daemon.config import SESSION_BUDGET_USD

        assert 0 < SESSION_BUDGET_USD <= 100


class TestModelDataclasses:
    def test_sprint_contract_to_dict(self):
        from daemon.models import SprintContract

        s = SprintContract(description="Test", done_criteria=["A", "B"])
        d = s.to_dict()
        assert "description" in d
        assert "done_criteria" in d
        assert d["done_criteria"] == ["A", "B"]

    def test_session_to_dict(self):
        from daemon.models import Session

        s = Session(objective="Build auth")
        d = s.to_dict()
        assert d["objective"] == "Build auth"

    def test_project_context_to_dict(self):
        from daemon.models import MCPServer, ProjectContext

        ctx = ProjectContext(
            framework="next",
            mcp_servers=[MCPServer(name="supabase")],
            available_tools={"gh": True},
        )
        d = ctx.to_dict()
        assert d["framework"] == "next"
        assert len(d["mcp_servers"]) == 1
