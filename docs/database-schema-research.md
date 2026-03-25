# Database Schema Design Patterns for Prompt Management Systems

## Research Document

---

## 1. Versioning Patterns in PostgreSQL

### 1.1 Temporal Tables vs. Append-Only Version Tables

There are two dominant patterns for modeling versioned entities in PostgreSQL:

**Temporal Tables (SQL:2011 / system-versioned)**

Temporal tables maintain a "current" row in the primary table and automatically move superseded rows into a history table. PostgreSQL does not natively support SQL:2011 temporal tables, but the pattern can be emulated with triggers or extensions like `temporal_tables` (pgxn).

```
prompts (current state)
  ├── id, slug, name, body, ...
  ├── valid_from TIMESTAMPTZ
  └── valid_to   TIMESTAMPTZ  (NULL = current)

prompts_history (automatically populated by trigger)
  ├── same columns as prompts
  └── valid_from, valid_to (both non-NULL)
```

Pros:
- The "current" query is trivially fast: `SELECT * FROM prompts WHERE slug = $1` -- no version filtering needed.
- History is queryable via `WHERE valid_from <= $ts AND valid_to > $ts` for point-in-time lookups.
- Keeps the hot table small.

Cons:
- Trigger-based emulation adds write overhead and maintenance complexity.
- The "current" row is mutable, which conflicts with immutability principles.
- Two-table join required for lineage queries.
- Not a natural fit when versions are first-class entities with their own metadata (source, created_by, content_hash).

**Append-Only Version Tables (recommended for this system)**

A separate `prompt_versions` table where each row is an immutable version. The parent `prompts` table holds a `current_version` pointer.

```
prompts
  ├── id, slug, name, current_version, ...

prompt_versions
  ├── id, prompt_id, version (monotonic int), body, content_hash, source, ...
  └── UNIQUE(prompt_id, version)
```

Pros:
- Each version is a first-class immutable record with its own metadata.
- Natural fit for content-addressable storage (content_hash).
- Clean lineage via `parent_version` column.
- No triggers needed. Simple INSERT-only pattern.
- Versions can be independently referenced by experiments, metrics, and optimization runs.

Cons:
- "Get latest" requires a join or subquery: `WHERE prompt_id = $1 AND version = (SELECT current_version FROM prompts WHERE id = $1)`.

**Recommendation**: Append-only version tables. The existing implementation plan already follows this pattern, and it is the right choice. Prompt versions are first-class entities with rich metadata (source, content_hash, parent_version, created_by) that would be awkward to model in a temporal-table approach.

### 1.2 Efficiently Querying "Latest Version"

The most frequently executed query in the system will be: "Give me the current prompt body for slug X." This is the hot path called on every `/resolve/{slug}` request.

**Strategy 1: Denormalized `current_version` pointer (recommended)**

The `prompts` table stores a `current_version INT` column. Resolving the latest version becomes:

```sql
SELECT pv.body, pv.version, pv.content_hash, pv.template_vars
FROM prompts p
JOIN prompt_versions pv ON pv.prompt_id = p.id AND pv.version = p.current_version
WHERE p.slug = $1 AND p.archived_at IS NULL;
```

This is a single index lookup on `prompts(slug)` followed by a single index lookup on `prompt_versions(prompt_id, version)`. Both are covered by existing unique indexes.

**Covering index for the hot path:**

```sql
-- Covers the slug lookup, filtering archived prompts
CREATE UNIQUE INDEX idx_prompts_slug_active
  ON prompts(slug)
  WHERE archived_at IS NULL
  INCLUDE (id, current_version);

-- Covers the version lookup with all columns needed for resolve
CREATE UNIQUE INDEX idx_versions_prompt_version_covering
  ON prompt_versions(prompt_id, version)
  INCLUDE (body, content_hash, template_vars, model_hint);
```

The `INCLUDE` clause (PostgreSQL 11+) stores additional columns in the index leaf pages, enabling index-only scans. For the resolve hot path, the query planner can satisfy the entire query from these two indexes without touching the heap.

Trade-off: The `INCLUDE (body)` is expensive if prompt bodies are large (several KB). In that case, omit `body` from the covering index and accept a heap fetch. For most prompts (under 4KB), the covering index is worth it.

**Strategy 2: Materialized view (not recommended for this use case)**

A materialized view `latest_prompt_versions` could precompute the join. However:
- It requires `REFRESH MATERIALIZED VIEW` on every version creation, adding latency to writes.
- `CONCURRENTLY` refresh requires a unique index and still takes time proportional to view size.
- The denormalized pointer approach is strictly better here because writes (new versions) are infrequent compared to reads (resolve calls).

**Strategy 3: Window function approach (not recommended for hot path)**

```sql
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY prompt_id ORDER BY version DESC) AS rn
  FROM prompt_versions
) t WHERE rn = 1 AND prompt_id = $1;
```

This is elegant for analytics but scans all versions of a prompt. Unacceptable for a hot path. Fine for admin dashboards.

### 1.3 Content-Addressable Storage (SHA-256 Dedup)

The existing design includes `content_hash TEXT NOT NULL` on `prompt_versions`, computed as SHA-256 of the body. This is the right approach.

