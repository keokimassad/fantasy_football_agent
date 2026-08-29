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
Track tier quality relative to the best currently available tier **within the same position**.
Tier scarcity describes replacement pain; it does not independently create cross-position
player value, and a singleton in a worse tier must not receive premium loss cost while a
better same-position tier remains available.

### Yahoo Rank / ADP

Market evidence.

- Yahoo rank and ADP jointly define the deterministic cross-position market window.
- When ADP exists, use the simple Rank/ADP midpoint as the transparent market-consensus
  estimate for desirability and close ordering decisions.
- Keep rank and ADP separately available for return-risk, availability-risk, and explanation.
- A player falling past ADP can be surfaced as value only when the user is actually on the
  clock.
- ADP does not become factual draft state.

### Candidate Desirability

Answers:

> Is this player a plausible cross-position selection in the current draft window?

Desirability prevents urgency/scarcity from making a substantially later market candidate
look like the best overall selection solely because that player is last in a positional tier.
It must not use Yahoo rank alone as a hard bucket boundary when ADP materially disagrees.

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
When on-clock candidates share the same desirability band, immediate roster utility should
be considered before scarcity/urgency so a low-utility FLEX option does not displace a
high-utility direct starter solely because it is last in tier.

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
utility to `MEDIUM`, preserving the market-consensus desirability cross-position guardrail.

Depth need should remain an explicit typed domain concept rather than being hidden inside an
opaque position bonus or numerical score.

### Availability Risk

Used while waiting for the user's next decision.

Answers:

> How likely is this player to disappear before I can select again?

Current market inputs are Yahoo rank and ADP. The waiting phase uses preparation-oriented
signals such as `VALUE_IF_AVAILABLE_AT_DECISION` rather than claiming a player has already
fallen past ADP. Within the same position and otherwise-equal decision band, position-relative
tier quality breaks close ordering ties before small Rank/ADP differences. Do not apply that
tier comparison across positions.

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
- large tier drops;
- whether the candidate is in the best currently available tier at that position.

High loss cost does not automatically mean the candidate has high cross-position value. A
last player in a worse available tier remains evidence, but it must not become `HIGH` loss
cost while a better tier at the same position is still available.

### Decision Priority / Urgency

`DecisionPriority` is an internal urgency classification. The CLI presents it as
**Urgency** to avoid implying that urgency equals player value.

Do not collapse desirability and urgency into an opaque magic score. Individual signals
should remain visible and independently testable.

## Phase-Aware Recommendation Flow

Candidate evaluation models two distinct horizons and two user-facing phases. Both horizons
are bounded by `get_total_draft_picks(league)` so snake-order arithmetic cannot create a
fictional post-draft user turn.

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
- a substantially later market candidate cannot leapfrog the plausible draft window solely
  because of scarcity;
- a small Yahoo-rank edge cannot override materially better ADP plus a better same-position
  tier when both players remain in the same plausible market window;
- a last player in a worse same-position tier cannot receive premium loss cost while a better
  tier remains available;
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
- substantially later positional scarcity does not leapfrog the plausible cross-position
  market window;
- the waiting shortlist can surface a different open-starter position when Rank/ADP consensus
  makes that candidate more plausible than a rank-only cutoff would suggest;
- comparable same-position candidates respect position-relative manual-tier quality before
  a small raw market-order difference;
- late-round lookahead never reports a user pick beyond the configured draft endpoint.

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
  than being treated as hard caps;
- within the same desirability band, high immediate roster utility precedes scarcity-driven
  urgency when the alternative is a low-utility FLEX candidate;
- a manager's final selection has no fictional following snake turn beyond the draft endpoint.

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
5. compare tier quality only relative to the best available tier at the same position;
6. use Rank/ADP market consensus for desirability instead of letting either source own the
   bucket boundary;
7. use same-position tier quality only inside an otherwise-comparable decision band;
8. give immediate roster utility precedence over scarcity when on-clock candidates share the
   same desirability band;
9. bound all future-pick/lookahead calculations to the configured draft endpoint;
10. treat generic opponent exposure as evidence, not probability;
11. treat position roster targets as soft construction guidance, not hard caps;
12. add one domain concept at a time;
13. write regression tests from realistic scenarios;
14. avoid player-specific production logic;
15. avoid arbitrary position penalties or hidden numerical bonuses;
16. preserve explainability;
17. rerun a real mock after meaningful changes.

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

