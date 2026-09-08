# 2026 Live Draft Postmortem

## Summary

On September 7, 2026, Fantasy Football Agent was used end to end during a real Yahoo Fantasy Football draft after several days of mock-draft acceptance testing.

The production session was a 10-team, 15-round, 0.5-PPR snake draft with a 90-second pick clock. The user drafted from slot 10. All 150 league selections were ultimately synchronized, the draft reached `COMPLETE`, and all required starter positions were filled.

The session-start telemetry recorded Python 3.12.8, a clean `main` worktree, and Git commit `8c410b8fdc5718a06098dae7be5d21af39162e79` as the runtime provenance for the live draft.

This postmortem is intentionally sanitized. The raw JSONL remains private because it contains copied Yahoo source text, participant identifiers/chat, and full source snapshots used for reproducibility.

## Architecture Used

The live path was:

```text
Yahoo copied selection data
        |
        v
ff-draft-update synchronization
        |
        v
persisted deterministic DraftState
        |
        v
ff-draft / deterministic candidate evaluation
        |
        v
schema-v3 DraftDecisionPacket
        |
        v
bearer-authenticated FastAPI gateway
        |
        v
HTTPS tunnel
        |
        v
private Custom GPT Action
        |
        v
human final decision
```

Append-only JSONL telemetry ran alongside the normal workflow and preserved synchronization attempts/results, draft state, exact CLI/gateway packets, and source/runtime provenance.

## What Went Well

### Deterministic state remained authoritative

The Custom GPT never owned current pick, availability, roster state, or completed selections. Those facts were supplied by the deterministic packet.

This mattered when synchronization failed or the tunnel/model path was unavailable: the system could fail closed rather than continue from guessed or remembered draft state.

### Turn-pair reasoning worked

Draft slot 10 created consecutive picks at every snake turn. The decision packet exposed `context.consecutive_turn=true`, allowing the AI layer to optimize a two-pick portfolio without inventing survival risk between the user's adjacent selections.

### Strategy remained separate from the baseline

The saved `rb-priority-wait-qb` strategy influenced the AI reasoning layer while every candidate retained its deterministic `baseline_rank`. This allowed explicit discussion of when roster construction justified a deviation and when raw baseline value remained preferable.

### Sync reconciliation protected state

The production log captured multiple incomplete copied ranges. Examples included local state expecting Pick 14 while the supplied range began at Pick 15, expecting Pick 99 while the supplied range began at Pick 102, and expecting Pick 121 while the supplied range began at Pick 124.

In each case, the synchronizer stopped with a gap error instead of silently skipping picks or corrupting historical state. Copying a larger overlapping range allowed recovery.

### The deterministic fallback remained available

The AI integration was useful for strategy and tradeoff explanation, but the CLI remained a complete fallback under the draft clock. Mock testing had already shown that downstream model latency could be materially slower than deterministic packet generation, so draft-day operations treated AI as advisory rather than required for state correctness.

### Historical observability was sufficient for real post-draft reconstruction

The JSONL history made it possible to inspect historical candidate packets and synchronization failures after the draft. The next improvement is an audit/query interface over this existing telemetry rather than a second logging mechanism.

## Production Incident: Yahoo Draft Chat Was Not a Reliable Source

### Expected behavior

Mock-draft acceptance testing primarily used copied Yahoo Draft Chat selection messages. The live workflow therefore assumed those messages would be visible during the real draft.

### Actual behavior

During the real draft, one client did not display draft-selection messages in Draft Chat even though another client did. A copied chat range from the affected client could contain ordinary human messages while yielding zero draft picks.

This created the most serious operational risk of the production draft: the recommendation system itself could be correct while its authoritative state source remained unable to advance.

### Recovery

Yahoo's Results view was used as an alternate source. Its copied representation differed from the mock Draft Chat representation, but it contained numeric selection blocks with player/position/team metadata that the current parser could process.

