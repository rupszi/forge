"""Security tests: input sanitization, no shell injection, WebSocket binding, budget caps."""

import os
import re
import tempfile

from daemon.budget import BudgetController
from daemon.config import MAX_TASK_DESCRIPTION_LENGTH, WS_HOST
from daemon.db import ForgeDB
from daemon.executors.claude_code import sanitize_prompt
from daemon.worktree import _validate_name, sanitize_worktree_name


class TestInputSanitization:
    def test_null_bytes_stripped(self):
        prompt = "Hello\x00World\x00!"
        result = sanitize_prompt(prompt)
        assert "\x00" not in result

    def test_control_chars_stripped(self):
        prompt = "Hello\x01\x02\x03World"
        result = sanitize_prompt(prompt)
        assert "\x01" not in result
        assert "\x02" not in result

    def test_newlines_preserved(self):
        prompt = "Line 1\nLine 2\n"
        result = sanitize_prompt(prompt)
        assert "\n" in result

    def test_tabs_preserved(self):
        prompt = "Col1\tCol2"
        result = sanitize_prompt(prompt)
        assert "\t" in result

    def test_max_length_enforced(self):
        prompt = "x" * 20000
        result = sanitize_prompt(prompt)
        assert len(result) <= MAX_TASK_DESCRIPTION_LENGTH

    def test_worktree_name_injection_blocked(self):
        """Path traversal in worktree names must be blocked."""
        assert not _validate_name("../../etc/passwd")
        assert not _validate_name("sprint; rm -rf /")
        assert not _validate_name("sprint && cat /etc/shadow")
        assert not _validate_name("sprint\necho evil")

    def test_worktree_name_sanitization(self):
        assert sanitize_worktree_name("sprint/../../evil") == "sprint-------evil"
        assert sanitize_worktree_name("sprint;rm") == "sprint-rm"

    def test_worktree_valid_names_pass(self):
        assert _validate_name("sprint-abc123")
        assert _validate_name("test-worktree")
        assert _validate_name("s1")


class TestNoShellTrue:
    """Verify no subprocess call uses shell=True anywhere in the codebase."""

    def _get_python_files(self):
        files = []
        for root, dirs, filenames in os.walk("daemon"):
            for f in filenames:
                if f.endswith(".py"):
                    files.append(os.path.join(root, f))
        return files

    def test_no_shell_true_in_codebase(self):
        """Critical: no shell=True in any subprocess call."""
        violations = []
        for filepath in self._get_python_files():
            with open(filepath) as f:
                lines = f.readlines()
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Skip comments and docstrings
                if (
                    stripped.startswith("#")
                    or stripped.startswith('"""')
                    or stripped.startswith("'")
                ):
                    continue
                if "shell=True" in line and not stripped.startswith("#") and '"""' not in stripped:
                    violations.append(f"{filepath}:{i}")
        assert violations == [], f"shell=True found in: {violations}"

    def test_no_os_system(self):
        """os.system() is dangerous — should not be used."""
        violations = []
        for filepath in self._get_python_files():
            with open(filepath) as f:
                content = f.read()
            if "os.system(" in content:
                violations.append(filepath)
        assert violations == [], f"os.system() found in: {violations}"

    def test_no_subprocess_shell(self):
        """subprocess.run/call with shell should not exist."""
        violations = []
        for filepath in self._get_python_files():
            with open(filepath) as f:
                content = f.read()
            # Check for subprocess patterns with shell=True
            if re.search(r"subprocess\.(run|call|Popen)\(.*shell\s*=\s*True", content):
                violations.append(filepath)
        assert violations == [], f"subprocess shell=True found in: {violations}"


class TestWebSocketSecurity:
    def test_ws_host_is_localhost_only(self):
        """WebSocket must bind to 127.0.0.1 ONLY, never 0.0.0.0."""
        assert WS_HOST == "127.0.0.1"

    def test_ws_host_not_configurable_via_env(self):
        """WS_HOST should be hardcoded, not from environment."""
        # Read the config file and verify WS_HOST is hardcoded
        with open("daemon/config.py") as f:
            content = f.read()
        # Should be a direct assignment, not os.environ.get
        assert 'WS_HOST = "127.0.0.1"' in content


class TestBudgetSecurity:
    def test_hard_cap_cannot_be_exceeded(self):
        """Budget controller must prevent exceeding the hard cap."""
        b = BudgetController(budget_usd=1.0)
        b.record_spend(1.0)
        assert b.exhausted
        assert b.remaining == 0.0

    def test_negative_spend_not_possible(self):
        """remaining should never go below 0."""
        b = BudgetController(budget_usd=1.0)
        b.record_spend(2.0)
        assert b.remaining == 0.0  # Clamped at 0

    def test_downgrade_cascade_reaches_ollama(self):
        """With zero budget, any model should downgrade to ollama (free)."""
        from daemon.models import SprintContract

        b = BudgetController(budget_usd=0.0)
        sprint = SprintContract(assigned_model="opus", estimated_tokens=10000)
        b.downgrade(sprint)
        assert sprint.assigned_model == "ollama"


class TestNoSecretsInCode:
    """Verify no hardcoded API keys or secrets."""

    def test_no_hardcoded_api_keys(self):
        violations = []
        for root, dirs, filenames in os.walk("daemon"):
            for f in filenames:
                if not f.endswith(".py"):
                    continue
                filepath = os.path.join(root, f)
                with open(filepath) as fh:
                    content = fh.read()
                # Check for common key patterns
                if re.search(r"(sk-[a-zA-Z0-9]{20,}|AKIA[0-9A-Z]{16})", content):
                    violations.append(filepath)
                # Check for hardcoded Bearer tokens
                if re.search(r"Bearer\s+[a-zA-Z0-9\-_.]{20,}", content):
                    violations.append(filepath)
        assert violations == [], f"Possible hardcoded secrets in: {violations}"

    def test_api_keys_from_env_only(self):
        """ANTHROPIC_API_KEY should only come from os.environ."""
        with open("daemon/executors/batch.py") as f:
            content = f.read()
        assert 'os.environ.get("ANTHROPIC_API_KEY"' in content


class TestSQLiteWAL:
    def test_wal_mode_enabled(self):
        """Database must use WAL mode for concurrent access safety."""
        with tempfile.TemporaryDirectory() as tmp:
            db = ForgeDB(os.path.join(tmp, "test.db"))
            mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
            db.close()


class TestGitignore:
    def test_forge_dir_gitignored(self):
        """.forge/ should be added to .gitignore during init."""
        # This is verified functionally in cli.py cmd_init
        # Here we just verify the intent exists in the code
        with open("daemon/cli.py") as f:
            content = f.read()
        assert ".forge/" in content
        assert ".gitignore" in content
