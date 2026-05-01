# Part 2D — Open-Weight LLMs for Forge

Research date: 2026-04-30. Author: Forge research notes (Part 2D of multi-part technical report).

Forge is designed to orchestrate Claude Code subprocesses, but it must also work entirely on local/open-weight LLMs (Ollama / vLLM / SGLang). For the planner role, the evaluator role, and the cheap-tier generator role, Forge needs models that reliably emit tool calls, handle 32k+ contexts, and run on a developer's GPU or laptop. This part of the report evaluates the candidate model families and the inference stack that surrounds them.

The key risk for Forge is not raw code quality of the underlying models — by April 2026 several open weights are roughly Claude-3.5-Sonnet-class on coding. The key risk is **tool-calling reliability**: whether a planner LLM can be trusted to emit a valid JSON sprint plan, whether an evaluator LLM can be trusted to emit a structured PASS/FAIL verdict, and whether a generator can string together file-edit/test-run tools without derailing. That subtopic gets its own deep dive at the end.

## Big comparison table

Scores are best public numbers reported on official model cards or official leaderboards as of April 2026. SWE-bench Verified is reported as "resolved %" with the scaffold in parens. Aider polyglot is "pass rate". BFCL is the v3 overall (the v4 leaderboard shifted to agentic eval and is partial as of writing).

| Model | Sizes | License | Context | Native tool calls | SWE-bench Verified | Aider polyglot | BFCL v3 | LiveCodeBench | Best engine |
|---|---|---|---|---|---|---|---|---|---|
| **Qwen2.5-Coder** | 0.5/1.5/3/7/14/32B | Apache 2.0 | 32k → 128k (YaRN) | Yes (Hermes parser) | ~30% (best 32B w/ scaffold) | 16.4% | ~62% | ~31% | vLLM / Ollama |
| **Qwen3 Instruct** (235B-A22B) | 235B MoE (22B active) + dense 0.6/1.7/4/8/14/32B | Apache 2.0 | 256k → 1M | Yes (Hermes / Qwen format) | n/r | 57.3% | **70.9%** | 51.8% | vLLM / SGLang |
| **Qwen3-Coder** | 30B-A3B (Flash), 480B-A35B | Apache 2.0 | 256k → 1M | Yes (specialized agentic) | **66.5%** Pass@1 (no test-time scaling) | n/r | n/r | n/r (TerminalBench 2.0: 23.9) | vLLM / SGLang / Ollama |
| **DeepSeek-V3** | 671B MoE (37B active) | MIT (code) + Model License (weights, commercial OK) | 128k | Prompted JSON; parser available (`deepseek_v3`) | 42.0% (Agentless) | 49.6% / 55.1% (V3-0324) | not on leaderboard; flaky in practice | 40.5% (CoT) | SGLang / vLLM / LMDeploy |
| **DeepSeek-R1** | 671B MoE + distilled 1.5/7/8/14/32/70B | MIT | 128k | Limited; "reluctant to call tools" | 49.2% | 53.3% / 71.4% (R1-0528) | n/r | 65.9% (CoT) | SGLang / vLLM |
| **DeepSeek-Coder-V2** | 236B MoE / 16B Lite | DeepSeek Model License (commercial) | 128k | Not native | n/r | n/r | n/r | n/r | vLLM |
| **Llama 3.3 70B Instruct** | 70B dense | Llama 3.3 Community (commercial OK <700M MAU) | 128k | Yes (`llama3_json` parser; no parallel calls) | n/r officially | n/r | 77.3% v2 | n/r | vLLM / SGLang |
| **Llama 4 Maverick** | 17B active / 400B MoE | Llama 4 Community License | 1M | Yes (`llama4_pythonic`; parallel supported) | n/r officially; ~weak on third-party | 15.6% | n/r | 43.4% | vLLM |
| **Llama 4 Scout** | 17B active / 109B MoE | Llama 4 Community License | 10M | Yes | n/r | n/r | n/r | n/r | vLLM |
| **Mistral Large 2 (2411)** | 123B dense | Mistral Research License (non-commercial; commercial requires paid plan) | 128k | Yes (Mistral format) | n/r | n/r | n/r | n/r | vLLM (mistral parser) |
| **Codestral 22B v0.1** | 22B dense | Mistral Non-Production (MNPL) — research only | 32k | No (pre-tool-calling era) | n/r | 11.1% (25.01 build) | n/r | n/r | mistral-inference / vLLM |
| **Devstral Small 2507** | 24B dense | Apache 2.0 | 128k | Yes (Mistral format) | **53.6%** (OpenHands) | n/r | n/r | n/r | vLLM / Ollama |
| **Devstral 2 / Medium** | 24B Small (Apache) + Medium (API/private) | Apache 2.0 (Small) / proprietary (Medium) | 128k | Yes | Small ~68%, Medium ~61.6% (later builds 72.2% reported) | n/r | n/r | n/r | vLLM |
| **Granite 3.3** (general) | 2B, 8B | Apache 2.0 | 128k | Yes (`granite` parser) | n/r | n/r | n/r officially | n/r | vLLM / Ollama |
| **Granite Code 34B Instruct** | 3/8/20/34B | Apache 2.0 | 8k | Prompted JSON | n/r | n/r | 57.1% (own paper) | n/r (HumanEval avg 41.9%) | vLLM |
| **StarCoder2 15B** | 3/7/15B | BigCode OpenRAIL-M | 16k (4k SWA) | None — base completion | n/r | n/r | n/r | n/r | llama.cpp |
| **CodeLlama 70B Instruct** | 7/13/34/70B | Llama 2 Community | 16k | None | n/r | n/r | n/r | n/r (HumanEval 67.8) | llama.cpp / vLLM |
| **gpt-oss 120b / 20b** | 120B MoE (5.1B active), 20B | Apache 2.0 | n/r in card (long; harmony format) | Yes (function calling, web browse, python exec, structured outputs) | 47.9 / 52.6 / **62.4** (low/med/high reasoning) | n/r | ~67–68% (third party) | n/r in card | vLLM / Ollama / Transformers |
| **Yi-Coder** | 1.5B, 9B | Apache 2.0 | 128k | No (legacy) | n/r | n/r | n/r | n/r | Ollama |
| **OLMo 2** | 7B, 13B | Apache 2.0 (fully open: data + weights) | 4k | No (general; not coder-tuned) | n/r | n/r | n/r | n/r | vLLM |

