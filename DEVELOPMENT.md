# Development Guide

This document is the engineering and operational runbook for the Fantasy Football Agent.

For the public project overview and end-user workflow, see [README.md](README.md).

## Development Environment

Target runtime:

```text
Python 3.12
```

Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Editable installation keeps the CLI entry points connected to the local source tree.

If `pyproject.toml` changes package metadata, dependencies, or entry points, reinstall:

```bash
python -m pip install -e ".[dev]"
hash -r
```

Confirm commands:

```bash
command -v ff-draft
command -v ff-draft-update
command -v ff-draft-new
```

## Architecture Rule

The draft engine is deterministic.

```text
Future AI / LLM
        ↓
reasoning and recommendations
        ↓
structured deterministic results
        ↓
draft engine
        ↓
factual state and calculations
        ↓
Yahoo integration boundary
```

The AI may reason about draft state, but it must not invent draft state.

Yahoo is an integration boundary, not the identity of the project.

## Recommendation Architecture

Recommendation behavior belongs in the draft domain rather than in CLI presentation code.

```text
DraftState + LeagueConfig + Rankings
              |
              v
      evaluate_candidates()
              |
              v
      CandidateEvaluation
              |
              v
build_candidate_recommendations()
              |
              v
 CandidateRecommendation[]
              |
              v
          CLI rendering
              |
              v
    future AI consumption
```

The CLI should render structured results rather than own recommendation rules.

## Recommendation Principles

Keep these concepts distinct.

### Manual Tier

The user's valuation of a player **within that player's position**.

Manual tiers are position-relative and must not be converted into a naive universal score.

### Yahoo Rank / ADP

Market evidence.

- Yahoo rank supplies a cross-position baseline.
- ADP helps estimate market timing.
- A player falling past ADP can be surfaced as value.
- ADP does not become factual draft state.

### Roster Fit

Describes where a player can fit:

```text
DIRECT_STARTER
FLEX
DEPTH
```

### Roster Utility

Describes the immediate value of that roster fit.

For example, FLEX eligibility is not the same as optimal FLEX usage. A second TE can be
eligible for FLEX while still having lower immediate utility when RB or WR starter slots
remain open.

### Return Risk

Answers:

> How likely is this player to disappear before the user's following pick?

Current inputs include:

- ADP timing;
- return-window opponent position exposure.

Return risk is a heuristic, not a probability.

### Loss Cost

Answers:

> How costly would it be if this player disappeared?

Current inputs include:

- roster fit;
- last-in-tier evidence;
- known next-tier information;
- large tier drops.

High loss cost does not automatically mean high immediate priority if return risk is low.

### Decision Priority

Combines the other dimensions into deterministic urgency.

Avoid collapsing all evidence into an opaque magic score. Individual signals should remain
visible and independently testable.

## Two Draft Horizons

Candidate evaluation models two distinct windows:

```text
current pick
    |
    | pre-decision exposure
    v
user decision pick
    |
    | return-window exposure
    v
user following pick
```

These answer different questions:

1. can the player survive until the user's next decision?
2. if the user passes, can the player survive until the following decision?

Tests should preserve this distinction.

## Primary CLI Commands

Create a draft session:

```bash
ff-draft-new --type mock --slot <SLOT> --workspace .
```

Replace an existing session:

```bash
ff-draft-new \
  --type mock \
  --slot <SLOT> \
  --replace \
  --workspace .
```

Synchronize Yahoo Draft Chat:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

Analyze the current draft:

```bash
ff-draft --workspace .
```

Undo the most recent pick:

```bash
ff-draft-update --undo --workspace .
```

## Full Quality Gate

Run this before committing or merging meaningful changes:

```bash
python -m ruff format --check src tests scripts tools
python -m ruff check src tests scripts tools
python -m mypy src tests
python tools/check_test_docstrings.py
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing
```

Expected:

- formatting passes;
- lint passes;
- strict mypy passes;
- test docstring validation passes;
- all tests pass;
- total branch-aware coverage remains at or above 90%.

If formatting needs to be applied:

```bash
python -m ruff format src tests scripts tools
```

Do not chase 100% coverage through low-value tests of launcher lines or trivial defensive
boilerplate.

## Test Documentation

Tests use behavioral docstrings:

```python
"""
GIVEN: ...
WHEN: ...
THEN: ...
"""
```

Validate them with:

```bash
python tools/check_test_docstrings.py
```

The docstring should describe behavior rather than implementation details.

## Targeted Test Commands

Recommendation layer:

```bash
python -m pytest \
  tests/unit/draft/test_recommendations.py \
  tests/unit/cli/test_draft_analyzer.py \
  -v
```

Yahoo synchronization:

```bash
python -m pytest \
  tests/unit/cli/test_draft_updater.py \
  tests/unit/draft/test_session.py \
  tests/unit/yahoo/test_draft_chat.py \
  tests/unit/yahoo/test_draft_sync.py \
  -v
```

All tests:

```bash
python -m pytest
```

Branch-aware coverage:

```bash
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing
```

HTML coverage:

```bash
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=html

open htmlcov/index.html
```

## Type-Safety Principle

When a required dataclass field is added, all construction paths must supply it.

Strict mypy should expose incomplete integration immediately.

Fix the integration point rather than weakening the type.

## Test Philosophy

Prefer tests of meaningful behavior and boundaries.

Important deterministic behavior includes:

- snake order;
- roster construction;
- FLEX overflow;
- player availability;
- tier depth and scarcity;
- player identity;
- current and following user picks;
- opponent exposure;
- candidate evaluation;
- roster fit;
- roster utility;
- return risk;
- loss cost;
- priority;
- deterministic ordering.

Recommendation tests should include regression cases derived from real mock drafts.

Useful examples already represented by the model include:

- medium return risk + high loss cost can outrank high return risk + lower replacement cost;
- a last-in-tier player with low return risk can remain medium priority;
- an unknown next tier must not be treated as a known tier cliff;
- FLEX eligibility can coexist with low immediate roster utility;
- a dedicated starter can outrank an early FLEX candidate even when Yahoo rank slightly
  favors the FLEX candidate.

Avoid player-specific hard-coding.

## Yahoo Boundary Principles

Yahoo synchronization should remain an adapter into deterministic state.

Important behaviors:

- structurally parse selection blocks;
- ignore ordinary chat;
- resolve exact player identities;
- surface true ambiguity;
- verify overlapping local/Yahoo history;
- stop on gaps;
- stop on conflicts;
- persist successful picks incrementally;
- keep keyboard ambiguity resolution available even when stdin is piped.

Do not silently resolve factual ambiguity from ADP.

## Yahoo Draft-Chat Smoke Test

Create a disposable mock:

```bash
ff-draft-new \
  --type mock \
  --slot 4 \
  --draft-id yahoo-chat-smoke-test \
  --replace \
  --workspace .
```

Feed representative Yahoo text:

```bash
cat <<'EOF2' | ff-draft-update --yahoo-chat --workspace .
1
Chris
J. Gibbs
RB
DET
Bye 6

2
Wes
B. Robinson
RB
ATL
Bye 11

3
Jace
J. Chase
WR
CIN
Bye 6

4
You
P. Nacua
WR
LAR
Bye 11
EOF2
```

The ambiguous `B. Robinson` case should require explicit resolution rather than an ADP-based
guess.

Then run:

```bash
ff-draft --workspace .
```

Confirm:

- current overall pick advanced correctly;
- the user's roster is correct;
- Yahoo IDs were persisted;
- the deterministic shortlist renders;
- detailed state remains consistent with the shortlist.

## Overlap Recovery

If synchronization stops after earlier selections were persisted, do not automatically
reset the draft.

Copy a recent overlapping Yahoo range and rerun:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

Expected behavior:

- matching prior picks are `VERIFIED`;
- the first new expected pick is `RECORDED`;
- conflicting overlap stops synchronization;
- a missing-pick gap stops synchronization.

## macOS Mock Helper

