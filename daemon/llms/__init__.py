"""Pluggable LLM-adapter registry (per docs/LLMS.md).

The provider-routing for built-in providers (Anthropic / Ollama /
OpenAI-compat) lives in ``daemon/routing.py::select_executor``. This
package adds a third path: user-supplied LLM adapters loaded from
``~/.forge/llms/<provider>/`` with a manifest.toml.

Every adapter goes through the same sandbox runtime as connectors and
skills (subprocess isolation + capability declaration + signed manifests).

Adding a new provider:
  1. Author the adapter (see docs/PLUGIN_DEVELOPMENT.md "LLM adapter")
  2. ``forge llms install <path>``
  3. ``forge llms enable <name>``
  4. Set ``MYPROVIDER_API_KEY`` in env (or whatever ``api_key_env`` declares)

CLI entry points (in cli.py):
  forge llms list
  forge llms add <provider>
  forge llms test <provider>
  forge llms enable <provider>
  forge llms disable <provider>
  forge llms remove <provider>
  forge llms families
  forge llms cost
"""

from __future__ import annotations

from .registry import LLMAdapterEntry, LLMManifest, list_llms, load_llm

__all__ = ["LLMAdapterEntry", "LLMManifest", "list_llms", "load_llm"]