n/r = not reliably reported on the official model card or leaderboard at the time of writing. Some figures (e.g., Devstral Medium 72.2%) come from third-party blogs and should be treated as approximate; primary sources are linked at the bottom.

The shortest summary: for Forge, **Qwen3-Coder-30B-A3B (Flash)** and **Devstral-Small-2507** are the practical cheap-tier generators on a single 24–48 GB GPU; **Qwen3-Coder-480B-A35B** is the high-tier ceiling for users who self-host on serious hardware or via Together/Nebius; **DeepSeek-R1** is the strongest open reasoner but is *not* a great agent; **gpt-oss-20b** is the easy laptop default for planner/evaluator if Apache 2.0 + native tool-call is required.

---

## Qwen2.5-Coder family

Six sizes: 0.5B, 1.5B, 3B, 7B, 14B, 32B. All Apache 2.0. Native context 32,768 tokens, extendable to 131,072 via YaRN. Trained on 5.5T tokens; the 32B-Instruct is described by Alibaba as "matching GPT-4o" on coding, which was credible at the time (Nov 2024) on HumanEval and MBPP-class benchmarks. On Aider polyglot, Qwen2.5-Coder-32B Instruct lands around 16.4% — substantially below the reasoning-heavy DeepSeek line but ahead of many same-size peers.

Tool calling is supported via the standard ChatML-with-tools template, and in vLLM it works with `--tool-call-parser hermes`. Qwen's own docs explicitly recommend "Hermes-style tool use for Qwen3 to maximize function calling performance" — the same is operationally true for Qwen2.5-Coder. Caveat: Qwen team notes "it is not guaranteed that the model generation will always follow the protocol", so a constrained-decoding fallback is recommended for production.

For Forge, Qwen2.5-Coder-7B-Instruct or 14B-Instruct are reasonable choices for the **planner** role on a developer laptop with 16–24 GB VRAM. The 32B is a good cheap-tier **generator** when run on vLLM with one A100 / two RTX 4090s. By April 2026 the family is largely superseded by Qwen3-Coder, so treat Qwen2.5-Coder as the reliable fallback rather than the hot path.

## Qwen3 family (incl. Qwen3-Coder)

The Qwen3 generation (May 2025+) brought several lines:

- **Qwen3 dense**: 0.6B, 1.7B, 4B, 8B, 14B, 32B — Apache 2.0, 256k native context.
- **Qwen3 MoE**: 30B-A3B, 235B-A22B — the "Instruct" line is the agentic one.
- **Qwen3-Coder**: 30B-A3B-Instruct (a.k.a. "Flash") and 480B-A35B-Instruct — coder-tuned, 256k native and 1M extended via YaRN.

License is Apache 2.0 across the line, which is rare at this scale and is a significant part of Forge's argument for picking Qwen3-Coder over DeepSeek for self-hosting.

Benchmarks worth highlighting (from official model cards):

- **Qwen3-235B-A22B-Instruct-2507**: BFCL v3 70.9%, Aider polyglot 57.3, LiveCodeBench v6 51.8%.
- **Qwen3-Coder-480B-A35B-Instruct**: SWE-bench Verified 66.5% Pass@1 *without test-time scaling*. This is the SOTA among open weights for SWE-bench as of summer 2025 and the model that put open weights into Sonnet-class SWE-bench territory. SWE-bench Pro reported 38.7, TerminalBench 2.0 23.9.

Tool-call format is Hermes-compatible by default, plus a Qwen-specific "agentic coding" function-call protocol shipped alongside the Qwen Code CLI. Both vLLM and SGLang are first-class targets — Qwen explicitly publishes "vLLM Recipes" and SGLang launch commands on the model card, including tensor-parallel-size 8 for the 480B variant. For local use, Ollama, llama.cpp, MLX-LM, LM Studio, KTransformers are all explicitly supported.