The AI boundary is now implemented in `draft.decision_packet`. The first AI agent should
consume `DraftDecisionPacket` rather than parse terminal output or reconstruct deterministic
facts.

Current packet shape:

```text
DraftDecisionPacket
  schema_version
  DraftDecisionContext
    league / draft identity
    current, decision, and following picks
    user roster and position counts
    open starter slots
    remaining / optional draft capacity
    roster requirements and scoring context
  CandidateDecisionEvidence[]
    player identity and market data
    manual-tier / scarcity evidence
    roster fit / utility / depth need
    desirability / risks / loss cost / urgency
    explanation signals
```

The default packet exposes more candidates than the five names rendered for compact human
review. The human top-five shortlist therefore remains a fast deterministic fallback while
the AI receives enough neighboring evidence to compare alternatives.

The initial integration target is a private Custom GPT Action over a read-only HTTPS gateway.
Keep provider/network concerns outside the draft domain package: the gateway may serialize the
packet, but it must not become a second source of truth for draft state or recommendation math.

The HTTP boundary lives under `fantasy_football_agent.gateway` and should remain thin:

```text
GET /health
GET /v1/draft/decision  -> build_current_decision_packet(...)
GET /openapi.json       -> generated Action schema
```

`/v1/draft/decision` is bearer-authenticated and read-only. The default server binds only to
`127.0.0.1`; public HTTPS exposure belongs to deployment/tunnel configuration, not the draft
domain. The gateway API key comes from `FANTASY_AGENT_GATEWAY_API_KEY` and must never be
committed.

### Gateway Secret Lifecycle on macOS

Use the macOS login Keychain for the local development bearer secret. Do not store the value in
`.env`, `.zshrc`, project configuration, Git, or the clipboard as part of the normal workflow.

One-time setup or rotation:

```bash
export FANTASY_AGENT_GATEWAY_API_KEY="$(
  python -c 'import secrets; print(secrets.token_urlsafe(32))'
)"
security add-generic-password \
  -a "$USER" \
  -s "fantasy_football_agent_gateway" \
  -w "$FANTASY_AGENT_GATEWAY_API_KEY" \
  -U
unset FANTASY_AGENT_GATEWAY_API_KEY
```

The Keychain entry survives logout and reboot. Environment variables are process-local and do
not survive a terminal close or reboot. Each shell that starts the gateway or sends authenticated
requests must load the value itself:

```bash
export FANTASY_AGENT_GATEWAY_API_KEY="$(
  security find-generic-password \
    -a "$USER" \
    -s "fantasy_football_agent_gateway" \
    -w
)"
```

Verify presence without printing the secret:

```bash
echo "${#FANTASY_AGENT_GATEWAY_API_KEY}"
```

A token generated with `secrets.token_urlsafe(32)` is normally 43 characters. Never print the
actual value into logs, screenshots, issue comments, PRs, or chat transcripts.

Smoke-test the local boundary before public exposure:

```bash
# Terminal 1
ff-gateway --workspace .

# Terminal 2, after loading the Keychain secret independently
curl http://127.0.0.1:8000/health
curl \
  -H "Authorization: Bearer $FANTASY_AGENT_GATEWAY_API_KEY" \
  http://127.0.0.1:8000/v1/draft/decision
curl http://127.0.0.1:8000/openapi.json \
  -o /tmp/fantasy-agent-openapi.json
```

Expected security behavior:

- `/health` succeeds without credentials and exposes no draft data;
- `/v1/draft/decision` returns `401` without the bearer secret;
- the same route returns `200` with the correct bearer secret;
- `/openapi.json` advertises only read operations and bearer authentication;
- a completed draft returns `phase=COMPLETE` and an empty candidate list rather than inventing a
  future pick.

After a shell no longer needs the secret, run `unset FANTASY_AGENT_GATEWAY_API_KEY`. To remove the
persistent development secret entirely:

```bash
security delete-generic-password \
  -a "$USER" \
  -s "fantasy_football_agent_gateway"
```

Keep HTTP tests split from deterministic packet tests. The gateway should prove authentication,
OpenAPI shape, and serialization, while draft behavior remains covered in `tests/unit/draft`.

### ngrok + Custom GPT Action Development Workflow

The development tunnel is intentionally outside the deterministic engine. A normal live test uses
three independent shells:

```text
Terminal 1: ff-gateway --workspace . --public-url <ngrok HTTPS URL>
Terminal 2: ngrok http 8000
Terminal 3: curl / smoke-test commands as needed
```

