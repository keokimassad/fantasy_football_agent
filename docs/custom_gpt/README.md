# Custom GPT Integration

This directory contains the version-controlled material used to configure the private Fantasy
Football Agent Custom GPT.

The Custom GPT is a reasoning layer over the deterministic draft engine. It is **not** a second
source of draft truth and it has no authority to modify draft selections.

## Files

```text
docs/custom_gpt/
├── README.md
├── instructions.md
└── yahoo_auto_draft_2026.md
```

### `instructions.md`

Paste this file into the Custom GPT **Instructions** field.

It contains the concise, always-on behavior contract:

- call `getDraftDecision` before answering current-draft questions;
- treat the deterministic packet as authoritative for factual draft state;
- recommend only players present in the packet's candidate set;
- follow `WAITING`, `ON_CLOCK`, and `COMPLETE` phase behavior;
- do not invent injuries, suspensions, player roles, availability, or opponent behavior;
- fall back to the deterministic CLI when the Action cannot retrieve current state;
- never claim to make or modify a selection; and
- apply the compact 2026 Yahoo auto-draft tendencies only as soft guidance.

Keep this file concise enough for the provider's Instructions field. Do not move essential safety or
authority boundaries into Knowledge merely to save space.

### `yahoo_auto_draft_2026.md`

Upload this file to the Custom GPT as a **Knowledge** document.

It contains supporting context that is useful but does not need to be repeated in every instruction,
including:

- historical Yahoo auto-draft behavior;
- the observed behavior shift over recent seasons;
- the 2026 working round-window hypotheses;
- interpretation of QB2/TE2 and late DEF/K behavior; and
- hypotheses for future validation.

The observations are specifically scoped to **2026 Yahoo Fantasy Football, 10-team, 15-round redraft
snake drafts**. They are not calibrated probabilities and should not be generalized automatically to
other league formats or future seasons.

## Source-of-truth hierarchy

For a live draft, use this hierarchy:

```text
Yahoo / local recorded draft state
        ↓
deterministic engine
        ↓
DraftDecisionPacket
        ↓
Custom GPT reasoning
        ↓
user final decision
```

Knowledge documents can influence interpretation and strategy, but they must never override the
Action's factual statements about who is available, who has been drafted, the current pick, roster
state, or league rules.

## Action setup

The Custom GPT Action consumes the read-only gateway's generated OpenAPI schema.

Expected routes:

```text
GET /health
GET /v1/draft/decision
GET /openapi.json
```

`/v1/draft/decision` requires the same bearer secret configured separately in the Custom GPT Action.
Never place the bearer secret, Yahoo OAuth credentials, ngrok auth token, or any other private
credential in this directory or in the OpenAPI schema.

Operational gateway/tunnel setup and secret lifecycle belong in the root
[`DEVELOPMENT.md`](../../DEVELOPMENT.md).

## Updating the Custom GPT

When behavior changes:

1. edit the repository file first;
2. copy the updated `instructions.md` into the Custom GPT Instructions field;
3. re-upload `yahoo_auto_draft_2026.md` when its Knowledge content changes;
4. test a fresh Action call rather than relying on remembered draft state;
5. revalidate phase behavior when instruction changes are material; and
6. verify the deterministic CLI still provides a complete fallback.

If the provider configuration differs from these version-controlled files, treat the repository as
the intended configuration and reconcile the provider copy.

## What belongs here

Good candidates:

- provider-facing behavioral instructions;
- Custom GPT Knowledge documents;
- Action-specific setup notes;
- validation procedures or examples tied specifically to the Custom GPT integration.

Do **not** put these here:

- live draft state;
- full Yahoo ranking datasets;
- league secrets or OAuth files;
- gateway/ngrok credentials;
- Python runtime configuration; or
- generated draft artifacts.
