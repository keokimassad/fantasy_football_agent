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
Tier scarcity describes replacement pain; it does not independently create cross-position
player value.

### Yahoo Rank / ADP

Market evidence.

- Yahoo rank is the primary deterministic cross-position guardrail.
- ADP supplies an independent market-timing signal.
- A player falling past ADP can be surfaced as value only when the user is actually on the
  clock.
- ADP does not become factual draft state.

### Candidate Desirability

Answers:

> Is this player a plausible cross-position selection in the current draft window?

Desirability prevents urgency/scarcity from making a substantially later-ranked player look
like the best overall selection solely because that player is last in a positional tier.

### Roster Fit

Describes where a player can fit:

```text
DIRECT_STARTER
FLEX
DEPTH
```

### Roster Utility

Describes the immediate value of that roster fit.

FLEX eligibility is not the same as optimal FLEX usage. A second TE can be eligible for
FLEX while still having lower immediate utility when RB or WR starter slots remain open.

### Position Depth Need

Bench-depth strategy is configured through `LeagueConfig.draft_strategy.position_roster_targets`.

For candidates whose `RosterFit` is `DEPTH`, `PositionDepthNeed` describes how far the current
roster remains below the configured target:

```text
HIGH            two or more players below target
MEDIUM          one player below target
LOW             target reached
NOT_APPLICABLE  candidate is not a depth fit
```

These are soft roster-construction targets, not caps. Reaching a target must not block or
automatically penalize an otherwise valuable player. Likewise, being below target does not
make bench depth a `HIGH`-utility candidate by itself. Needed depth currently raises roster
utility to `MEDIUM`, preserving the Yahoo-rank/desirability cross-position guardrail.

Depth need should remain an explicit typed domain concept rather than being hidden inside an
opaque position bonus or numerical score.

### Availability Risk

Used while waiting for the user's next decision.

Answers:

> How likely is this player to disappear before I can select again?

Current market inputs are Yahoo rank and ADP. The waiting phase uses preparation-oriented
signals such as `VALUE_IF_AVAILABLE_AT_DECISION` rather than claiming a player has already
fallen past ADP.

### Return Risk

Used while the user is on the clock.

Answers:

> If I pass now, how likely is this player to disappear before my following pick?

Yahoo rank and ADP are independent market signals. Generic opponent position exposure is
retained as evidence but is **not treated as selection probability**.

### Loss Cost

Answers:

> How costly would it be if this player disappeared?

Current inputs include:

- roster fit;
- last-in-tier evidence;
- known next-tier information;
- large tier drops.

High loss cost does not automatically mean the candidate has high cross-position value.

### Decision Priority / Urgency

`DecisionPriority` is an internal urgency classification. The CLI presents it as
**Urgency** to avoid implying that urgency equals player value.

Do not collapse desirability and urgency into an opaque magic score. Individual signals
should remain visible and independently testable.

## Phase-Aware Recommendation Flow

Candidate evaluation models two distinct horizons and two user-facing phases.

```text
current pick
    |
    | pre-decision window
    v
user decision pick
    |
    | return window
    v
user following pick
```

### Waiting for the decision pick

Primary questions:

1. which players are plausible targets for the upcoming pick?
2. which players are unlikely to survive until that pick?

User-facing output:

```text
Decision prep shortlist for pick #X
Desirability
Availability risk
```

Waiting-mode signals may include:

```text
VALUE_IF_AVAILABLE_AT_DECISION
PRE_DECISION_POSITION_PRESSURE
```

Waiting mode must not emit `FALLEN_PAST_ADP` merely because the future decision pick is
later than the player's ADP.

### On the clock

Primary questions:

1. which available players are plausible selections now?
2. how painful is it to lose each candidate?
3. if the candidate is passed over, how likely is the candidate to survive until the next
   turn?

User-facing output:

```text
Deterministic shortlist
Desirability
Roster utility
Loss cost
Return risk
Urgency
```

The phase boundary is part of domain behavior and should have regression coverage.

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

Larger test modules use semantic `Test...` classes to group related behavior. The class name
should provide the broad context while the individual test method names only describe the
distinguishing scenario. Keep the full GIVEN/WHEN/THEN detail in the docstring rather than
encoding the entire scenario into an excessively long function name.

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
- waiting-vs-on-clock phase detection;
- candidate evaluation;
- candidate desirability;
- roster fit;
- roster utility;
- position depth need and soft roster targets;
- availability risk;
- return risk;
- loss cost;
- urgency;
- cross-position market guardrails;
- deterministic ordering.

