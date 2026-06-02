"""Parsing `ollama list` output for the model picker (M5)."""

from __future__ import annotations

from daemon import ollama_models


def test_parse_ollama_list():
    sample = (
        "NAME                 ID              SIZE      MODIFIED\n"
        "qwen2.5-coder:7b     abc123          4.7 GB    2 hours ago\n"
        "llama3.1:8b          def456          4.9 GB    3 days ago\n"
    )
    models = ollama_models.parse_ollama_list(sample)
    assert {m["name"] for m in models} == {"qwen2.5-coder:7b", "llama3.1:8b"}
    coder = next(m for m in models if m["name"] == "qwen2.5-coder:7b")
    assert coder["size"] == "4.7 GB"


def test_parse_empty():
    assert ollama_models.parse_ollama_list("NAME  ID  SIZE  MODIFIED\n") == []
    assert ollama_models.parse_ollama_list("") == []


def test_installed_models_no_ollama(monkeypatch):
    monkeypatch.setattr(ollama_models.shutil, "which", lambda _n: None)
    assert ollama_models.installed_models() == []
