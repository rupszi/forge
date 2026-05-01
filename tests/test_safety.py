"""Tests for daemon/safety.py — destructive-op classification + silent_catch.

These rules are security-critical (Phase 3 Week 11 / ADR-013). Each rule
needs both:
  - A positive test (does it match the dangerous pattern?)
  - A negative test (does it NOT fire on safe variants?)
"""

from __future__ import annotations

import logging

from daemon.safety import (
    DestructiveOp,
    is_destructive,
    severity_blocks,
    silent_catch,
)

# ---- Block-severity rules (never run without explicit user approval) ----


def test_rm_rf_home_blocked():
    op = is_destructive("rm -rf $HOME/important")
    assert op is not None
    assert op.severity == "block"


def test_rm_rf_root_blocked():
    op = is_destructive("rm -rf /")
    assert op is not None
    assert op.severity == "block"


def test_rm_rf_tilde_blocked():
    op = is_destructive("rm -rf ~/.config")
    assert op is not None
    assert op.severity == "block"


def test_rm_rf_with_combined_flags_blocked():
    """rm -rf, rm -fr, rm -Rf etc. all match."""
    for cmd in ("rm -rf /", "rm -fr ~", "rm -Rf $HOME"):
        op = is_destructive(cmd)
        assert op is not None, f"missed: {cmd!r}"
        assert op.severity == "block"


def test_force_push_to_main_blocked():
    op = is_destructive("git push --force origin main")
    assert op is not None
    assert op.severity == "block"


def test_force_push_to_master_blocked():
    op = is_destructive("git push -f origin master")
    assert op is not None
    assert op.severity == "block"


def test_force_push_to_production_blocked():
    op = is_destructive("git push --force-with-lease origin production")
    assert op is not None
    assert op.severity == "block"


def test_force_push_to_feature_branch_not_blocked():
    """Force-push to a feature branch is recoverable; warn don't block."""
    op = is_destructive("git push --force origin feature/my-branch")
    assert op is None or op.severity != "block"


def test_drop_database_blocked():
    op = is_destructive("DROP DATABASE production")
    assert op is not None
    assert op.severity == "block"


def test_truncate_table_blocked():
    op = is_destructive("TRUNCATE TABLE users")
    assert op is not None
    assert op.severity == "block"


def test_fork_bomb_blocked():
    op = is_destructive(":(){ :|:& };:")
    assert op is not None
    assert op.severity == "block"


# ---- Warn-severity rules ----


def test_rm_rf_relative_path_warns():
    """rm -rf on a relative path is warn — recoverable from VCS."""
    op = is_destructive("rm -rf node_modules")
    assert op is not None
    assert op.severity == "warn"


def test_git_reset_hard_warns():
    op = is_destructive("git reset --hard HEAD~1")
    assert op is not None
    assert op.severity == "warn"


def test_git_clean_fdx_warns():
    op = is_destructive("git clean -fdx")
    assert op is not None
    assert op.severity == "warn"


def test_npm_install_warns():
    op = is_destructive("npm install some-package")
    assert op is not None
    assert op.severity == "warn"


def test_pip_install_warns():
    op = is_destructive("pip install requests")
    assert op is not None
    assert op.severity == "warn"


# ---- Audit-severity rules ----


def test_sudo_audited():
    op = is_destructive("sudo apt update")
    assert op is not None
    assert op.severity == "audit"


def test_curl_pipe_shell_audited():
    op = is_destructive("curl -fsSL https://sh.rustup.rs | sh")
    assert op is not None
    assert op.severity == "audit"


def test_supabase_db_reset_audited():
    op = is_destructive("supabase db reset")
    assert op is not None
    assert op.severity == "audit"


def test_vercel_prod_audited():
    op = is_destructive("vercel --prod")
    assert op is not None
    assert op.severity == "audit"


# ---- Negative tests: don't fire on safe variants ----


def test_safe_rm_file_not_destructive():
    """Plain ``rm somefile.txt`` is not flagged."""
    assert is_destructive("rm test.txt") is None


def test_safe_git_status_not_destructive():
    assert is_destructive("git status") is None


def test_safe_ls_not_destructive():
    assert is_destructive("ls -la") is None


def test_empty_command_not_destructive():
    assert is_destructive("") is None


