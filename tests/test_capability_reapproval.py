"""Capability-change re-approval prompt tests (Sprint 6.1.5).

The wizard exposes ``confirm_capability_changes`` for the dispatcher and
CLI to call when a plugin's manifest widened its declared capabilities.
The prompt fires only on widening — narrowing is always safe and
auto-approves.

The function is stdin-free for testing: callers inject a ``confirm``
callable that takes (prompt, default) → bool. Production wires this to
the same TTY prompt the wizard uses.
"""

from __future__ import annotations

from daemon.wizard import (
    confirm_capability_changes,
    find_widened_capabilities,
)

# ---- find_widened_capabilities ----


def test_widened_list_added_host() -> None:
    diff = {"network": (["api.x.com"], ["api.x.com", "evil.com"])}
    widened = find_widened_capabilities(diff)
    assert "network" in widened


def test_narrowed_list_not_widened() -> None:
    diff = {"network": (["api.x.com", "api.y.com"], ["api.x.com"])}
    assert find_widened_capabilities(diff) == {}


def test_unchanged_membership_not_widened() -> None:
    """Same set even if order differs is not widening."""
    diff = {"network": (["a", "b"], ["b", "a"])}
    # Order changed but membership is identical → no new items
    assert find_widened_capabilities(diff) == {}


def test_increased_numeric_limit_is_widened() -> None:
    diff = {"memory_mb": (256, 512)}
    assert find_widened_capabilities(diff) == diff


def test_decreased_numeric_limit_not_widened() -> None:
    diff = {"memory_mb": (512, 256)}
    assert find_widened_capabilities(diff) == {}


def test_added_capability_key_treated_as_widening() -> None:
    """A capability that wasn't declared before being declared now
    counts as widening — the previously approved scope was effectively
    empty for that key."""
    diff = {"exec": (None, ["python3"])}
    assert "exec" in find_widened_capabilities(diff)


def test_mixed_diff_keeps_only_widening() -> None:
    diff = {
        "network": (["a"], ["a", "b"]),  # widened
        "filesystem": (["x", "y"], ["x"]),  # narrowed
        "memory_mb": (256, 512),  # widened
    }
    w = find_widened_capabilities(diff)
    assert set(w.keys()) == {"network", "memory_mb"}


# ---- confirm_capability_changes ----


def test_pure_narrowing_auto_approves() -> None:
    """Narrowing the scope is always safe — no prompt, return True."""
    captured: list[str] = []
    confirm_called: list[tuple[str, bool]] = []

    def fake_confirm(prompt: str, default: bool) -> bool:
        confirm_called.append((prompt, default))
        return False

    result = confirm_capability_changes(
        plugin_kind="skill",
        plugin_name="x",
        diff={"network": (["a", "b"], ["a"])},
        confirm=fake_confirm,
        print_fn=captured.append,
    )
    assert result is True
    # No prompt fired
    assert confirm_called == []
    # No printout either — narrowing is silent
    assert captured == []


def test_widening_calls_confirm_with_default_false() -> None:
    """The default for the prompt is *refuse* — accidental Enter shouldn't
    rubber-stamp a security-relevant change."""
    confirm_calls: list[tuple[str, bool]] = []

    def fake_confirm(prompt: str, default: bool) -> bool:
        confirm_calls.append((prompt, default))
        return False

    result = confirm_capability_changes(
        plugin_kind="connector",
        plugin_name="github",
        diff={"network": (["api.github.com"], ["api.github.com", "evil.com"])},
        confirm=fake_confirm,
        print_fn=lambda _msg: None,
    )
    assert result is False
    assert len(confirm_calls) == 1
    _prompt, default = confirm_calls[0]
    assert default is False  # Y/n with default-N


def test_widening_user_approves() -> None:
    result = confirm_capability_changes(
        plugin_kind="skill",
        plugin_name="x",
        diff={"memory_mb": (256, 512)},
        confirm=lambda _p, _d: True,
        print_fn=lambda _msg: None,
    )
    assert result is True


def test_prompt_lists_old_and_new_for_user_review() -> None:
    """The prompt must show both the previously approved and the newly
    requested scope so the user can decide informed."""
    captured: list[str] = []
    confirm_capability_changes(
        plugin_kind="skill",
        plugin_name="leaky",
        diff={"network": (["api.x.com"], ["api.x.com", "evil.com"])},
        confirm=lambda _p, _d: False,
        print_fn=captured.append,
    )
    blob = "\n".join(captured)
    assert "leaky" in blob
    assert "skill" in blob
    assert "api.x.com" in blob
    assert "evil.com" in blob
    # Both directions of the change are visible
    assert "previously approved" in blob
    assert "new manifest wants" in blob


def test_plugin_kind_and_name_in_warning() -> None:
    """The first user-visible line names exactly which plugin needs review."""
    captured: list[str] = []
    confirm_capability_changes(
        plugin_kind="connector",
        plugin_name="github",
        diff={"network": (["a"], ["a", "b"])},
        confirm=lambda _p, _d: False,
        print_fn=captured.append,
    )
    # Find the "asking for broader" warning — must name plugin
    warnings = [line for line in captured if "broader capabilities" in line]
    assert warnings, "expected a 'broader capabilities' warning line"
    assert "connector:github" in warnings[0]
