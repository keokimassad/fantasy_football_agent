# Fantasy Football Agent

A Python 3.12 fantasy-football draft decision-support system built around a deterministic-first architecture. Draft state, roster accounting, player availability, tier analysis, snake-draft lookahead, Yahoo synchronization, candidate evaluation, and strategy inputs are handled by deterministic code. A private Custom GPT reasons over a versioned `DraftDecisionPacket` through a read-only HTTPS gateway without becoming the source of draft truth.

The project is **live-draft validated**. After repeated Yahoo mock-draft acceptance tests, the complete system was used during a real 10-team, 15-round Yahoo Fantasy Football snake draft on September 7, 2026. The draft reached `COMPLETE` with all 150 league selections synchronized and all required roster positions filled.

The core rule is:

> **AI may reason about draft state, but it should not invent draft state.**

## What It Does

- Loads and validates league configuration, draft strategy, rankings, market overrides, and persisted draft state.
- Creates fresh mock or actual draft sessions with an explicit draft slot.
- Models snake-draft ownership, including round turns and consecutive user selections.
- Tracks team rosters, FLEX accounting, open starter slots, remaining selections, and optional bench capacity.
- Uses Yahoo Player ID as the preferred stable player identity.
- Supports manually curated position tiers alongside Yahoo rank and ADP.
- Applies audited ADP `VALID` / `IGNORE` / `OVERRIDE` policy without mutating the source ranking snapshot.
- Calculates tier depth, tier drops, scarcity flags, market timing, opponent exposure, and return/loss risk.
- Builds a deterministic candidate ordering and a versioned, JSON-compatible `DraftDecisionPacket`.
- Preserves each AI-visible candidate's independent `baseline_rank` so saved strategy never silently rewrites the deterministic baseline.
- Uses phase-aware candidate horizons for `WAITING`, `ON_CLOCK`, consecutive turns, and `COMPLETE`.
- Safely reconciles overlapping Yahoo history and detects missing-pick gaps, conflicts, duplicates, and ambiguous player identities.
- Persists successful selections incrementally so later failures do not discard verified progress.
- Fails closed after synchronization errors so stale state cannot produce CLI or gateway recommendations.
- Exposes the current packet through a bearer-authenticated, read-only FastAPI/OpenAPI gateway.
- Supports a private Custom GPT Action that refreshes authoritative state before current-draft recommendations.
- Keeps the deterministic CLI as the required low-latency fallback if the gateway, tunnel, Action, or model is unavailable.
- Automatically records append-only JSONL telemetry with synchronization input/results, deterministic state, exact CLI/gateway packets, runtime provenance, and source snapshots.

## Architecture

```text
Yahoo draft input / local config / rankings
                  |
                  v
      synchronization + identity resolution
                  |
                  v
       persisted deterministic draft state
                  |
                  v
       deterministic candidate evaluation
                  |
                  v
       versioned DraftDecisionPacket
                  |
                  v
       read-only FastAPI/OpenAPI gateway
                  |
                  v
             private Custom GPT
                  |
                  v
      strategy / tradeoff explanation
                  |
                  v
             user final decision

normal draft workflow -----------------------> append-only JSONL telemetry
```

Yahoo-specific parsing, synchronization, authentication, gateway behavior, and model-facing integration remain outside the deterministic draft engine. This keeps the core testable without network access, preserves a complete deterministic fallback, and allows the AI layer to evolve without weakening factual draft-state integrity.

See [`docs/architecture.md`](docs/architecture.md) for the detailed component and authority boundaries.

## Live-Draft Validation — September 7, 2026

The 2026 draft cycle culminated in a real Yahoo draft using the same deterministic engine, strategy configuration, gateway, Custom GPT Action, and observability path exercised in mocks.

```text
Platform:        Yahoo Fantasy Football
Format:          10-team, 15-round snake
Scoring:         0.5 PPR
Draft slot:      10
Pick clock:      90 seconds
League picks:    150
Final phase:     COMPLETE
```

The live draft validated more than recommendation quality. It exercised state recovery, turn-pair reasoning, specialist timing, gateway/model fallback, append-only audit logging, and fail-closed reconciliation when copied Yahoo ranges were incomplete.

