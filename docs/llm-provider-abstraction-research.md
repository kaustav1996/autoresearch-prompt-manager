# LLM Provider Abstraction Patterns — Research Document

**Date**: 2026-03-25
**Scope**: Research for the autoresearch-prompt-manager library's `llm/` module
**Status**: Research only — no code produced

---

## Table of Contents

1. [Existing LLM Abstraction Libraries](#1-existing-llm-abstraction-libraries)
2. [Structured Output for Prompt Optimization](#2-structured-output-for-prompt-optimization)
3. [Provider-Specific Considerations](#3-provider-specific-considerations)
4. [Meta-Prompt Engineering for Prompt Optimization](#4-meta-prompt-engineering-for-prompt-optimization)
5. [Cost and Rate Limiting](#5-cost-and-rate-limiting)
6. [Recommendation: Build vs Depend](#6-recommendation-build-vs-depend)

---

## 1. Existing LLM Abstraction Libraries

### 1.1 LiteLLM

**What it is**: Open-source Python SDK + Proxy Server that unifies 100+ LLM providers behind an OpenAI-compatible interface. Call `litellm.completion()` with a model string like `"anthropic/claude-sonnet-4-20250514"` or `"groq/llama3-70b"` and get back an OpenAI-format response object.

**How it unifies providers**:
- Maps each provider's auth, endpoint, and message format to OpenAI's `ChatCompletion` shape
- Model string prefix determines routing: `anthropic/`, `groq/`, `bedrock/`, `gemini/`, `openrouter/`, etc.
- Handles token mapping, message role translation, and response normalization
- Built-in Router for retry/fallback across multiple deployments
- Cost tracking via token counting per provider

**What is good about LiteLLM**:
- Enormous provider coverage (100+ models)
- Drop-in replacement for OpenAI client — minimal learning curve
- Built-in retry/fallback logic at the config level
- Structured output support across providers (`response_format` with `json_schema`)
- Cost and token tracking out of the box
- Active community; used as the LLM layer by CrewAI, Giskard, and others
- Open source — can audit key handling and data flow

**What is bad about LiteLLM**:

| Problem | Detail |
|---------|--------|
| **Cold start** | `from litellm import completion` takes 3-4 seconds due to 1,200+ lines of imports loading every provider SDK |
| **Memory** | 300-400MB RAM for what should be a lightweight proxy layer |
| **Performance ceiling** | P99 latency spikes to 90+ seconds at ~500 RPS; unstable beyond that |
| **Memory leaks** | Requires worker recycling (`max_requests_before_restart=10000`) to mitigate |
| **Global state** | Configuration via global variables; cannot have different configs per component |
| **Code quality** | Main request handler exceeds 5,500 lines; monolithic and hard to debug |
| **Release instability** | Multiple daily releases; September 2025 release caused OOM on Kubernetes |
| **800+ open GitHub issues** | Significant portion are production bugs |
| **Documentation drift** | Docs frequently diverge from actual behavior |
| **Enterprise features gated** | SSO, RBAC, team budgets behind paywall |

**Structured output handling in LiteLLM**:
- Supports `response_format: {"type": "json_schema", "json_schema": {...}, "strict": true}` across OpenAI, Anthropic, Gemini, Groq, Bedrock, Ollama, Databricks
- For Anthropic: automatically adds the `structured-outputs-2025-11-13` beta header and transforms OpenAI's `response_format` to Anthropic's `output_format`/`output_config`
- For Gemini 2.0+: uses native `responseJsonSchema` parameter
- Client-side validation fallback: `litellm.enable_json_schema_validation=True` for providers without native schema support
- `supports_response_schema()` and `get_supported_openai_params()` helpers to check capabilities at runtime

### 1.2 AISuite

**What it is**: Lightweight Python library by Andrew Ng that provides an OpenAI-like API around popular LLMs. The core value proposition is switching providers by changing a single string.

**Key differences from LiteLLM**:
- Much simpler and more lightweight — fewer features, smaller footprint
- Does **not** support streaming, rate limits, token usage monitoring, or cost tracking
- Still in early development (infancy stage as of late 2025)
- Narrower provider coverage compared to LiteLLM

**Assessment**: Too immature for production use in the prompt manager. Lacks streaming, structured output support, and rate limiting — all critical for the optimization loop.

### 1.3 Magentic

**What it is**: A library for seamlessly integrating LLMs as Python functions using decorators. Focuses on structured output rather than provider abstraction.

**Key patterns**:
- `@prompt` decorator: converts a template string + return type annotation into an LLM-powered function
- `@chatprompt` decorator: accepts chat messages (system, user, assistant) for few-shot examples
- `@prompt_chain`: auto-resolves `FunctionCall` objects in a loop until reaching a final answer
- Return types can be any Pydantic model, list, enum, or primitive — the library enforces schema adherence

**Structured output approach**:
- Leverages Pydantic models and Python type annotations
- LLM-Assisted Retries: if the output doesn't match the schema, it re-prompts the LLM with the validation error
- Supports OpenAI, Anthropic, Ollama, and LiteLLM as backends

**Async capabilities**:
- Full async/await support throughout
- `AsyncStreamedStr` for streaming
- Demonstrated 7x speedup via concurrent LLM queries with `asyncio.create_task()`

**Assessment**: Magentic's decorator pattern is elegant but opinionated. It would be a poor fit as a dependency since the prompt manager needs low-level control over the LLM request (building meta-prompts dynamically, controlling token budgets, handling partial failures). However, its LLM-Assisted Retry pattern is worth adopting.

### 1.4 Other Alternatives

| Library | Approach | Relevance |
|---------|----------|-----------|
| **Bifrost** (Maxim AI) | Rust-based, 50x faster than LiteLLM (11us overhead at 5K RPS) | High performance but less Python-native |
| **Portkey** | Enterprise gateway with observability | Managed service, not embeddable |
| **Instructor** | Structured output library using Pydantic + retries | Good retry patterns; works with any OpenAI-compatible client |
| **DSPy** | Framework for programming (not prompting) LLMs with automatic prompt optimization | Relevant for the optimization loop; MIPROv2 optimizer is state-of-art |

### 1.5 SDK API Differences (Async)

| Feature | Anthropic SDK | OpenAI SDK | Groq SDK |
|---------|--------------|------------|----------|
| Async client | `AsyncAnthropic()` | `AsyncOpenAI()` | `AsyncGroq()` (OpenAI-compatible) |
| Chat method | `client.messages.create()` | `client.chat.completions.create()` | `client.chat.completions.create()` |
| System prompt | Separate `system` parameter | Message with `role: "system"` | Message with `role: "system"` |
| Streaming | `async for event in stream:` | `async for chunk in stream:` | `async for chunk in stream:` |
| Message format | Strict user/assistant alternation required | Flexible message ordering | Flexible (OpenAI-compatible) |
| Tool use | `tool_use` content blocks | `tool_calls` on assistant message | `tool_calls` (OpenAI-compatible) |
| Parallel tools | One-at-a-time (more rigid) | Multiple tools in one response | Multiple tools (OpenAI-compatible) |
| Structured output | `output_config.format` (native, 2025) + `tool_use` trick (legacy) | `response_format: {"type": "json_schema"}` | `response_format` (OpenAI-compatible) |

---

## 2. Structured Output for Prompt Optimization

The prompt manager's optimization loop needs to reliably extract JSON from the optimizer LLM (the improved prompt, reasoning, metadata). This is a critical path — failures here stall the entire optimization cycle.

### 2.1 Provider-by-Provider Structured Output Methods

#### Claude (Anthropic)

**Native Structured Outputs** (GA as of 2025-11):
- `output_config.format` with `type: "json_schema"` — constrains token generation at inference time
- `strict: true` on tool definitions — validates tool names and input schemas
- Supports Pydantic models via `client.messages.parse()` which returns a `parsed_output` attribute
- Available on Claude Opus 4.6, Sonnet 4.6, Sonnet 4.5, Opus 4.5, Haiku 4.5
- Zero Data Retention: schemas cached up to 24 hours for optimization only

**Legacy approach (tool_use trick)**:
- Define a fake tool with the desired JSON schema as `input_schema`
- Force the model to call it via `tool_choice: {"type": "tool", "name": "extract_data"}`
- Parse the tool's `input` field as the structured output
- Still works, but `output_config.format` is now preferred

**Key detail for prompt manager**: Claude's native structured outputs can be combined with tool use in the same request — useful if the optimization loop needs both a structured response AND tool calls.

#### OpenAI

**Structured Outputs** (GA since August 2024):
- `response_format: {"type": "json_schema", "json_schema": {...}, "strict": true}`
- 100% schema compliance in evaluations — the gold standard
- Supports Pydantic models via `client.beta.chat.completions.parse()`
- Built-in refusal detection: `response.choices[0].message.refusal` is non-null if the model refused
- Available on GPT-4o and later models

**JSON Mode** (simpler, weaker):
- `response_format: {"type": "json_object"}`
- Guarantees valid JSON but does NOT enforce a schema
- Must mention "JSON" in the prompt for it to work

**Function Calling** (alternative):
- `functions` parameter with JSON Schema definitions
- Model returns `function_call` with name + arguments
- Similar to Claude's tool_use trick

#### Gemini (Google)

**Response Schema**:
- `response_mime_type="application/json"` + `response_schema` parameter
- Schema defined via `genai.types.Schema` (not standard JSON Schema — uses Google's format)
- Gemini 2.0+ supports native `responseJsonSchema` with standard JSON Schema (lowercase types, `additionalProperties: false`)
- Gemini 1.5 uses OpenAPI format instead — different validation rules
- Cannot combine streaming with structured outputs (as of July 2025)

**Key limitation**: Gemini's schema format is cumbersome compared to OpenAI/Claude. Use the `genai.types.Schema` class rather than raw dicts.

#### Groq

- OpenAI-compatible: `response_format: {"type": "json_object"}` works
- JSON schema mode support depends on the model (Llama models via Groq support it)
- Speed advantage: structured output responses return faster due to Groq's hardware

#### Bedrock

- Via the Converse API: supports tool definitions with JSON schemas
- Structured output support varies by foundation model
- Claude on Bedrock supports structured outputs (same as direct Anthropic API)
- For non-Claude models, use the `tool_use` trick or prompt-based extraction

#### OpenRouter

- OpenAI-compatible API: `response_format` with `json_schema` supported
- Routes to underlying model's native structured output capability
- Not all models support it — check per model

### 2.2 Handling Structured Output Failures

Failures will happen. The optimization loop must handle them gracefully.

**Failure modes**:
1. **Malformed JSON**: Model returns text that is not valid JSON despite schema constraint
2. **Schema violation**: Valid JSON but missing required fields or wrong types
3. **Refusal**: Model refuses to generate content (safety filters)
4. **Timeout/rate limit**: Network-level failure before a response is received
5. **Partial response**: Streaming cut off mid-JSON

**Recommended strategy (layered)**:

```
Layer 1: Native schema enforcement (output_config / response_format / json_schema)
  |
  v (if provider doesn't support native schemas)
Layer 2: Tool-use trick (define a fake tool with the desired schema)
  |
  v (if response fails validation)
Layer 3: LLM-Assisted Retry (re-prompt with the validation error)
  |
  v (if retry also fails)
Layer 4: Prompt-based fallback (ask the LLM to fix its own malformed JSON)
  |
  v (if all else fails)
Layer 5: Graceful failure (log the error, skip this optimization cycle)
```

**Implementation pattern** (inspired by Instructor and Magentic):

```python
async def get_structured_output(
    provider: LLMProvider,
    messages: list[dict],
    schema: type[BaseModel],
    max_retries: int = 3,
) -> BaseModel:
    for attempt in range(max_retries):
        try:
            raw = await provider.complete(messages, response_schema=schema)
            return schema.model_validate_json(raw)
        except ValidationError as e:
            # LLM-Assisted Retry: append the error and ask for correction
            messages.append({"role": "assistant", "content": raw})
            messages.append({
                "role": "user",
                "content": f"Your response did not match the required schema. "
                           f"Error: {e}. Please fix and try again."
            })
    raise StructuredOutputError("Failed after max retries")
```

### 2.3 Comparison Matrix

| Provider | Native JSON Schema | Tool-Use Trick | Pydantic Integration | Streaming + Schema |
|----------|-------------------|----------------|---------------------|-------------------|
| Claude | `output_config.format` (GA) | `tool_use` (legacy) | `messages.parse()` | Yes |
| OpenAI | `response_format.json_schema` (GA) | `functions` | `.parse()` (beta) | Yes |
| Gemini | `response_schema` (native) | Function calling | Via Instructor | No (as of 2025-07) |
| Groq | `response_format` (OpenAI-compat) | Function calling | Via OpenAI SDK | Yes |
| Bedrock | Via Converse API (model-dependent) | Tool definitions | Manual | Model-dependent |
| OpenRouter | `response_format` (OpenAI-compat) | Function calling | Via OpenAI SDK | Model-dependent |

---

## 3. Provider-Specific Considerations

### 3.1 Claude (Anthropic)

**API**: Messages API (`/v1/messages`)

**Key differences from OpenAI**:
- System prompt is a separate top-level parameter, not a message
- Strict user/assistant message alternation required
- `max_tokens` is mandatory (not optional like OpenAI)
- Response in `content` array of typed blocks (`text`, `tool_use`, `thinking`)

**Structured output**: Native via `output_config.format` (preferred) or `tool_use` trick. The `client.messages.parse()` method accepts Pydantic models and returns `parsed_output`.

**Streaming**: `client.messages.stream()` yields typed events. Token-level streaming supported.

**Token counting**: Anthropic SDK provides a free `count_tokens` endpoint (does not consume rate limit). Uses a proprietary tokenizer distinct from tiktoken. For approximation, `tiktoken` with `p50k_base` encoding is close but not billing-accurate.

**Extended thinking**: Claude can show its reasoning via `thinking` content blocks. Relevant for the optimization loop — the optimizer's reasoning can be captured.

**Async**: `AsyncAnthropic()` client, fully async via `httpx`.

### 3.2 OpenAI

**API**: Chat Completions (`/v1/chat/completions`) and Responses API (`/v1/responses`)

**Structured output**: `response_format: {"type": "json_schema", "json_schema": {...}, "strict": true}` — 100% schema compliance. Also available via function calling with `strict: true`.

**JSON mode** (weaker): `response_format: {"type": "json_object"}` — valid JSON but no schema enforcement.

**Streaming**: `stream=True` yields `ChatCompletionChunk` objects.

**Token counting**: `tiktoken` library. `cl100k_base` for GPT-4, `o200k_base` for newer models. Response includes `usage.prompt_tokens` and `usage.completion_tokens`.

**Async**: `AsyncOpenAI()` client. Same interface as sync but returns coroutines.

### 3.3 Groq

**API**: OpenAI-compatible (`/v1/chat/completions`). Can use the OpenAI SDK with `base_url` override.

**Speed vs quality**: Groq runs open models (Llama, Mixtral, Gemma) on custom TPU-like hardware. 10-50x faster inference than cloud GPU. Cost is 10-50x cheaper than Claude/GPT-4 for comparable open models. Quality is lower than frontier models — suitable for draft optimization proposals but not final judgment.

**Structured output**: OpenAI-compatible `response_format` works. Schema support depends on the model.

**Rate limits**: Generous free tier but strict rate limits on tokens-per-minute. Burst-friendly but throttles on sustained load.

**Async**: Use `AsyncGroq()` or `AsyncOpenAI(base_url="https://api.groq.com/openai/v1")`.

**Relevance to prompt manager**: Could be used as the "fast draft" optimizer in a multi-agent optimization pattern — Groq generates candidates quickly, a frontier model judges them.

### 3.4 Gemini (Google)

**SDK**: `google-genai` Python SDK (`from google import genai`)

**API**: `client.models.generate_content()` (not OpenAI-compatible natively)

**Structured output**: `response_mime_type="application/json"` + `response_schema` parameter. Gemini 2.0+ supports standard JSON Schema; Gemini 1.5 uses OpenAPI format. Cannot stream with structured outputs.

**Token counting**: `client.models.count_tokens()` — uses Google's SentencePiece tokenizer. Not compatible with tiktoken.

**Key gotcha**: Gemini's API shape is significantly different from OpenAI/Anthropic. The `GenerateContentConfig` object, `Content`/`Part` message format, and schema definition via `genai.types.Schema` all require a distinct adapter.

**Async**: The `google-genai` SDK supports async via `await client.aio.models.generate_content()`.

**Relevance to prompt manager**: Gemini 2.5 Flash offers the lowest cost for structured output extraction ($0.000050/extraction) — 507x cheaper than Claude Opus. Excellent for high-volume metric-driven optimization.

### 3.5 Bedrock (AWS)

**SDK**: `boto3` with `bedrock-runtime` client

**Two APIs**:
- **`invoke_model`**: Low-level, model-specific request formatting. Each foundation model has its own JSON shape. More control but more work.
- **`converse`**: Higher-level, model-agnostic interface with standardized message format. AWS recommends this for new implementations. Supports tool definitions with JSON schemas.

**Async considerations**:
- `boto3` is synchronous. For async, use `aioboto3` (third-party wrapper).
- `aioboto3` has had issues with Converse API support historically — verify compatibility with current versions.
- Alternative: run boto3 calls in `asyncio.to_thread()` to avoid blocking the event loop.

**Model IDs**: Format is `"anthropic.claude-3-5-sonnet-20241022-v2:0"` (differs from direct Anthropic model names). Must maintain a mapping table.

**Structured output**: Claude models on Bedrock support structured outputs via the Converse API's tool definitions. For non-Claude models, use prompt-based extraction.

**Relevance to prompt manager**: Important for enterprise customers who must route traffic through AWS. The abstraction layer needs to handle the Bedrock model ID format and the different API surface.

### 3.6 OpenRouter

**API**: OpenAI-compatible (`/v1/chat/completions`). Use the OpenAI SDK with `base_url="https://openrouter.ai/api/v1"`.

**Model routing**: Access any model from any provider via a unified endpoint. Model names like `"anthropic/claude-3.5-sonnet"`, `"openai/gpt-4o"`, `"meta-llama/llama-3.1-405b"`.

**Structured output**: Passes through to the underlying model's native capability. Not all models support it.

**Key advantage**: Single API key for all providers. Useful for users who don't want to manage multiple provider credentials.

**Key disadvantage**: Additional latency from the routing layer. Pricing markup over direct provider access.

**Relevance to prompt manager**: OpenRouter can be treated as an OpenAI-compatible endpoint with a custom `base_url`. No special adapter needed beyond the OpenAI provider.

### 3.7 Custom OpenAI-Compatible Endpoints (vLLM, Ollama, etc.)

**Pattern**: These all implement the OpenAI chat completions API. The prompt manager's OpenAI provider with a configurable `base_url` covers them all.

**vLLM**: Self-hosted serving. Supports structured output via `response_format` with JSON schema (uses outlines/xgrammar for constrained decoding).

**Ollama**: Local model serving. Supports `response_format: {"type": "json_object"}`. JSON schema support depends on the version.

**Implementation**: A single `CustomOpenAIProvider` class with `base_url`, `api_key`, and `model` parameters handles all of these.

---

## 4. Meta-Prompt Engineering for Prompt Optimization

This section covers how the optimizer LLM should be instructed to improve another prompt — the core of the autoresearch pattern.

### 4.1 The "LLM as Prompt Engineer" Pattern

The optimizer LLM receives:
1. The current prompt text (the "baseline")
2. Performance metrics (quality scores, latency, success rates)
3. Sample interactions (good and bad examples)
4. Constraints (template variables, max length, tone requirements)
5. History of previous optimization attempts and their outcomes

It outputs:
1. An improved prompt text
2. Reasoning for the changes
3. Expected impact

### 4.2 Meta-Prompt Template

```
You are an expert prompt engineer. Your task is to improve the following prompt
based on its measured performance.

## Current Prompt
```
{current_prompt}
```

## Performance Metrics
- Quality Score (mean): {quality_mean} (target: > {quality_target})
- Quality Score (p25): {quality_p25}
- Success Rate: {success_rate}%
- Average Latency: {avg_latency}ms
- Sample Size: {sample_count} interactions

## Sample Interactions

### High-Quality Examples (these worked well):
{good_examples}

### Low-Quality Examples (these failed or scored poorly):
{bad_examples}

## Constraints
- Template variables that MUST be preserved: {template_vars}
- Maximum prompt length: {max_length} characters
- Tone: {tone_requirement}
- The prompt is used with model: {target_model}

## Previous Optimization Attempts
{optimization_history}

## Instructions
1. Analyze the failure patterns in the low-quality examples
2. Identify what works well in the high-quality examples
3. Propose a specific, targeted improvement to the prompt
4. Prefer shorter prompts that perform equally — simplicity is a feature
5. Do NOT add unnecessary instructions for marginal gains
6. Removing unhelpful parts of the prompt IS an improvement
7. Ensure ALL template variables are preserved exactly
8. Explain your reasoning

Respond with the improved prompt and your reasoning.
```

### 4.3 Context to Include

| Context Type | Why It Matters | How to Collect |
|-------------|---------------|----------------|
| **Metric summary** | Tells the optimizer what to improve | Aggregate from `metric_events` table |
| **Good examples** | Shows what success looks like | Top-K interactions by quality score |
| **Bad examples** | Shows failure patterns the optimizer should fix | Bottom-K interactions by quality score |
| **Template variables** | Prevents the optimizer from breaking variable interpolation | Parsed from current prompt version |
| **Optimization history** | Prevents repeating failed strategies | From `optimization_runs` table |
| **Target model info** | Allows model-specific prompt tuning | From prompt's `model_hint` |

### 4.4 Preventing Prompt Drift and Regression

**Problem**: After many optimization cycles, the prompt diverges from its original intent. Version 1 is human-authored and legible; version 47 is an LLM-optimized artifact that exploits model-specific quirks.

**Prevention strategies**:

1. **Anchor to original intent**: Include the original prompt (version 1) and its description in every optimization meta-prompt. The optimizer should improve within the spirit of the original.

2. **Edit distance budget**: Reject proposed prompts that differ too much from the current version (measured by Levenshtein distance or similar). Forces incremental changes.

3. **Regression test suite**: Maintain a fixed set of test cases (input/expected-output pairs) that every new version must pass before deployment. These are the "evaluation harness" from the autoresearch pattern.

4. **Simplicity criterion**: Explicitly instruct the optimizer to prefer shorter prompts. If a proposed version is significantly longer with only marginal improvement, reject it.

5. **Lineage tracking**: Every version stores its `parent_version` and `source` ("manual" vs "optimization"). A "diff from original" view lets humans audit the cumulative drift.

6. **Human review gates**: Default to `auto_deploy: false`. Optimized prompts enter as experiment arms at low weight and require human approval to promote.

7. **Metric guard rails**: Composite metrics with hard constraints (e.g., optimize quality BUT reject if hallucination rate exceeds 5%). Prevents Goodhart's Law gaming.

8. **Cooldown periods**: Minimum time between optimization runs per prompt. Prevents oscillation where the optimizer repeatedly undoes its own changes.

### 4.5 Advanced Patterns

**Collaborative optimization** (multi-LLM):
```
1. Multiple LLMs propose improvements in parallel:
   - Claude: conservative edit focusing on clarity
   - GPT-4o: structural rewrite focusing on instruction following
   - Gemini Flash: ablation study (try removing sections)

2. A judge LLM (e.g., Claude Opus) evaluates all proposals:
   - Scores each on: likely quality improvement, risk of regression, simplicity
   - Selects the best proposal or synthesizes elements from multiple

3. Winner enters experiment as a low-weight arm
```

**Contrastive learning (LCP pattern)**:
```
Instead of "improve this prompt", show the optimizer:
  - Prompt A (scored 0.85) vs Prompt B (scored 0.72)
  - "What makes A better than B? Apply those lessons to create Prompt C."
```

**Ablation testing**:
```
1. Remove one section of the prompt
2. Run experiment to see if performance changes
3. If no change: the section was unnecessary noise
4. If performance drops: the section is load-bearing
```

### 4.6 Structured Output for Optimization Responses

The optimizer LLM's response should itself be structured:

```json
{
  "improved_prompt": "The new prompt text...",
  "reasoning": "I changed X because the failure examples showed Y...",
  "changes_summary": [
    {"type": "modified", "section": "system instruction", "description": "Added explicit format requirement"},
    {"type": "removed", "section": "redundant example", "description": "Example 3 was redundant with example 1"}
  ],
  "preserved_template_vars": ["name", "context", "format"],
  "estimated_impact": {
    "quality": "+5-10%",
    "length_change": "-15%",
    "risk": "low"
  }
}
```

This structured response should be enforced using the provider's native schema support (Section 2), with LLM-assisted retries as fallback.

---

## 5. Cost and Rate Limiting

### 5.1 Token Counting Per Provider

**Key insight**: Tokenization is NOT standardized. The same text produces different token counts across providers.

| Provider | Tokenizer | Library | Notes |
|----------|-----------|---------|-------|
| OpenAI | BPE | `tiktoken` (`cl100k_base` for GPT-4, `o200k_base` for newer) | Official, deterministic, fast |
| Anthropic | Proprietary | `client.count_tokens()` (API call, free, no rate limit impact) | Approximate with `tiktoken`/`p50k_base` but not billing-accurate |
| Gemini | SentencePiece | `client.models.count_tokens()` (API call) | Incompatible with tiktoken |
| Groq | Model-dependent | Depends on model (Llama uses Llama tokenizer) | Use provider's count or estimate from tiktoken |
| Bedrock | Model-dependent | Response includes `usage` in API response | Counted server-side |

**Practical approach for cost estimation**:
1. Use `tiktoken` with `cl100k_base` as a rough universal estimate (within ~20% for most models)
2. For billing-accurate counts, call each provider's count_tokens API
3. Track actual usage from API response `usage` fields after each call

### 5.2 Pricing Comparison (as of 2025-2026)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Notes |
|-------|----------------------|------------------------|-------|
| Claude Opus 4 | $15.00 | $75.00 | Highest quality, highest cost |
| Claude Sonnet 4 | $3.00 | $15.00 | Best quality/cost for optimization |
| GPT-4o | $2.50 | $10.00 | Strong structured output |
| Gemini 2.5 Flash | $0.15 | $0.60 | 507x cheaper than Opus for extraction |
| Groq Llama 3.1 70B | ~$0.59 | ~$0.79 | Fastest inference, open model |
| Groq Llama 3.1 8B | ~$0.05 | ~$0.08 | Cheapest option, lower quality |

**Cost estimation for optimization runs**:
A typical optimization run involves:
- Input: ~2,000-4,000 tokens (meta-prompt + current prompt + metrics + examples)
- Output: ~1,000-2,000 tokens (improved prompt + reasoning)
- Per run with Claude Sonnet 4: ~$0.009-$0.036
- Per run with Gemini Flash: ~$0.0003-$0.0012
- Budget of 24 runs/day with Sonnet: ~$0.22-$0.86/day

### 5.3 Rate Limit Handling and Retry Strategies

**Error classification** (retry only what makes sense):

| Error Type | Should Retry? | Strategy |
|-----------|--------------|----------|
| 429 Rate Limit | Yes | Exponential backoff with jitter |
| 500 Server Error | Yes | Exponential backoff (up to 3 retries) |
| 502/503 Temporary | Yes | Short delay then retry |
| 401 Auth Error | No | Fail immediately, surface to user |
| 400 Bad Request | No (usually) | Fail unless it's a transient schema issue |
| Timeout | Yes | Retry with shorter max_tokens or different model |

**Recommended retry implementation**:

```python
# Using tenacity (preferred library for Python)
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(
        initial=1,      # 1 second
        max=60,          # cap at 60 seconds
        jitter=5,        # up to 5 seconds random jitter
    ),
    retry=retry_if_exception_type(RateLimitError),
)
async def call_with_retry(provider, messages, **kwargs):
    return await provider.complete(messages, **kwargs)
```

**Provider-specific rate limits**:
- **Anthropic**: Tiered (free/build/scale). Rate limits on requests/min AND tokens/min. Headers include `retry-after`.
- **OpenAI**: Tiered. Separate limits for RPM and TPM. `x-ratelimit-remaining-*` headers.
- **Groq**: Generous free tier but strict TPM limits. Burst-friendly.
- **Gemini**: Per-model limits. Flash models have higher limits than Pro.
- **Bedrock**: Per-model, per-region quotas. Can request increases via AWS console.

**Fallback chain pattern** (for the optimization loop):
```
Primary: Claude Sonnet 4 (best quality for prompt optimization)
  |
  v (if rate limited or down)
Fallback 1: GPT-4o (comparable quality, different provider)
  |
  v (if also unavailable)
Fallback 2: Gemini 2.5 Pro (different infrastructure entirely)
  |
  v (if all cloud providers fail)
Fallback 3: Skip this optimization cycle, log the failure, try again later
```

---

## 6. Recommendation: Build vs Depend

### 6.1 Should We Depend on LiteLLM?

**No. Build a thin custom abstraction.**

Reasoning:

| Factor | LiteLLM | Custom Abstraction |
|--------|---------|-------------------|
| Import time | 3-4 seconds cold start | Milliseconds (lazy imports) |
| Memory | 300-400MB | <50MB (only load needed providers) |
| Dependencies | Pulls in every provider SDK | Only the SDKs the user configures |
| Stability | Multiple daily releases, breaking changes | Under our control |
| Structured output | Good support but abstraction adds a layer of indirection | Direct use of each provider's native API |
| Configuration | Global state, cannot have per-component configs | Instance-based, fully configurable |
| Debugging | 5,500-line monolith | Small, provider-specific files |

### 6.2 Recommended Architecture

```
llm/
  base.py              # LLMProvider ABC + LLMResponse dataclass
  factory.py           # create_provider(config) -> LLMProvider
  retry.py             # Retry logic with tenacity
  structured.py        # Structured output extraction with retries
  token_counter.py     # Per-provider token counting
  providers/
    anthropic.py       # ~100 lines: AsyncAnthropic wrapper
    openai_compat.py   # ~100 lines: covers OpenAI, Groq, OpenRouter, custom
    gemini.py          # ~100 lines: google-genai wrapper
    bedrock.py         # ~100 lines: aioboto3/boto3 wrapper
  prompt_improver.py   # Meta-prompt construction + LLM response parsing
```

**Key design decisions**:

1. **Lazy provider loading**: Don't import `anthropic` until someone configures an Anthropic provider. This keeps startup fast and avoids unnecessary dependencies.

2. **OpenAI-compatible consolidation**: One `OpenAICompatibleProvider` class handles OpenAI, Groq, OpenRouter, vLLM, Ollama, and any custom endpoint. Just change `base_url`.

3. **Instance-based configuration**: Each provider instance carries its own config. Multiple providers can coexist.

4. **Structured output as a cross-cutting concern**: `structured.py` handles the retry-with-validation loop, delegating the actual LLM call to the provider. Providers expose a `supports_native_schema` flag.

5. **LiteLLM as optional backend**: For users who want LiteLLM's breadth, offer a `LiteLLMProvider` that wraps `litellm.acompletion()`. This is a single additional provider, not a hard dependency.

### 6.3 Abstract Interface

```python
class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @abstractmethod
    async def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_schema: type[BaseModel] | None = None,
        tools: list[ToolDefinition] | None = None,
        stop: list[str] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def count_tokens(self, text: str) -> int: ...

    @property
    @abstractmethod
    def supports_native_schema(self) -> bool: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
```

This interface is deliberately minimal. It covers the prompt manager's needs (completion with optional structured output, token counting) without trying to be a universal LLM abstraction.

---

## Sources

- [LiteLLM Documentation](https://docs.litellm.ai/docs/)
- [LiteLLM GitHub Repository](https://github.com/BerriAI/litellm)
- [The Real Problems With LiteLLM](https://dev.to/debmckinney/the-real-problems-with-litellm-and-what-actually-works-better-227k)
- [LiteLLM Structured Outputs / JSON Mode](https://docs.litellm.ai/docs/completion/json_mode)
- [Top 5 LiteLLM Alternatives in 2025](https://www.getmaxim.ai/articles/top-5-litellm-alternatives-in-2025/)
- [Top 5 LiteLLM Alternatives in 2026](https://www.truefoundry.com/blog/litellm-alternatives)
- [AISuite: Cross-LLM API (InfoQ)](https://www.infoq.com/news/2024/12/aisuite-cross-llm-api/)
- [AISuite vs LiteLLM Discussion](https://github.com/andrewyng/aisuite/issues/87)
- [Magentic GitHub Repository](https://github.com/jackmpcollins/magentic)
- [Magentic Structured Outputs](https://magentic.dev/structured-outputs/)
- [Claude Structured Outputs Documentation](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [OpenAI Structured Outputs Guide](https://platform.openai.com/docs/guides/structured-outputs)
- [Gemini Structured Output Documentation](https://ai.google.dev/gemini-api/docs/structured-output)
- [Google GenAI Python SDK](https://github.com/googleapis/python-genai)
- [AWS Bedrock Converse API (Boto3 Docs)](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime/client/converse.html)
- [OpenRouter Structured Outputs](https://openrouter.ai/docs/guides/features/structured-outputs)
- [Structured Output Comparison Across Providers (Glukhov)](https://www.glukhov.org/post/2025/10/structured-output-comparison-popular-llm-providers)
- [Meta Prompting Guide: Automated LLM Prompt Engineering](https://intuitionlabs.ai/articles/meta-prompting-automated-llm-prompt-engineering)
- [Meta-Prompting: LLMs Crafting Their Own Prompts](https://intuitionlabs.ai/articles/meta-prompting-llm-self-optimization)
- [DSPy: The Framework for Programming Language Models](https://dspy.ai/)
- [DSPy Optimizers](https://dspy.ai/learn/optimization/optimizers/)
- [Token Counting: tiktoken, Anthropic, and Gemini (2025 Guide)](https://www.propelcode.ai/blog/token-counting-tiktoken-anthropic-gemini-guide-2025)
- [tokencost: Token Price Estimates for 400+ LLMs](https://github.com/AgentOps-AI/tokencost)
- [AI API Pricing Comparison 2026](https://intuitionlabs.ai/articles/ai-api-pricing-comparison-grok-gemini-openai-claude)
- [Retry Logic with Tenacity (Instructor)](https://python.useinstructor.com/concepts/retrying/)
- [Mastering Retry Logic Agents (2025)](https://sparkco.ai/blog/mastering-retry-logic-agents-a-deep-dive-into-2025-best-practices)
- [OpenAI vs Anthropic vs Groq: Choosing the Right LLM API (2026)](https://use-apify.com/blog/openai-vs-anthropic-vs-groq-2026)
- [Prompt Regression Testing: Preventing Quality Decay (Statsig)](https://www.statsig.com/perspectives/slug-prompt-regression-testing)
- [LLM Guardrails: Complete 2025 Guide](https://orq.ai/blog/llm-guardrails)