For Forge, **Qwen3-Coder-30B-A3B (Flash)** is the sweet spot: 30B total, 3B active, 256k context, runs on a single high-VRAM consumer card (RTX 4090 / 3090) at usable speed, and can drop into Ollama with `qwen3-coder:30b`. It is the best default cheap-tier generator for self-hosters. The 480B is for users with multi-GPU servers or who route to Together/Nebius/Hyperbolic.

## DeepSeek-V3

671B MoE with 37B active per token. Multi-head Latent Attention (MLA) plus DeepSeekMoE plus Multi-Token Prediction. Trained natively in FP8. Code under MIT; weights under DeepSeek Model License which permits commercial use.

Reported scores from the V3 paper and updates:
- SWE-bench Verified (Agentless scaffold): 42.0%.
- Aider polyglot: 49.6% (V3 base) / 55.1% (V3-0324) / 70.2% (V3.2-Exp).
- LiveCodeBench Pass@1 CoT: 40.5%.

Tool calling is the soft spot. DeepSeek's own API supports `tool_calls` in JSON, but in open-weight deployments via vLLM/SGLang/Ollama, function calling has been documented as **unstable** — looped calls, empty responses, function-call text leaking into the response body instead of into `tool_calls`. vLLM ships dedicated parsers `deepseek_v3` / `deepseek_v31` to fix this, but those need to be wired up explicitly. The NVIDIA NeMo + Triton integration even has a thread titled "Native tool calls fail on DeepSeek 3.2".

Hardware: minimum 2× H100 (FP8) or 4× H100 (BF16); realistically 8× H100 / H200 for serving with reasonable batch. SGLang is the *preferred* engine per DeepSeek's own README, then LMDeploy, then vLLM.

For Forge, DeepSeek-V3 is a **server-class** option: not for laptops, and not yet for shrink-wrapped agentic use without a structured-decoding fallback. If a Forge user has the hardware, V3 is a strong evaluator and planner if you wrap each tool call in xgrammar-enforced JSON.

## DeepSeek-R1 and distillates

R1 is a *reasoning* model — it emits a long `<think>...</think>` chain before answering. 671B MoE (same backbone as V3); also released as distilled checkpoints into Qwen-1.5B, Qwen-7B, Llama-8B, Qwen-14B, Qwen-32B, and Llama-70B, all permissively licensed (Apache 2.0 or Llama Community for the Llama distillates, MIT for the originals). 128k context.

Scores: SWE-bench Verified 49.2%, Aider polyglot 53.3% (base) / 71.4% (R1-0528 update), LiveCodeBench 65.9% Pass@1-CoT, Codeforces rating 2029, AIME 2024 79.8%. As a *reasoner* it is at the top of the open-weight pile.

As an *agent*, R1 is documented as "reluctant to call tools" (this is in the llama.cpp tool-calling docs) and the official guidance is *no system prompt*, all instructions in the user message, and start the assistant turn with `<think>\n` — none of which composes naturally with multi-turn agent loops or tool-use protocols. Ollama needs a custom checkpoint (`MFDoom/deepseek-r1-tool-calling`) to even expose tool calls cleanly.

For Forge, R1 is the right model for a **research / classifier / hard-debugging** role where you want one big "think" with no tools. It is the *wrong* model for a generator that has to call `read_file` then `edit_file` then `run_tests`. If you want R1's reasoning quality on agent loops, use the *thinking* mode of Qwen3 / DeepSeek-V3.2 instead.

## DeepSeek-Coder-V2

236B MoE (21B active) and a Lite 16B (2.4B active) variant. DeepSeek Model License with commercial use. 128k context, 338 programming languages. Outperformed GPT-4-Turbo on coding/math at release (mid-2024) but is now dated by V3 / R1 / Qwen3-Coder. No native tool-calling support documented; treat it as a code-completion / chat model. Hardware: 8× 80GB GPUs for full BF16 inference. For Forge, only relevant for users with a strict "must be DeepSeek line" requirement; otherwise skip.

## Llama 3.3 70B Instruct

70B dense, 128k context. Released Dec 6 2024. Llama 3.3 Community License — commercial allowed below 700M MAU, attribution "Built with Llama" required. Native tool calling via the Llama 3.x JSON format (vLLM `--tool-call-parser llama3_json`). Caveat: **parallel tool calls are explicitly not supported** on Llama 3.x in vLLM; you have to serialize. BFCL v2 score 77.3%; HumanEval 88.4%; IFEval 92.1%.

For Forge, Llama 3.3 70B is a solid evaluator (instruction following is a strong suit) and a perfectly fine planner. As a generator it is mid-tier vs Qwen3-Coder. Hardware: ~140 GB BF16, ~70 GB INT8, ~35 GB INT4 — fits on 1× H100 at INT8 or 2× consumer 4090 at INT4. The main reason to pick Llama 3.3 over Qwen3 in 2026 is if the rest of the stack (e.g., a fine-tune, an internal tool) is already on the Llama 3.x format.

## Llama 4 (Maverick / Scout / Behemoth)

