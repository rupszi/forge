"""M7 — local artifact storage + export (documents stay on disk, no cloud)."""

from __future__ import annotations

import pytest

from daemon import artifacts


class TestSaveArtifact:
    def test_saves_markdown_under_forge_artifacts(self, tmp_path):
        path = artifacts.save_artifact(
            "readme", "# Title\n\nbody", fmt="md", base_path=str(tmp_path)
        )
        assert path.endswith(".md")
        assert ".forge/artifacts" in path.replace("\\", "/")
        with open(path) as f:
            assert "# Title" in f.read()

    def test_slugifies_unsafe_names(self, tmp_path):
        path = artifacts.save_artifact(
            "my doc/../etc passwd!", "x", fmt="md", base_path=str(tmp_path)
        )
        # No path traversal; name reduced to a safe slug.
        assert ".." not in path
        assert "/etc/passwd" not in path

    def test_txt_format(self, tmp_path):
        path = artifacts.save_artifact("notes", "plain", fmt="txt", base_path=str(tmp_path))
        assert path.endswith(".txt")

    def test_html_export_wraps_markdown(self, tmp_path):
        path = artifacts.save_artifact(
            "page", "# Heading\n\nA paragraph.", fmt="html", base_path=str(tmp_path)
        )
        assert path.endswith(".html")
        with open(path) as f:
            html = f.read()
        assert "<h1>" in html and "Heading" in html
        assert "<p>" in html

    def test_unknown_format_raises(self, tmp_path):
        with pytest.raises(ValueError):
            artifacts.save_artifact("x", "y", fmt="exe", base_path=str(tmp_path))


class TestMarkdownToHtml:
    def test_headings_and_paragraphs(self):
        html = artifacts.markdown_to_html("# H1\n## H2\n\ntext here")
        assert "<h1>" in html
        assert "<h2>" in html
        assert "<p>" in html

    def test_escapes_html(self):
        html = artifacts.markdown_to_html("a <script>alert(1)</script> b")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_bullet_list(self):
        html = artifacts.markdown_to_html("- one\n- two")
        assert "<ul>" in html
        assert html.count("<li>") == 2
