# Fantasy Football Agent

A Python 3.12 fantasy-football draft assistant built around a deterministic-first architecture. Draft state, roster accounting, player availability, tier analysis, snake-draft lookahead, Yahoo draft synchronization, and candidate evaluation are handled by deterministic code. A private Custom GPT can then reason over a versioned `DraftDecisionPacket` through a read-only HTTPS gateway without becoming the source of draft truth.

The project is currently **AI-assisted mock-draft ready**: Yahoo mock drafts can be synchronized from copied draft chat, analyzed deterministically, and exposed to the private Custom GPT for phase-aware recommendations while the deterministic CLI remains the fallback.

## What It Does

- Loads and validates league configuration and persisted draft state.
- Creates fresh mock or actual draft sessions with an explicit draft slot.
- Models snake-draft ownership, including round turns.
- Tracks team rosters and open starter slots, including FLEX overflow.
- Loads ranked players and determines which players remain available.
- Uses Yahoo Player ID as the preferred stable player identity.
- Supports optional manual player tiers alongside Yahoo rank and ADP.
- Calculates tier depth, tier drops, scarcity flags, and tier coverage.
- Builds active lookahead windows between the current pick and the user's next turn.
- Estimates position exposure from opponents drafting inside that window.
- Parses copied Yahoo draft-chat selections.
- Resolves Yahoo-style abbreviated player names using position, NFL team, bye week, and Yahoo Player ID.
- Safely reconciles copied Yahoo history with existing local draft state.
- Detects overlapping history, missing-pick gaps, conflicts, and ambiguous player identities.
- Persists successful new selections incrementally so later failures do not discard earlier work.
- Supports manual pick entry and undo.
- Isolates Yahoo OAuth/client code behind a dedicated integration boundary.
- Exposes draft creation, synchronization/update, and analysis through command-line entry points.
- Builds a versioned, JSON-compatible `DraftDecisionPacket` for downstream AI reasoning.
- Exposes the current packet through a bearer-authenticated, read-only FastAPI gateway.
- Supports a private Custom GPT Action that refreshes deterministic state before current-draft decisions.

## Architecture

```text
Yahoo Draft Chat / local config / rankings
        ↓
deterministic draft state
        ↓
deterministic candidate evaluation
        ↓
versioned DraftDecisionPacket
        ↓
read-only HTTPS gateway
        ↓
private Custom GPT Action
        ↓
AI recommendation / tradeoff reasoning
        ↓
user final decision
```

The core rule is:

> **AI may reason about draft state, but it should not invent draft state.**

Yahoo-specific parsing, synchronization, authentication, gateway behavior, and model-facing integration remain outside the deterministic draft engine. This keeps the core testable without network access, preserves a complete deterministic fallback, and allows the AI layer to evolve without weakening factual draft-state integrity.

## Project Structure