**How it works (git-like model):**

1. On version creation, compute `SHA-256(body)`.
2. Check if any existing version for this prompt has the same hash.
3. If yes: reject the creation ("no-op version") or return the existing version. This prevents accidental duplicate versions from concurrent human edits or optimizer runs producing identical output.
4. If no: insert the new version.

```sql
-- Check for duplicate content before inserting
SELECT id, version FROM prompt_versions
WHERE prompt_id = $1 AND content_hash = $2;
```

**Index for hash lookups:**

```sql
CREATE INDEX idx_versions_content_hash
  ON prompt_versions(prompt_id, content_hash);
```

**Important considerations:**

- Hash the normalized body (strip trailing whitespace, normalize newlines) to catch semantically identical content with superficial formatting differences.
- The hash serves a dedup function, not a security function. SHA-256 is appropriate; no need for a more expensive hash.
- Store the hash as lowercase hex string (64 characters) for readability and consistency.
- Unlike git, do not use the hash as the primary key. UUIDs are better PKs because they are opaque and do not leak content information. The hash is a secondary index for dedup only.

### 1.4 Soft Deletes vs. Hard Deletes for Audit Trails

**Soft deletes (recommended):**

The `prompts` table uses `archived_at TIMESTAMPTZ` (NULL = active). This is the correct pattern for this system because:

1. **Referential integrity**: `metric_events`, `optimization_runs`, and `experiment_arms` all reference prompts and versions. Hard-deleting a prompt would require cascading deletes across the entire history, destroying audit data.
2. **Regulatory compliance**: Many organizations require audit trails of what content was served to users. Soft deletes preserve this.
3. **Undo capability**: Archiving is reversible. Set `archived_at = NULL` to restore.
4. **Query simplicity**: All active queries simply add `WHERE archived_at IS NULL`. The partial index `ON prompts(slug) WHERE archived_at IS NULL` ensures this filter is essentially free.

**When to hard delete:**

- `session_assignments` can be hard-deleted when an experiment concludes. These are operational data, not audit data. A scheduled cleanup job can purge them.
- `metric_events` older than a retention period (e.g., 90 days) can be hard-deleted or moved to cold storage. Use partitioning to make this efficient (see Section 3).

**Pattern for versions:**

Versions should never be deleted, even when their parent prompt is archived. They are immutable historical records. If storage becomes a concern, the body text of very old versions (beyond the retention window) can be moved to object storage (S3), leaving a stub with the `content_hash` as a pointer.

---

## 2. Experiment / A/B Testing Schemas

### 2.1 How Industry Systems Model Experiments

**LaunchDarkly model:**

LaunchDarkly separates the concepts of feature flags (the entity) and targeting rules (who sees what). Their core model is:
- **Flag**: Has a key (slug), variations (like our versions), and targeting rules.
- **Variation**: An ordered list of possible values. For prompts, each variation would be a version.
- **Targeting rule**: Conditions that map users to variations. Can be percentage-based, user-segment-based, or individual-user-based.
- **Fallthrough**: The default variation when no targeting rule matches. Percentage rollout is configured here.

Key insight: LaunchDarkly stores the percentage rollout as a list of `(variation_index, weight)` pairs that sum to 100000 (millipercent precision). Using integers instead of floats avoids floating-point rounding issues.

**Optimizely model:**

Optimizely uses a more traditional experiment model:
- **Experiment**: Has a status (running, paused, archived), a list of variations, and traffic allocation.
- **Variation**: Each variation has a key and a set of variable values.
- **Traffic allocation**: A list of `(entity_id, end_of_range)` pairs where ranges are [0, 10000] (basis points).
- **Bucketing**: Users are hashed to a bucket [0, 10000] and assigned to the variation whose range they fall into.

Key insight: Deterministic bucketing via hashing (MurmurHash3 of `experiment_id + user_id`) gives sticky assignment without a database lookup. This is more scalable than a `session_assignments` table but less flexible (cannot reassign a user).

**GrowthBook model:**

GrowthBook uses a similar hash-based bucketing approach but adds:
- **Feature**: The top-level entity (like our prompt).
- **Experiment rule**: Attached to a feature, defines how traffic is split.
- **Namespace**: Allows multiple experiments on the same feature by partitioning the hash space. Experiment A gets hash range [0, 0.5), Experiment B gets [0.5, 1.0).

Key insight: Namespaces solve the "one active experiment per entity" constraint more elegantly than a database constraint. Multiple experiments can coexist on the same prompt if they partition the traffic space.

### 2.2 Weighted Routing Tables

**Recommended schema (integer weights in basis points):**

```sql
CREATE TABLE experiment_arms (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id   UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    version_id      UUID NOT NULL REFERENCES prompt_versions(id),
    weight_bps      INT NOT NULL CHECK (weight_bps >= 0 AND weight_bps <= 10000),
    label           TEXT,  -- 'control', 'variant-a', etc.
    is_control      BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Enforce: total weight per experiment <= 10000 basis points
-- This is best done as an application-level check within a transaction,
-- because CHECK constraints cannot reference other rows.
-- Alternative: a trigger.
```

