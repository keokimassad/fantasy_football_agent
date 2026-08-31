# 2026 Yahoo Auto-Draft Observations

This file provides supporting context for the Fantasy Football Agent's concise auto-draft instructions. The behavioral rules in the Custom GPT Instructions remain authoritative; this document adds history and interpretation.

## Scope
Observed in 2026 Yahoo Fantasy Football mock drafts using a standard:
- 10-team league
- 15-round draft
- redraft format
- snake draft

Do not assume the same behavior for other league sizes, roster structures, dynasty/keeper, best ball, auction drafts, or future Yahoo seasons.

## Historical change
The user has tracked Yahoo auto-draft behavior for years.

Older Yahoo auto-draft behavior appeared more directly focused on filling the starting lineup. Under that older pattern, DEF and K were often taken at predictable rounds because the algorithm was satisfying remaining starting roster requirements.

The user observed a meaningful behavior shift roughly 2-3 years before the 2026 season. Current 2026 mocks show a different structure: Yahoo appears willing to fill QB2 and TE2 before the late DEF/K completion window, rather than simply completing all starters as early as possible.

Therefore, prioritize repeated 2026 observations over older generic Yahoo auto-draft assumptions.

## Activation rule

These observations model Yahoo auto-draft behavior, not generic opponent behavior.

For a real league:
- known human -> use human strategic reasoning;
- unknown control status -> default to human-like reasoning;
- strongly auto-like behavior -> use these tendencies as supporting evidence;
- confirmed auto-draft -> use these tendencies strongly.

Do not infer that an opponent has low RB/WR demand simply because its starting lineup is complete.
A human may continue drafting RB/WR bench value instead of immediately filling K or DEF.

The auto-draft model should therefore modify opponent-survival reasoning only when there is evidence
that the opponent is actually following Yahoo auto-draft behavior.

## Current working hypotheses
For a typical 15-round 2026 Yahoo mock:
- R1-5: RB/WR dominate, with premium QB/TE exceptions.
- R6: QB1 selection pressure rises substantially.
- R7: TE1 selection pressure rises substantially.
- R8-10: RB/WR depth and remaining starter cleanup.
- R10-12: QB2 becomes plausible; R11 is the current central expectation.
- R12: TE2 is notably common.
- R13: remaining bench/value cleanup.
- R14-15: DEF and K are rapidly completed; their order can flip.

These are tendencies, not hard scheduling rules. Yahoo player rank/order can cause a premium option to break the normal positional window.

## Strategic implications
A starter-filled position is not equivalent to zero future demand for an auto-drafting team:
- QB1 filled does not eliminate QB demand around the QB2 window.
- TE1 filled does not eliminate TE demand around the TE2 window.
- Late required DEF/K slots can consume picks that a generic model might otherwise assign to RB/WR.

That means RB/WR survival can sometimes be better than raw intervening-pick count suggests.

Conversely, open QB/TE starter slots early in the draft do not necessarily imply immediate selection pressure before their observed auto-draft windows.

Use these patterns alongside actual roster construction, Yahoo rank/ADP, exact pick windows, and deterministic opponent evidence. Never convert these observations into false numeric precision without a calibrated model.

## Future validation
Useful hypotheses to test across labeled auto-draft mocks:
1. QB1 selection hazard spikes around R6.
2. TE1 selection hazard spikes around R7.
3. QB2 selection hazard spikes R10-12.
4. TE2 selection hazard spikes near R12.
5. DEF/K selection hazard spikes R14-15.
6. Yahoo player ordering can override each default positional window.