A major production discovery was that Yahoo Draft Chat did **not** expose selection messages consistently across the live clients being used. The draft continued by copying Yahoo's Results view instead. The existing structural parser successfully handled those numeric selection blocks, while the synchronizer correctly rejected ranges that skipped the next locally expected pick. Yahoo Results is therefore a validated emergency input from this draft, but it is not yet modeled as a dedicated first-class adapter.

The sanitized public postmortem and final draft snapshot are available at:

- [`docs/postmortems/2026-live-draft.md`](docs/postmortems/2026-live-draft.md)
- [`docs/live_draft/2026-final-state.json`](docs/live_draft/2026-final-state.json)

Raw production draft logs remain private because telemetry intentionally preserves copied Yahoo input and may contain league-member chat/usernames and other source material.

## Project Structure

```text
fantasy_football_agent/
├── .github/
│   └── workflows/
│       └── ci.yml
├── config/
│   ├── draft_strategy.example.json
│   ├── draft_strategy.json
│   ├── draft_strategy_archive/
│   └── league.example.json
├── data/
│   ├── draft_state.example.json
│   ├── player_overrides.example.json
│   ├── player_overrides_2026.json
│   ├── yahoo_rankings.example.csv
│   └── yahoo_rankings_2026.csv
├── docs/
│   ├── architecture.md
│   ├── live-draft-runbook.md
│   ├── live_draft/
│   │   └── 2026-final-state.json
│   ├── postmortems/
│   │   └── 2026-live-draft.md
│   └── custom_gpt/
│       ├── README.md
│       ├── instructions.md
│       └── yahoo_auto_draft_2026.md
├── scripts/
│   └── check_yahoo_connection.py
├── src/
│   └── fantasy_football_agent/
│       ├── application_paths.py
│       ├── observability.py
│       ├── cli/
│       │   ├── draft_analyzer.py
│       │   ├── draft_creator.py
│       │   └── draft_updater.py
│       ├── draft/
│       │   ├── analysis.py
│       │   ├── decision_packet.py
│       │   ├── market_overrides.py
│       │   ├── models.py
│       │   ├── rankings.py
│       │   ├── recommendations.py
│       │   ├── session.py
│       │   ├── state.py
│       │   └── sync_status.py
│       ├── gateway/
│       │   ├── app.py
│       │   └── service.py
│       └── yahoo/
│           ├── draft_chat.py
│           ├── draft_sync.py
│           ├── yahoo_client.py
│           └── yahoo_config.py
├── tests/
├── tools/
│   └── check_test_docstrings.py
├── .pre-commit-config.yaml
├── DEVELOPMENT.md
├── pyproject.toml
└── README.md
```

Secrets and ephemeral runtime files such as `oauth2.json`, the active league configuration, active draft state, synchronization status, raw Yahoo input, and draft logs are intentionally ignored by Git. Reproducible decision inputs such as the active draft strategy, named strategy snapshots, tracked ranking inputs, and player overrides are version controlled.

## Setup

Create and activate a Python 3.12 virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install the project and development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Create the local league configuration from its sanitized example:

```bash
cp config/league.example.json config/league.json
```

The repository contains tracked decision inputs for the 2026 draft cycle. Their `*.example` counterparts document schemas and should not replace active files during normal setup. A draft-state file should normally be created with `ff-draft-new` rather than copied manually.

Keep `config/league.json` specific to league facts. User-controlled drafting philosophy lives in `config/draft_strategy.json`, including position-roster targets and reusable soft preferences. Those preferences are exposed to the Custom GPT as a strategy overlay and never mutate deterministic recommendation ordering.

### Local Market-Data Overrides

`data/player_overrides_2026.json` is the tracked active exception file for market data that became stale after the Yahoo/ADP snapshot was captured.

Supported ADP policies are:

```text
VALID      use source ADP normally
IGNORE     preserve source ADP for auditability but exclude it from current market calculations
OVERRIDE   preserve source ADP and use an explicitly supplied replacement ADP
```

Each override is keyed by Yahoo Player ID and carries a reason and `as_of` date. The deterministic packet exposes both effective `adp` and historical `source_adp` plus override metadata so the reasoning layer can explain the distinction without resurrecting stale ADP as current evidence.

## Starting a Draft Session

Create a mock draft:

```bash
ff-draft-new --type mock --slot 4 --workspace .
```

Create the actual league draft once the slot is known:

```bash
ff-draft-new --type actual --slot <YOUR_SLOT> --workspace .
```

An existing active `draft_state.json` is protected unless replacement is explicit:

```bash
ff-draft-new --type mock --slot 7 --replace --workspace .
```

Do not recreate or replace an actual draft after selections have started. Active state is persisted under `data/draft_state.json` and should be recovered rather than reset.

## Synchronizing Yahoo Draft State

The current CLI option is named `--yahoo-chat` because Draft Chat was the original integration format:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

The parser processes numeric Yahoo selection blocks and ignores unrelated text. It supports overlapping pasted history, so copying a generous recent range is safe.

For each parsed selection:

- an already-recorded pick is verified against local state;
- the exact next pick is resolved and recorded;
- a future pick that skips expected history produces a synchronization error;
- a conflicting historical pick stops synchronization rather than overwriting state;
- ambiguous Yahoo abbreviations require explicit resolution; and
- successful new picks are persisted before later selections are processed.

The real 2026 draft showed that Yahoo Results can provide usable numeric selection blocks when Draft Chat is unavailable. A future source-neutral ingestion interface with explicit Draft Chat and Results adapters is the highest-priority draft-sync improvement.

## Draft Analysis and Live Workflow

Run deterministic analysis with:

```bash
ff-draft --workspace .
```

For live use, synchronization and analysis should be chained so a failed sync cannot be followed by stale analysis:

```bash
ffmock() {
  pbpaste | ff-draft-update --yahoo-chat --workspace . && \
    ff-draft --workspace .
}
```

The normal draft-day stack consists of the deterministic CLI/synchronizer, `ff-gateway`, an HTTPS tunnel, the Yahoo draft UI, and the private Custom GPT. Detailed startup and failure-recovery steps live in [`docs/live-draft-runbook.md`](docs/live-draft-runbook.md).

## Automatic Draft Telemetry

No extra command is required during a mock or actual draft. The normal create/sync/analyze/GPT workflow appends JSONL events under:

```text
data/draft_logs/<draft-id>.jsonl
```

The first event snapshots non-secret inputs needed for later reproduction, including league config, rankings, player overrides, version-controlled Custom GPT instructions/knowledge, Python version, and Git revision. Runtime events record exact Yahoo text supplied to synchronization, pre/post-sync state, synchronization failures, manual corrections/undo, CLI packets, gateway packets, and stale-state blocks.

`data/draft_logs/` remains ignored by Git. This is intentional: raw Yahoo text is valuable for local debugging but can include league-member chat/usernames, and source snapshots can duplicate externally derived datasets. Credentials and OAuth files are not captured.

For public portfolio evidence, publish a **sanitized derived artifact** rather than the raw production log. The 2026 example is [`docs/live_draft/2026-final-state.json`](docs/live_draft/2026-final-state.json).

## Private Custom GPT Integration

The private Custom GPT consumes the deterministic `DraftDecisionPacket` through a read-only gateway. It does not own draft state and cannot modify selections.

Version-controlled provider material lives under [`docs/custom_gpt/`](docs/custom_gpt/). The Action boundary exposes:

```text
GET /health
GET /v1/draft/decision
GET /openapi.json
```

`/v1/draft/decision` is bearer authenticated. The GPT instructions require a fresh deterministic call for current-draft decisions, restrict recommendations to packet candidates, preserve baseline-vs-strategy disagreement, and require deterministic fallback if the Action cannot retrieve current state.

The decision packet uses different candidate frontiers by phase:

- `WAITING` expands its market horizon with the selections before the user's next decision;
- ordinary `ON_CLOCK` remains compact while preserving useful positional breadth;
- consecutive snake turns set `context.consecutive_turn=true` and expose a broader two-pick frontier; and
- `COMPLETE` prevents further draft recommendations.

## Yahoo OAuth

Yahoo API access is optional for the deterministic/manual-ingestion draft workflow. A local `oauth2.json` may be placed in the workspace root for API integration and must never be committed.

OAuth path precedence is:

```text
explicit path
    ↓
YAHOO_OAUTH_FILE
    ↓
<workspace>/oauth2.json
```

