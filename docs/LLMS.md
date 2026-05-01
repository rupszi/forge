# Adding LLM Providers to Forge

Forge ships with adapters for three provider categories:

| Provider class | Module | Models out of box |
|---|---|---|
| **Anthropic** (Claude API + claude-code subprocess) | `daemon/executors/claude_code.py` + `daemon/executors/batch.py` | claude-sonnet-4-7, claude-opus-4-7, claude-haiku-4-7 |
| **Ollama** (any local model) | `daemon/executors/ollama.py` | gpt-oss:20b, qwen3-coder-next, qwen3.6:27b, deepseek-v4-flash, devstral-small-2507 |
| **OpenAI-compatible** (vLLM / SGLang / OpenRouter / Together / LM Studio / etc.) | `daemon/executors/openai_compatible.py` | any model the endpoint exposes |

Adding a new provider takes one file plus a registry entry.

---

## Provider registry — how Forge picks one

The router lives in `daemon/routing.py::select_executor(model)`:

```python
def select_executor(model: str) -> str:
    fam = model_family(model)
    if fam == "anthropic":
        return "claude_code"
    if os.environ.get("OPENAI_BASE_URL"):
        return "openai_compatible"
    return "ollama"
```

`model_family(model)` is in `daemon/config.py`. It maps each model identifier to a family (`anthropic`, `openai`, `qwen`, `mistral`, `deepseek`, etc.). Family identity drives:

1. **Cross-family evaluator selection** — `pick_evaluator_model` returns the first registered model whose family differs from the generator's
2. **Procedural-memory routing** — patterns are keyed on family for transferable learning
3. **Capability flags** — which models support tool calling, JSON mode, prompt caching

## Adding a new model in an existing family

If your model fits a family Forge already knows about (Anthropic / Qwen / Mistral / etc.), it's a one-line config change.

`daemon/config.py`:

```python
LOCAL_MODEL_REGISTRY = {
    "qwen3-coder-next": {"family": "qwen", "context": 256_000, "tools": True},
    "qwen3.6:27b":      {"family": "qwen", "context": 128_000, "tools": True},
    # NEW:
    "qwen3.7:32b":      {"family": "qwen", "context": 256_000, "tools": True},
    ...
}
```

That's it. The router already handles Qwen via `ollama.py` (or `openai_compatible.py` if you set `OPENAI_BASE_URL`).

## Adding a new family in an existing provider

If your model uses a new family but fits an existing provider (Ollama / OpenAI-compatible), update two places:

1. **`daemon/config.py`** — add a `model_family` mapping rule and the model to `LOCAL_MODEL_REGISTRY`
2. **`daemon/agents/classifier.py::pick_evaluator_model`** — append the new family's representative model to the candidate list (so the cross-family evaluator can pick it)

```python
# daemon/agents/classifier.py
candidates = [
    LOCAL_CLASSIFY_MODEL,    # gpt-oss:20b — openai
    LOCAL_BACKUP_MID_MODEL,  # devstral-small-2507 — mistral
    LOCAL_MID_MODEL,         # qwen3.6:27b — qwen
    LOCAL_PREMIUM_MODEL,     # deepseek-v4-flash — deepseek
    "yi-coder-9b",            # NEW — yi family
    LOCAL_CODE_MODEL,         # qwen3-coder-next — qwen
    "claude-sonnet-4",        # anthropic — last resort
]
```

The function picks the first candidate whose family differs from the generator's. Order = preference; cheap models first.

## Adding a new provider entirely

For providers that don't fit Anthropic / OpenAI-compatible / Ollama (e.g., Cohere, Mistral La Plateforme native API, custom internal HTTP endpoint), write a plugin LLM adapter.

### Minimal adapter