Released April 5 2025. **Maverick**: 17B active / 400B MoE / 128 experts / 1M context. **Scout**: 17B active / 109B MoE / 16 experts / 10M context. Behemoth (~2T) was previewed but not generally released. Native multimodal (text + image) via early fusion. Llama 4 Community License (same 700M-MAU clause; not OSI-approved).

Tool-calling is supported — vLLM ships `llama4_pythonic` and parallel calls *are* supported on Llama 4 (unlike Llama 3). Coding benchmarks have been lukewarm: LiveCodeBench 43.4 on Maverick, Aider polyglot 15.6%. Independent third-party rankings (Rootly) put Llama 4 well behind frontier closed models on coding.

For Forge, Llama 4 Scout's 10M context is genuinely interesting for whole-repo retrieval tasks, but its lower coding benchmarks and the non-OSI license argue for Qwen3-Coder as the default open choice. Use Llama 4 Scout when context length itself is the deciding factor.

## Mistral Large 2 (123B)

123B dense, 128k context. Released July 2024 (2407) and updated Nov 2024 (2411). License: **Mistral Research License** — *non-commercial only*; commercial use requires a Mistral commercial license. This effectively disqualifies it from being shipped as a default in Forge for most users, even though it has best-in-class agentic capabilities, native function calling, and JSON output mode. Inference via vLLM with `--tool-call-parser mistral`.

For Forge: do not bake into the default config; allow as an opt-in alternative for users who already have a Mistral commercial agreement.

## Codestral 22B v0.1

22B dense, code-focused. Released May 2024. License: **Mistral Non-Production License (MNPL)** — research only. Older than the rest, no native tool calling, ~32k context, Aider polyglot 11.1% on the 25.01 build. By April 2026 it is essentially superseded by Devstral.

For Forge: skip. The license alone is disqualifying for a developer tool that wants "git clone and go".

## Devstral (Devstral Small / Devstral 2 / Devstral Medium)

Mistral's agent-tuned model line, fine-tuned from Mistral-Small-3.1-24B-Base.

- **Devstral-Small-2505** (May 2025): 24B, Apache 2.0, 128k context, **46.8% on SWE-bench Verified with OpenHands scaffold**. Fits on a single RTX 4090 or 32 GB Mac.
- **Devstral-Small-2507** (July 2025): 24B, Apache 2.0, **53.6% on SWE-bench Verified** with OpenHands. #1 open-source model on SWE-bench at release.
- **Devstral 2 / Devstral Medium** (late 2025): Small remains Apache 2.0; Medium is API-only / proprietary. Reported scores up to ~68–72% range on SWE-bench in third-party blogs.

Tool calling: native, Mistral format. vLLM: `--tool-call-parser mistral --enable-auto-tool-choice`. Recommended scaffold: **OpenHands** (the model card explicitly documents this). Also runs in Ollama (`devstral-2`).

For Forge, **Devstral-Small-2507 (24B, Apache 2.0)** is the single best "drop-in for a developer's laptop" generator option in early 2026: Apache 2.0, fits on 24 GB VRAM, SWE-bench-verified score in the 50%+ range, native Mistral tool calls. It is the strongest argument that open weights can run an agentic loop on commodity hardware.

## Granite (general 3.3 / Granite Code 34B / Granite 4)

IBM's enterprise line, all Apache 2.0.

- **Granite 3.3** general: 2B, 8B; 128k context. HumanEval 89.7 / 86.1 (8B). Tool-calling supported and native in vLLM (`granite` parser). Reasoning via `<think>/<response>` tags.
- **Granite Code** (older 2024 series): 3B / 8B / 20B / 34B; smaller 8k context. BFCL accuracy improves from 25.65% (3B) to **57.12% (34B base)**, demonstrating function calling as a learned scale effect. HumanEval avg 41.9% on Granite-34B-Code-Instruct.
- **Granite 4** (late 2025): explicit improvements to instruction-following and tool calling, parser `granite4` in vLLM.

For Forge, the Granite line is the **safe, IBM-blessed, Apache 2.0** option for organizations that want a familiar vendor. Smaller and more constrained than Qwen3 / Devstral on coding benchmarks, but the parser support in vLLM is mature, and 8B fits anywhere.

## StarCoder2

3B / 7B / 15B. BigCode OpenRAIL-M license — not OSI-approved (use restrictions on biometrics / surveillance / etc.). Released Feb 2024. 16k context with 4k sliding window. **Pure code completion model — no tool calling, no instruct mode**. HumanEval 46.3% (15B). For Forge: useful only as a `Tab`-completion model in an IDE-style flow, not for the agent role.

## CodeLlama 7/13/34/70B

Meta legacy. CodeLlama-70B-Instruct: HumanEval 67.8%, MBPP-class strong, *no native tool calling*, 16k context. Llama 2 Community License. By 2026 it's been thoroughly lapped by Qwen2.5/3-Coder, Devstral, Granite. Mention it only as a baseline; don't ship it.

## gpt-oss (OpenAI's open-weight reasoning model)

OpenAI's first open-weight release in years. Two sizes: **gpt-oss-120b** (117B params, 5.1B active, MoE, fits on 1× 80 GB GPU using MXFP4) and **gpt-oss-20b** (~16 GB memory). **Apache 2.0**. Native function calling, Python execution, web browse, structured outputs, agentic operations. Uses OpenAI's "harmony" format.