Using integer basis points (0-10000) instead of float percentages (0.0-100.0) eliminates floating-point precision issues. 10000 = 100.00%. The remainder (10000 minus sum of weights) routes to the default/control version.

**Weight update pattern (atomic):**

```sql
-- Update multiple arm weights in a single statement
UPDATE experiment_arms
SET weight_bps = CASE id
    WHEN $arm_a_id THEN $new_weight_a
    WHEN $arm_b_id THEN $new_weight_b
END
WHERE id IN ($arm_a_id, $arm_b_id)
  AND experiment_id = $experiment_id;
```

This ensures atomicity without needing an explicit transaction for multi-arm weight updates.

### 2.3 Session Assignment Tables for Sticky Routing

**Database-backed sticky sessions (current design):**

```sql
CREATE TABLE session_assignments (
    session_id      TEXT NOT NULL,
    experiment_id   UUID NOT NULL REFERENCES experiments(id) ON DELETE CASCADE,
    arm_id          UUID NOT NULL REFERENCES experiment_arms(id),
    assigned_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, experiment_id)
);
```

This table grows linearly with the number of unique sessions. For a system processing 10,000 unique sessions per day across 5 experiments, that is 50,000 rows per day or roughly 18 million rows per year.

**Mitigation for table growth:**
- Add `ON DELETE CASCADE` from experiments so concluded experiments automatically clean up assignments.
- Scheduled cleanup: `DELETE FROM session_assignments WHERE experiment_id IN (SELECT id FROM experiments WHERE status = 'concluded' AND concluded_at < now() - INTERVAL '7 days')`.
- Partition by experiment_id if the table becomes very large (unlikely for most prompt management use cases).

**Hash-based sticky sessions (alternative, no database):**

```python
import hashlib

def deterministic_bucket(session_id: str, experiment_id: str) -> int:
    """Returns a bucket in [0, 10000) for consistent assignment."""
    key = f"{experiment_id}:{session_id}"
    h = hashlib.md5(key.encode()).hexdigest()
    return int(h[:8], 16) % 10000
```

Pros: No database writes for assignment. Infinitely scalable. Deterministic.
Cons: Cannot reassign a session. Cannot track assignment history. Weight changes affect existing sessions (users may see a different variant after a weight update).

**Recommendation**: Use database-backed sticky sessions for v1. The write volume is manageable for a prompt management system (which is not at ad-serving scale). The ability to track and audit assignments is valuable. Consider hash-based bucketing as a v2 optimization if the session_assignments table becomes a bottleneck.

### 2.4 Partial Unique Indexes for "One Active Experiment Per Entity"

This is one of the most elegant PostgreSQL patterns for enforcing business rules:

```sql
CREATE UNIQUE INDEX idx_one_running_experiment_per_prompt
  ON experiments(prompt_id)
  WHERE status = 'running';
```

This index:
- Allows unlimited `draft`, `paused`, and `concluded` experiments per prompt.
- Prevents inserting or updating a second experiment to `running` status for the same prompt.
- Is enforced at the database level, immune to application-level race conditions.
- Is tiny (only indexes rows where `status = 'running'`).

**Transitioning experiment status:**

```sql
-- Start an experiment (will fail if another is running for this prompt)
UPDATE experiments SET status = 'running', started_at = now()
WHERE id = $1 AND status = 'draft';
-- If another experiment is running, this raises a unique violation.
```

**Multi-experiment support (future, GrowthBook-style namespaces):**

If the system eventually needs multiple concurrent experiments per prompt, replace the partial unique index with namespace-based partitioning:

```sql
ALTER TABLE experiments ADD COLUMN namespace TEXT NOT NULL DEFAULT 'default';

CREATE UNIQUE INDEX idx_one_running_experiment_per_prompt_namespace
  ON experiments(prompt_id, namespace)
  WHERE status = 'running';
```

This allows one running experiment per prompt per namespace. Different namespaces partition the traffic space, so experiments in namespace "wording" and namespace "format" can run simultaneously without interfering.

---

## 3. High-Volume Metric/Event Storage in PostgreSQL

### 3.1 Time-Series Patterns: Partitioning by Time

The `metric_events` table is the highest-volume table in the system. It is append-only and queried primarily by time range, prompt, and experiment. This is a textbook case for declarative partitioning.

**Monthly range partitioning (recommended):**

```sql
CREATE TABLE metric_events (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL,
    version_id      UUID NOT NULL,
    experiment_id   UUID,
    arm_id          UUID,
    session_id      TEXT,
    metric_name     TEXT NOT NULL,
    metric_value    DOUBLE PRECISION NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, created_at)  -- partition key must be in PK
) PARTITION BY RANGE (created_at);

-- Create partitions
CREATE TABLE metric_events_2026_01 PARTITION OF metric_events
  FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE metric_events_2026_02 PARTITION OF metric_events
  FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
-- ... etc.
```

**Monthly vs. weekly partitioning:**

| Factor | Monthly | Weekly |
|--------|---------|--------|
| Partition count per year | 12 | 52 |
| Partition pruning effectiveness | Good for queries spanning days | Better for narrow time ranges |
| Maintenance overhead | Low | Higher (more DDL, more partitions to manage) |
| DROP speed for retention | Fast (drop one month) | Fast (drop one week) |