```python
# ~/.forge/llms/cohere/plugin.py
from __future__ import annotations

from forge_plugin_api import LLMAdapter, GenerationRequest, GenerationResult


class CohereAdapter(LLMAdapter):
    name = "cohere"
    family = "cohere"

    def __init__(self, secrets: dict[str, str]):
        self.api_key = secrets["COHERE_API_KEY"]
        self.base_url = "https://api.cohere.com/v1"

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        async with self.http_client() as client:
            r = await client.post(
                f"{self.base_url}/chat",
                json={
                    "model": request.model,
                    "message": request.messages[-1]["content"],
                    "chat_history": [
                        {"role": m["role"].upper(), "message": m["content"]}
                        for m in request.messages[:-1]
                    ],
                    "temperature": request.temperature,
                },
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            r.raise_for_status()
            data = r.json()
        return GenerationResult(
            text=data["text"],
            tokens_in=data["meta"]["billed_units"]["input_tokens"],
            tokens_out=data["meta"]["billed_units"]["output_tokens"],
            cost_usd=self._price(data["meta"]["billed_units"], request.model),
            stop_reason=data.get("finish_reason", "stop"),
        )

    def supports_tools(self, model: str) -> bool:
        return model in ("command-r-plus", "command-r")

    @staticmethod
    def _price(billed: dict, model: str) -> float:
        prices = {
            "command-r-plus": (3.0, 15.0),
            "command-r":      (0.5, 1.5),
        }
        per_m_in, per_m_out = prices.get(model, (1.0, 3.0))
        return (billed["input_tokens"] / 1e6) * per_m_in + (billed["output_tokens"] / 1e6) * per_m_out
```

### Manifest

```toml
# ~/.forge/llms/cohere/manifest.toml
[plugin]
name = "cohere"
version = "0.1.0"
description = "Cohere Command-R adapter"
schema_version = 1

[capabilities]
network = ["https://api.cohere.com"]
secrets_read = ["COHERE_API_KEY"]

[llm]
provider = "cohere"
family = "cohere"
default_model = "command-r-plus"
endpoint_env = "COHERE_BASE_URL"        # optional override
api_key_env = "COHERE_API_KEY"

[llm.models.command-r-plus]
context_window = 128000
supports_tools = true
supports_json_mode = true
price_per_m_input = 3.00
price_per_m_output = 15.00

[llm.models.command-r]
context_window = 128000
supports_tools = true
price_per_m_input = 0.50
price_per_m_output = 1.50
```

### Install + register

```bash
forge llms install ~/.forge/llms/cohere
forge llms list
forge llms test cohere     # runs a small generation against the configured endpoint
```

Once registered, the model is selectable via `assigned_model = "command-r-plus"` in any sprint contract.

## How the cross-family evaluator picks against your new family

If you register a `family = "cohere"` adapter, `pick_evaluator_model` automatically sees it and can pick a Cohere model when grading a non-Cohere generator. To explicitly prefer your new family for evaluations, add it to the candidate list:

```python
# daemon/agents/classifier.py
candidates = [
    LOCAL_CLASSIFY_MODEL,
    "command-r",                  # NEW — cohere as second candidate
    LOCAL_BACKUP_MID_MODEL,
    LOCAL_MID_MODEL,
    LOCAL_PREMIUM_MODEL,
    LOCAL_CODE_MODEL,
    "claude-sonnet-4",
]
```

Or set per-project preference in `.forge/config.toml`:

```toml
[evaluator]
preferred_family = "cohere"
```

## Routing a sprint to a specific model

Three ways:

1. **Planner picks** — default; based on classifier complexity tier and procedural memory
2. **Sprint contract `assigned_model` field** — explicit override per sprint
3. **Project config** — `.forge/config.toml`

```toml
# Force a specific model for everything in this project
[router]
default_generator = "claude-sonnet-4-7"
default_evaluator = "deepseek-v4-flash"

# Or per-task-type
[router.task_types]
"schema migration" = "claude-opus-4-7"
"unit tests" = "qwen3-coder-next"
"docs" = "gpt-oss:20b"
```

## Cost calibration

Forge's `BudgetController` (`daemon/budget.py`) reads per-model prices from `MODEL_COSTS` in `daemon/config.py`. When you add a new family:

```python
MODEL_COSTS = {
    "claude-sonnet-4-7": {"input": 3.0, "output": 15.0},
    "claude-opus-4-7":   {"input": 15.0, "output": 75.0},
    "command-r-plus":    {"input": 3.0, "output": 15.0},   # NEW
    "command-r":         {"input": 0.5, "output": 1.5},
    # Open-weight via Ollama: 0 (you provide GPU)
    "qwen3-coder-next":  {"input": 0.0, "output": 0.0},
}
```