SWE-bench Verified at three reasoning levels: 47.9 / 52.6 / **62.4** (low/med/high). Third-party numbers put BFCL v3 ~67–68%. vLLM has a dedicated gpt-oss build path; Ollama, Transformers, LM Studio all support it.

For Forge, **gpt-oss-20b** is the best default *small* model for the planner / evaluator role on a developer laptop in 2026: Apache 2.0, native tool calls, reasoning levels are configurable, 16 GB memory ceiling. **gpt-oss-120b** is a great "I have one H100" sweet spot for the cheap-tier generator. The combination is strategically interesting because it puts an *OpenAI-shaped* tool-call model in the open weights tier, which makes prompt portability between Claude Code (closed) and Forge-on-open-weights cleaner.

## Other notable open models (April 2026)

- **Yi-Coder** (1.5B / 9B): Apache 2.0, 128k. Older. Good for tiny on-device tasks.
- **InternLM2 / 2.5**: Apache 2.0. Tool calling supported (vLLM `internlm` parser). General-purpose; not coder-tuned.
- **OLMo 2** (7B / 13B): Apache 2.0 with full data-and-weights openness. Not coder-tuned, 4k context — useful for principled-open use cases, not for Forge's hot path.
- **GLM-4.5 / GLM-4.7** (Zhipu): Frontier-class numbers reported in third-party leaderboards (BFCL v3 leader at 76.7%); Apache-style license; vLLM `glm45` / `glm47` parsers exist. A serious dark-horse contender if licensing terms remain permissive.
- **Kimi K2 / K2.5** (Moonshot): MoE, strong third-party benchmarks; vLLM `kimi_k2` parser.

These are worth tracking but not yet first-class in the open-weight tooling ecosystem.

---

## Tool-calling reliability deep dive

This is the make-or-break subtopic. Open weights *will* emit malformed JSON. The questions are: which models are least bad, which libraries pin the model down, and what does a working stack look like?

### Native tool-calling vs prompted JSON

**Native tool calling** means the model was post-trained on a tool-call protocol (Hermes, Llama 3.x, Mistral, Qwen, harmony) and has special tokens / templates for it. This is currently working well for:

- Qwen2.5 / Qwen3 / Qwen3-Coder (Hermes-compatible + Qwen agentic format)
- Devstral / Mistral Large / Mistral Nemo (Mistral format)
- Llama 3.1 / 3.2 / 3.3 (Llama 3 JSON format; **no parallel calls on 3.x**)
- Llama 4 (pythonic format; parallel calls supported)
- Granite 3.x / 4 (granite parser; parallel supported)
- gpt-oss (harmony; native)
- Hermes-2 / Hermes-3 (the namesake of the format)

**Prompted JSON** (no native protocol — describe the schema in the system prompt, parse the assistant string) is the fallback for: DeepSeek-Coder-V2, StarCoder2, CodeLlama, OLMo, Yi-Coder. Works *sometimes*, fails ugly on schema drift, especially under temperature > 0.

DeepSeek-V3 / R1 are an awkward middle: there *is* a `deepseek_v3` parser in vLLM, but field reports describe the function-call output as flaky (looped calls, content-vs-`tool_calls` confusion). Treat them as "needs constrained decoding" rather than "natively reliable".

### Constrained-decoding libraries

The reason this matters for Forge: at session boundaries (planner emits sprint JSON; evaluator emits PASS/FAIL JSON), Forge cannot afford to retry a malformed response. Constrained decoding turns "the model usually emits valid JSON" into "the model **provably** emits valid JSON".

| Library | What it does | Inference engines | Performance | Notes |
|---|---|---|---|---|
| **Outlines** (dottxt-ai) | JSON schema, regex, CFG, multiple choice | transformers, llama.cpp, vLLM, Ollama; APIs (OpenAI, Gemini) | Heavy startup cost; pre-computed automata can be slow first run | Most mature; Pydantic-friendly. Can infer structure from a Python function signature. |
| **xgrammar** (mlc-ai) | JSON schema, BNF grammar | **vLLM (default), SGLang (default), TensorRT-LLM, MLC-LLM** | "Near-zero overhead" in JSON generation | The default structured-output backend in vLLM and SGLang as of late 2024. |
| **llguidance** (microsoft) | JSON schema, regex, Lark | llama.cpp, SGLang, vLLM, mistral.rs, onnxruntime-genai, OpenAI structured output | <50 µs/token mask, no startup cost; "<1% of masks exceed 1 ms" | Newest of the three; lazy automata. The right pick if startup latency matters. |
| **BAML** (boundaryml) | Schema-aligned parsing (SAP) — model-agnostic, parses messy JSON-in-markdown into typed objects | OpenAI-compatible providers (Ollama, vLLM, LMStudio, Together) | n/a (parsing, not decoding) | Different layer: BAML lets you skip constrained decoding by parsing tolerantly. Cross-language SDKs. |
| **Guidance** (guidance-ai) | Programmatic prompts with `select`, `gen`, etc. | llama.cpp, transformers, vLLM | Mature | Older; useful for stepwise generation. |
| **LMQL** | Query-language for LLMs | transformers, OpenAI | Heavier syntax; less momentum | Cited for completeness; not the modern recommendation. |

