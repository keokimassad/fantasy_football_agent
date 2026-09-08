# Live Draft Runbook

This runbook documents the operational setup used for the 2026 Yahoo live draft. Replace placeholders with local values and keep all credentials outside source control.

## Pre-Draft Repository Check

```bash
cd /path/to/fantasy_football_agent
source venv/bin/activate

git switch main
git pull --ff-only
git status

command -v ff-draft
command -v ff-draft-new
command -v ff-draft-update
command -v ff-gateway
```

If the CLI commands are missing after a fresh environment/setup change:

```bash
python -m pip install -e ".[dev]"
```

Do not reinstall packages routinely during a live draft if the commands already resolve.

## Terminal 1 — Draft Synchronization / CLI

Define a helper that only runs analysis after successful synchronization:

```bash
ffmock() {
  pbpaste | ff-draft-update --yahoo-chat --workspace . && \
    ff-draft --workspace .
}
```

Create the actual draft once the slot is known and **before any selections begin**:

```bash
ff-draft-new \
  --type actual \
  --slot <YAHOO_DRAFT_SLOT> \
  --replace \
  --workspace .
```

Verify state:

```bash
ff-draft --workspace .
```

Once the real draft has started, **never rerun `ff-draft-new --replace`**. Recover the persisted state instead.

During the draft, copy a generous overlapping range of Yahoo selections and run:

```bash
ffmock
```

If synchronization reports a missing expected pick, copy a larger overlapping range. Do not reset the draft.

## Terminal 2 — FastAPI Gateway

```bash
cd /path/to/fantasy_football_agent
source venv/bin/activate

export FANTASY_AGENT_GATEWAY_API_KEY="$(<load from local secret store>)"

ff-gateway \
  --workspace . \
  --public-url https://<PUBLIC-HTTPS-HOST>
```

Local health check:

```bash
curl http://127.0.0.1:8000/health
```

Authenticated decision check:

```bash
curl \
  -H "Authorization: Bearer $FANTASY_AGENT_GATEWAY_API_KEY" \
  http://127.0.0.1:8000/v1/draft/decision
```

## Terminal 3 — HTTPS Tunnel

Start the configured HTTPS tunnel to local port 8000. For ngrok, the command is conceptually:

```bash
export NGROK_AUTHTOKEN="$(<load from local secret store>)"
ngrok http 8000 --url https://<RESERVED-HOST>
```

Confirm the public HTTPS host forwards to `http://localhost:8000` and matches the gateway's `--public-url`.

If the hostname changes, update/re-import the Custom GPT Action schema from the new `/openapi.json` endpoint. Do not rotate the bearer secret solely because the tunnel restarted.

## Final End-to-End Check

Before the draft begins:

1. verify deterministic `ff-draft` state;
2. verify local `/health`;
3. verify public `/health`;
4. verify authenticated `/v1/draft/decision`;
5. make one Custom GPT draft-state request;
6. stop changing the system if the full path works.

## Restart Recovery

The active draft persists in:

```text
data/draft_state.json
```

After a restart during a live draft:

1. activate the virtual environment;
2. restart the HTTPS tunnel;
3. restart `ff-gateway`;
4. redefine the shell helper if necessary;
5. run `ff-draft --workspace .` before any destructive action;
6. copy a generous overlapping Yahoo Results/Chat range;
7. run the sync/analyze helper.

Do **not** create a new draft session after picks have begun.

## Clock-Safety Rule

If the model/gateway/tunnel is slow or unavailable while on the clock, stop troubleshooting and use the deterministic CLI recommendation. The AI layer is advisory; missing the Yahoo pick clock is a worse failure than temporarily losing the AI explanation layer.

## 2026 Production Lesson: Yahoo Input Source

Mock drafts were exercised primarily through copied Draft Chat. During the real September 7, 2026 draft, one live client did not expose selection messages in Draft Chat even though another client did.

The working recovery path was Yahoo Results. The current parser handled its numeric selection blocks, and gap detection safely rejected incomplete ranges.

Until source-neutral adapters are implemented, treat Results as an important alternate source and always copy overlapping history rather than only the newest visible selections.