For a prompt management system (not an ad-tech or IoT system), monthly partitioning is the right granularity. The event volume is moderate (thousands to low millions per month), and queries typically aggregate over days or weeks.

**Automated partition creation:**

Use `pg_partman` extension or a cron job that creates future partitions ahead of time:

```sql
-- Create next 3 months of partitions
DO $$
DECLARE
  m INT;
  start_date DATE;
  end_date DATE;
BEGIN
  FOR m IN 0..2 LOOP
    start_date := date_trunc('month', now()) + (m || ' months')::INTERVAL;
    end_date := start_date + '1 month'::INTERVAL;
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS metric_events_%s PARTITION OF metric_events FOR VALUES FROM (%L) TO (%L)',
      to_char(start_date, 'YYYY_MM'), start_date, end_date
    );
  END LOOP;
END $$;
```

**Retention via partition drop:**

```sql
-- Drop data older than 6 months (instant, no vacuum needed)
DROP TABLE metric_events_2025_09;
```

This is vastly faster than `DELETE FROM metric_events WHERE created_at < '2025-10-01'`, which would leave dead tuples requiring vacuum.

### 3.2 BRIN Indexes vs. B-tree for Time-Range Queries

**BRIN (Block Range Index):**

BRIN indexes store summary information (min/max values) for ranges of physical table blocks. They are ideal when the physical order of rows correlates with the indexed column -- which is naturally the case for append-only tables ordered by `created_at`.

```sql
CREATE INDEX idx_metric_events_created_brin
  ON metric_events USING BRIN (created_at)
  WITH (pages_per_range = 32);
```

| Property | BRIN | B-tree |
|----------|------|--------|
| Index size (100M rows) | ~1 MB | ~2 GB |
| Time-range query speed | Good (scans some extra blocks) | Excellent (precise) |
| Insert overhead | Minimal | Moderate |
| Works with partitioning | Yes (per-partition) | Yes (per-partition) |

**When to use BRIN:**
- The table is append-only (rows arrive in chronological order).
- Queries filter on time ranges spanning hours or days (not single-second precision).
- The table has millions or billions of rows.
- You want to minimize index storage and write amplification.

**When to use B-tree:**
- You need exact point lookups by time.
- The physical row order does not correlate with `created_at` (unlikely for append-only tables).
- The table is small enough that B-tree overhead is negligible.

**Recommendation for this system:**

Use BRIN on `created_at` within each partition for broad time-range filtering. Use B-tree composite indexes for the specific query patterns:

```sql
-- Per-partition indexes (created automatically if defined on parent)
-- BRIN for time-range scans
CREATE INDEX idx_metric_created_brin ON metric_events USING BRIN (created_at);

-- B-tree for specific prompt+version queries within a time range
CREATE INDEX idx_metric_prompt_version
  ON metric_events(prompt_id, version_id, created_at DESC);

-- B-tree for experiment arm aggregation
CREATE INDEX idx_metric_experiment_arm
  ON metric_events(experiment_id, arm_id, metric_name, created_at DESC);
```

The composite B-tree indexes handle the two primary query patterns:
1. "What are the metrics for prompt X, version Y, in the last 24 hours?"
2. "What are the per-arm metrics for experiment E, metric M, in the last 7 days?"

Partition pruning handles the time range, and the B-tree handles the entity filtering within the pruned partition(s).

### 3.3 Aggregation Strategies

**Pre-computed rollups (recommended for dashboards):**

```sql
CREATE TABLE metric_rollups (
    prompt_id       UUID NOT NULL,
    version_id      UUID NOT NULL,
    experiment_id   UUID,
    arm_id          UUID,
    metric_name     TEXT NOT NULL,
    period          TEXT NOT NULL,  -- 'hour', 'day'
    period_start    TIMESTAMPTZ NOT NULL,
    count           BIGINT NOT NULL,
    sum             DOUBLE PRECISION NOT NULL,
    min             DOUBLE PRECISION NOT NULL,
    max             DOUBLE PRECISION NOT NULL,
    avg             DOUBLE PRECISION NOT NULL,
    p50             DOUBLE PRECISION,
    p95             DOUBLE PRECISION,
    p99             DOUBLE PRECISION,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (prompt_id, version_id, metric_name, period, period_start)
);
```

**Rollup computation (scheduled job, runs hourly):**

```sql
INSERT INTO metric_rollups (prompt_id, version_id, experiment_id, arm_id,
                            metric_name, period, period_start,
                            count, sum, min, max, avg, p50, p95, p99)
SELECT
    prompt_id, version_id, experiment_id, arm_id,
    metric_name,
    'hour',
    date_trunc('hour', created_at),
    COUNT(*),
    SUM(metric_value),
    MIN(metric_value),
    MAX(metric_value),
    AVG(metric_value),
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY metric_value),
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY metric_value),
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY metric_value)
FROM metric_events
WHERE created_at >= date_trunc('hour', now() - INTERVAL '1 hour')
  AND created_at < date_trunc('hour', now())
GROUP BY prompt_id, version_id, experiment_id, arm_id, metric_name,
         date_trunc('hour', created_at)
ON CONFLICT (prompt_id, version_id, metric_name, period, period_start)
DO UPDATE SET
    count = EXCLUDED.count,
    sum = EXCLUDED.sum,
    min = EXCLUDED.min,
    max = EXCLUDED.max,
    avg = EXCLUDED.avg,
    p50 = EXCLUDED.p50,
    p95 = EXCLUDED.p95,
    p99 = EXCLUDED.p99,
    updated_at = now();
```