Concrete recommendation for Forge: target **xgrammar via vLLM/SGLang** for self-hosted JSON-mode (planner output, evaluator verdict, sprint contract), and keep **BAML** as the "messy provider" option for users on Ollama or non-vLLM setups. Outlines is a fine alternative when running through the Hugging Face transformers path.

### JSON mode in inference engines

- **vLLM**: native JSON-mode via `response_format` (OpenAI-compatible API), backed by xgrammar by default. Tool-call parsers per model family (see below).
- **SGLang**: structured outputs via xgrammar; *grammar mask is overlapped with GPU inference*, so the latency hit is near-zero. SGLang is the engine where constrained decoding hurts least.
- **llama.cpp**: GBNF grammar files; built-in tool-call templates for Llama 3.x, Functionary, Hermes, Qwen 2.5, Mistral Nemo, FireFunction v2, Command R7B, DeepSeek R1 ("seems reluctant to call any tools"). Fall back to "Generic" handler for anything else. Note: extreme KV quantization (q4_0) degrades tool-call performance.
- **Ollama**: tool calls are passed through to the underlying llama.cpp engine. Works well for Qwen3 (v0.17.6+), Granite 4, Gemma 4, Mistral, Llama 3. Documented unstable with vanilla DeepSeek (use the community `MFDoom/deepseek-r1-tool-calling` checkpoint). Improving rapidly.
- **TGI**: Hugging Face's TGI **entered maintenance mode in December 2025**; HF now recommends vLLM or SGLang for new deployments. Don't target it.

### Tool-call schema compatibility matrix

Cross-cutting, what does each model "speak"?

| Schema family | Models | vLLM parser | Parallel calls |
|---|---|---|---|
| **Hermes / NousResearch** | Hermes 2/3, Qwen 2.5, Qwen 3 | `hermes` | Yes |
| **Llama 3 JSON** | Llama 3.1, 3.2, 3.3, 4 | `llama3_json` | No on 3.x; Yes on 4 |
| **Llama 4 pythonic** | Llama 4 | `llama4_pythonic` | Yes |
| **Mistral** | Mistral Nemo / Large / Devstral | `mistral` | Yes |
| **Granite** | Granite 3.x, 4.x | `granite` / `granite4` | Yes |
| **DeepSeek** | DeepSeek V3 / V3.1 / V3.2 | `deepseek_v3` / `deepseek_v31` | Partial (flaky) |
| **GLM** | GLM-4.5, GLM-4.7 | `glm45` / `glm47` | Yes |
| **Hunyuan / Kimi K2 / Cohere Command3 / Olmo3** | various | `hunyuan_a13b`, `kimi_k2`, `cohere_command3`, `olmo3` | Varies |
| **Pythonic generic** | Llama 3.2 small, ToolACE-8B | `pythonic` | Yes |
| **harmony** | gpt-oss | dedicated handling | Yes |
| **XML / Anthropic-style** | (Claude only — closed) | n/a | n/a |

Note that **Anthropic-style XML tool blocks are not used by any open weight** by default — Forge cannot expect "Claude Code-shaped tool calls" from open weights and must adapt. This argues for an abstraction layer (LiteLLM router; or BAML; or a Forge-internal tool-call adapter) so the orchestrator emits the same canonical contract regardless of which model serves it.

### What the agentic-coding community actually does

From OpenHands, Aider, smolagents, Qwen-Agent, and Cline practice in 2026:

1. **OpenHands** is the de-facto evaluation harness for SWE-bench scoring on open weights. Devstral and Qwen3-Coder both publish their numbers using the OpenHands scaffold. OpenHands does *not* trust raw tool-call JSON — it parses, validates, and re-prompts on failure.
2. **Aider** uses its own search/replace block format rather than function calls — it sidesteps tool-call reliability by using a markdown contract that's easier for any model to emit.
3. **smolagents** (Hugging Face) leans on "ReAct"-style or code-agent-style outputs and validates with parsing rather than relying on the model's `tool_calls` field.
4. **Qwen-Agent** (Alibaba) wraps Qwen3 with an MCP-aware client and ships its own parser that tolerates schema drift; this is the "official" recommendation for agentic Qwen.
5. **Models smaller than ~32B are not recommended for agentic coding** — the OpenHands LM repo says this directly; instruction-following degrades materially below 32B for multi-step workflows.

The synthesis for Forge: **never rely on a single tool-call parser for an open-weight model in production**. Pair the native parser (e.g., `hermes` for Qwen3) with a constrained-decoding fallback (xgrammar JSON schema) **and** a tolerant parser (BAML SAP) for the worst case. Three layers of defense — model → grammar → tolerant parser — is the practical recipe.

---

## Inference engines