Recommendation tests should include regression cases derived from real mock drafts.

Useful examples already represented by the model include:

- medium return risk + high loss cost can outrank high return risk + lower replacement cost
  inside a plausible market window;
- a last-in-tier player with low return risk can remain medium urgency;
- an unknown next tier must not be treated as a known tier cliff;
- FLEX eligibility can coexist with low immediate roster utility;
- a dedicated starter can outrank an early FLEX candidate even when Yahoo rank slightly
  favors the FLEX candidate;
- a much later-ranked last-in-tier player cannot leapfrog the plausible draft window solely
  because of scarcity;
- generic opponent position exposure does not independently become return probability;
- missing ADP can still yield medium return risk when Yahoo rank supplies meaningful market
  evidence;
- needed RB depth can outrank comparable excess WR depth after the WR target is reached;
- a roster with RB2 / WR4 should not produce a WR-only top three when viable RB depth exists;
- at RB2 / WR5, viable RB3 depth should be strongly elevated over excess WR depth when market
  value remains plausible.

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

Fatal Yahoo synchronization failures mark the active draft stale. While stale, both `ff-draft` and the decision gateway refuse recommendations until a later successful Yahoo sync catches up beyond the observed failure point. An active-draft Yahoo sync that parses zero selections also exits nonzero so the `ffmock` chain stops, but it does not persist a stale marker because no newer Yahoo pick was actually observed.

## macOS Mock Helper

```bash
ffmock() {
  pbpaste | ff-draft-update --yahoo-chat --workspace . && \
    ff-draft --workspace .
}
```

The `&&` prevents analysis from running after a failed synchronization. Successful analysis also repeats live pick status and the top three deterministic/prep candidates in a compact footer at the bottom of the report.

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

Create the mock only after Yahoo reveals the assigned slot:

```bash
ff-draft-new \
  --type mock \
  --slot <YAHOO_MOCK_SLOT> \
  --replace \
  --workspace .
```

Before any selections exist, run:

```bash
ff-draft --workspace .
```

Expected waiting-phase behavior:

- heading is `Decision prep shortlist for pick #X:`;
- `Desirability` and `Availability risk` are visible;
- preparation signals can include `VALUE_IF_AVAILABLE_AT_DECISION`;
- `FALLEN_PAST_ADP` is not emitted before the user is on the clock;
- later-ranked positional scarcity does not leapfrog the plausible cross-position market
  window.

After Yahoo Draft Chat contains selections, copy a recent overlapping range and run:

```bash
ffmock
```

When on the clock, expected behavior is:

- heading is `Deterministic shortlist:`;
- `Desirability`, `Roster utility`, `Loss cost`, `Return risk`, and `Urgency` are visible;
- `FALLEN_PAST_ADP` may appear when it is factually true at the current pick;
- raw opponent exposure remains explanatory context rather than probability;
- depth candidates below their position target expose `HIGH_POSITION_DEPTH_NEED` or
  `POSITION_DEPTH_BELOW_TARGET` as appropriate;
- positions that have reached their target remain eligible for additional value picks rather
  than being treated as hard caps.

When a recommendation feels wrong, record:

```text
Pick / situation:
Phase: waiting / on-clock
Recommended:
What I would have chosen:
Why it felt wrong:
  cross-position value / desirability?
  roster construction?
  tier / replacement cost?
  ADP / timing?
  opponent behavior?
  positional strategy?
  current news / injury?
  other?
```

Do not immediately create a heuristic for every surprising output.

First determine:

1. whether the issue is desirability, availability, urgency, or factual state;
2. which domain concept is missing;
3. whether the behavior repeats;
4. whether the rule can be generalized;
5. whether the change remains explainable.

Then add a regression test.

## Recommendation-Tuning Rules

When changing recommendation behavior:

1. preserve factual evidence separately from interpretation;
2. preserve the distinction between desirability and urgency;
3. preserve the distinction between waiting and on-clock phases;
4. keep tier scarcity as replacement-cost/urgency evidence rather than universal value;
5. treat generic opponent exposure as evidence, not probability;
6. treat position roster targets as soft construction guidance, not hard caps;
7. add one domain concept at a time;
8. write regression tests from realistic scenarios;
9. avoid player-specific production logic;
10. avoid arbitrary position penalties or hidden numerical bonuses;
11. preserve explainability;
12. rerun a real mock after meaningful changes.

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