**On-the-fly aggregation (for real-time and ad-hoc queries):**

For queries that need up-to-the-minute data (e.g., the optimization loop checking current performance), query raw `metric_events` directly with the appropriate indexes.

**Hybrid approach (recommended):**

- Dashboard and reporting endpoints read from `metric_rollups` (fast, pre-computed).
- The optimization loop reads from `metric_events` directly for the most recent window (e.g., last 2 hours) to get fresh data.
- Real-time experiment monitoring combines rollups (for historical context) with live queries (for the current period).

### 3.4 TimescaleDB vs. Plain PostgreSQL

**When TimescaleDB adds value:**

- Continuous aggregates (materialized views that auto-refresh incrementally).
- Compression (columnar compression for old partitions, 10-20x space savings).
- Retention policies (automatic partition drop by age).
- Hypertable abstraction (automatic partition management).
- Advanced time-series functions (time_bucket, interpolation, gap filling).

**When plain PostgreSQL is sufficient:**

- The event volume is moderate (under 10 million events per month).
- You need only basic aggregations (sum, avg, percentiles).
- You can manage partitions with a simple cron job or pg_partman.
- You want to minimize operational dependencies.

**Recommendation for this system:**

Start with plain PostgreSQL declarative partitioning. The event volume for a prompt management system is moderate -- even a high-traffic deployment is unlikely to exceed a few million events per month. PostgreSQL's native partitioning, BRIN indexes, and a simple hourly rollup job are sufficient.

Consider TimescaleDB if:
- The system grows to serve 100+ prompts with continuous experiments, generating tens of millions of events per month.
- You need compressed cold storage for metric history beyond 6 months.
- You want continuous aggregates instead of maintaining rollup jobs.

The migration path is non-disruptive: TimescaleDB's `create_hypertable` can convert an existing partitioned table.

### 3.5 COPY-Based Bulk Ingestion for Metric Events

The `POST /metrics/batch` endpoint should use PostgreSQL's `COPY` protocol for high-throughput ingestion, not individual `INSERT` statements.

**asyncpg's `copy_records_to_table` (recommended):**

```python
# asyncpg supports binary COPY natively
async def bulk_insert_metrics(pool, events: list[MetricEvent]):
    records = [
        (e.id, e.prompt_id, e.version_id, e.experiment_id, e.arm_id,
         e.session_id, e.metric_name, e.metric_value,
         json.dumps(e.metadata), e.created_at)
        for e in events
    ]
    async with pool.acquire() as conn:
        await conn.copy_records_to_table(
            'metric_events',
            records=records,
            columns=['id', 'prompt_id', 'version_id', 'experiment_id',
                     'arm_id', 'session_id', 'metric_name', 'metric_value',
                     'metadata', 'created_at'],
        )
```

**Performance comparison (approximate, 10,000 events):**

| Method | Time | Network round-trips |
|--------|------|-------------------|
| Individual INSERTs | ~5,000 ms | 10,000 |
| Batched INSERT (VALUES list) | ~200 ms | 1 |
| COPY (text mode) | ~50 ms | 1 (streaming) |
| COPY (binary mode via asyncpg) | ~30 ms | 1 (streaming) |

For the `[metric]` package's batched reporter, accumulate events in memory (configurable buffer size, e.g., 1000 events or 5 seconds) and flush via COPY. This handles metric storms gracefully.

---

## 4. Optimization Run Tracking

### 4.1 Modeling a "Propose - Review - Accept/Reject" Workflow

The optimization run lifecycle is a state machine:

```
                    ┌──────────┐
                    │ PENDING  │  (LLM called, proposal generated)
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
              ▼          ▼          ▼
        ┌──────────┐ ┌────────┐ ┌────────┐
        │ ACCEPTED │ │REJECTED│ │ FAILED │
        └────┬─────┘ └────────┘ └────────┘
             │
             ▼
        ┌──────────────┐
        │AUTO_DEPLOYED │  (if auto_deploy=true)
        └──────────────┘
```

**Recommended schema enhancement:**

