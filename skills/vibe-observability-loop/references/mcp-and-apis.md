# Connecting Live Data Sources (MCP Servers & Read-Only APIs)

Choose either **MCP servers** (interactive queries inside your AI agent) or the
bundled **`scripts/pull_signals.py`** CLI (zero MCP context overhead, works in
any shell or scheduled automation).

---

## Option A: Read-Only Signal Puller (`scripts/pull_signals.py`)

Create **read-only** API credentials (never use org-admin or write tokens) and
export only the providers you use:

```bash
# Sentry (Project/Org Read-Only Auth Token: event:read, project:read)
export SENTRY_AUTH_TOKEN="sntrys_..."
export SENTRY_ORG="your-org-slug"
export SENTRY_PROJECT="your-project-slug"
# Optional for EU/self-hosted Sentry:
# export SENTRY_BASE_URL="https://de.sentry.io"

# PostHog (Personal API Key with read-only query scope)
export POSTHOG_PERSONAL_API_KEY="phx_..."
export POSTHOG_PROJECT_ID="12345"
export POSTHOG_HOST="https://us.posthog.com" # or https://eu.posthog.com
```

Run the puller to generate a compact Markdown or JSON brief:

```bash
python3 skills/vibe-observability-loop/scripts/pull_signals.py --days 7
python3 skills/vibe-observability-loop/scripts/pull_signals.py --days 7 --json
# Also analyze local Python scraper/job JSONL summaries:
python3 skills/vibe-observability-loop/scripts/pull_signals.py --days 7 --job-history ./logs/runs.jsonl
```

---

## Option B: Live MCP Servers (Interactive Deep Dives)

### 1. Sentry MCP
- **Antigravity**: Install the official **Sentry** partner plugin from the
  Marketplace (bundles Sentry MCP + expert skills).
- **Claude Code / Cursor / Codex** (remote OAuth MCP):
  ```json
  {
    "mcpServers": {
      "sentry": {
        "url": "https://mcp.sentry.dev/mcp"
      }
    }
  }
  ```

### 2. PostHog MCP
- Official hosted MCP (OAuth or Personal API Key with read scopes):
  ```json
  {
    "mcpServers": {
      "posthog": {
        "url": "https://mcp.posthog.com/mcp",
        "headers": {
          "Authorization": "Bearer ${POSTHOG_PERSONAL_API_KEY}"
        }
      }
    }
  }
  ```

### 3. Microsoft Clarity
Clarity's Data Export API allows up to 10 read requests/day per project
(`GET https://www.clarity.ms/export-data/api/v1/project-live-insights?numOfDays=3`
with `Authorization: Bearer <CLARITY_API_TOKEN>`), or simply paste a weekly
Rage Click / Dead Click / Quick Back screenshot or CSV into chat.

### 4. Pigsty / Prometheus & `pgmq`
Query Pigsty's Prometheus HTTP API or paste key SQL snapshots:
- `pgmq` backlog & age:
  ```sql
  SELECT queue_name, queue_length, oldest_msg_age_sec, total_messages
  FROM pgmq.metrics_all();
  ```
- Slowest PostgreSQL queries (`pg_stat_statements`):
  ```sql
  SELECT left(query, 120) AS query, calls, round(mean_exec_time::numeric, 2) AS mean_ms
  FROM pg_stat_statements
  ORDER BY total_exec_time DESC
  LIMIT 10;
  ```
