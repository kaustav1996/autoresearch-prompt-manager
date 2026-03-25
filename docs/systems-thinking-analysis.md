# Prompt Manager: Systems Thinking Analysis

## 1. Stakeholders and Actors

### Primary Actors

| Actor | Role | Interaction Surface |
|-------|------|-------------------|
| **Application Developer** | Integrates `[client]` SDK into their application to fetch prompts at runtime | Client SDK init, `selectPrompt()` calls |
| **Prompt Engineer** | Creates, versions, and tunes prompts via the API; designs experiments | HTTP/RPC API, MCP tools |
| **Platform Operator** | Deploys and configures the `[api]` server, manages PostgreSQL, sets LLM credentials | Configuration files, environment variables, migration runner |
| **LLM Provider** | External service (Claude, OpenAI, Groq, Gemini, Bedrock, OpenRouter, custom) that executes prompt-improvement requests | Outbound HTTP from `[api]` |
| **End User** | The human whose request flows through the application; never touches the prompt manager directly but is the ultimate subject of prompt quality | Indirect -- their interactions produce the metrics |
| **MCP Client** | Any MCP-compatible tool (e.g., Claude Code, IDE plugin) that discovers and invokes prompt management tools | MCP protocol over `[api]` |
| **Observability System** | External logging, tracing, or alerting infrastructure consuming signals from all three packages | Structured logs, health endpoints |

### Secondary / Emergent Actors

| Actor | How They Emerge |
|-------|----------------|
| **The Optimization Loop Itself** | Once metric signals trigger LLM-based prompt rewriting, the loop becomes an autonomous actor making decisions that affect all downstream consumers |
| **The Experiment Scheduler** | The routing logic that decides which prompt version a given request receives; it acts as a silent gatekeeper shaping user experience |
| **Database (PostgreSQL)** | Not passive storage -- async connection pooling, migration state, and row-level locks make it an active participant in consistency guarantees |

---

## 2. Feedback Loops

### 2.1 Primary Optimization Loop (Reinforcing)

```
Metric Signal ──> [metric] package ──> [api] server
       ^                                     │
       │                                     ▼
       │                            Prompt Improver (LLM call)
       │                                     │
       │                                     ▼
       │                            New Prompt Version created
       │                                     │
       │                                     ▼
       │                            Experiment weights adjusted
       │                                     │
       │                                     ▼
       │                            [client] serves new version
       │                                     │
       │                                     ▼
       │                            End-user interaction
       │                                     │
       └─────────────────────────────────────┘
```