```text
fantasy_football_agent/
├── .github/
│   └── workflows/
│       └── ci.yml
├── config/
│   └── league.example.json
├── data/
│   ├── draft_state.example.json
│   └── yahoo_rankings.example.csv
├── docs/
│   └── custom_gpt/
│       ├── README.md
│       ├── instructions.md
│       └── yahoo_auto_draft_2026.md
├── scripts/
│   └── check_yahoo_connection.py
├── src/
│   └── fantasy_football_agent/
│       ├── application_paths.py
│       ├── cli/
│       │   ├── draft_analyzer.py
│       │   ├── draft_creator.py
│       │   └── draft_updater.py
│       ├── draft/
│       │   ├── analysis.py
│       │   ├── decision_packet.py
│       │   ├── models.py
│       │   ├── rankings.py
│       │   ├── session.py
│       │   └── state.py
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

Local runtime files such as `oauth2.json`, the active league configuration, current draft state, and full ranking data are intentionally ignored by Git.

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

Create local working copies of the example inputs:

```bash
cp config/league.example.json config/league.json
cp data/yahoo_rankings.example.csv data/yahoo_rankings_2026.csv
```

A draft-state file should normally be created with `ff-draft-new` rather than copied manually.

The ranking CSV schema is:

```text
Rank,Position Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Yahoo Data As Of,Recommended Tier As Of,Recommended Tier,Manual - Tier,Yahoo Status,Yahoo Injury Note
```

`Yahoo Player ID` is the preferred stable identity when available. `Recommended Tier` is the current expert/analyst tier and is dated independently from the Yahoo market snapshot. `Manual - Tier` is the user's preserved position-relative tier and remains the deterministic tier input when populated. Compact Yahoo status/injury fields provide current risk context without embedding verbose notes or source URLs in the runtime file.

## Starting a Draft Session

Create a fresh mock draft:

```bash
ff-draft-new --type mock --slot 4 --workspace .
```

Create the actual league draft once the draft slot is known:

```bash
ff-draft-new --type actual --slot <YOUR_SLOT> --workspace .
```

A timestamp-based draft ID is generated automatically. An explicit ID may instead be supplied:

```bash
ff-draft-new \
  --type mock \
  --slot 4 \
  --draft-id mock-test-01 \
  --workspace .
```

An existing active `draft_state.json` is protected unless replacement is explicit:

```bash
ff-draft-new --type mock --slot 7 --replace --workspace .
```

Creating a new session resets draft-specific state only. League configuration, rankings, and manual tiers remain reusable across drafts.

## Synchronizing a Yahoo Draft

The intended mock-draft workflow uses copied Yahoo draft-chat history as an input source.

Copy a recent portion of the Yahoo draft chat, then synchronize it:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

The synchronizer processes numeric Yahoo selection blocks and ignores unrelated chat text. It supports overlapping pasted history, so copying a generous recent range is safe.

For each parsed selection:

- an already-recorded pick is verified against local state;
- the exact next pick is resolved and recorded;
- a future pick that skips expected history produces a synchronization error;
- a conflicting historical pick stops synchronization rather than overwriting state;
- ambiguous Yahoo abbreviations require an explicit user choice;
- successful new picks are saved immediately before processing later selections.

Interactive ambiguity choices are read from the terminal even when Yahoo chat is piped through standard input.

## Draft Analysis

Run the analyzer from the workspace containing `config/` and `data/`:

```bash
ff-draft --workspace .
```

The report includes:

- current overall pick and drafting team;
- the user's roster;
- top available players;
- Yahoo rank and ADP;
- manual tiers and tier-scarcity signals;
- tier coverage;
- team roster construction;
- open starter slots;
- active snake-draft lookahead;
- opponent pick opportunities; and
- position exposure before the user's next selection.

The current live workflow is intentionally two steps:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
ff-draft --workspace .
```

This keeps synchronization and analysis loosely coupled while the live mock-draft UX is being evaluated.

## Manual Pick Updates

Manual entry remains available as a fallback or debugging path.

Record one or more players by name or Yahoo Player ID:

```bash
ff-draft-update "Player Name" --workspace .
ff-draft-update 12345 "Another Player" --workspace .
```

With no player arguments, the updater prompts interactively until a blank line is entered:

```bash
ff-draft-update --workspace .
```

Undo the most recently recorded selection:

```bash
ff-draft-update --undo --workspace .
```

## Private Custom GPT Integration

The initial AI integration is a private Custom GPT that consumes the deterministic
`DraftDecisionPacket` through the read-only gateway. The GPT does not own draft state and cannot
modify selections.

Version-controlled Custom GPT material lives under [`docs/custom_gpt/`](docs/custom_gpt/):

- [`instructions.md`](docs/custom_gpt/instructions.md) contains the concise behavior contract pasted
  into the Custom GPT Instructions field.
- [`yahoo_auto_draft_2026.md`](docs/custom_gpt/yahoo_auto_draft_2026.md) is a Knowledge document with
  the longer 2026 Yahoo auto-draft observations and historical context.
