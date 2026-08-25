# Fantasy Football Agent

A Python 3.12 fantasy-football draft assistant built around a deterministic-first architecture.

The project keeps draft state, player availability, roster accounting, tier analysis, pick
lookahead, opponent exposure, and candidate recommendations deterministic and testable.
Yahoo Fantasy is treated as an integration boundary, while future news/context and AI layers
will reason over structured outputs rather than owning factual draft state.

## Core Principle

> **The agent may reason about draft state, but it should not invent draft state.**

The deterministic engine remains the source of truth for:

- draft order;
- player availability;
- roster construction;
- persisted selections;
- tier evidence;
- pick windows;
- opponent exposure;
- recommendation evidence.

Future AI functionality will consume those results rather than recreate them.

## Current Capabilities

- Load and validate league configuration and persisted draft state.
- Model snake-draft ownership, including turn picks.
- Track rosters and open starter slots, including FLEX overflow.
- Load Yahoo-derived rankings with:
  - Yahoo rank;
  - ADP;
  - player name;
  - position;
  - team;
  - bye;
  - drafted percentage;
  - Yahoo Player ID;
  - manual tier.
- Determine available players using Yahoo Player ID as the preferred stable identity.
- Calculate:
  - tier depth;
  - next position tier;
  - last-in-tier conditions;
  - tier drops;
  - scarcity flags;
  - tier coverage.
- Build draft lookahead windows between the current pick and future user picks.
- Estimate opponent position exposure inside those windows.
- Evaluate candidates deterministically.
- Produce a compact top-five recommendation shortlist.
- Distinguish:
  - roster fit;
  - roster utility;
  - return risk;
  - loss cost;
  - decision priority.
- Record draft picks locally.
- Undo the most recent pick.
- Parse copied Yahoo Draft Chat selections.
- Safely reconcile overlapping Yahoo draft history.
- Detect synchronization gaps and conflicts.
- Surface ambiguous Yahoo player identities instead of guessing.
- Authenticate to Yahoo Fantasy through a dedicated OAuth/client boundary.
- Expose the workflow through installable CLI commands.

## Architecture

```text
Yahoo Draft Chat / future Yahoo API
              |
              | observed selections
              v
          DraftState
              |
              | availability
              | roster accounting
              | tiers
              | snake order
              | lookahead
              | opponent exposure
              v
      CandidateEvaluation
              |
              | roster fit
              | roster utility
              | tier loss cost
              | market return risk
              | deterministic signals
              v
  Deterministic Recommendations
              |
              | structured decision evidence
              v
 Future player-news context + AI agent
```

Yahoo-specific code remains outside the core draft engine so deterministic behavior can be
tested without network access.

## Recommendation Model

The recommendation layer intentionally keeps several concepts separate.

### Roster Fit

Describes where a candidate can fit on the current roster:

- `DIRECT_STARTER`
- `FLEX`
- `DEPTH`

### Roster Utility

Describes how useful that roster fit is **right now**.

For example, a second TE may technically fit in FLEX, but its immediate roster utility can
be lower while dedicated RB or WR starter slots remain open.

### Return Risk

Estimates whether a player is likely to disappear before the user's following pick.

Inputs include:

- player ADP relative to the decision and following picks;
- opponent positional exposure inside the return window.

This is a deterministic heuristic, not a probability model.

### Loss Cost

Estimates how costly it would be if a player disappeared.

Inputs include:

- roster fit;
- `LAST_IN_TIER`;
- known next-tier information;
- large tier drops.

A player can have high loss cost but low return risk, meaning the player is valuable to
preserve but may still be safe to wait on.

### Decision Priority

Combines roster utility, loss cost, and return risk into an explainable urgency category.

### Manual Tiers

Manual tiers remain **position-relative**.

A Tier 1 RB is not assumed to have the same universal value as a Tier 1 WR. The engine does
not convert tiers into an arbitrary cross-position numerical score.

Yahoo rank remains the deterministic cross-position baseline and tie-breaker.

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
│       ├── __init__.py
│       ├── application_paths.py
│       ├── py.typed
│       ├── cli/
│       │   ├── __init__.py
│       │   ├── draft_analyzer.py
│       │   ├── draft_creator.py
│       │   └── draft_updater.py
│       ├── draft/
│       │   ├── __init__.py
│       │   ├── analysis.py
│       │   ├── models.py
│       │   ├── rankings.py
│       │   ├── recommendations.py
│       │   ├── session.py
│       │   └── state.py
│       └── yahoo/
│           ├── __init__.py
│           ├── draft_chat.py
│           ├── draft_sync.py
│           ├── yahoo_client.py
│           └── yahoo_config.py
├── tests/
├── tools/
│   └── check_test_docstrings.py
├── .gitignore
├── .pre-commit-config.yaml
├── DEVELOPMENT.md
├── pyproject.toml
└── README.md
```

Local/private files such as real league configuration, current draft state, full rankings,
raw Yahoo data, and OAuth credentials are intentionally excluded from Git.

## Setup

Create and activate a Python 3.12 environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install the project in editable mode with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Create local working copies of the example inputs:

```bash
cp config/league.example.json config/league.json
cp data/draft_state.example.json data/draft_state.json
cp data/yahoo_rankings.example.csv data/yahoo_rankings_2026.csv
```

The ranking CSV schema is:

```text
Rank,ADP,Player Name,Position,Team,Bye,% Drafted,Yahoo Player ID,Manual - Tier
```

## CLI Commands

The installed entry points are:

```text
ff-draft
ff-draft-update
ff-draft-new
```

### Create a Draft Session

Create a mock session after Yahoo reveals the slot:

```bash
ff-draft-new --type mock --slot <SLOT> --workspace .
```

Create the actual league session once the real slot is known:

```bash
ff-draft-new --type actual --slot <SLOT> --workspace .
```

Replace an existing active session explicitly:

```bash
ff-draft-new   --type mock   --slot <SLOT>   --replace   --workspace .
```

A custom draft ID may be supplied with `--draft-id`.

## Yahoo Draft-Chat Synchronization

Copy a recent Yahoo Draft Chat selection range and pipe the clipboard into the updater:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

The synchronizer:

- ignores arbitrary non-selection chat;
- verifies matching overlapping history;
- records the next expected selections;
- persists successful picks incrementally;
- stops on gaps or conflicts;
- resolves exact player identities from ranking data;
- prompts when Yahoo abbreviations are genuinely ambiguous.

Using a recent overlapping range is intentional. Already-recorded selections can be safely
verified before new picks are added.

## Draft Analysis

Run:

```bash
ff-draft --workspace .
```

The report begins with a compact deterministic shortlist.

Example shape:

```text
Deterministic shortlist:
  1. Candidate | WR T3 | Priority HIGH | Roster utility HIGH | Loss cost HIGH | Return risk MEDIUM
     Rank #38 | ADP 43.3 | Fit DIRECT_STARTER | Tier left 1 | Next T4
     Why: FILLS_DIRECT_STARTER, LAST_IN_TIER, RETURN_WINDOW_POSITION_PRESSURE