```bash
ffmock() {
  pbpaste | ff-draft-update --yahoo-chat --workspace .
  ff-draft --workspace .
}
```

Create the mock session only after Yahoo reveals the slot:

```bash
ff-draft-new \
  --type mock \
  --slot <YAHOO_MOCK_SLOT> \
  --replace \
  --workspace .
```

## Real Mock-Draft Acceptance Testing

Real mocks are the main acceptance test for recommendation behavior and live workflow.

During the mock, inspect the `Deterministic shortlist:` first.

When a recommendation feels wrong, record:

```text
Pick / situation:
Recommended:
What I would have chosen:
Why it felt wrong:
  roster construction?
  tier / replacement cost?
  ADP / return timing?
  opponent behavior?
  positional strategy?
  current news / injury?
  other?
```

Do not immediately create a heuristic for every surprising output.

First determine:

1. which domain concept is missing;
2. whether the behavior repeats;
3. whether the rule can be generalized;
4. whether the change remains explainable.

Then add a regression test.

## Recommendation-Tuning Rules

When changing recommendation behavior:

1. preserve factual evidence separately from interpretation;
2. add one domain concept at a time;
3. write regression tests from realistic scenarios;
4. avoid player-specific logic;
5. avoid arbitrary position penalties;
6. preserve explainability;
7. rerun a real mock after meaningful changes.

## Future News / Injury Context

Recent news should be a separate input layer.

It should not mutate DraftState or silently rewrite manual tiers.

Intended shape:

```text
Rankings / Manual Tiers        DraftState
          \                     /
           \                   /
            Candidate Evaluation
                    ^
                    |
           PlayerContext snapshot
           - injury/status
           - practice news
           - depth-chart changes
           - suspension/availability
           - role changes
           - timestamp
           - sources
                    |
                    v
                AI agent
```

Preferred workflow:

1. refresh broad player context before the draft;
2. evaluate deterministic candidates;
3. refresh only the small set of relevant candidates when necessary;
4. cache player context with timestamps;
5. preserve deterministic fallback if news retrieval fails.

## AI Integration Principle

The first AI layer should consume structured deterministic candidate evaluations.

It should not parse a giant terminal dump as its primary interface.

Likely input:

```text
DraftState summary
CandidateRecommendation[]
PlayerContext[]
small league context
```

Likely output:

```text
preferred pick
backup choices
reasoning
wait/pivot guidance
counterargument
```

The deterministic shortlist remains the fallback if the AI call fails or exceeds the draft
clock.

Start with one AI recommendation agent. Add multi-agent behavior only if later mocks show a
clear measurable benefit.

## Git Workflow

Typical feature flow:

```bash
git switch main
git pull
git switch -c feature/<feature-name>
```

Before commit:

```bash
python -m ruff format --check src tests scripts tools
python -m ruff check src tests scripts tools
python -m mypy src tests
python tools/check_test_docstrings.py
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing

git status
git diff
```

If public capabilities or developer workflow changed, update both `README.md` and
`DEVELOPMENT.md` before merging.

## Current Milestone

The project is now **mock-draft ready with deterministic recommendations**.

Completed foundations:

1. deterministic league, state, roster, tier, and snake-order modeling;
2. draft session creation and persistence;
3. Yahoo copied-chat parsing;
4. safe reconciliation and overlap recovery;
5. ambiguity handling;
6. incremental persistence;
7. candidate evaluation;
8. two decision horizons;
9. roster fit;
10. roster utility;
11. return-risk heuristics;
12. tier loss-cost modeling;
13. explainable top-five deterministic recommendations;
14. CLI recommendation presentation.

Next sequence:

1. run additional real Yahoo mocks;
2. collect recommendation regressions and timing feedback;
3. refine compact live-draft UX;
4. add recent-news and injury context;
5. add one AI recommendation agent;
6. run AI-assisted mocks;
7. harden fallback and failure behavior;
8. evaluate richer Yahoo API ingestion when available.

If schedule pressure increases, reduce scope rather than lowering architecture, typing,
testing, readability, or maintainability standards.