To manually exercise the Yahoo API boundary when valid credentials and Fantasy Sports API access are available:

```bash
python scripts/check_yahoo_connection.py
```

Unit tests do not require Yahoo credentials or network access.

## Quality and Testing

The project uses Ruff, strict mypy, pytest, branch-aware pytest-cov, pre-commit, GitHub Actions, and an AST-based behavioral test-documentation check.

Tests cover meaningful system boundaries including snake ownership/turns, FLEX and roster accounting, identity resolution, persistence/undo, Yahoo parsing and reconciliation, ambiguity/overlap/gap/conflict behavior, recommendation ordering, strategy context, phase-aware decision packets, specialist visibility, ADP overrides, observability, gateway authentication/read-only behavior, and Yahoo OAuth boundaries without live network calls.

The repository enforces a minimum of **90% branch-aware test coverage**. At a late-stage pre-draft quality gate, 267 tests passed along with Ruff, strict mypy, and test-documentation validation; the exact current test count may evolve after that milestone.

Development commands and targeted test workflows are documented in [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Data and Privacy

Public source control should contain code, documentation, sanitized examples, and intentionally tracked decision inputs only. Keep OAuth credentials, active league state, raw Yahoo settings, draft logs, copied chat text, gateway/tunnel secrets, and other runtime artifacts local.

The real 2026 `draft_state.json` should **not** be unignored merely to archive one season. A frozen sanitized copy belongs under documentation, while the active runtime path should remain ignored so a future draft cannot be accidentally committed.

The raw 2026 JSONL should likewise remain private. It does not contain the gateway/Yahoo credentials in the captured session, but it does contain copied Yahoo source text and participant identifiers/chat, and its session manifest embeds complete source snapshots. Keep the raw file in a private personal backup if long-term historical preservation is desired.

If external ranking or league data is stored or redistributed, the user remains responsible for the applicable source terms and permissions.

## Current Status

The 2026 draft cycle is complete and the project is **live-draft validated**:

- deterministic candidate evaluation and strategy-aware AI reasoning were exercised across repeated Yahoo mocks;
- the bearer-authenticated FastAPI/OpenAPI gateway and private Custom GPT Action were used end to end;
- `WAITING`, `ON_CLOCK`, consecutive-turn, and `COMPLETE` behavior were exercised;
- the deterministic CLI remained available as the operational fallback;
- the real draft synchronized all 150 league selections and reached `COMPLETE`;
- fail-closed gap detection prevented incomplete Yahoo Results ranges from corrupting draft state; and
- production telemetry preserved enough state and packet history for post-draft reconstruction.

No immediate recommendation-engine retuning is planned from isolated draft outcomes. The real and mock histories are now calibration datasets for future work.

## Roadmap

### Completed — 2026 Draft Cycle

- deterministic draft state, roster accounting, and snake lookahead;
- stable Yahoo player identity and synchronization/reconciliation;
- tier/scarcity and market-timing analysis;
- deterministic candidate evaluation;
- explicit draft-strategy configuration with independent baseline ranking;
- versioned `DraftDecisionPacket` and phase-aware candidate frontiers;
- FastAPI/OpenAPI read-only gateway;
- private Custom GPT decision layer;
- Yahoo auto-draft research/knowledge with human-vs-auto guardrails;
- append-only observability with source/runtime provenance;
- repeated live Yahoo mock-draft acceptance testing; and
- successful real-draft use on September 7, 2026.

### Next — Season and 2027 Draft Cycle

1. Create a source-neutral Yahoo ingestion boundary with first-class Draft Chat and Results adapters.
2. Build an audit/query interface over existing JSONL history rather than adding duplicate logging.
3. Add selection provenance such as system-recommended, user-override, user-predecided, auto-drafted, or unknown.
4. Add separately sourced, timestamped player-role/depth-chart context where reliable data exists.
5. Calibrate marginal bench-slot utility for QB2/TE2 and realized candidate return risk from mock/real history.
6. Improve opponent human/auto classification before applying Yahoo auto-draft tendencies more strongly.
7. Extend the same deterministic-first architecture into in-season lineup, waiver, trade, and roster-management workflows.

The long-term goal remains an agentic fantasy-football assistant whose reasoning can evolve without weakening the reliability of its underlying state, audit trail, or deterministic fallback.