```sql
CREATE TABLE optimization_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_id       UUID NOT NULL REFERENCES prompts(id),
    experiment_id   UUID REFERENCES experiments(id),

    -- Trigger context
    trigger         TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled', 'metric_threshold')),
    trigger_context JSONB DEFAULT '{}',  -- e.g., which metric crossed what threshold

    -- LLM details
    llm_provider    TEXT NOT NULL,
    llm_model       TEXT NOT NULL,
    llm_temperature REAL,
    llm_token_usage JSONB,  -- {input_tokens, output_tokens, cost_usd}

    -- Input state (snapshot at time of run)
    input_version_id UUID NOT NULL REFERENCES prompt_versions(id),
    input_metrics    JSONB NOT NULL,  -- Aggregated metrics at time of trigger

    -- LLM output
    proposed_body   TEXT NOT NULL,
    proposed_hash   TEXT NOT NULL,  -- SHA-256 of proposed_body
    llm_reasoning   TEXT,
    llm_raw_response TEXT,  -- Full LLM response for audit

    -- Review workflow
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'accepted', 'rejected', 'failed', 'auto_deployed')),
    reviewed_by     TEXT,            -- user ID or 'system' for auto
    reviewed_at     TIMESTAMPTZ,
    rejection_reason TEXT,

    -- Output (set when accepted/auto_deployed)
    output_version_id UUID REFERENCES prompt_versions(id),

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

-- Only one pending/running optimization per prompt at a time
CREATE UNIQUE INDEX idx_one_pending_optimization_per_prompt
  ON optimization_runs(prompt_id)
  WHERE status = 'pending';
```

Key additions over the original design:
- `input_version_id` (UUID FK) instead of `input_version` (INT) for unambiguous reference.
- `proposed_hash` for dedup against existing versions.
- `llm_raw_response` for full audit trail.
- `llm_token_usage` for cost tracking.
- `rejection_reason` for human reviewers to explain why a proposal was rejected.
- `trigger_context` to capture what specifically triggered the run.
- Partial unique index preventing concurrent pending optimizations.

### 4.2 Storing LLM Input/Output for Audit

Every optimization run should store enough information to fully reproduce the LLM call. This serves three purposes:

1. **Debugging**: When an optimization produces a bad prompt, you can examine exactly what the LLM was asked and what it returned.
2. **Cost tracking**: Token usage and cost per optimization run.
3. **Compliance**: Some organizations need to log all LLM interactions.

**What to store:**

| Field | Content | Storage |
|-------|---------|---------|
| `input_metrics` | Aggregated metrics snapshot | JSONB (structured) |
| `proposed_body` | The LLM's proposed prompt text | TEXT |
| `llm_reasoning` | The LLM's explanation of changes | TEXT |
| `llm_raw_response` | Full API response (JSON) | TEXT (can be large) |
| `llm_token_usage` | `{input_tokens, output_tokens, total_cost}` | JSONB |
| `trigger_context` | What triggered the run | JSONB |

**Separate table for LLM call details (if raw responses are large):**

```sql
CREATE TABLE optimization_llm_calls (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    optimization_run_id UUID NOT NULL REFERENCES optimization_runs(id) ON DELETE CASCADE,
    call_order          INT NOT NULL DEFAULT 1,  -- For multi-step optimizations

    -- Request
    request_messages    JSONB NOT NULL,  -- The full messages array sent to the LLM
    request_params      JSONB NOT NULL,  -- temperature, max_tokens, etc.

    -- Response
    response_raw        TEXT,            -- Full API response body
    response_content    TEXT,            -- Extracted content/text

    -- Metrics
    input_tokens        INT,
    output_tokens       INT,
    latency_ms          INT,
    cost_usd            NUMERIC(10, 6),

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

This separates the large raw response data from the core optimization run record, keeping the main table lean for queries.

### 4.3 Linking Optimization Runs to Created Versions

The linkage is straightforward:

```
optimization_runs.input_version_id  → prompt_versions.id  (what was optimized)
optimization_runs.output_version_id → prompt_versions.id  (what was created)
```

When an optimization run is accepted:

```sql
BEGIN;

-- 1. Create the new version
INSERT INTO prompt_versions (id, prompt_id, version, body, content_hash, parent_version, source, created_by)
VALUES ($new_id, $prompt_id, $next_version, $proposed_body, $proposed_hash,
        (SELECT version FROM prompt_versions WHERE id = $input_version_id),
        'optimization', 'system:optimizer');

-- 2. Update the optimization run
UPDATE optimization_runs
SET status = 'accepted',
    output_version_id = $new_id,
    reviewed_by = $reviewer,
    reviewed_at = now(),
    completed_at = now()
WHERE id = $run_id;

-- 3. Optionally update the prompt's current_version
UPDATE prompts SET current_version = $next_version, updated_at = now()
WHERE id = $prompt_id;