## AI Integration and Custom GPT Boundary

The first AI layer is now implemented as a private Custom GPT Action over structured deterministic
candidate evidence. The model does **not** parse terminal output as its primary interface and does not
own factual draft state.

Current flow:

```text
Yahoo Draft Chat / local config / rankings
        ↓
deterministic state + candidate evaluation
        ↓
DraftDecisionPacket
        ↓
read-only bearer-authenticated gateway
        ↓
private Custom GPT Action
        ↓
reasoned recommendation
        ↓
user final decision
```

The deterministic shortlist remains the fallback if the gateway, tunnel, Action, or model fails or
cannot complete safely within the draft clock.

### Phase-aware AI candidate frontier

The five-player deterministic CLI shortlist and the AI packet solve different problems. Keep the CLI shortlist compact. The `DraftDecisionPacket` uses a broader phase-aware frontier:

```text
WAITING
    dynamic horizon = selections before decision + target set + uncertainty buffer
    minimum 20, maximum 50 candidates before positional supplementation

ON_CLOCK
    deterministic top-five anchor
    top 10 by effective current market timing
    guarantee at least RB 3 / WR 3 / QB 2 / TE 2 when available

ON_CLOCK consecutive turn
    deterministic top-five anchor
    broader top-15 market horizon
    same skill-position minimums
    context.consecutive_turn = true
```

The deterministic top-five is always retained as an anchor. The additional horizon is selected by effective market timing rather than by repeating the deterministic comparator, which prevents low-desirability specialist depth from consuming the entire AI boundary. Positional minimums are additive safeguards, not quotas or maximums. DEF/K are not guaranteed merely because those starter slots are open; one is normally supplemented only when its deterministic desirability is not `LOW`. Once `optional_draft_capacity` is smaller than the number of user selections represented by the current decision, the frontier also guarantees options for every open required starter slot so a normal or consecutive-turn decision can preserve a legal finish.

For `WAITING`, the market horizon deliberately exceeds the number of intervening selections. Skill-position minimums also expand by snake-length wait cycles: a standard 18-pick end-turn wait carries at least seven RBs, seven WRs, four QBs, and four TEs when available. This lets the model distinguish premium fall-watch players from realistic future decision and contingency targets instead of receiving a list likely to be exhausted before the user's turn.

An explicit `candidate_limit` remains available for tests/diagnostics and bypasses phase-aware supplementation.

### Local market-data overrides

The Yahoo rankings CSV remains the immutable source snapshot. Material news can make historical ADP actively misleading before the next full data refresh, so the runtime may load `data/player_overrides.json` after rankings parsing. The file is local/ignored by Git; `data/player_overrides.example.json` documents the schema.

Supported policies:

```text
VALID      source ADP remains effective
IGNORE     source ADP is preserved but excluded from market calculations
OVERRIDE   a supplied replacement ADP becomes effective while source ADP is preserved
```

Each override is keyed by Yahoo Player ID and must include an auditable reason and `as_of` date. Prefer `IGNORE` when news invalidates historical ADP but no trustworthy replacement value exists. This avoids inventing a synthetic market number.

`Player.adp` and packet `candidate.adp` always mean the effective ADP used by the deterministic engine. `source_adp` is historical/audit metadata. ADP-derived value, availability, return-risk, and recommendation signals must use the effective value only.

The initial regression case is Josh Jacobs: source ADP 35 is retained for auditability, but an `IGNORE` override prevents that stale pre-news number from generating `FALLEN_PAST_ADP` or other current-value signals.

### Custom GPT documentation layout

Keep provider-facing Custom GPT material under:

```text
docs/custom_gpt/
├── README.md
├── instructions.md
└── yahoo_auto_draft_2026.md
```

Responsibilities:

- `instructions.md` is the concise, always-on behavioral contract pasted into the Custom GPT
  Instructions field.
- `yahoo_auto_draft_2026.md` is uploaded as Knowledge and contains supporting 2026 Yahoo auto-draft
  observations, historical context, and working hypotheses.
- `README.md` documents setup, maintenance boundaries, and which material belongs in Instructions
  versus Knowledge.

Do not place these files in `config/`: the Python application does not load them as runtime
configuration. Do not place the auto-draft document in `data/`: it is behavioral/contextual knowledge,
not a runtime dataset.

### Instructions vs. Knowledge

Keep rules that must apply to every draft decision in `instructions.md`, including:

- refresh `getDraftDecision` before current-state answers;
- deterministic packet is authoritative for factual draft state;
- recommend only candidates supplied by the packet;
- phase-specific `WAITING`, `ON_CLOCK`, consecutive-turn, and `COMPLETE` behavior;
- use effective ADP policy rather than historical source ADP when an override is present;
- no invented availability, injuries, roles, opponent behavior, or draft facts;
- deterministic fallback on Action failure;
- read-only authority; and
- the compact 2026 auto-draft tendencies needed for return-window reasoning.

Move longer explanation, history, examples, and hypotheses into Knowledge documents. The Custom GPT
Instructions field has a finite size, so repeating background there weakens maintainability without
improving the factual boundary.

If Instructions and Knowledge ever conflict, fix the repository documentation; until corrected,
the behavioral contract in `instructions.md` takes precedence.

### 2026 auto-draft knowledge scope

The current auto-draft observations are scoped to 2026 Yahoo Fantasy Football, standard 10-team,
15-round redraft snake drafts. They are soft behavioral guidance, not calibrated probabilities.

The compact expectations retained in Instructions are:

```text
R1-5     mostly RB/WR; premium QB/TE can break through
R6       QB1 pressure commonly rises
R7       TE1 pressure commonly rises
R10-12   QB2 becomes plausible; R11 is the central expectation
R12      TE2 commonly clusters
R14-15   DEF/K completion window; order can vary
```

Historical context and fuller interpretation belong in
`docs/custom_gpt/yahoo_auto_draft_2026.md`.

### Maintenance workflow

When Custom GPT behavior changes:

1. update the repository copy first;
2. keep `instructions.md` concise and provider-ready;
3. re-import the generated `/openapi.json` into the Custom GPT Action when the packet schema changes;
4. update/re-upload Knowledge documents when their content changes;
5. validate the Action against fresh `WAITING`, `ON_CLOCK`, and `COMPLETE` states when behavior
   changes materially;
6. keep the deterministic CLI functional as an independent fallback; and
7. never commit bearer secrets, ngrok auth tokens, Yahoo OAuth credentials, or private Action
   credentials.

Changes to the Python decision packet or OpenAPI schema should be tested independently from prompt
changes so data-contract regressions are distinguishable from reasoning/prompt regressions.

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
`DEVELOPMENT.md` before merging. If Custom GPT behavior or knowledge changed, also update the
version-controlled material under `docs/custom_gpt/` before changing the provider configuration.

## Current Milestone

The project is now **AI-assisted mock-draft ready with a deterministic fallback**.

Validated foundations include:

1. deterministic league, state, roster, tier, and snake-order modeling;
2. safe Yahoo Draft Chat parsing, reconciliation, overlap handling, persistence, and undo;
3. phase-aware deterministic candidate evaluation and explainable top-five fallback;
4. a versioned, JSON-compatible `DraftDecisionPacket` with phase-aware candidate horizons, skill-position breadth, and consecutive-turn context;
5. a read-only bearer-authenticated FastAPI gateway;
6. public HTTPS tunnel validation without exposing the local service directly;
7. a private Custom GPT Action consuming the generated OpenAPI schema;
8. successful `WAITING`, `ON_CLOCK`, and `COMPLETE` Action-path validation;
9. deterministic fallback preserved when external AI infrastructure is unavailable;
10. compact 2026 Yahoo auto-draft guidance separated from longer Knowledge context; and
11. current rankings that preserve manual tiers while carrying dated expert tiers, position rank,
    Yahoo status, and injury context;
12. local audited ADP `IGNORE` / `OVERRIDE` policy for stale market snapshots; and
13. slot-one regression coverage for long waiting horizons and consecutive-turn candidate breadth.

Next sequence:

1. validate gateway/tunnel/Action failure paths under live-clock conditions;
2. run the final real-league acceptance workflow using the current 10-team, 15-round configuration;
3. continue AI-assisted mocks and record meaningful AI-vs-deterministic divergences;
4. improve opponent-specific return/survival modeling;
5. add player-relationship/portfolio evidence only when it can be represented reliably;
6. refine compact live-draft UX and Draft Chat gap recovery;
7. keep recent news/injury context separate from deterministic availability/state; and
8. evaluate richer Yahoo API ingestion after the live-draft path is reliable.

If schedule pressure increases, reduce scope rather than lowering architecture, typing, testing,
readability, or maintainability standards.