```

The detailed report also includes:

- draft/session metadata;
- the user's roster;
- top available players;
- tier scarcity;
- tier coverage;
- team roster construction;
- open starter slots;
- active lookahead;
- opponent lookahead;
- position exposure before the following user pick.

## Manual Draft Updates

Record a player manually:

```bash
ff-draft-update "Player Name" --workspace .
```

Record by Yahoo Player ID:

```bash
ff-draft-update 12345 --workspace .
```

Run interactively:

```bash
ff-draft-update --workspace .
```

Undo the most recent pick:

```bash
ff-draft-update --undo --workspace .
```

## Fast macOS Mock Workflow

A small shell helper can synchronize copied Yahoo chat and immediately rerun analysis:

```bash
ffmock() {
  pbpaste | ff-draft-update --yahoo-chat --workspace .
  ff-draft --workspace .
}
```

Typical mock workflow:

1. wait until Yahoo reveals the draft slot;
2. create a fresh mock session with `ff-draft-new`;
3. copy a recent Yahoo Draft Chat selection range;
4. run `ffmock`;
5. verify `Current overall pick`;
6. review the deterministic shortlist;
7. repeat before upcoming selections.

## Yahoo OAuth

Yahoo API access is optional for the copied-chat workflow.

A local workspace-level `oauth2.json` may contain:

```json
{
  "consumer_key": "YOUR_YAHOO_CLIENT_ID",
  "consumer_secret": "YOUR_YAHOO_CLIENT_SECRET"
}
```

Never commit OAuth credentials, access tokens, refresh tokens, client secrets, `.env`, or
real private league data.

OAuth path precedence is:

```text
explicit path
    ↓
YAHOO_OAUTH_FILE
    ↓
<workspace>/oauth2.json
```

A manual Yahoo connectivity check is available:

```bash
python scripts/check_yahoo_connection.py
```

## Quality Gates

The project uses:

- Ruff;
- strict mypy;
- pytest;
- pytest-cov with branch coverage;
- behavioral test docstrings;
- pre-commit;
- GitHub Actions.

Install pre-commit once per clone:

```bash
python -m pre_commit install
```

Run all configured hooks:

```bash
python -m pre_commit run --all-files
```

Run the full local quality gate:

```bash
python -m ruff format --check src tests scripts tools
python -m ruff check src tests scripts tools
python -m mypy src tests
python tools/check_test_docstrings.py
python -m pytest   --cov=fantasy_football_agent   --cov-branch   --cov-report=term-missing
```

The project enforces a minimum of 90% branch-aware coverage.

Exact test counts and coverage percentages are intentionally not documented here because
they change as the project evolves.

## Testing Philosophy

Tests focus on meaningful behavior rather than coverage for its own sake.

Important areas include:

- snake-draft ownership;
- roster/FLEX accounting;
- tier boundaries;
- player availability;
- two-horizon candidate evaluation;
- roster fit;
- roster utility;
- return risk;
- loss cost;
- recommendation ordering;
- Yahoo draft-chat parsing;
- ambiguity handling;
- overlap verification;
- gap/conflict detection;
- persistence;
- undo;
- OAuth refresh behavior without live network calls.

## Data and Privacy

The repository should contain sanitized example data only.

Keep the following local:

- `config/league.json`
- `data/draft_state.json`
- `data/yahoo_rankings_2026.csv`
- `data/raw/`
- `oauth2.json`

If external ranking or league data is used, ensure that storage and redistribution comply
with the provider's terms.

## Roadmap

The deterministic recommendation layer is now implemented and ready for additional mock
validation.

Next priorities:

1. run more live Yahoo mock drafts and collect recommendation regressions;
2. refine the live-draft decision workflow based on clock pressure and readability;
3. add timestamped recent-news and injury context as a separate input layer;
4. add one AI recommendation agent over structured deterministic results;
5. run AI-assisted mocks and harden deterministic fallback behavior;
6. evaluate richer Yahoo API ingestion when available;
7. consider specialized multi-agent roles only if they add measurable value.

The core rule remains:

> **The agent may reason about draft state, but it should not invent draft state.**