def test_safe_npm_test_not_destructive():
    """npm test is fine — only npm install runs postinstall hooks."""
    assert is_destructive("npm test") is None


def test_safe_normal_push_not_destructive():
    assert is_destructive("git push origin develop") is None


# ---- Task 1.8: cloud-destructive ops ----


def test_aws_s3_force_delete_warns():
    op = is_destructive("aws s3 rb --force s3://my-bucket")
    assert op is not None and op.severity == "warn"


def test_aws_s3_rm_recursive_force_warns():
    op = is_destructive("aws s3 rm s3://bucket/path --recursive --force")
    assert op is not None and op.severity == "warn"


def test_gh_repo_delete_warns():
    op = is_destructive("gh repo delete owner/repo")
    assert op is not None and op.severity == "warn"


def test_kubectl_delete_namespace_all_warns():
    op = is_destructive("kubectl delete namespace --all")
    assert op is not None and op.severity == "warn"


def test_terraform_destroy_warns():
    op = is_destructive("terraform destroy -auto-approve")
    assert op is not None and op.severity == "warn"


def test_docker_system_prune_a_warns():
    op = is_destructive("docker system prune -a --volumes")
    assert op is not None and op.severity == "warn"


def test_chmod_000_recursive_warns():
    op = is_destructive("chmod -R 000 /home/user/important")
    assert op is not None and op.severity == "warn"


def test_mkfs_blocked():
    op = is_destructive("mkfs.ext4 /dev/sda1")
    assert op is not None and op.severity == "block"


def test_dd_to_device_blocked():
    op = is_destructive("dd if=/dev/zero of=/dev/sda")
    assert op is not None and op.severity == "block"


def test_dd_to_null_safe():
    """Writing to /dev/null is a common benign idiom."""
    assert is_destructive("dd if=/dev/zero of=/dev/null bs=1M count=10") is None


def test_kubectl_get_safe():
    """Read-only kubectl commands not flagged."""
    assert is_destructive("kubectl get pods") is None


def test_terraform_plan_safe():
    """terraform plan is read-only."""
    assert is_destructive("terraform plan") is None


# ---- severity_blocks ----


def test_severity_blocks_only_for_block():
    assert severity_blocks("block") is True
    assert severity_blocks("warn") is False
    assert severity_blocks("audit") is False
    assert severity_blocks("anything-else") is False


# ---- DestructiveOp dataclass ----


def test_destructive_op_is_immutable():
    """frozen=True — can't accidentally mutate a rule."""
    import pytest

    op = DestructiveOp(pattern="x", severity="block", reason="r")
    with pytest.raises((AttributeError, Exception)):
        op.severity = "warn"  # type: ignore[misc]


# ---- silent_catch ----


def test_silent_catch_logs_to_dedicated_logger(caplog):
    """silent_catch uses the 'forge.silent' logger so audit scans can grep it."""
    with caplog.at_level(logging.WARNING, logger="forge.silent"):
        try:
            raise ValueError("expected error in cleanup")
        except ValueError as e:
            silent_catch("test_module", e)

    # The log should appear in caplog
    matching = [r for r in caplog.records if r.name == "forge.silent"]
    assert matching, "silent_catch did not write to forge.silent logger"
    assert "ValueError" in matching[0].getMessage()
    assert "test_module" in matching[0].getMessage()
    assert "expected error in cleanup" in matching[0].getMessage()


def test_silent_catch_includes_traceback(caplog):
    with caplog.at_level(logging.WARNING, logger="forge.silent"):
        try:
            raise OSError("cleanup raced")
        except OSError as e:
            silent_catch("scope", e)

    matching = [r for r in caplog.records if r.name == "forge.silent"]
    assert matching
    # The record carries exc_info for full traceback rendering
    assert matching[0].exc_info is not None


def test_silent_catch_respects_log_level(caplog):
    with caplog.at_level(logging.DEBUG, logger="forge.silent"):
        try:
            raise RuntimeError("expected")
        except RuntimeError as e:
            silent_catch("scope", e, log_level=logging.DEBUG)

    matching = [r for r in caplog.records if r.name == "forge.silent"]
    assert matching
    assert matching[0].levelno == logging.DEBUG