- [`README.md`](docs/custom_gpt/README.md) explains how these files are used and maintained.

The instructions are intentionally kept concise. Durable behavioral constraints belong in
`instructions.md`; supporting background that does not need to be present in every prompt belongs in
Knowledge documents.

The Action boundary is read-only:

```text
GET /health
GET /v1/draft/decision
GET /openapi.json
```

The deterministic CLI remains the required fallback if the gateway, HTTPS tunnel, Action
authentication, or model is unavailable.

## Yahoo OAuth

Yahoo API access is optional for the deterministic draft and copied-chat workflow.

A local `oauth2.json` may be placed in the workspace root for API integration:

```json
{
  "consumer_key": "YOUR_YAHOO_CLIENT_ID",
  "consumer_secret": "YOUR_YAHOO_CLIENT_SECRET"
}
```

Never commit access tokens, refresh tokens, client secrets, `.env` files, or `oauth2.json`.

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

The project uses Ruff, strict mypy, pytest, branch-aware pytest-cov, pre-commit, GitHub Actions, and an AST-based test-documentation check.

Tests are written around meaningful behavior and boundaries, including:

- snake-draft turns and ownership;
- roster and FLEX accounting;
- tier boundaries and scarcity;
- player identity and duplicate protection;
- persistence and undo;
- Yahoo draft-chat parsing;
- Yahoo/local-state reconciliation;
- ambiguity, overlap, gap, and conflict behavior;
- CLI orchestration;
- decision-packet serialization and phase behavior;
- gateway authentication/read-only API behavior; and
- Yahoo OAuth behavior without live network calls.

The repository enforces a minimum of 90% branch-aware test coverage. The threshold is intentionally below 100% so coverage does not encourage low-value tests of trivial launcher or defensive boilerplate.

Development commands, targeted test workflows, the full quality gate, coverage commands, and smoke-test procedures are documented in [DEVELOPMENT.md](DEVELOPMENT.md).

## Data and Privacy

The repository contains only sanitized example inputs. Real league settings, active draft state, raw Yahoo settings, OAuth credentials, and full Yahoo-derived ranking datasets should remain local.

If external ranking or league data is used, the user is responsible for ensuring that storage and redistribution are permitted. The deterministic engine only requires data that conforms to the documented local schemas.

## Current Status

The deterministic draft assistant is stable as the authoritative fallback, and the initial
AI boundary is working end to end:

- deterministic candidate evaluation produces the broader `DraftDecisionPacket`;
- a bearer-authenticated read-only FastAPI gateway exposes the current packet;
- the gateway has been validated through a public HTTPS tunnel;
- the private Custom GPT Action successfully retrieves live deterministic packets; and
- `WAITING`, `ON_CLOCK`, and `COMPLETE` behaviors have been exercised through the Action path.

Current mock work is focused on measuring where the AI reasoning layer adds value over the
deterministic shortlist, improving return-window/opponent modeling, and preserving fast failure
recovery under a live draft clock.

## Roadmap

Planned progression:

1. Continue AI-assisted mocks and capture meaningful AI-vs-deterministic divergences.
2. Validate failure/fallback behavior for gateway, tunnel, Action authentication, and model failures.
3. Improve opponent-specific return/survival modeling without inventing false probabilities.
4. Add player-relationship/portfolio concepts such as backfield redundancy, handcuffs, stacks, and
   bye-week concentration when reliable data exists.
5. Refine compact live-draft UX and synchronization recovery under the real draft clock.
6. Add current news/injury context as a separately sourced layer that cannot override deterministic
   availability or draft state.
7. Evaluate richer Yahoo API ingestion and additional agent roles only when they add measurable value.

The long-term goal is an agentic fantasy-football assistant whose reasoning can evolve without weakening the reliability of the underlying draft state.