COMMIT;
```

The `source = 'optimization'` on the version and the `output_version_id` on the run create a bidirectional link. You can query:
- "What optimization run produced version X?" via `optimization_runs WHERE output_version_id = X`.
- "What version did optimization run Y produce?" via `optimization_runs.output_version_id`.
- "Full lineage of this prompt" via recursive `parent_version` chain on `prompt_versions`.

---

## 5. asyncpg Best Practices

### 5.1 Connection Pool Sizing

**Rule of thumb:**

```
pool_max = min(
    num_cpu_cores * 2 + effective_spindle_count,  -- PostgreSQL guideline
    max_connections / num_app_instances            -- Don't exceed PG limit
)
```

For a typical deployment:
- PostgreSQL `max_connections = 100` (default)
- 2 app server instances
- 4 CPU cores per instance

```
pool_max = min(4 * 2 + 1, 100 / 2) = min(9, 50) = 9 ≈ 10
```

**Recommended configuration:**

```python
pool = await asyncpg.create_pool(
    dsn=settings.database_url,
    min_size=2,       # Keep 2 warm connections (avoids cold-start latency)
    max_size=10,      # Scale up to 10 under load
    max_inactive_connection_lifetime=300,  # Close idle connections after 5 min
    command_timeout=30,  # Query timeout
    statement_cache_size=1024,  # Cache prepared statements (see 5.2)
)
```

**Separate pools for read and write paths (recommended for production):**

```python
read_pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=2, max_size=8)
write_pool = await asyncpg.create_pool(dsn=settings.database_url, min_size=1, max_size=4)
```

This prevents metric ingestion writes from starving prompt resolve reads. The resolve hot path uses the read pool; metric batch inserts, version creation, and optimization runs use the write pool.

### 5.2 Prepared Statements

asyncpg automatically prepares statements on first use and caches them. This is one of the reasons asyncpg is faster than other PostgreSQL drivers.

**How it works:**

```python
# asyncpg automatically prepares this on first call
row = await conn.fetchrow(
    'SELECT body FROM prompt_versions WHERE prompt_id = $1 AND version = $2',
    prompt_id, version
)
# Second call with same SQL text reuses the prepared statement
```

**Best practices:**

1. **Use parameterized queries everywhere** (`$1`, `$2`, etc.). asyncpg can only cache parameterized queries.
2. **Avoid dynamic SQL** (string concatenation of query parts). Each unique SQL string creates a new prepared statement, polluting the cache.
3. **Set appropriate cache size**: `statement_cache_size=1024` (default is 1024, which is sufficient for most applications).
4. **Be aware of schema changes**: Prepared statements cache the query plan, including column types. After `ALTER TABLE`, stale prepared statements may fail. Call `await conn.reset()` or restart the pool after migrations.

**When to manually prepare:**

For the resolve hot path (called on every request), explicit preparation can save one round-trip on the first call per connection:

```python
async def init_connection(conn):
    """Called for each new connection in the pool."""
    await conn.prepare(
        'SELECT pv.body, pv.version, pv.content_hash, pv.template_vars '
        'FROM prompts p '
        'JOIN prompt_versions pv ON pv.prompt_id = p.id AND pv.version = p.current_version '
        'WHERE p.slug = $1 AND p.archived_at IS NULL'
    )

pool = await asyncpg.create_pool(
    dsn=settings.database_url,
    init=init_connection,  # Called for each new connection
)
```

### 5.3 LISTEN/NOTIFY for Real-Time Updates

PostgreSQL's LISTEN/NOTIFY provides a lightweight pub/sub mechanism. It is useful for:

1. **Cache invalidation**: When a new version is created, notify all API instances to invalidate their prompt cache.
2. **Experiment state changes**: When an experiment starts or concludes, notify connected clients.
3. **Optimization results**: When an optimization run completes, notify the admin dashboard.

**Setup:**

```sql
-- Trigger that fires NOTIFY on version creation
CREATE OR REPLACE FUNCTION notify_version_created()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        'prompt_updated',
        json_build_object(
            'prompt_id', NEW.prompt_id,
            'version', NEW.version,
            'source', NEW.source
        )::TEXT
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_version_created
AFTER INSERT ON prompt_versions
FOR EACH ROW EXECUTE FUNCTION notify_version_created();
```

**asyncpg listener:**

```python
async def setup_listeners(pool):
    conn = await pool.acquire()
    await conn.add_listener('prompt_updated', on_prompt_updated)
    # Important: this connection is now dedicated to listening.
    # Do NOT release it back to the pool or use it for queries.

async def on_prompt_updated(conn, pid, channel, payload):
    data = json.loads(payload)
    prompt_id = data['prompt_id']
    # Invalidate cache for this prompt
    cache.invalidate(prompt_id)
```

**Important caveats:**

- LISTEN/NOTIFY is per-connection. The listening connection must remain open and idle. Allocate a dedicated connection outside the pool for this purpose.
- NOTIFY payload is limited to 8000 bytes. Send only identifiers, not full data.
- NOTIFY is transactional: the notification is sent only when the transaction commits.
- If the listener disconnects, notifications sent during the disconnection are lost. This is acceptable for cache invalidation (the cache will eventually expire via TTL) but not for critical state changes.

### 5.4 Transaction Isolation Levels for Concurrent Experiments

**Default: READ COMMITTED (sufficient for most operations)**

PostgreSQL's default isolation level. Each statement within a transaction sees the most recently committed data. This is fine for:
- Prompt CRUD operations
- Metric event insertion
- Experiment arm weight reads for routing (eventual consistency is acceptable)

**REPEATABLE READ (recommended for optimization runs)**

Within a REPEATABLE READ transaction, all statements see a consistent snapshot as of the transaction start. Use this for the optimization workflow:

```python
async with pool.acquire() as conn:
    async with conn.transaction(isolation='repeatable_read'):
        # 1. Read current metrics -- sees consistent snapshot
        metrics = await conn.fetch(
            'SELECT ... FROM metric_events WHERE prompt_id = $1 AND created_at > $2',
            prompt_id, cutoff
        )
        # 2. Read current version -- same snapshot
        version = await conn.fetchrow(
            'SELECT * FROM prompt_versions WHERE prompt_id = $1 AND version = $2',
            prompt_id, current_version
        )
        # 3. Call LLM (outside the transaction would be better, see below)
        # 4. Create new version
        # If another transaction created a version with the same number,
        # this transaction will be aborted with a serialization error.
