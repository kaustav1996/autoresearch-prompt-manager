# Client SDK Design Patterns for a Prompt Management Library

## Research Document — March 2026

---

## Table of Contents

1. [SDK Design Patterns from Best-in-Class Libraries](#1-sdk-design-patterns-from-best-in-class-libraries)
2. [Caching Strategies for Prompt SDKs](#2-caching-strategies-for-prompt-sdks)
3. [Client-Side Experiment Routing](#3-client-side-experiment-routing)
4. [Resilience Patterns](#4-resilience-patterns)
5. [Metric Batching in the Client](#5-metric-batching-in-the-client)
6. [Multi-Language SDK Considerations](#6-multi-language-sdk-considerations)
7. [MCP Client Integration](#7-mcp-client-integration)
8. [Synthesis and Recommendations](#8-synthesis-and-recommendations)

---

## 1. SDK Design Patterns from Best-in-Class Libraries

### 1.1 Stripe SDK — The Gold Standard for API Client Design

Stripe's SDK is widely regarded as the benchmark for developer-facing API clients. Key patterns to adopt:

**Sync/Async Dual Interface**

Stripe offers both sync and async methods on the same client. The sync client uses `requests` under the hood; the async path uses `httpx`. The naming convention is explicit: `client.customers.retrieve()` (sync) vs `client.customers.retrieve_async()` (async). This avoids the "two libraries" problem while keeping the sync path zero-dependency for simple use cases.

For a prompt SDK, the recommended approach:
- Ship sync by default (zero friction for scripts, notebooks, prototypes)
- Offer `_async` suffixed methods that return awaitables
- Use `httpx` as the HTTP backend for both paths (httpx supports sync and async from one library)
- Let users inject their own HTTP client for advanced use cases (e.g., custom connection pools, proxies)

**Resource-Oriented Client Structure**

Stripe organizes its client as a tree of resource namespaces: `stripe.customers`, `stripe.charges`, `stripe.subscriptions`. Each resource exposes CRUD verbs. This pattern maps directly to a prompt SDK:

```
client.prompts.get(slug)
client.prompts.list(tags=["production"])
client.prompts.resolve(slug, session_id=...)
client.experiments.get(id)
client.metrics.report(slug, session_id, metrics={...})
```

**Typed Error Hierarchy**

Stripe defines a clear error class hierarchy:
- `StripeError` (base)
  - `APIError` (5xx, server-side)
  - `APIConnectionError` (network failure)
  - `AuthenticationError` (invalid API key)
  - `InvalidRequestError` (400, bad parameters)
  - `RateLimitError` (429)

For a prompt SDK, the equivalent hierarchy:
- `PromptManagerError` (base)
  - `APIError` (unexpected server error)
  - `ConnectionError` (network unreachable, timeout)
  - `AuthenticationError` (invalid or expired API key)
  - `NotFoundError` (prompt slug does not exist)
  - `ValidationError` (bad parameters)
  - `RateLimitError` (429 Too Many Requests)

Each error should carry: `status_code`, `message`, `request_id` (for support debugging), and `code` (machine-readable error type).

**Idempotency Keys for Safe Retries**

Stripe attaches idempotency keys to mutating requests, allowing the SDK to automatically retry on transient failures without risk of double-execution. The server stores the result of the first request and replays it for subsequent requests with the same key. This pattern is essential for the `POST /metrics/batch` endpoint, where a network timeout after the server has accepted the batch should not result in duplicate metric events.

**Auto-Pagination**

Stripe's `.auto_paging_iter()` returns an iterator (sync) or async iterator that transparently fetches the next page when the current one is exhausted. The cursor is managed internally. This is critical for `client.prompts.list()` where the number of prompts may exceed a single page.

Implementation: cursor-based pagination using `starting_after` (not offset-based, which breaks under concurrent writes). The response includes `has_more: bool` and the SDK uses the last item's ID as the cursor for the next page.

### 1.2 LaunchDarkly SDK — Local Evaluation + Streaming Updates

LaunchDarkly's architecture is the closest analog to what a prompt SDK needs. Their key innovation: **the SDK downloads the entire flag ruleset on init, evaluates locally, and receives incremental updates via SSE**.

**Initialization and Flag Store**

On startup, the SDK:
1. Fetches the full set of flag definitions from the server (a single GET request)
2. Stores them in an in-memory "flag store" (a hash map of flag key to flag config)
3. Opens a persistent SSE connection for real-time updates
4. Falls back to polling if SSE is unavailable (configurable interval, default 30s)

All flag evaluations after init are local, in-memory lookups with zero network I/O. This is the pattern a prompt SDK should follow for the "resolve" hot path.

**SSE Streaming for Real-Time Updates**

When a flag is changed in the LaunchDarkly dashboard, the change propagates to all connected SDKs within ~200ms via server-sent events. The SSE protocol is simple, firewall-friendly (it is regular HTTP), and has built-in reconnection semantics. The SDK applies reconnection with exponential backoff and jitter:
- Initial reconnect delay: ~1 second
- Doubles with each subsequent failure
- Random jitter subtracted to prevent thundering herd
- Caps at a configurable maximum delay

**Offline Mode and Fallback**

If the SDK cannot reach LaunchDarkly during initialization, it falls back to developer-provided default values. If the SDK was previously connected and loses connectivity, it continues serving from the in-memory store (stale but functional). This is the critical resilience property: **the prompt SDK must never be a single point of failure in the application's hot path**.

**Server-Side vs Client-Side SDK Distinction**

LaunchDarkly makes a sharp distinction:
- **Server-side SDKs** download the full ruleset and evaluate locally. They are trusted (run in your infrastructure).
- **Client-side SDKs** send evaluation context to LaunchDarkly, which evaluates server-side and returns results. They are untrusted (run in browsers/mobile).

For a prompt SDK:
- The Python/Node.js server SDK should download experiment configs and route locally (like LD server-side)
- A hypothetical browser/edge SDK should call the `/resolve` endpoint (like LD client-side)

### 1.3 PostHog SDK — Local Evaluation with External Cache

PostHog's approach is similar to LaunchDarkly but with a key innovation for distributed environments: **external cache providers**.

**Polling-Based Sync**

PostHog uses periodic polling rather than SSE:
- Default interval: 30 seconds (Python, Node.js), 5 minutes (Go)
- The SDK fetches the full flag definition set on each poll
- Evaluation happens locally using cached definitions

**External Cache for Distributed/Stateless Environments**

The challenge: in a horizontally scaled deployment (multiple server instances, lambdas, edge workers), each instance independently polls for flag definitions, wasting API calls and causing cold-start latency.

PostHog's solution: an external cache provider (Redis, database, Cloudflare KV) that acts as a shared store. One instance polls and writes to the cache; all others read from it. A distributed lock (e.g., Redis SETNX) ensures only one instance polls at a time.

This pattern is directly applicable to a prompt SDK:
- Single-instance apps: in-memory cache is sufficient
- Multi-instance apps: add a Redis/Memcached cache layer
- Serverless (Lambda/Edge): external cache is essential (no persistent memory)

**Cost Optimization**

PostHog charges per flag evaluation API call. Local evaluation dramatically reduces cost because only the periodic polling requests count, not each individual evaluation. For a prompt SDK with a usage-based pricing model, this same argument applies: clients that evaluate locally reduce server load by orders of magnitude.

### 1.4 Sentry SDK — Efficient Event Batching

Sentry's SDK architecture is the reference for how to batch and ship telemetry from a client. The key components:

**Envelope Format**

Sentry wraps events in "envelopes" — a container format that can hold multiple items (error events, transactions, attachments, client reports) in a single HTTP request. This reduces per-event overhead and allows batching heterogeneous data types.

For a prompt SDK, the metrics batch endpoint should accept a similar envelope: multiple metric events (possibly for different prompts/sessions) in a single POST.

**Background Worker Thread**

The Sentry Python SDK runs a `BackgroundWorker` that:
1. Maintains a bounded queue (`transport_queue_size`, default 100)
2. Drains the queue on a background thread
3. Sends events via HTTP to the Sentry ingest endpoint
4. Drops events (and records the loss) when the queue is full

This is the exact pattern for metric reporting in a prompt SDK: the main application thread enqueues metric events; a background worker batches and ships them.

**Flush and Graceful Shutdown**

- `flush(timeout)`: blocks the calling thread until all queued events are sent, or the timeout expires. Returns `False` if the timeout was reached (some events may be lost).
- `close(timeout)`: flushes then disables the client. No more events are accepted.
- Automatic flush on interpreter shutdown via `atexit` hook (configurable via `shutdown_timeout`)

The prompt SDK should implement the same lifecycle:
- `client.flush()` for manual drain before deploy/restart
- `client.close()` for clean shutdown
- `atexit` hook for automatic drain

**Buffering Strategy for Logs**

Sentry recently added a buffered log system: logs are collected in a buffer and flushed as a batch when either:
- The buffer exceeds 100 items, OR
- 5 seconds have elapsed since the last flush

This dual-trigger (count OR time) pattern is the standard for metric batching. The prompt SDK should use the same approach with configurable thresholds.

---

## 2. Caching Strategies for Prompt SDKs

### 2.1 Three-Layer Cache Architecture

The recommended caching strategy uses three layers, from fastest to most durable:

```
Layer 1: In-Memory TTL Cache (LRU, size-bounded)
   |
   v  (miss or expired)
Layer 2: ETag Revalidation (conditional HTTP request)
   |
   v  (server down or first boot)
Layer 3: Local File Fallback (disaster recovery)
```

### 2.2 Layer 1 — In-Memory TTL Cache

**Data Structure**: LRU (Least Recently Used) cache bounded by both entry count and total memory.

**Key design decisions**:
- **TTL per entry**: Default 60 seconds. After TTL, the entry is "stale" but not evicted — it can still be served while a background revalidation occurs (stale-while-revalidate pattern).
- **Max entries**: Default 1000 (configurable). Prevents unbounded memory growth if the application uses many prompt slugs.
- **Thread safety**: Use `threading.Lock` for sync access, or store the cache in a per-event-loop context for async.
- **Cache key**: `(slug, version, session_id_hash)` — include session_id hash only if experiment routing is active.

**Stale-While-Revalidate**:
When an entry's TTL expires, the SDK:
1. Returns the stale value immediately (no latency hit)
2. Fires a background revalidation request
3. Updates the cache when the response arrives

This pattern ensures the hot path never blocks on network I/O after the first request.

**Implementation consideration**: Python's `functools.lru_cache` does not support TTL. Use `cachetools.TTLCache` or a custom implementation with `OrderedDict` + timestamp tracking.

### 2.3 Layer 2 — ETag/If-None-Match Revalidation

When the in-memory TTL expires, the SDK revalidates against the server using HTTP conditional requests:

1. The server returns an `ETag` header with each `/resolve` response (e.g., the `content_hash` of the prompt version)
2. On revalidation, the SDK sends `If-None-Match: <etag>` with the request
3. If the prompt has not changed, the server returns `304 Not Modified` with an empty body
4. If the prompt has changed, the server returns `200 OK` with the new content and a new ETag

**Bandwidth savings**: For a prompt body that is 2KB, a 304 response saves 2KB per revalidation. At 1000 revalidations/minute across a fleet, this saves ~120MB/hour of bandwidth.

**Combined with `Cache-Control`**: The server should also set `Cache-Control: max-age=60, stale-while-revalidate=300` to enable CDN and proxy caching for deployments behind a reverse proxy.

**Weak vs Strong ETags**: Use strong ETags (the SHA-256 content hash). The prompt body is the only thing that matters for cache validity — there is no scenario where "semantic equivalence" (weak ETag) is sufficient but byte-for-byte equivalence is not.

### 2.4 Layer 3 — Local File Fallback

For disaster recovery (server completely unreachable, cache cold, no previous in-memory entry):

**Write-through on every successful fetch**: When the SDK receives a prompt from the server, it writes it to a local file: `{fallback_dir}/{slug}.json`. The file contains the full resolved prompt including version, body, content_hash, and a timestamp.

**Read on cold start or total failure**: If the SDK cannot reach the server AND has no in-memory cache entry, it reads from the local fallback file.

**File format**:
```json
{
  "slug": "welcome-email",
  "version": 7,
  "body": "Hello {{name}}, welcome to...",
  "content_hash": "sha256:abc123...",
  "model_hint": "claude-sonnet-4-20250514",
  "template_vars": ["name"],
  "cached_at": "2026-03-25T10:00:00Z"
}
```

**Security consideration**: The fallback directory should have restricted permissions (0700). Prompt bodies may contain proprietary system instructions.

**Staleness indicator**: The SDK should log a warning when serving from file fallback, including the age of the cached data. The application can optionally receive a callback or flag indicating degraded mode.

### 2.5 Cache Invalidation — Push vs Pull

| Strategy | Latency | Complexity | Best For |
|----------|---------|------------|----------|
| **SSE (push)** | ~200ms | Medium | Long-lived server processes |
| **Polling (pull)** | 0–30s | Low | Serverless, simple deployments |
| **Webhook (push)** | ~1s | High | External systems, CI/CD triggers |

**Recommended default**: Polling with a 30-second interval, matching PostHog's approach. SSE as an opt-in for latency-sensitive deployments.

**Polling with jitter**: To prevent thundering herd when many SDK instances poll simultaneously, add random jitter to the polling interval: `actual_interval = base_interval + random(0, base_interval * 0.1)`.

### 2.6 Cache Warming on Startup

The SDK should support pre-fetching a set of prompt slugs on initialization:

```python
client = PromptClient(
    url="http://localhost:8910",
    warm_slugs=["welcome-email", "summarize-article", "chat-system"],
)
```

On init, the SDK fires parallel requests (or a single batch endpoint) for all warm slugs. This ensures the first `resolve()` call for these prompts is a cache hit. The batch endpoint (`GET /v1/resolve/batch?slugs=a,b,c`) should be a server-side feature to avoid N+1 requests on startup.

---

## 3. Client-Side Experiment Routing

### 3.1 Download Full Config, Route Locally

The SDK should support a "local routing" mode where it downloads the full experiment configuration (all active experiments, their arms, weights, and prompt bodies) and evaluates routing locally without any per-resolve network call.

**Config structure downloaded from server**:
```json
{
  "prompts": {
    "welcome-email": {
      "default_version": 7,
      "body": "Hello {{name}}...",
      "experiment": {
        "id": "exp_abc",
        "sticky": true,
        "arms": [
          {"id": "arm_1", "version": 7, "weight": 50, "label": "control", "body": "Hello {{name}}..."},
          {"id": "arm_2", "version": 8, "weight": 30, "label": "variant-a", "body": "Hey {{name}}!..."}
        ]
      }
    }
  },
  "config_version": "etag:xyz789",
  "fetched_at": "2026-03-25T10:00:00Z"
}
```

### 3.2 Periodic Sync with Jitter

The experiment config is synced periodically:
- **Default interval**: 30 seconds
- **Jitter**: +/- 10% random offset to prevent synchronized polling across instances
- **Force refresh**: The SDK should expose `client.refresh()` for manual re-sync after a deployment or experiment change

**Sync lifecycle**:
1. On init: fetch full config (blocking, with timeout)
2. Start background timer with interval + jitter
3. On each tick: fetch config, compare `config_version`, update in-memory store if changed
4. If fetch fails: keep using existing config, log warning, retry on next tick

### 3.3 Deterministic Hashing for Consistent Assignment

For sticky experiment routing without server-side state, use deterministic hashing:

**Algorithm**: MurmurHash3 (32-bit) — fast, well-distributed, and used by Optimizely, LaunchDarkly, Amplitude, and GrowthBook.

**Bucketing process**:
1. Compute `hash = murmurhash3(experiment_id + ":" + session_id)`
2. Normalize to a bucket: `bucket = (hash % 10000) / 100.0` (gives a value in [0.0, 100.0))
3. Walk the arms in order, accumulating weights. Assign to the first arm where `bucket < cumulative_weight`
4. If `bucket >= total_weight`, serve the default (control) prompt

**Critical implementation detail — use different seeds for different operations**: As Unleash discovered, using the same hash seed for both "is this user in the experiment?" and "which arm?" introduces bias. Use distinct seeds (or concatenate different salt strings) for the inclusion check vs the arm assignment.

**Benefits of client-side deterministic hashing**:
- Zero network I/O per resolve
- Consistent assignment across SDK restarts (same session_id always gets same arm)
- Works offline
- No session_assignments table writes needed (the assignment is implicit in the hash)

**Drawbacks**:
- Cannot support server-side overrides (e.g., force a specific user into a specific arm) without a config refresh
- Experiment weight changes take effect only after the next config sync (up to 30s delay)

### 3.4 When to Prefer Server-Side vs Client-Side Routing

| Factor | Server-Side Routing | Client-Side Routing |
|--------|-------------------|-------------------|
| **Latency** | +50-200ms per resolve | 0ms (in-memory) |
| **Consistency** | Immediate (server is source of truth) | Eventually consistent (~30s) |
| **Sticky sessions** | Stored in DB | Deterministic hash (no DB) |
| **Override support** | Full (force user into arm) | Limited (needs config refresh) |
| **Offline capability** | None | Full |
| **Complexity** | Lower (server does routing) | Higher (SDK implements routing) |
| **Best for** | Low-throughput, admin tools | High-throughput production, latency-sensitive |

**Recommendation**: Default to server-side routing (simpler, correct). Offer client-side routing as an opt-in for high-throughput deployments. The server-side `/resolve` endpoint should be fast enough (<10ms with connection pooling and caching) for most use cases.

---

## 4. Resilience Patterns

### 4.1 Circuit Breaker

The SDK should implement a circuit breaker for all API calls to protect against cascading failures when the prompt management server is degraded.

**Three states**:
- **Closed** (normal): Requests flow through. Failures are counted.
- **Open** (tripped): Requests are immediately rejected (or served from cache). No network calls.
- **Half-Open** (probing): One probe request is allowed. If it succeeds, the circuit closes. If it fails, the circuit opens again.

**Thresholds** (configurable):
- Open after 5 consecutive failures OR >50% failure rate in a 60-second window
- Stay open for 30 seconds before transitioning to half-open
- Close after 2 consecutive successes in half-open state

**Behavior when open**:
- `resolve()` serves from cache (stale but functional)
- `report_metric()` enqueues locally (will flush when circuit closes)
- SDK emits an event/callback so the application can monitor circuit state

### 4.2 Retry with Exponential Backoff and Jitter

**Retry policy for different request types**:

| Request Type | Retries | Backoff | Idempotent? |
|-------------|---------|---------|-------------|
| `GET /resolve` | 2 | 100ms, 400ms | Yes (safe) |
| `POST /metrics/batch` | 3 | 200ms, 800ms, 3200ms | Yes (with idempotency key) |
| `GET /config` | 2 | 500ms, 2000ms | Yes (safe) |

**Backoff formula**: `delay = min(base_delay * 2^attempt + random(0, base_delay), max_delay)`

**Jitter strategy**: Use "full jitter" (random between 0 and the calculated delay) rather than "equal jitter" or "decorrelated jitter". AWS research shows full jitter produces the best spread and lowest total time to completion across a fleet of clients.

**Non-retryable errors**: 400 (bad request), 401 (unauthorized), 403 (forbidden), 404 (not found). These indicate a client-side problem that retrying will not fix.

**Retryable errors**: 429 (rate limited, respect `Retry-After` header), 500 (server error), 502/503/504 (infrastructure error), connection timeout, connection reset.

### 4.3 Graceful Degradation

The SDK should never throw an unrecoverable error on the hot path. Degradation order:

1. **Fresh cache** (ideal): serve from in-memory cache within TTL
2. **Stale cache**: serve from in-memory cache past TTL, trigger background revalidation
3. **File fallback**: serve from local file fallback, log warning
4. **Developer default**: if no cache and no fallback, return a developer-provided default value

```python
prompt = await client.resolve(
    "welcome-email",
    default="Hello {{name}}, welcome to our service."
)
```

The `default` parameter ensures the application never crashes due to the prompt management system being unavailable.

### 4.4 Health Checks and Connection Pooling

**Health check**: The SDK should expose `client.health()` that returns the current state:
- `healthy`: server reachable, cache fresh
- `degraded`: serving from stale cache, server unreachable
- `unhealthy`: serving from file fallback or defaults

**Connection pooling**: Use `httpx` connection pooling with:
- `max_connections=10` (default, configurable)
- `max_keepalive_connections=5`
- `keepalive_expiry=30` seconds
- Connection reuse avoids TCP handshake + TLS negotiation overhead (~50-100ms per new connection)

---

## 5. Metric Batching in the Client

### 5.1 Async Queue + Periodic Flush

The metric reporter should use an async queue with dual-trigger flushing:

**Architecture**:
```
Application Thread          Background Worker
     |                           |
     | --- enqueue(event) --->   |
     |                        [Queue (bounded)]
     |                           |
     |                        Timer fires OR queue full
     |                           |
     |                        Batch POST /metrics/batch
     |                           |
     |                        Success: clear batch
     |                        Failure: retry or drop
```

**Flush triggers** (whichever comes first):
- **Time-based**: Every 10 seconds (configurable via `flush_interval`)
- **Count-based**: When the queue reaches 100 events (configurable via `flush_size`)
- **Manual**: `client.flush()` forces an immediate drain

### 5.2 Backpressure Handling

When the queue is full (default max: 1000 events), the SDK must make a choice:

| Strategy | Behavior | Trade-off |
|----------|----------|-----------|
| **Drop newest** | Reject the incoming event | Loses most recent data, preserves ordering |
| **Drop oldest** | Evict the oldest event, enqueue the new one | Loses historical data, keeps freshest |
| **Block** | Block the calling thread until space is available | Risks application slowdown |
| **Overflow to disk** | Write excess events to a local file | Complex, but no data loss |

**Recommended default**: Drop newest with a warning log. The calling application's latency must never be affected by metric reporting. Optionally, expose a callback: `on_metric_dropped(event)` so the application can monitor data loss.

**Monitoring**: The SDK should track and periodically report:
- `metrics_enqueued`: total events enqueued
- `metrics_flushed`: total events successfully sent
- `metrics_dropped`: total events dropped due to backpressure
- `flush_failures`: total failed flush attempts

### 5.3 Delivery Semantics

| Semantic | Guarantee | Implementation |
|----------|-----------|----------------|
| **At-most-once** | Events may be lost, never duplicated | Fire and forget. No retry. |
| **At-least-once** | Events may be duplicated, never lost | Retry with idempotency keys. Keep in queue until ACK. |
| **Exactly-once** | Neither lost nor duplicated | Requires server-side dedup (idempotency key + dedup window). |

**Recommended default**: At-least-once. The metric batch endpoint should accept an idempotency key per batch. If a flush succeeds on the server but the SDK does not receive the ACK (network timeout), it will retry and the server will deduplicate.

**Implementation**:
1. Each batch gets a UUID idempotency key
2. On successful flush (2xx response): remove events from queue
3. On timeout or 5xx: keep events in queue, retry on next flush cycle
4. On 400 (malformed): drop events, log error (retrying will not help)
5. On 429 (rate limited): keep events, back off, respect `Retry-After`

### 5.4 Client-Side Aggregation

For high-throughput applications generating thousands of metric events per second, the SDK can pre-aggregate before sending:

**Aggregation strategy**:
- Group by `(prompt_slug, version_id, experiment_id, arm_id, metric_name)`
- For each group in the flush window, compute: `count`, `sum`, `min`, `max`
- Send the aggregated summary instead of individual events

**Example**: 10,000 individual "latency_ms" events for "welcome-email" v7 in a 10-second window become a single aggregated record:
```json
{
  "slug": "welcome-email",
  "version_id": "uuid-v7",
  "metric_name": "latency_ms",
  "count": 10000,
  "sum": 2500000,
  "min": 45,
  "max": 1200,
  "window_start": "2026-03-25T10:00:00Z",
  "window_end": "2026-03-25T10:00:10Z"
}
```

This reduces payload size by 99%+ and server-side ingestion load proportionally.

**Trade-off**: Aggregation loses per-event metadata and individual session_id attribution. It should be opt-in and is only suitable for numeric metrics where aggregate statistics are sufficient. Quality signals (thumbs up/down) with per-session attribution should not be aggregated.

---

## 6. Multi-Language SDK Considerations

### 6.1 Python (Primary SDK)

**HTTP Client**: `httpx` — supports both sync and async from a single library, connection pooling, HTTP/2, timeouts, and streaming. It is the modern replacement for `requests`.

**Async Pattern**:
```python
# Sync
client = PromptClient(url="http://localhost:8910")
prompt = client.resolve("welcome-email")

# Async
async_client = AsyncPromptClient(url="http://localhost:8910")
prompt = await async_client.resolve("welcome-email")
```

Alternatively, follow Stripe's pattern of a single client with `_async` suffixed methods. This reduces the API surface but mixes sync/async on one object, which can confuse type checkers.

**Background worker**: Use `threading.Thread` for the sync client (like Sentry does), `asyncio.Task` for the async client. The sync client should not require an event loop.

**Type hints**: Full type annotations with `py.typed` marker. Use Pydantic models for response types to get validation and serialization for free.

**Minimum Python version**: 3.10+ (for match statements, union type syntax `X | Y`, and ParamSpec). This matches the target audience (ML/AI teams who tend to be on recent Python versions).

### 6.2 TypeScript / Node.js

**HTTP Client options**:
- `fetch` (built-in since Node 18) — zero dependencies, standard API
- `undici` — the HTTP client that powers Node's built-in fetch, offers more control (connection pooling, interceptors)
- `node-fetch` — legacy, avoid for new SDKs

**Recommended**: Use the global `fetch` API with a thin wrapper for retry/timeout logic. This works in Node.js 18+, Deno, Bun, Cloudflare Workers, and browsers — maximum portability.

**TypeScript-specific patterns**:
- Export discriminated union types for errors
- Use generics for paginated responses: `PaginatedResponse<Prompt>`
- Ship ESM and CJS dual builds
- Include source maps for debugging
- Use Zod or similar for runtime validation of server responses

**Background worker**: `setInterval` for periodic flush. Use `process.on('beforeExit')` and `process.on('SIGTERM')` for graceful shutdown flush.

### 6.3 Go

**Key idioms**:
- Return `(result, error)` tuples instead of throwing exceptions
- Use `context.Context` for cancellation and timeout propagation
- Use `sync.Pool` for connection reuse
- The metric reporter should use a goroutine with a `chan` for the event queue
- Use `sync.Once` for lazy initialization of the SSE connection

**HTTP Client**: `net/http` with a custom `Transport` for connection pooling. Consider `golang.org/x/net/http2` for HTTP/2 support.

**Polling interval**: Go's `time.Ticker` with jitter added per tick.

### 6.4 Java

**Key idioms**:
- Builder pattern for client construction: `PromptClient.builder().url(...).apiKey(...).build()`
- Use `CompletableFuture<T>` for async operations
- HTTP client: `java.net.http.HttpClient` (Java 11+) or OkHttp
- Metric queue: `java.util.concurrent.LinkedBlockingQueue` with a `ScheduledExecutorService` for periodic flush
- Use SLF4J for logging (lets the application choose the logging backend)

### 6.5 Ruby

**Key idioms**:
- Method naming follows snake_case convention
- Use `Faraday` as the HTTP client (adapter pattern, supports multiple backends)
- Background thread for metric flushing via `Thread.new`
- Use `at_exit` hook for graceful shutdown

### 6.6 Code Generation from OpenAPI Spec

**When to use code generation**:
- For "outer ring" SDKs (languages where you do not want to invest in hand-crafted code)
- For generating type definitions and request/response models
- For ensuring all SDKs stay in sync with API changes

**When NOT to use code generation**:
- For the primary SDK (Python) — hand-crafted code is more idiomatic and allows caching/batching logic
- For complex SDK behavior (circuit breakers, local routing, metric aggregation)

**Recommended tools**:
- **Fern**: Generates idiomatic SDKs for TypeScript, Python, Go, Java, Ruby, etc. Produces code that follows each language's conventions. Supports retries, pagination, and streaming out of the box.
- **OpenAPI Generator**: Open source, supports 50+ languages. Quality varies by language. Good for one-off generation, but generated code often needs manual polish.
- **Speakeasy**: Commercial, high-quality output. Good for companies that want to ship SDKs quickly.

**Recommended strategy**: Hand-craft the Python and TypeScript SDKs (primary audiences). Use Fern or OpenAPI Generator for Go, Java, Ruby, and other languages. Export the OpenAPI spec from FastAPI automatically (`app.openapi()`) and use it as the single source of truth for generated SDKs.

---

## 7. MCP Client Integration

### 7.1 How MCP Tools Enable Prompt Management from AI Agents

The Model Context Protocol (MCP) enables AI agents to discover and invoke tools exposed by MCP servers. For a prompt management library, this means an AI agent (Claude, GPT, etc.) can directly manage prompts, run experiments, and trigger optimizations through natural language interaction.

**Why this matters**: An AI agent that is generating or refining prompts (e.g., in an agentic workflow) can use MCP tools to:
1. Check the current version of a prompt before modifying it
2. Create a new version with proposed improvements
3. Set up an A/B experiment between the old and new versions
4. Monitor experiment metrics
5. Conclude the experiment and promote the winner

This closes the loop between "AI generates a better prompt" and "the better prompt is deployed to production" — all without human intervention (if desired).

### 7.2 MCP Tool Definitions

The prompt management MCP server should expose these tools:

| Tool | Description | Parameters |
|------|-------------|------------|
| `resolve_prompt` | Get the current prompt text for a given slug | `slug`, `version?`, `session_id?`, `variables?` |
| `list_prompts` | List available prompts with metadata | `tags?`, `limit?`, `cursor?` |
| `create_prompt` | Create a new prompt | `slug`, `name`, `body`, `model_hint?`, `tags?` |
| `create_version` | Create a new version of an existing prompt | `slug`, `body`, `model_hint?` |
| `get_experiment` | Get experiment status, arms, and metrics | `experiment_id` |
| `create_experiment` | Create an A/B experiment | `slug`, `arms[]`, `sticky?` |
| `conclude_experiment` | End experiment and promote winner | `experiment_id`, `winner_arm_id` |
| `report_metric` | Report a quality/performance signal | `slug`, `session_id`, `metrics{}` |
| `optimize_prompt` | Trigger LLM-powered optimization | `slug`, `constraints?` |

### 7.3 MCP Resource Exposure

MCP resources allow AI agents to read structured data without invoking a tool. Resources are identified by URIs and can be listed and read.

**Resource URIs for the prompt manager**:

| URI Pattern | Description |
|-------------|-------------|
| `prompt://prompts` | List of all prompts (metadata only) |
| `prompt://prompts/{slug}` | Full prompt details including current version body |
| `prompt://prompts/{slug}/versions` | Version history for a prompt |
| `prompt://experiments/{id}` | Experiment details with per-arm metrics |
| `prompt://experiments/{id}/metrics` | Detailed metric breakdown for an experiment |

**Why resources in addition to tools**: Resources are read-only and can be subscribed to for changes. An AI agent can subscribe to `prompt://experiments/{id}/metrics` and receive updates as new metrics arrive, enabling real-time monitoring of experiment progress without polling.

### 7.4 MCP Server Architecture

The MCP server should:
- Share the same service layer as the HTTP API (no logic duplication)
- Support both `stdio` transport (for local development, Claude Desktop) and `SSE` transport (for remote access)
- Be enabled/disabled via configuration (`PM_MCP_ENABLED=true`)
- Run as a separate process or be embedded in the FastAPI application

**Security considerations**:
- MCP tool invocations from AI agents should be subject to the same API key authentication as HTTP requests
- Tool poisoning is a known MCP attack vector — the server should validate all inputs strictly
- Rate limiting should apply to MCP tool calls to prevent runaway agent loops

### 7.5 Agent-to-Agent Communication (2026 Roadmap)

The MCP specification roadmap includes extensions for agent-to-agent communication, where an MCP server can act as an agent itself. This opens the possibility of:
- An "optimizer agent" that monitors experiment metrics and automatically triggers optimization runs
- A "reviewer agent" that evaluates proposed prompt changes before they are deployed
- Composable agent workflows where one agent creates a prompt and another agent tests it

---

## 8. Synthesis and Recommendations

### Priority-Ordered Implementation Plan for the SDK

| Priority | Feature | Pattern Source | Effort |
|----------|---------|---------------|--------|
| **P0** | In-memory TTL cache + file fallback | PostHog, LaunchDarkly | Medium |
| **P0** | Typed error hierarchy | Stripe | Low |
| **P0** | Retry with exponential backoff + jitter | Stripe, AWS | Low |
| **P0** | Graceful degradation (stale cache, defaults) | LaunchDarkly | Medium |
| **P1** | Metric batching (async queue + periodic flush) | Sentry | Medium |
| **P1** | ETag revalidation | HTTP standard | Low |
| **P1** | Circuit breaker | AWS, Azure patterns | Medium |
| **P1** | MCP tool definitions | MCP spec | Medium |
| **P2** | Client-side experiment routing (deterministic hashing) | Optimizely, LaunchDarkly | High |
| **P2** | SSE streaming for real-time updates | LaunchDarkly | High |
| **P2** | Client-side metric aggregation | Sentry, PostHog | Medium |
| **P2** | External cache provider (Redis) | PostHog | Medium |
| **P3** | OpenAPI-generated SDKs (Go, Java, Ruby) | Fern, OpenAPI Generator | High |
| **P3** | MCP resource subscriptions | MCP spec | Medium |

### Key Architectural Decisions

1. **Default to server-side routing, offer client-side as opt-in.** Server-side routing is simpler, immediately consistent, and sufficient for most use cases. Client-side routing (with deterministic hashing) should be available for high-throughput deployments.

2. **Use httpx as the sole HTTP dependency for Python.** It supports sync and async, connection pooling, HTTP/2, timeouts, and streaming. Do not pull in both `requests` and `aiohttp`.

3. **Metric reporting must never block the application.** Use a bounded queue with drop-on-overflow semantics. At-least-once delivery with idempotency keys for reliability without risking application latency.

4. **The SDK must work when the server is down.** The three-layer cache (memory, ETag, file) plus developer-provided defaults means the application is never blocked by the prompt management system.

5. **Hand-craft Python and TypeScript SDKs. Generate the rest.** The primary audience (ML/AI teams) uses Python. Web teams use TypeScript. Both deserve first-class, idiomatic SDKs. Other languages can be generated from the OpenAPI spec.

6. **MCP integration is a differentiator.** No other prompt management library exposes prompts as MCP tools and resources. This enables AI agents to self-manage their own prompts — a unique capability for agentic workflows.

---

## Sources

- [Stripe Python SDK — GitHub](https://github.com/stripe/stripe-python)
- [Stripe Error Handling Documentation](https://docs.stripe.com/error-handling?lang=python)
- [Stripe Idempotency Blog Post](https://stripe.com/blog/idempotency)
- [Stripe API v2 Overview](https://docs.stripe.com/api-v2-overview)
- [Stripe Advanced Error Handling](https://docs.stripe.com/error-low-level)
- [LaunchDarkly Architecture](https://launchdarkly.com/docs/home/getting-started/architecture)
- [LaunchDarkly SDK Contributor's Guide](https://docs.launchdarkly.com/sdk/concepts/contributors-guide)
- [LaunchDarkly Deeper Architecture Dive](https://launchdarkly.com/docs/tutorials/ld-arch-deep-dive)
- [LaunchDarkly Client-Side vs Server-Side SDKs](https://launchdarkly.com/docs/sdk/concepts/client-side-server-side)
- [PostHog Local Evaluation](https://posthog.com/docs/feature-flags/local-evaluation)
- [PostHog Local Evaluation in Distributed Environments](https://posthog.com/docs/feature-flags/local-evaluation/distributed-environments)
- [PostHog Feature Flag Resilience Blog](https://posthog.com/blog/how-we-improved-feature-flags-resiliency)
- [Sentry Envelope Format](https://develop.sentry.dev/sdk/foundations/transport/envelopes/)
- [Sentry SDK Expected Features](https://develop.sentry.dev/sdk/expected-features/)
- [Sentry Python Transport Source](https://github.com/getsentry/sentry-python/blob/master/sentry_sdk/transport.py)
- [Sentry Shutdown and Draining](https://docs.sentry.io/platforms/python/configuration/draining/)
- [AWS Timeouts, Retries and Backoff with Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)
- [AWS Circuit Breaker Pattern](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/circuit-breaker.html)
- [Azure Circuit Breaker Pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/circuit-breaker)
- [Optimizely Bucketing](https://docs.developers.optimizely.com/feature-experimentation/docs/how-bucketing-works-feature-experimentation)
- [Unleash Hashing Blog](https://www.getunleash.io/blog/hashing-it-right-solving-a-gradual-rollout-puzzle)
- [GrowthBook Feature Flag Experiments](https://docs.growthbook.io/feature-flag-experiments)
- [MDN ETag Header](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/ETag)
- [MCP Specification — Tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP Wikipedia](https://en.wikipedia.org/wiki/Model_Context_Protocol)
- [Fern SDK Generation](https://buildwithfern.com/post/best-sdk-generation-tools-multi-language-api)
- [OpenAPI Generator](https://openapi-generator.tech/)
- [FastAPI SDK Generation](https://fastapi.tiangolo.com/advanced/generate-clients/)