The ngrok account token should also live in macOS Keychain under
`fantasy_football_agent_ngrok`. Load it into `NGROK_AUTHTOKEN` only in the shell that starts the
tunnel. Do not copy either secret into documentation, screenshots, issue comments, PR text, or
chat transcripts.

Before configuring or reconfiguring the Action, verify the public route itself:

```text
GET /health                     -> 200 without credentials
GET /v1/draft/decision          -> 401 without bearer credentials
GET /v1/draft/decision          -> 200 with the gateway bearer secret
GET /openapi.json               -> public schema with ngrok HTTPS server
```

The private Custom GPT Action uses the generated OpenAPI schema and the same gateway bearer
secret. The GPT's exact behavioral prompt belongs in `CUSTOM_GPT_INSTRUCTIONS.md`; keep that file
provider-facing and keep deterministic recommendation math out of it.

Validated behavior from the first end-to-end mock cycle:

```text
COMPLETE
  completed 150-pick mock -> no decision pick, no following pick, zero candidates

WAITING (pick 82, next user pick 86)
  -> identifies four selections before the user's turn
  -> treats targets as conditional on survival
  -> does not instruct the user to select immediately

ON_CLOCK (pick 86, next user pick 95)
  -> receives 15 deterministic candidates
  -> compares scarcity, roster depth, market evidence, return risk, and loss cost
  -> may agree with or explicitly override deterministic ordering
```

The first ON_CLOCK Action recommendation selected Rico Dowdle and agreed with the deterministic
leader because of tier scarcity, RB depth need, high return risk, and market position. The first
WAITING response correctly shifted to a conditional Metcalf/Pollard/Dowdle target set based on the
four-pick exposure window. These are behavioral validation observations, not new recommendation
rules to hard-code.

When testing with a historical mock, work from a backup and restore the original state after the
phase tests. Never leave the workspace silently rewound after Action validation.

Future `PlayerContext[]` news/injury snapshots should be added as a separate layer rather than
folded into factual draft state.

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

The project is now **mock-draft ready with phase-aware, position-depth-aware deterministic recommendations**.

Completed foundations:

1. deterministic league, state, roster, tier, and snake-order modeling;
2. draft session creation and persistence;
3. Yahoo copied-chat parsing;
4. safe reconciliation and overlap recovery;
5. ambiguity handling;
6. incremental persistence;
7. candidate evaluation;
8. two decision horizons;
9. waiting-vs-on-clock recommendation phases;
10. cross-position candidate desirability;
11. roster fit;
12. roster utility;
13. availability-risk heuristics;
14. return-risk heuristics using Yahoo rank and ADP market evidence;
15. tier loss-cost modeling;
16. Rank/ADP market-consensus desirability so neither market source owns the hard bucket
    boundary;
17. position-relative tier-gap handling so worse-tier scarcity cannot overpower better
    same-position options;
18. market guardrails preventing scarcity from independently overpowering cross-position
    value;
19. opponent exposure retained as deterministic context rather than probability;
20. explainable top-five deterministic recommendations;
21. phase-aware CLI recommendation presentation;
22. configurable soft position roster targets;
23. typed position-depth need integrated into roster utility and recommendation ordering;
24. real-mock regressions covering same-position Rank/ADP disagreement, tier-quality
    scarcity, shortlist composition, and RB-depth vs excess-WR construction;
25. semantic `Test...` class organization for larger test modules;
26. versioned, JSON-compatible `DraftDecisionPacket` boundary exposing broader deterministic
    context for a downstream AI agent;
27. bearer-authenticated, read-only HTTP gateway exposing the decision packet and generated
    OpenAPI schema for a private Custom GPT Action;
28. macOS Keychain secret lifecycle for the gateway and ngrok development credentials;
29. public HTTPS development path validated through ngrok with correct `200`/`401` authentication
    behavior and OpenAPI server metadata;
30. private Custom GPT Action validated end to end against `COMPLETE`, `WAITING`, and `ON_CLOCK`
    deterministic packet phases.

Next sequence:

1. run the final Sunday-configuration acceptance mock and validate clock/fallback timing;
2. finish local manual-tier coverage for realistically draftable WRs;
3. run additional AI-assisted mocks and compare AI choices/explanations with deterministic evidence;
4. harden deterministic fallback and model/action failure behavior under live-clock pressure;
5. refine compact live-draft UX and add recent-news/injury context;
6. evaluate richer Yahoo API ingestion when available.

If schedule pressure increases, reduce scope rather than lowering architecture, typing,
testing, readability, or maintainability standards.