```

**SERIALIZABLE (use sparingly)**

Full serializability. Use only for:
- Version number assignment: `SELECT MAX(version) + 1 FROM prompt_versions WHERE prompt_id = $1 FOR UPDATE`.
- Experiment status transitions (draft -> running) where the partial unique index prevents conflicts.

In practice, the `FOR UPDATE` lock on the prompt row is sufficient for version number serialization, and the partial unique index handles experiment conflicts. Full SERIALIZABLE isolation is rarely needed.

**Pattern for optimization runs (claim-then-execute):**

The LLM call takes seconds. Holding a database transaction open during the LLM call wastes a connection and risks timeouts. Use a claim pattern instead:

```python
# Step 1: Claim the optimization slot (fast, in a transaction)
async with pool.acquire() as conn:
    async with conn.transaction():
        run_id = await conn.fetchval(
            "INSERT INTO optimization_runs (prompt_id, status, ...) "
            "VALUES ($1, 'running', ...) RETURNING id",
            prompt_id
        )
        # The partial unique index prevents concurrent claims

# Step 2: Call LLM (no transaction, no connection held)
proposal = await call_llm(prompt_text, metrics)

# Step 3: Write result (fast, in a transaction)
async with pool.acquire() as conn:
    async with conn.transaction():
        # Verify the run is still valid (not cancelled)
        status = await conn.fetchval(
            "SELECT status FROM optimization_runs WHERE id = $1",
            run_id
        )
        if status != 'running':
            return  # Cancelled while LLM was thinking

        # Create version and update run
        await conn.execute(...)
```

This pattern minimizes connection and lock holding time.

---

## 6. Consolidated Schema Recommendations

### 6.1 Summary of Recommendations

| Area | Recommendation | Rationale |
|------|---------------|-----------|
| Versioning | Append-only version table with `current_version` pointer | Immutability, rich metadata, clean lineage |
| Latest version query | Covering indexes on slug and (prompt_id, version) | Index-only scans for the hot path |
| Content dedup | SHA-256 content_hash, reject duplicate content | Prevent no-op versions |
| Deletes | Soft delete (archived_at) for prompts; never delete versions | Audit trail, referential integrity |
| Experiment weights | Integer basis points (0-10000) | Avoid floating-point issues |
| One active experiment | Partial unique index on `(prompt_id) WHERE status = 'running'` | Database-enforced invariant |
| Sticky sessions | Database-backed session_assignments table | Auditability, flexibility |
| Metric storage | Monthly range partitioning on created_at | Fast retention management, partition pruning |
| Metric indexes | BRIN on created_at, B-tree composites for entity+time queries | Balance write overhead and read performance |
| Aggregation | Pre-computed hourly rollups + live queries for recent data | Fast dashboards, fresh optimization data |
| Bulk ingestion | asyncpg COPY protocol for metric batches | 100x faster than individual INSERTs |
| Optimization workflow | Claim-then-execute pattern with partial unique index | Prevent concurrent runs, minimize lock time |
| LLM audit | Separate optimization_llm_calls table for raw responses | Keep main table lean, full audit trail |
| Connection pool | Separate read/write pools, min_size=2, max_size=10 | Isolation between hot path and background work |
| Real-time updates | LISTEN/NOTIFY for cache invalidation | Low-latency propagation, no polling |
| Isolation levels | READ COMMITTED default, REPEATABLE READ for optimization | Balance consistency and performance |

### 6.2 Extension Recommendations

| Extension | Purpose | When to Add |
|-----------|---------|-------------|
| `pg_partman` | Automated partition management | When manual partition creation becomes tedious |
| `pg_stat_statements` | Query performance monitoring | Always (low overhead, high value) |
| `pgcrypto` | `gen_random_uuid()` | Required for UUID PKs |
| `timescaledb` | Advanced time-series features | If metric volume exceeds 10M events/month |
| `pg_trgm` | Fuzzy text search on prompt slugs/names | If search functionality is needed |

### 6.3 Migration Strategy

Use Alembic with asyncpg dialect. Key migrations in order:

1. **001_initial_schema**: Core tables (prompts, prompt_versions, experiments, experiment_arms, session_assignments)
2. **002_metric_events_partitioned**: Partitioned metric_events table with initial partitions
3. **003_metric_rollups**: Rollup table and indexes
4. **004_optimization_runs**: Optimization tracking tables (optimization_runs, optimization_llm_calls)
5. **005_covering_indexes**: Covering indexes for the hot path
6. **006_listen_notify_triggers**: NOTIFY triggers for cache invalidation

Each migration should be backward-compatible and deployable without downtime. Use `CREATE INDEX CONCURRENTLY` for index creation on populated tables.
