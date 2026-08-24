# Fantasy Football Agent

A Python 3.12 fantasy-football draft assistant built around a deterministic-first architecture. Draft state, roster accounting, player availability, tier analysis, snake-draft lookahead, and Yahoo draft synchronization are handled by deterministic code so future AI agents can reason over trusted facts instead of becoming the source of truth.

The project is currently **mock-draft ready**: a Yahoo mock draft can be initialized, copied draft-chat selections can be synchronized into local state, and the updated draft can be analyzed from the command line.

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

## Architecture

```text
Future AI / agent layer
        |
        | recommendations, tradeoffs, explanation
        v
Deterministic draft engine
        |
        | draft state, roster accounting, availability,
        | tiers, lookahead, persistence
        v
Yahoo integration boundary
        |
        | copied draft chat and optional API access
        v
Yahoo Fantasy
```

The core rule is:

> **AI may reason about draft state, but it should not invent draft state.**

Yahoo-specific parsing, synchronization, authentication, and external-service behavior remain outside the deterministic draft engine. This keeps the core testable without network access and allows additional data sources later.

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
│       │   ├── models.py
│       │   ├── rankings.py
│       │   ├── session.py
│       │   └── state.py
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
Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Manual - Tier
```

`Yahoo Player ID` is the preferred stable identity when available. `Manual - Tier` is optional and represents the user's own position-relative player tiers.

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
- CLI orchestration; and
- Yahoo OAuth behavior without live network calls.

The repository enforces a minimum of 90% branch-aware test coverage. The threshold is intentionally below 100% so coverage does not encourage low-value tests of trivial launcher or defensive boilerplate.

Development commands, targeted test workflows, the full quality gate, coverage commands, and smoke-test procedures are documented in [DEVELOPMENT.md](DEVELOPMENT.md).

## Data and Privacy

The repository contains only sanitized example inputs. Real league settings, active draft state, raw Yahoo settings, OAuth credentials, and full Yahoo-derived ranking datasets should remain local.

If external ranking or league data is used, the user is responsible for ensuring that storage and redistribution are permitted. The deterministic engine only requires data that conforms to the documented local schemas.

## Current Status

The deterministic draft engine and Yahoo copied-chat synchronization path are ready for real Yahoo mock-draft testing.

The next milestone is to use real mock drafts as acceptance tests and identify practical issues in:

- copy/paste latency and ergonomics;
- unexpected Yahoo chat formats;
- player-resolution edge cases;
- synchronization recovery;
- live output density; and
- usefulness of tier/lookahead information under a short draft clock.

The mock-draft experience should drive the next UX changes rather than adding speculative complexity beforehand.

## Roadmap

Planned progression:

1. Run real Yahoo mock drafts and harden the live synchronization/analysis workflow.
2. Build a deterministic candidate-evaluation layer using tiers, ADP, roster fit, scarcity, opponent exposure, and expected survival.
3. Add a single AI agent that consumes structured deterministic candidate analysis and explains/recommends draft choices.
4. Evaluate the single-agent approach through repeated mock drafts.
5. Introduce specialized agents only where separate reasoning roles demonstrably add value.
6. Optionally expand Yahoo API synchronization when external access is available.

The long-term goal is an agentic fantasy-football assistant whose reasoning can evolve without weakening the reliability of the underlying draft state.