**Type**: Reinforcing (positive feedback). Better prompts generate better metrics, which trigger further optimization. Without constraints this loop can:
- Overfit to a narrow metric (Goodhart's Law)
- Oscillate if the LLM "improvement" degrades the metric, triggering another improvement in the opposite direction
- Amplify bias present in the metric definition

**Required Dampers**:
- Cooldown period between optimization runs per prompt
- Maximum version churn rate (e.g., no more than N new versions per hour)
- Metric confidence threshold before triggering optimization (minimum sample size)
- Rollback capability when a new version underperforms

### 2.2 Experiment Convergence Loop (Balancing)

```
Experiment running (versions A: 70%, B: 30%)
       │
       ▼
Metrics collected for A and B independently
       │
       ▼
Statistical comparison ──> Winner identified
       │
       ▼
Weights shift toward winner (A: 90%, B: 10%)
       │
       ▼
Eventually: loser retired, winner becomes default
```

**Type**: Balancing (negative feedback). The system converges on the best-performing variant and eliminates underperformers. This is healthy but can:
- Prematurely converge with insufficient data (multi-armed bandit cold-start problem)
- Starve minority variants of traffic before they accumulate meaningful signal

### 2.3 LLM Provider Feedback Loop (External Coupling)

```
Prompt improvement request ──> LLM Provider
       │                              │
       │    (latency, cost, quality)   │
       ▼                              ▼
API server receives improved prompt
       │
       ▼
If LLM is down/slow ──> improvement stalls ──> stale prompts served
```

**Type**: Dependent on external system. The optimization loop's liveness is coupled to LLM provider availability.

---

## 3. Emergent Behaviors and Second-Order Effects

### 3.1 Prompt Drift

When the optimization loop runs continuously, prompts will diverge from their original intent over many iterations. Version 1 of a prompt may be recognizably authored by a human; version 47 may be an LLM-optimized artifact that no human wrote or reviewed. This creates:
- **Auditability gaps**: Compliance-sensitive environments cannot explain why a prompt says what it says.
- **Fragility**: LLM-optimized prompts may exploit model-specific quirks that break on provider changes.

**Mitigation**: Maintain an immutable lineage chain. Every version stores its parent version ID and the optimization rationale. Provide a "diff from original" view.

### 3.2 Metric Gaming

If the metric is "user clicked the suggested action," the optimizer will learn to produce prompts that maximize clicks, not necessarily quality. This is a classic Goodhart scenario where the measure becomes the target.

**Mitigation**: Support composite metrics with guard-rail constraints (e.g., optimize for engagement BUT reject if hallucination rate exceeds threshold).

### 3.3 Thundering Herd on Experiment Transition

When an experiment concludes and weights shift to 100/0, all client SDK instances must pick up the change. If the client polls on a fixed interval, a large fleet will hit the API simultaneously.

**Mitigation**: Jittered polling intervals in `[client]`. Cache headers with stale-while-revalidate semantics. Event-driven push via WebSocket or SSE as an alternative to polling.

### 3.4 Cold Start Amplification

A new prompt with no versions has no metrics. The optimizer has no signal. If a new experiment is created against a prompt with zero historical data, the LLM improver is operating blind, and early metrics from a tiny sample will have outsized influence.

**Mitigation**: Require a minimum observation window and sample size before the optimization loop activates for any prompt/experiment.

### 3.5 Cross-Experiment Interference

If Prompt A and Prompt B are used in the same user flow (e.g., A generates a summary, B generates follow-up questions), running experiments on both simultaneously creates interaction effects that neither experiment's metrics can isolate.

**Mitigation**: Document experiment scoping. Optionally support experiment groups/layers (as in Google's overlapping experiment infrastructure).

---

## 4. Package Dependencies and Coupling

### Dependency Graph

```
┌──────────┐         ┌──────────┐         ┌──────────┐
│ [client]  │────────>│  [api]   │<────────│ [metric] │
└──────────┘  HTTP/   └──────────┘  HTTP/  └──────────┘
              RPC       │      │    RPC
                        │      │
                        ▼      ▼
                   PostgreSQL  LLM Provider(s)
```

### Coupling Analysis

| Relationship | Type | Strength | Risk |
|-------------|------|----------|------|
| `[client]` -> `[api]` | Runtime (HTTP/RPC) | **Tight** | Client cannot function if API is unreachable. Every prompt selection requires a network call. |
| `[metric]` -> `[api]` | Runtime (HTTP/RPC) | **Medium** | Metric signals can be buffered/batched. Temporary API unavailability means delayed optimization, not broken applications. |
| `[api]` -> PostgreSQL | Runtime (async DB) | **Tight** | API is stateless; all state lives in PostgreSQL. DB failure is total system failure. |
| `[api]` -> LLM Provider | Runtime (HTTP) | **Loose** | Only the optimization subsystem needs the LLM. CRUD, versioning, experiment routing all work without it. |
| `[client]` -> `[metric]` | **None** | None | These packages have no direct dependency. The application code bridges them. |

### Shared Contracts (Implicit Coupling)

All three packages share implicit contracts that, if violated, cause silent failures:

1. **Prompt ID format**: All packages must agree on the identifier scheme.
2. **Version numbering**: `[client]` assumes "latest" means the highest version number. If `[api]` changes versioning semantics, `[client]` breaks.
3. **Experiment routing protocol**: `[client]` must implement the same weighted-random algorithm the `[api]` uses to assign variants, OR the `[api]` must make the selection and `[client]` just receives the result. This is an architectural decision with significant coupling implications.
4. **Metric signal schema**: `[metric]` sends signals that `[api]` must parse. Schema evolution must be backward-compatible.

### Recommended Decoupling Strategies

- **Client-side caching with TTL**: `[client]` caches prompt selections locally, reducing tight coupling to API availability.
- **Metric buffering**: `[metric]` writes to a local queue (in-memory or disk) and flushes asynchronously, decoupling metric collection from API availability.
- **Schema versioning**: All API contracts include a version field. `[api]` supports N-1 client versions.
- **Server-side routing**: The `[api]` should resolve experiment routing and return the selected prompt version. Do not push routing logic to `[client]`; this avoids duplicating weighted-random logic and ensures consistency.

---

## 5. Failure Modes and Cascading Failures

### 5.1 Failure Mode Map

| Failure | Blast Radius | Cascade Path | Severity |
|---------|-------------|--------------|----------|
| **PostgreSQL down** | Total system outage | API cannot serve prompts -> Client gets errors -> Application degrades | **Critical** |
| **API server down** | All consumers affected | Client cannot select prompts -> Metric signals lost -> Optimization stops | **Critical** |
| **LLM provider down** | Optimization only | Prompt improvement fails -> Stale prompts continue serving (graceful degradation) | **Low** |
| **LLM returns bad prompt** | Single prompt/experiment | Bad version enters rotation -> Metrics degrade -> Optimization tries to fix it (may succeed or spiral) | **Medium** |
| **Metric pipeline lag** | Delayed optimization | Stale routing weights -> Suboptimal variant distribution -> Slow convergence | **Low** |
| **Client SDK misconfiguration** | Single application | Wrong API path -> All prompt selections fail -> Application defaults or crashes | **Medium** (isolated) |
| **Migration failure** | Total system outage | Schema mismatch -> API cannot query DB -> All operations fail | **Critical** |
| **Experiment weight overflow** | Data integrity | Weights sum > 100% -> Undefined routing behavior -> Inconsistent user experience | **High** |
| **Concurrent version creation** | Data integrity | Two optimization runs create conflicting "latest" versions -> Client gets non-deterministic results | **High** |

### 5.2 Cascade Scenario: Bad Optimization Spiral

```
1. LLM produces a subtly degraded prompt (passes validation but performs poorly)
2. New version enters experiment at low weight (10%)
3. Metrics come in negative for new version
4. Optimizer triggers again, asks LLM to improve the already-bad version
5. LLM compounds the error (it cannot see what went wrong from metrics alone)
6. Cycle repeats: each "improvement" makes things worse
7. Meanwhile, traffic shifts keep the bad version in rotation
```

**Circuit Breaker**: If a version's metrics are below a threshold after N observations, automatically revert to the previous version and halt optimization for that prompt. Require human review to resume.

### 5.3 Cascade Scenario: Database Connection Pool Exhaustion

```
1. Spike in client SDK requests (e.g., application scales up)
2. API opens many async DB connections
3. Connection pool exhausts
4. New requests queue up
5. Client SDK timeouts cascade to application-level errors
6. Metric signals also fail (they hit the same API)
7. Optimization loop starves for data
```

**Mitigation**: Separate connection pools for read (prompt selection) and write (metrics, optimization) paths. Rate limiting on the API. Client-side circuit breaker with cached fallback.

---

## 6. Experiment Routing System Dynamics

### 6.1 State Machine

```
                    ┌─────────────┐
                    │   DRAFT     │  (experiment created, not active)
                    └──────┬──────┘
                           │ activate()
                           ▼
                    ┌─────────────┐
            ┌──────│   RUNNING   │──────┐
            │      └──────┬──────┘      │
            │             │             │
     pause()│             │ conclude()  │ abort()
            │             │             │
            ▼             ▼             ▼
     ┌──────────┐  ┌───────────┐  ┌─────────┐
     │  PAUSED  │  │ CONCLUDED │  │ ABORTED │
     └──────┬───┘  └───────────┘  └─────────┘
            │
            │ resume()
            ▼
     ┌─────────────┐
     │   RUNNING   │
     └─────────────┘
```

### 6.2 Weight Distribution Invariants

The routing system must enforce these invariants at all times:

1. **Sum Constraint**: For any prompt, the sum of all active experiment variant weights must equal exactly 100%, OR a "default" bucket absorbs the remainder.
2. **Non-Negative Weights**: No variant may have a weight < 0%.
3. **Atomicity**: Weight changes across variants in the same experiment must be atomic. Updating A from 70->60 and B from 30->40 must happen in one transaction.
4. **No Orphan Traffic**: If all experiments for a prompt are paused/concluded, 100% of traffic goes to the default (latest) version.

### 6.3 Routing Algorithm

Two viable approaches, with different system dynamics:

**Server-Side Routing** (Recommended):
- Client sends `selectPrompt(promptId)` with no version
- Server generates a random number, maps it to a variant based on weights
- Server returns the resolved prompt text and version
- Consistent behavior: all clients use identical routing logic
- Trade-off: every selection requires a server round-trip

**Client-Side Routing with Server-Provided Config**:
- Client fetches experiment config (variants + weights) and caches it
- Client performs weighted random selection locally
- Trade-off: stale configs mean clients route differently from each other during config propagation windows
- Risk: different language SDKs may implement weighted random differently, creating subtle distribution skew

### 6.4 Multi-Experiment Conflicts

If Prompt P has two active experiments (E1 and E2), the system must decide:
- **Option A**: Disallow. Only one active experiment per prompt at a time. Simple and safe.
- **Option B**: Layer experiments. E1 and E2 operate on orthogonal dimensions (e.g., E1 tests wording, E2 tests format). Requires careful traffic splitting.

**Recommendation**: Option A for v1. The complexity of layered experiments introduces combinatorial explosion in metric attribution.

---

## 7. Race Conditions in Concurrent Prompt Updates

### 7.1 Identified Race Conditions

#### Race 1: Concurrent "Latest" Version Creation

```
Time    Thread A (Human Edit)          Thread B (Optimizer)
─────   ─────────────────────          ────────────────────
T1      Read current latest: v3
T2                                     Read current latest: v3
T3      Create v4 (from human edit)
T4                                     Create v4 (from optimization)
T5      ??? -- Two v4s, or one overwrites the other
```

**Solution**: Use a database-level advisory lock or optimistic concurrency control (OCC) on the `(prompt_id, version_number)` pair. The version number should be assigned by a `SELECT MAX(version) + 1 ... FOR UPDATE` within a transaction, serializing version creation.

#### Race 2: Experiment Weight Update During Routing

```
Time    Client Request                 Optimizer
─────   ──────────────                 ─────────
T1      Read weights: A=70, B=30
T2                                     Begin weight update
T3                                     Write: A=60, B=40
T4      Route using stale weights
```

**Impact**: Low. Stale weights for a single request cause a minor statistical deviation. Over many requests, the distribution self-corrects. This is an acceptable eventual-consistency trade-off.

**If strict consistency is required**: Use PostgreSQL's `SERIALIZABLE` isolation level for weight reads during routing. But this adds latency and contention. Not recommended for v1.

#### Race 3: Metric Signal Arrives for Retired Version

```
Time    Event
─────   ─────
T1      Experiment concludes, version B retired
T2      Metric signal arrives for version B (delayed in transit)
T3      Optimizer processes metric for a version that no longer exists
```

**Solution**: Metric signals must include a timestamp. Discard signals that arrive after the version/experiment was retired. Maintain a tombstone record for retired versions with a `retired_at` timestamp.

#### Race 4: Simultaneous Optimization Runs for the Same Prompt

```
Time    Optimizer Instance 1           Optimizer Instance 2
─────   ────────────────────           ────────────────────
T1      Triggered by metric batch 1
T2                                     Triggered by metric batch 2
T3      Calls LLM to improve v3
T4                                     Calls LLM to improve v3
T5      Creates v4 from LLM result A
T6                                     Creates v5 from LLM result B
T7      Two divergent improvements exist; experiment state unclear
```

**Solution**: Use a distributed lock (PostgreSQL advisory lock keyed on `prompt_id`) around the entire optimization cycle: read metrics -> call LLM -> create version -> update experiment. Only one optimization run per prompt at a time.

### 7.2 Concurrency Control Strategy Summary

| Resource | Strategy | Mechanism |
|----------|----------|-----------|
| Version number assignment | Pessimistic locking | `SELECT ... FOR UPDATE` in transaction |
| Experiment weight reads | Eventual consistency | Acceptable staleness for routing |
| Experiment weight writes | Atomic transaction | Single `UPDATE` with `WHERE` clause check |
| Optimization run per prompt | Distributed mutex | PostgreSQL advisory lock on `prompt_id` |
| Metric signal processing | Idempotent with timestamp | Discard stale signals, dedup by signal ID |

---

## 8. Information Flows

### 8.1 Complete Information Flow Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL BOUNDARY                            │
│                                                                     │
│  ┌──────────┐    prompt text     ┌──────────┐                      │
│  │End User's│◄──────────────────│Application│                      │
│  │ Request  │                    │  Code     │                      │
│  └──────────┘                    └────┬──┬───┘                      │
│                                       │  │                          │
│                    selectPrompt()─────┘  └───── reportMetric()      │
│                         │                         │                 │
│  ┌──────────────────────┼─────────────────────────┼──────────────┐  │
│  │                LIBRARY BOUNDARY                │              │  │
│  │                      │                         │              │  │
│  │                      ▼                         ▼              │  │
│  │               ┌──────────┐              ┌──────────┐          │  │
│  │               │ [client] │              │ [metric] │          │  │
│  │               │          │              │          │          │  │
│  │               │ - cache  │              │ - buffer │          │  │
│  │               │ - retry  │              │ - batch  │          │  │
│  │               └────┬─────┘              └────┬─────┘          │  │
│  │                    │                         │                │  │
│  │              HTTP/RPC                  HTTP/RPC               │  │
│  │                    │                         │                │  │
│  │                    ▼                         ▼                │  │
│  │               ┌──────────────────────────────────┐            │  │
│  │               │            [api]                  │            │  │
│  │               │                                   │            │  │
│  │               │  ┌────────────┐  ┌────────────┐  │            │  │
│  │               │  │ Prompt     │  │ Experiment │  │            │  │
│  │               │  │ CRUD +     │  │ Router +   │  │            │  │
│  │               │  │ Versioning │  │ Weights    │  │            │  │
│  │               │  └────────────┘  └────────────┘  │            │  │
│  │               │                                   │            │  │
│  │               │  ┌────────────┐  ┌────────────┐  │            │  │
│  │               │  │ Metric     │  │ Prompt     │  │            │  │
│  │               │  │ Aggregator │──│ Improver   │──┼──► LLM    │  │
│  │               │  └────────────┘  └────────────┘  │   Provider│  │
│  │               │                                   │            │  │
│  │               │  ┌────────────┐  ┌────────────┐  │            │  │
│  │               │  │ Migration  │  │ MCP        │  │            │  │
│  │               │  │ Runner     │  │ Server     │  │            │  │
│  │               │  └────────────┘  └────────────┘  │            │  │
│  │               │         │                         │            │  │
│  │               └─────────┼─────────────────────────┘            │  │
│  │                         │                                      │  │
│  └─────────────────────────┼──────────────────────────────────────┘  │
│                            │                                         │
│                            ▼                                         │
│                      ┌──────────┐                                    │
│                      │PostgreSQL│                                    │
│                      │          │                                    │
│                      │ prompts  │                                    │
│                      │ versions │                                    │
│                      │ expts    │                                    │
│                      │ metrics  │                                    │
│                      │ locks    │                                    │
│                      └──────────┘                                    │
└─────────────────────────────────────────────────────────────────────┘
```

### 8.2 Data Flow Classification

| Flow | Data | Direction | Frequency | Latency Sensitivity |
|------|------|-----------|-----------|-------------------|
| Prompt Selection | Prompt text + metadata | `[client]` <- `[api]` <- DB | Per user request | **High** (in critical path) |
| Metric Reporting | Metric name, value, prompt_id, version | `[metric]` -> `[api]` -> DB | Per user interaction | **Low** (can be batched) |
| Optimization Trigger | Aggregated metrics | DB -> `[api]` (internal) | Periodic / threshold | **Low** |
| LLM Improvement | Prompt text + metrics context | `[api]` -> LLM Provider | Per optimization run | **Low** (background) |
| Experiment Config | Variant IDs + weights | `[api]` -> `[client]` (embedded in selection response) | Per selection or per cache refresh | **High** |
| CRUD Operations | Full prompt objects | MCP/HTTP -> `[api]` -> DB | Human-initiated | **Medium** |
| Migration | DDL statements | `[api]` -> DB | On deploy | N/A (offline) |

### 8.3 Information Bottlenecks

1. **The API server is a single chokepoint**: All three data flows (selection, metrics, optimization) pass through it. Under load, prompt selection (latency-sensitive) competes with metric ingestion (throughput-sensitive) for the same server resources.

   **Mitigation**: Separate read and write endpoints. Consider read replicas for prompt selection. Metric ingestion could write to a queue (Redis, SQS) rather than directly to PostgreSQL.

2. **PostgreSQL is the single source of truth AND the hot path**: Every prompt selection hits the DB (unless cached).

   **Mitigation**: Aggressive caching in `[api]` with invalidation on version creation. CDN-friendly cache headers for the HTTP API.

3. **LLM provider is an external dependency with variable latency**: A single slow LLM call can hold a database advisory lock for seconds, blocking other optimization runs.

   **Mitigation**: Timeout on LLM calls. Release the advisory lock before calling the LLM (use a "claim" pattern: mark the optimization as in-progress, release lock, call LLM, re-acquire lock to write result).

---

## 9. System Boundaries and Contracts

### 9.1 API Contract Boundaries

The system has three critical contract boundaries that must be versioned independently:

1. **`[api]` <-> `[client]`**: Prompt selection protocol. Breaking changes here affect all downstream applications.
2. **`[api]` <-> `[metric]`**: Metric signal schema. Must be append-only (new fields OK, removing fields breaks).
3. **`[api]` <-> LLM Provider**: The prompt-improvement meta-prompt. This is itself a prompt that should be versioned and potentially optimized -- a meta-level concern.

### 9.2 Configuration Dependency Map

```
[api] requires:
  ├── PostgreSQL connection string (async driver)
  ├── Server port
  ├── LLM provider credentials (at least one)
  │   ├── Claude: API key + model
  │   ├── OpenAI: API key + model
  │   ├── Groq: API key + model
  │   ├── Gemini: API key + model
  │   ├── Bedrock: AWS credentials + region + model
  │   ├── OpenRouter: API key + model
  │   └── Custom: base URL + auth header + model
  ├── Optimization parameters
  │   ├── Cooldown period
  │   ├── Minimum sample size
  │   └── Confidence threshold
  └── MCP server configuration

[client] requires:
  ├── API base URL (HTTP/RPC path)
  ├── Authentication token (optional)
  └── Cache TTL (optional, with sensible default)

[metric] requires:
  ├── API base URL (HTTP/RPC path)
  ├── Authentication token (optional)
  ├── Buffer size (optional)
  └── Flush interval (optional)
```

---

## 10. Recommendations Summary

| Priority | Recommendation | Addresses |
|----------|---------------|-----------|
| **P0** | Server-side experiment routing (do not push to client) | Consistency, coupling reduction |
| **P0** | Advisory locks on prompt_id for optimization runs | Race condition 4 |
| **P0** | Serialized version number assignment via `FOR UPDATE` | Race condition 1 |
| **P0** | Weight sum constraint enforced at DB level (`CHECK` constraint or trigger) | Experiment integrity |
| **P1** | Client-side cache with TTL and jittered refresh | Thundering herd, API availability |
| **P1** | Metric buffering in `[metric]` package with async flush | Decoupling, throughput |
| **P1** | Circuit breaker on optimization loop (revert on sustained metric decline) | Bad optimization spiral |
| **P1** | Cooldown + minimum sample size before optimization triggers | Cold start, oscillation |
| **P2** | Separate DB connection pools for reads vs writes | Connection pool exhaustion |
| **P2** | Metric signal timestamping and stale-signal discard | Race condition 3 |
| **P2** | Prompt lineage tracking (parent version, optimization rationale) | Prompt drift auditability |
| **P3** | Single active experiment per prompt constraint (v1) | Cross-experiment interference |
| **P3** | Composite metrics with guard-rail constraints | Metric gaming |
| **P3** | Meta-prompt versioning for the prompt improver itself | Meta-level optimization |
