"""Git branch control for the folder/branch picker (M5 onboarding).

Tested against real temp git repos — no mocking, so the actual git behavior is
what's verified.
"""

from __future__ import annotations

import subprocess

import pytest

from daemon import gitctl


def _git(path, *args):
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    _git(p, "init")
    _git(p, "config", "user.email", "t@t.dev")
    _git(p, "config", "user.name", "t")
    (p / "f.txt").write_text("x")
    _git(p, "add", ".")
    _git(p, "commit", "-m", "init")
    return p


class TestListBranches:
    @pytest.mark.asyncio
    async def test_empty_folder_is_not_git(self, tmp_path):
        out = await gitctl.list_branches(str(tmp_path))
        assert out["is_git"] is False
        assert out["branches"] == []

    @pytest.mark.asyncio
    async def test_lists_branches_and_current(self, repo):
        _git(repo, "branch", "feature-x")
        out = await gitctl.list_branches(str(repo))
        assert out["is_git"] is True
        assert set(out["branches"]) >= {"feature-x"}
        assert out["current"] in out["branches"]


class TestCheckout:
    @pytest.mark.asyncio
    async def test_checkout_existing_branch(self, repo):
        _git(repo, "branch", "dev")
        out = await gitctl.checkout_branch(str(repo), "dev")
        assert out["ok"] is True
        assert out["current"] == "dev"

    @pytest.mark.asyncio
    async def test_create_new_branch(self, repo):
        out = await gitctl.checkout_branch(str(repo), "brand-new", create=True)
        assert out["ok"] is True
        listing = await gitctl.list_branches(str(repo))
        assert "brand-new" in listing["branches"]

    @pytest.mark.asyncio
    async def test_invalid_branch_name_rejected(self, repo):
        for bad in ["a b", "a..b", "a~b", "-x", "a:b", "../escape"]:
            out = await gitctl.checkout_branch(str(repo), bad)
            assert out["ok"] is False
            assert "invalid" in out["error"].lower()

    @pytest.mark.asyncio
    async def test_checkout_nonexistent_branch_fails_cleanly(self, repo):
        out = await gitctl.checkout_branch(str(repo), "ghost")
        assert out["ok"] is False
        assert out["error"]


class TestInit:
    @pytest.mark.asyncio
    async def test_init_empty_folder(self, tmp_path):
        out = await gitctl.init_repo(str(tmp_path))
        assert out["ok"] is True
        listing = await gitctl.list_branches(str(tmp_path))
        assert listing["is_git"] is True
