"""M3 — research content is redacted before it's stored / injected (G-AGT-4).

Web research can carry leaked secrets (a token in a GitHub thread). The audit
flagged that research wasn't redacted before entering the KB/prompt path. The
extraction choke point now redacts so the DB never holds the raw secret.
"""

from __future__ import annotations

import pytest

from daemon.agents.researcher import Researcher
from daemon.memory.research import ResearchCache


class _FakeResult:
    def __init__(self, content, url="https://example.com", title="t"):
        self.content = content
        self.url = url
        self.title = title


class TestResearchRedaction:
    @pytest.mark.asyncio
    async def test_extracted_content_is_redacted(self, tmp_db, monkeypatch):
        cache = ResearchCache(tmp_db)
        researcher = Researcher(cache)

        leaked = "Fix: set the key sk-ant-api03-AAAABBBBCCCCDDDDEEEEFFFFGGGGHHHHIIIIJJJJ now"

        async def fake_extract_raw(result, error):
            return leaked

        # Patch the *raw* extraction the redaction wraps. We assert the public
        # extractor returns redacted text.
        monkeypatch.setattr(researcher, "_extract_raw", fake_extract_raw, raising=False)
        out = await researcher._extract_relevant_content(_FakeResult(leaked), "err")
        assert "sk-ant-api03-AAAABBBB" not in out
        assert "REDACT" in out.upper()