| Engine | Tool calls | Throughput / batching | Hardware | API compat | Best for |
|---|---|---|---|---|---|
| **vLLM** | Per-model parsers (broadest list); xgrammar JSON mode default | Strong PagedAttention; best generalist | Single GPU → multi-node; CUDA + ROCm | OpenAI-compatible | Default Forge target for self-hosters with a GPU |
| **SGLang** | Compressed FSM + xgrammar; grammar mask overlapped with GPU pass (lowest tool-call overhead) | ~29% above vLLM in some H100 batch benches | NVIDIA + AMD GPU; multi-node | OpenAI-compatible | Heavy structured-output workloads; DeepSeek's own preferred engine |
| **llama.cpp** | Native + Generic handler; GBNF grammar; many model templates built in | CPU + GPU + Metal; modest batch | CPU laptops, Mac, single GPU | OpenAI-compatible HTTP server | The portable backbone; what Ollama uses |
| **Ollama** | Inherits llama.cpp; reliable for Qwen3, Granite 4, Mistral, Llama 3; flaky for vanilla DeepSeek | Single-stream optimized | Laptop / single GPU; Mac Metal | OpenAI-compatible (limited) | The "developer just runs `ollama serve`" path. **Forge's primary local target.** |
| **TGI** | Maintenance mode since Dec 2025 | n/a | n/a | OpenAI-compatible | **Do not target for new work.** |
| **MLX / MLX-LM** | Limited; depends on model card | Apple Silicon optimized | Mac M-series | Custom + OpenAI-compatible bridges | Forge users on Apple Silicon; Qwen3-Coder, Devstral, gpt-oss all have MLX builds |
| **LiteLLM** (router) | Routes to any backend; normalizes tool-call formats | Pure proxy | Anywhere | OpenAI + Anthropic compatible | The right abstraction layer between Forge and "whatever the user has" |
| **TensorRT-LLM** | xgrammar integrated; per-model | Highest throughput on NVIDIA | NVIDIA-only | OpenAI-compatible | Production server, not developer tool — overkill for Forge |
| **LMDeploy** | Mistral / DeepSeek strong | Strong | NVIDIA + AMD | OpenAI-compatible | DeepSeek in particular |

### Recommendation for Forge

Forge is a **developer-laptop-first** tool that runs inside an existing project. The inference targets should be:

1. **Ollama** — the first-class local target. Most Forge users will install Ollama and pull a model. Forge should ship known-good model+parser combinations: `qwen3-coder:30b`, `devstral-small-2507`, `granite3.3:8b`, `gpt-oss:20b`. Avoid vanilla DeepSeek for tool-call paths; if the user wants R1's reasoning, use it as a non-tool "thinker" called between tool steps.

2. **vLLM (OpenAI-compatible endpoint)** — the second target for users with a real GPU or who deploy on a remote box (Together, Nebius, Hyperbolic, RunPod, Modal). Forge should expect a `OPENAI_BASE_URL` env var pointing to a vLLM endpoint and pass model + tool spec via the OpenAI tool-calling API. Document the recommended `--tool-call-parser` flag per model in Forge's docs.

3. **LiteLLM** as the optional adapter layer when users mix providers (some sprints on Anthropic, some on Ollama, some on vLLM). LiteLLM normalizes tool-calling format across OpenAI / Anthropic / Ollama / vLLM and provides retry/fallback. Forge does *not* need to take a hard dependency on LiteLLM — just be compatible with it (i.e., speak OpenAI API; let users point Forge at a LiteLLM proxy if they want).

4. **SGLang** as a documented advanced option for users who already self-host and want better structured-output throughput (especially if the planner / evaluator are JSON-schema-constrained).

