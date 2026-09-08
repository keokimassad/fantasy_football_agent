# Architecture

Fantasy Football Agent uses a deterministic-first decision-support architecture. The LLM is intentionally downstream of authoritative draft-state handling and cannot modify Yahoo selections.

## Authority Boundary

```text
Yahoo / local inputs
      |
      v
synchronization + identity resolution
      |
      v
persisted DraftState
      |
      v
deterministic analysis + recommendations
      |
      v
DraftDecisionPacket (schema versioned)
      |
      v
read-only FastAPI/OpenAPI gateway
      |
      v
Custom GPT strategy/reasoning
      |
      v
human final decision
```

The model may interpret deterministic evidence, compare tradeoffs, and apply saved or temporary strategy. It may not invent ownership, availability, roster state, the current pick, or completed selections.

## Deterministic Domain

The deterministic core owns:

- league and scoring configuration;
- snake-draft ownership and turn calculation;
- persisted pick history;
- roster/FLEX accounting;
- available-player calculation;
- Yahoo Player ID-based identity;
- manual tiers and tier scarcity;
- rank/ADP market evidence and governed overrides;
- exact user decision windows;
- opponent position exposure;
- candidate ordering;
- phase and starter-capacity constraints.

Recommendation code returns structured typed data. CLI rendering and model-facing presentation do not own recommendation rules.

## Strategy Boundary

`config/draft_strategy.json` is separate from league facts. It contains user-controlled roster targets and reusable soft preferences.

The deterministic candidate ordering remains independent. AI-visible candidates preserve `baseline_rank`, allowing the reasoning layer to quantify a strategy-driven deviation instead of silently rewriting the baseline.

A current-chat instruction may temporarily overlay saved strategy for a session, but it should not automatically become a permanent configuration change.

## Decision Packet

`DraftDecisionPacket` is the contract between deterministic code and the AI layer. It is JSON-compatible and schema versioned.

The packet contains factual context plus a bounded candidate frontier. Candidate records expose independent evidence such as rank, ADP, manual tier, market estimate, roster fit/utility, depth need, tier remaining, scarcity flags, return risk, loss cost, desirability, priority, and explanatory signals.

Candidate visibility differs by phase:

- `WAITING`: broader horizon for preparation before the user's next decision;
- `ON_CLOCK`: compact decision set for latency and focus;
- consecutive turn: broader frontier for a two-pick portfolio from one fresh state call;
- `COMPLETE`: no further draft recommendation.

The deterministic CLI top candidates remain available even if the AI path is unavailable.

## Yahoo Integration Boundary

Yahoo-specific behavior is isolated from the domain engine. Current components handle copied selection parsing, player-name/metadata resolution, OAuth/client access, and local-state reconciliation.

Synchronization is fail closed:

- verified overlap is accepted;
- the exact next selection may be appended;
- a missing expected pick is a gap error;
- conflicting history is rejected;
- ambiguous identity requires resolution;
- successful picks are persisted incrementally.

The September 7, 2026 live draft exposed an important source-assumption failure: Draft Chat selections were not consistently visible across clients. Yahoo Results was used successfully as an alternate copied input. Future work should formalize Draft Chat and Results as separate adapters behind a source-neutral ingestion interface.

## Gateway / Model Boundary

The FastAPI gateway is read only and exposes the current deterministic packet to a private Custom GPT using OpenAPI.

Expected routes:

```text
GET /health
GET /v1/draft/decision
GET /openapi.json
```

The decision endpoint is bearer authenticated. The Custom GPT instructions require a fresh decision call for current-draft questions, recommendations only from packet candidates, and deterministic fallback when the Action cannot retrieve current state.

The Action cannot make, undo, or modify a Yahoo selection.

## Observability

Draft sessions append JSONL events to `data/draft_logs/`.

The session-start event captures reproducibility metadata and source snapshots. Runtime events capture synchronization attempts/results, pre/post state, manual changes, CLI decision packets, gateway packets, and stale-state blocks.

This provides sufficient evidence to reconstruct many historical decision points after the draft. The next architectural step is a query/audit layer over these logs, not a second logging implementation.

Raw logs intentionally remain private because copied Yahoo ranges can contain participant chat/usernames and the session manifest can embed externally derived source datasets.

## Operational Failure Model

The architecture assumes individual layers can fail during a timed draft.

- bad/incomplete Yahoo input -> synchronization fails closed;
- stale local state -> deterministic recommendation is blocked;
- gateway/tunnel/model unavailable -> use the deterministic CLI;
- system restart -> recover persisted `data/draft_state.json`, do not recreate the draft;
- high LLM latency -> stop troubleshooting and use the current deterministic recommendation.

The system is therefore designed as decision support with graceful degradation rather than a model-dependent drafting bot.