The downgrade cascade (`DOWNGRADE_MAP` in `budget.py`) walks expensive → cheap on budget pressure. To register your model in the cascade:

```python
DOWNGRADE_MAP = {
    "command-r-plus": "command-r",
    "command-r": "ollama",
    ...
}
```

## Tool-calling reliability

Per [ADR-003](DECISIONS.md), Forge's three-layer tool-call defense is:

1. **Native parser** — your adapter passes through whatever the provider returned
2. **Constrained decoding** — pass `response_format` (xgrammar / GBNF) to enforce a JSON schema server-side
3. **Tolerant client-side parser** — `daemon/parsing.py` recovers from malformed JSON

Your adapter only owns Layer 1. Tell Forge what your model supports via `supports_tools(model)` and `supports_json_mode(model)`. Forge will skip Layer 2 if the provider doesn't support constrained decoding.

## Testing

```python
# tests/test_my_adapter.py
import pytest
from forge_plugin_api.testing import MockSandbox, FakeHttpClient
from plugin import CohereAdapter, GenerationRequest


@pytest.mark.asyncio
async def test_cohere_basic_generation():
    sandbox = MockSandbox(
        secrets={"COHERE_API_KEY": "test-key"},
        http=FakeHttpClient({
            "POST https://api.cohere.com/v1/chat": {
                "status": 200,
                "body": {
                    "text": "hello world",
                    "meta": {"billed_units": {"input_tokens": 10, "output_tokens": 5}},
                    "finish_reason": "stop",
                }
            }
        }),
    )
    adapter = CohereAdapter(sandbox.secrets)
    adapter.http_client = sandbox.http_client_factory  # type: ignore

    result = await adapter.generate(GenerationRequest(
        model="command-r-plus",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.2,
        max_tokens=100,
    ))

    assert result.text == "hello world"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.cost_usd == pytest.approx(3.0 * 10 / 1e6 + 15.0 * 5 / 1e6)
```

## CLI commands

```bash
forge llms list                      Show registered providers and models
forge llms add <provider>            Wizard to add a new provider (uses ~/.forge/llms/)
forge llms test <provider>           Run a small generation against the provider
forge llms enable <provider>         Enable in routing
forge llms disable <provider>        Disable without removing
forge llms remove <provider>         Remove from registry
forge llms families                  Show families + which generator/evaluator pairs are valid
forge llms cost                      Show per-model cost matrix
```

## Adding open-weight families (Llama, Mistral, Yi, …)

Most open-weight families are accessible via Ollama or vLLM, so the right path is **not** a new adapter — it's adding the model identifier to `LOCAL_MODEL_REGISTRY` and routing through the existing `ollama.py` or `openai_compatible.py` executor.

```python
# daemon/config.py
LOCAL_MODEL_REGISTRY = {
    # ... existing ...
    "llama-3.3:70b":       {"family": "llama",   "context": 128_000, "tools": True},
    "mistral-large-2:34b": {"family": "mistral", "context": 128_000, "tools": True},
    "yi-coder:32b":        {"family": "yi",      "context": 128_000, "tools": True},
    "phi-4":               {"family": "phi",     "context": 64_000,  "tools": False},
}
```

Pull via Ollama:

```bash
ollama pull llama-3.3:70b
ollama pull mistral-large-2:34b
ollama pull yi-coder:32b
```

Or expose via vLLM:

```bash
vllm serve meta-llama/Llama-3.3-70B-Instruct --port 8000 \
    --tool-call-parser llama3_json --enable-auto-tool-choice
export OPENAI_BASE_URL=http://localhost:8000/v1
```

Forge auto-routes through `openai_compatible` when `OPENAI_BASE_URL` is set.

## Roadmap

| Capability | Status | Target |
|---|---|---|
| Pluggable LLM adapters via `~/.forge/llms/` | 🔨 in progress | v0.1.0 |
| `forge llms` CLI | 📅 planned | v0.1.0 |
| Per-project router config (`.forge/config.toml`) | 📅 planned | v0.1.0 |
| Cost-aware downgrade with provider mix | 📅 planned | v0.2.0 |
| Speculative routing (cheap → expensive on retry) | 📅 planned | v0.2.0 |