5. **Avoid TGI**; **avoid MLX as primary** (good fallback for Mac users — check it works but don't lead with it); **don't target TensorRT-LLM** (production-only).

Forge's executor abstraction should expose two engines beyond `claude -p`: an `ollama` executor (REST API at `http://127.0.0.1:11434`) and a generic `openai_compatible` executor (any URL, any model name). Both should pass the OpenAI-format `tools` array. The **classifier** decides which model to route to; the **executor** doesn't care what backend serves it.

### Concrete Forge default model lineup (April 2026)

If a user runs `forge init` on a laptop with no Anthropic key and no GPU bigger than 24 GB, the recommended local stack is:

- **Planner (cheap, fast)**: `gpt-oss:20b` via Ollama. Apache 2.0, native tool calls, configurable reasoning. Falls back to Qwen3-32B-Instruct if a user is on Ollama < 0.17.
- **Generator (cheap-tier, single-task)**: `qwen3-coder:30b` (Qwen3-Coder-Flash) via Ollama. Apache 2.0, 256k context, agentic tool calls.
- **Generator (medium-tier, harder task)**: `devstral-small-2507` via Ollama or vLLM. Apache 2.0, OpenHands-validated SWE-bench score.
- **Evaluator (must be different from generator)**: cross-model — if the generator was Qwen3-Coder, evaluate with Devstral or gpt-oss; if generator was Devstral, evaluate with Qwen3 or gpt-oss. Forge should enforce "evaluator family ≠ generator family" automatically.
- **Researcher / hard reasoning**: `deepseek-r1-distill-qwen-32b` (no tool use; pure reasoning text).
- **Fallback for users with $$ / GPU servers**: `qwen3-coder-480b` (Together / Nebius / self-hosted on 8× H100), `gpt-oss-120b` (1× H100 with MXFP4), `devstral-medium` (API).

This avoids non-commercial licenses (no Codestral, no Mistral Large 2), avoids the unreliable-tool-call models (no vanilla DeepSeek-V3 in the agentic path, no R1 inside tool loops), and stays Apache 2.0 across the board.

---

## Citations / primary sources

Official model cards and leaderboards consulted:

- Qwen2.5-Coder-32B-Instruct: https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct
- Qwen3-Coder-480B-A35B-Instruct: https://huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct
- Qwen3-235B-A22B-Instruct-2507: https://huggingface.co/Qwen/Qwen3-235B-A22B-Instruct-2507
- Qwen3-Coder blog (Alibaba): https://qwenlm.github.io/blog/qwen3-coder/
- Qwen function-calling docs: https://qwen.readthedocs.io/en/latest/framework/function_call.html
- DeepSeek-V3: https://huggingface.co/deepseek-ai/DeepSeek-V3
- DeepSeek-R1: https://huggingface.co/deepseek-ai/DeepSeek-R1
- DeepSeek-Coder-V2: https://huggingface.co/deepseek-ai/DeepSeek-Coder-V2-Instruct
- DeepSeek API tool calling docs: https://api-docs.deepseek.com/guides/tool_calls
- Llama 3.3 70B Instruct: https://huggingface.co/meta-llama/Llama-3.3-70B-Instruct
- Llama 4 Maverick: https://huggingface.co/meta-llama/Llama-4-Maverick-17B-128E-Instruct
- Llama 4 Scout: https://huggingface.co/meta-llama/Llama-4-Scout-17B-16E
- Mistral Large 2 (2411): https://huggingface.co/mistralai/Mistral-Large-Instruct-2411
- Codestral 22B v0.1: https://huggingface.co/mistralai/Codestral-22B-v0.1
- Devstral-Small-2505: https://huggingface.co/mistralai/Devstral-Small-2505
- Devstral-Small-2507: https://huggingface.co/mistralai/Devstral-Small-2507
- Devstral 2 announcement: https://mistral.ai/news/devstral-2-vibe-cli
- Granite 3.3 8B: https://huggingface.co/ibm-granite/granite-3.3-8b-instruct
- Granite Code paper: https://arxiv.org/pdf/2405.04324
- StarCoder2 15B: https://huggingface.co/bigcode/starcoder2-15b
- gpt-oss-120b: https://huggingface.co/openai/gpt-oss-120b
- Yi-Coder: https://github.com/01-ai/Yi-Coder
- BFCL / Berkeley Function Calling Leaderboard: https://gorilla.cs.berkeley.edu/leaderboard.html
- SWE-bench leaderboard: https://www.swebench.com/
- Aider polyglot leaderboard: https://aider.chat/docs/leaderboards/
- vLLM tool calling docs: https://docs.vllm.ai/en/latest/features/tool_calling.html
- vLLM Qwen3-Coder recipe: https://docs.vllm.ai/projects/recipes/en/latest/Qwen/Qwen3-Coder-480B-A35B.html
- llama.cpp function calling docs: https://github.com/ggml-org/llama.cpp/blob/master/docs/function-calling.md
- Outlines: https://github.com/dottxt-ai/outlines
- xgrammar: https://github.com/mlc-ai/xgrammar
- llguidance: https://github.com/microsoft/llguidance
- BAML: https://github.com/boundaryml/baml
- LiteLLM: https://github.com/BerriAI/litellm
- SGLang vs vLLM (Yotta): https://www.yottalabs.ai/post/best-llm-inference-engines-in-2026-vllm-tensorrt-llm-tgi-and-sglang-compared
- vLLM/TGI/SGLang/Triton comparison (PremAI): https://blog.premai.io/llm-inference-servers-compared-vllm-vs-tgi-vs-sglang-vs-triton-2026/
- OpenHands trajectories with Qwen3-Coder (Nebius): https://nebius.com/blog/posts/openhands-trajectories-with-qwen3-coder-480b
- Together AI Qwen3-Coder: https://www.together.ai/blog/qwen-3-coder
- Ollama tool-calling DeepSeek issue: https://github.com/ollama/ollama/issues/8517
- DeepSeek-R1 with custom tool-call template (Ollama): https://ollama.com/MFDoom/deepseek-r1-tool-calling
- Clarifai gpt-oss vs GLM/Qwen/DeepSeek/Kimi: https://www.clarifai.com/blog/openai-gpt-oss-benchmarks-how-it-compares-to-glm-4.5-qwen3-deepseek-and-kimi-k2

Notes on figures: scores marked "n/r" are not reliably published on the official model card or the canonical leaderboard at the time of writing (April 30 2026); leaderboards refresh weekly and Forge's internal benchmark harness should re-pull these on every release. Where a third-party blog supplied a figure (e.g., Devstral Medium 72.2%, GLM-4.5 BFCL v3 76.7%) it is flagged as such and should be re-verified before being baked into Forge's defaults.
