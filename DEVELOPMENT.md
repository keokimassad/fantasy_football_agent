# Development Guide

This document contains local development, testing, quality-gate, and smoke-test workflows for the Fantasy Football Agent project.

For project goals, architecture, setup, and end-user draft workflows, see [README.md](README.md).

## Development Environment

The project targets Python 3.12.

Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install the package in editable mode with development dependencies:

```bash
python -m pip install -e ".[dev]"
```

Editable installation is important because the command-line entry points execute the local source tree.

If `pyproject.toml` changes an entry point, dependency, or package metadata, reinstall:

```bash
python -m pip install -e ".[dev]"
hash -r
```

Confirm installed commands when needed:

```bash
command -v ff-draft
command -v ff-draft-update
command -v ff-draft-new
```

## Primary CLI Commands

Create a fresh draft session:

```bash
ff-draft-new --type mock --slot <SLOT> --workspace .
```

Replace an existing active mock explicitly:

```bash
ff-draft-new \
  --type mock \
  --slot <SLOT> \
  --replace \
  --workspace .
```

Synchronize copied Yahoo draft chat on macOS:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

Run deterministic draft analysis:

```bash
ff-draft --workspace .
```

Undo the last recorded selection:

```bash
ff-draft-update --undo --workspace .
```

## Full Quality Gate

Run this before committing or merging a meaningful feature:

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

Expected results:

- Ruff formatting passes.
- Ruff lint passes.
- strict mypy passes.
- test documentation validation passes.
- all tests pass.
- total branch-aware coverage remains at or above 90%.

If formatting fails, apply Ruff formatting:

```bash
python -m ruff format src tests scripts tools
```

Then rerun the full quality gate.

## Formatting and Linting

Check formatting:

```bash
python -m ruff format --check src tests scripts tools
```

Apply formatting:

```bash
python -m ruff format src tests scripts tools
```

Run lint checks:

```bash
python -m ruff check src tests scripts tools
```

## Static Type Checking

Run strict mypy checks:

```bash
python -m mypy src tests
```

Yahoo third-party libraries are isolated behind local typed boundaries so unit tests and the deterministic engine can remain strictly typed without requiring broad `Any` usage.

## Test Documentation Check

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

## Running Tests

Run the complete test suite:

```bash
python -m pytest
```

Run one test file:

```bash
python -m pytest tests/unit/yahoo/test_draft_sync.py
```

Run several related files:

```bash
python -m pytest \
  tests/unit/cli/test_draft_updater.py \
  tests/unit/draft/test_session.py \
  tests/unit/yahoo/test_draft_chat.py \
  tests/unit/yahoo/test_draft_sync.py
```

Run tests verbosely:

```bash
python -m pytest tests/unit/cli/test_draft_updater.py -v
```

Run a single test by node ID:

```bash
python -m pytest \
  tests/unit/cli/test_draft_updater.py::test_read_terminal_input_uses_tty_when_stdin_is_piped \
  -v
```

## Coverage

Run branch-aware coverage:

```bash
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing
```

Generate an HTML coverage report when deeper investigation is useful:

```bash
python -m pytest \
  --cov=fantasy_football_agent \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=html
```

Open it on macOS:

```bash
open htmlcov/index.html
```

The repository enforces a minimum of 90% branch-aware coverage. Coverage should guide testing toward meaningful untested behavior, not toward tests whose only purpose is reaching 100%.

## Pre-commit

Install the Git hook once per clone:

```bash
python -m pre_commit install
```

Run all configured hooks manually:

```bash
python -m pre_commit run --all-files
```

Pre-commit is intended as a fast local safety net. The full pytest/coverage gate remains part of CI and should be run manually before important merges.

## Test Philosophy

Prefer tests of observable behavior and meaningful boundaries over tests coupled to implementation details.

Important deterministic behaviors include:

- snake-draft ownership and round turns;
- roster and FLEX accounting;
- player availability;
- tier boundaries and scarcity;
- player identity;
- duplicate-draft prevention;
- state persistence;
- undo;
- active lookahead;
- opponent exposure.

Important Yahoo-boundary behaviors include:

- structural parsing of Yahoo draft-chat selections;
- tolerance of arbitrary non-selection chat;
- abbreviated player resolution;
- ambiguous player detection;
- overlapping-history verification;
- missing-pick gap detection;
- historical conflict detection;
- incremental persistence;
- interactive ambiguity resolution while draft data is piped through stdin.

Tests that exercise external Yahoo APIs should be kept separate from deterministic unit tests.

## Yahoo API Integration Check

The Yahoo API is not required for the copied-chat draft workflow.

When valid OAuth credentials and Yahoo Fantasy Sports API access are available, run:

```bash
python scripts/check_yahoo_connection.py
```

This command may access the network and should not be treated as part of deterministic unit testing.

Never commit `oauth2.json`, access tokens, refresh tokens, client secrets, or real private league data.

## Yahoo Draft-Chat Smoke Test

Use a disposable local mock state when validating the full copied-chat path.

Create the mock:

```bash
ff-draft-new \
  --type mock \
  --slot 4 \
  --draft-id yahoo-chat-smoke-test \
  --replace \
  --workspace .
```

Feed representative Yahoo-style text:

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

The `B. Robinson` selection intentionally exercises an ambiguous Yahoo abbreviation. Select the intended player at the terminal prompt.

Expected behavior:

- pick #1 is recorded;
- ambiguous identity is surfaced rather than guessed;
- the terminal remains interactive even though draft data arrived through stdin;
- picks #2-#4 continue after ambiguity is resolved;
- active state advances to overall pick #5;
- the slot-four roster contains the player selected at pick #4.

Then run:

```bash
ff-draft --workspace .
```

## Overlap Recovery Smoke Test

Incremental persistence and overlap verification are intentionally supported.

If synchronization stops after earlier picks were saved, do not automatically reset the draft. Copy a recent Yahoo range again and rerun:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
```

Already-recorded matching selections should be reported as verified, and synchronization should resume at the first new expected pick.

A conflict or missing-pick gap should stop synchronization instead of silently rewriting or skipping state.

## Real Mock-Draft Acceptance Testing

Before a Yahoo mock:

```bash
ff-draft-new \
  --type mock \
  --slot <YAHOO_MOCK_SLOT> \
  --replace \
  --workspace .
```

During the mock:

```bash
pbpaste | ff-draft-update --yahoo-chat --workspace .
ff-draft --workspace .
```

Observe and record issues in these areas:

- time required to copy and synchronize Yahoo chat;
- unexpected Yahoo formatting;
- unresolved or ambiguous player references;
- synchronization gaps or conflicts;
- whether copied overlap ranges recover cleanly;
- analysis readability under the draft clock;
- whether displayed tier and lookahead information changes decisions.

The first real mocks are acceptance tests. Prefer fixing observed workflow problems over adding speculative functionality.

## Git Workflow

A typical feature workflow:

```bash
git switch main
git pull
git switch -c feature/<feature-name>
```

Before commit, run the full quality gate, then review:

```bash
git status
git diff
```

Commit and push using the normal Git workflow.

## CI

GitHub Actions runs the repository quality gate on supported pushes and pull requests.

Local development should use the same fundamental checks so CI confirms work rather than becoming the first place errors are discovered.

## Current Development Milestone

The project is currently **mock-draft ready**.

The next engineering sequence is:

1. run real Yahoo mock drafts;
2. harden synchronization and live UX from observed failures;
3. build deterministic candidate evaluation;
4. add one AI agent over structured deterministic outputs;
5. evaluate whether specialized multi-agent roles add measurable value.