The system then continued using overlapping Results ranges. When a copied range omitted the exact next expected selection, fail-closed gap detection blocked the update until a broader range was supplied.

### Root cause

The primary issue was not a deterministic recommendation bug. It was an overly narrow operational assumption about where authoritative Yahoo selection text would always be available.

### Follow-up

Promote draft ingestion to a source-neutral interface with explicit adapters for:

```text
Yahoo Draft Chat
Yahoo Results
future direct/API source when reliable
```

The CLI should identify the detected source, parsed pick range, locally expected next pick, and gap/conflict status before mutation.

## Decision-System Findings

### Early/mid-draft construction behaved as intended

The system could preserve a deterministic baseline while applying a strong early-RB preference without turning that preference into an unconditional RB bonus.

The live roster opened with a balanced WR/RB foundation and used the consecutive-turn behavior to make paired decisions rather than independent recommendations.

### Backup-QB marginal utility remains a useful calibration question

At Pick 130, Patrick Mahomes was deterministic baseline #1 because of his value/tier evidence even though the roster already contained Drake Maye and the packet correctly marked QB depth as low roster utility.

The user intentionally selected Mahomes. This is a useful real-world test case for future marginal bench-slot utility: how large must a market/value fall be to justify using scarce optional capacity on QB2 or TE2?

No immediate retuning is warranted from a single draft outcome.

### Final TE selection was user-predecided, not an engine recommendation failure

The final Pick 150, Terrance Ferguson, was a deliberate user choice for backup TE. The user did not request a fresh on-clock GPT recommendation because the selection had already been decided.

Future audit data should therefore distinguish selection provenance instead of assuming every final pick represents the model's preferred candidate.

Suggested provenance values:

```text
SYSTEM_RECOMMENDED
USER_OVERRIDE
USER_PREDECIDED
AUTO_DRAFTED
UNKNOWN
```

### Role/depth-chart facts were outside the deterministic packet

Questions about whether a player was the current starter, direct backup, or part of a committee exposed a real information boundary. The system correctly avoided manufacturing those facts.

A future separately sourced player-role layer should include source timestamp and confidence and must not override authoritative draft ownership/availability state.

## Privacy and Archive Policy

The raw production log is valuable as a private engineering artifact, but it should not be committed to the public repository as-is.

Raw telemetry can contain:

- copied participant chat/usernames;
- raw Yahoo selection text;
- private league/config context;
- complete source snapshots, including externally derived ranking data;
- operational state not intended as a stable public API.

The active `data/draft_state.json` should also remain ignored. Tracking the runtime path would create a future risk of accidentally committing another live league state.

For public evidence, this repository instead includes [`../live_draft/2026-final-state.json`](../live_draft/2026-final-state.json), a frozen derivative that removes participant names, chat, league name, raw source text, source datasets, and Yahoo player IDs while preserving the completed draft board and runtime provenance.

The raw JSONL should be backed up privately if long-term personal/audit preservation is desired.

## 2027 Priorities

1. Multi-source Yahoo ingestion with dedicated Draft Chat and Results adapters.
2. Audit/query API or CLI over the existing JSONL history.
3. Selection provenance for user/system/autodraft decisions.
4. Separately sourced current player-role/depth-chart metadata.
5. Marginal optional-roster utility calibration, especially QB2/TE2.
6. Realized return-risk calibration from mock and production histories.
7. Opponent human/auto classification before stronger Yahoo auto-draft assumptions.
8. Reuse the deterministic-first architecture for in-season lineup, waiver, trade, and roster-management workflows.

## Outcome

The real draft validated the project's central architectural choice: keep factual state deterministic and make the AI layer replaceable/advisory.

The most important production lesson was upstream of the recommendation algorithm. An input-source assumption that survived all mocks failed in the real environment, but conservative synchronization, persisted state, and a manual alternate source allowed the draft to complete without corrupting authoritative state.
