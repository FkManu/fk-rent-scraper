# Affitto 2.3 Stable

Affitto 2.3 Stable is a Windows-oriented research and engineering project focused on reverse engineering, observing, and hardening browser-based monitoring workflows for Italian real-estate portals.

This repository is the promoted stable line of the former `2.3_test` cycle. It preserves the modular architecture introduced in the `2.2` generation and packages it as a more mature, operator-friendly baseline with a clear separation between scraping logic, runtime state, anti-bot observability, notifications, GUI operations, and Windows distribution.

The project should be read as a reverse-engineering and browser-observability system, not as a generic "scraper script". Its main engineering value lies in how it models live automation as a stateful runtime with diagnostics, budgets, cooldowns, persistent browser identities, service lifecycle controls, and regression coverage.

## What The Project Does

Affitto monitors public property-search pages, extracts listing data, deduplicates results locally, and dispatches alerts when genuinely new items appear.

The active line supports:

- site-specific extraction for `idealista.it` and `immobiliare.it`
- private-only filtering through agency-signal detection
- SQLite-backed listing persistence and notification state
- Telegram notifications and SMTP email digests
- one-shot fetch mode and continuous live-service mode
- persistent browser personas and profile generations
- anti-bot state tracking with cooldown, challenge, blocked, degraded, and assist-required states
- Windows GUI control for configuration, runs, resets, and monitoring
- PyInstaller-based Windows packaging

## Why This Repository Matters

From an engineering perspective, this repository is interesting because it combines concerns that are often fragmented across many prototypes:

- reverse engineering of changing public web interfaces
- runtime reliability for browser automation under friction
- typed configuration and secret handling
- deterministic browser identity and render-context instrumentation
- stateful recovery decisions instead of blind retries
- operator tooling through both CLI and GUI
- packaging and testability for a Windows-first deployment model

For a technical reviewer or employer, the strongest signal is not just the extraction itself. It is the quality of the surrounding system: observability, lifecycle control, data hygiene, explicit failure states, and iterative architecture.

## Current Positioning

This repository is now the `2.3_stable` line.

Historically:

- the line started as `2.3_test`
- it was opened as the next controlled iteration on top of the `2.2` stable baseline
- it has now been promoted as a stable line and should be described accordingly in the documentation

The codebase currently reflects a stable `camoufox`-based runtime with deterministic browser persona handling, guard-state persistence, and continuous-service orchestration.

## Validation Snapshot

The local regression suite in this workspace passed successfully:

- `100` tests passed with `.\.venv\Scripts\python.exe -m pytest`

## Architecture

The main implementation lives in `src/affitto_v2/` and is intentionally split by concern.

### Application Layer

- `src/affitto_v2/main.py`
  Owns CLI command parsing, service lifecycle, one-shot execution, runtime disposition, config overrides, and email diagnostic commands.
- `src/affitto_v2/gui_app.py`
  Provides a Tkinter-based operator console for URLs, notification channels, runtime actions, guard resets, live logs, and Windows autostart management.
- `run.py`
  Source entrypoint for the repository.

### Configuration And Models

- `src/affitto_v2/models.py`
  Defines the Pydantic configuration schema for search URLs, extraction options, runtime cadence, storage, Telegram, and email delivery.
- `src/affitto_v2/config_store.py`
  Loads, validates, creates, and atomically writes JSON configuration.
- `src/affitto_v2/paths.py`
  Resolves source-mode versus bundle-mode paths for config, database, logs, and runtime data.

### Persistence

- `src/affitto_v2/db.py`
  Creates and manages the SQLite schema for listings, blocked agency patterns, private-only agency memory, and small application state.

The persistence layer handles:

- deduplication via normalized listing fingerprints
- notification markers per channel
- retention cleanup
- blocked-agency filtering
- email verification/test state
- professional-agency caching for private-only logic

### Notification Stack

- `src/affitto_v2/notifiers/telegram_notifier.py`
  Sends HTML-formatted Telegram alerts and surfaces transport/API failures explicitly.
- `src/affitto_v2/notifiers/email_notifier.py`
  Sends SMTP test messages and batched digests.
- `src/affitto_v2/pipeline.py`
  Applies final filtering, persists new listings, batches email sends, sends Telegram notifications, and degrades channels gracefully without crashing the run.

### Email Profiles And Secret Handling

- `src/affitto_v2/email_profiles.py`
  Stores reusable sender profiles and encrypts sensitive fields at rest.
- `src/affitto_v2/email_setup.py`
  Classifies email readiness and records the last connection/send verification result.
- `src/affitto_v2/secret_crypto.py`
  Handles secret protection and unprotection with Windows-aware behavior.

### Scraper Runtime

- `src/affitto_v2/scrapers/live_fetch.py`
  Main orchestration layer for fetch attempts, site outcomes, guard logic, retries, diagnostics, and final run reports.
- `src/affitto_v2/scrapers/core_types.py`
  Defines the runtime contracts: budgets, telemetry snapshots, session slots, outcomes, guard decisions, and reports.
- `src/affitto_v2/scrapers/sites/idealista.py`
  Encodes Idealista-specific selectors and publisher/private-only heuristics.
- `src/affitto_v2/scrapers/sites/immobiliare.py`
  Encodes Immobiliare-specific selectors, list switching, and scroll behavior.

### Guard State And State Machine

- `src/affitto_v2/scrapers/guard/state_machine.py`
  Maps fetch outcomes to observable runtime states such as `warmup`, `stable`, `suspect`, `challenge_seen`, `degraded`, `cooldown`, `blocked`, and `assist_required`.
- `src/affitto_v2/scrapers/guard/store.py`
  Persists strikes, cooldown timers, warmup progress, profile generations, and guard snapshots.

This layer is central to the project's reverse-engineering value because it treats anti-bot friction as a measurable system with state transitions and explicit operator consequences.

### Browser Identity, Persona, And Render Context

- `src/affitto_v2/scrapers/browser/session_policy.py`
  Defines per-site browser policy, user agent, hardware signature, bootstrap URLs, and pacing parameters.
- `src/affitto_v2/scrapers/browser/persona.py`
  Generates deterministic `CamoufoxPersona` records and persistent profile roots per site and profile generation.
- `src/affitto_v2/scrapers/render_context.py`
  Installs a browser init script to normalize exposed browser values such as `navigator.userAgent`, WebGL identity, and canvas offsets.
- `src/affitto_v2/scrapers/browser/bootstrap.py`
  Handles early resource bootstrap and interaction pacing.
- `src/affitto_v2/scrapers/browser/factory.py`
  Owns browser cleanup, session-slot cleanup, and persistent-profile destruction when needed.

## Runtime Model

The system can operate in two main modes:

### One-Shot Fetch

Used for bounded runs or operator-triggered checks.

Flow:

1. load config and runtime paths
2. fetch listings from configured URLs
3. classify site outcomes and update guard state
4. run the notification pipeline
5. exit cleanly with a summarized report

### Continuous Live Service

Used for unattended monitoring.

The service mode adds:

- cycle cadence control
- jittered sleep planning
- cycle-overrun detection
- missed-slot detection
- runtime-disposition decisions after each cycle
- selective recycle of one affected site slot or the full shared runtime
- graceful stop via stop-flag file

## CLI Commands

The stable line exposes the following primary CLI commands:

- `init-config`
- `validate-config`
- `init-db`
- `doctor`
- `gui`
- `init-email-profiles`
- `list-email-profiles`
- `upsert-email-profile`
- `email-status`
- `test-email`
- `test-pipeline`
- `fetch-live-once`
- `fetch-live-service`

## GUI Capabilities

The GUI is intended as an operational console, not only as a demo interface.

It supports:

- editing and sanitizing supported search URLs
- Telegram and email configuration
- sender-profile management
- blocked-agency management
- private-only toggles
- one-shot and continuous run control
- guard-state reset
- database reset
- runtime privacy reset
- live log viewing
- optional Windows autostart

## Documentation Layout

The repository contains both live and archived documentation.

Key documents for the stable line include:

- `README.md`
- `docs/repo_summary.md`
- `docs/context/README.md`
- `docs/context/HANDOFF.md`
- `docs/context/NEXT_STEPS.md`
- `docs/context/2_3_STABLE_MANIFEST.md`
- `docs/context/STRATEGY_2_3_STABLE.md`
- `docs/context/STATE_MACHINE_2_3_STABLE.md`
- `docs/context/STOP_TRIGGERS_2_3_STABLE.md`
- `docs/context/EXPERIMENT_PLAN_2_3_STABLE.md`
- `docs/context/PROMOTION_GATE_2_3_STABLE.md`
- `docs/risk_scoring_e_griglia_segnali_antibot.md`

## Repository Structure

```text
repo-root/
+-- src/affitto_v2/         # application, persistence, notifications, scraper runtime
+-- tests/                  # regression suite
+-- docs/                   # live documentation and historical context
+-- scripts/                # setup and packaging helpers
+-- packaging/              # PyInstaller entrypoints and specs
+-- requirements.txt
+-- requirements-packaging.txt
+-- run.py
```

## Evolution

This stable line sits in a broader repository history:

- `v1_stable`: compact legacy prototype with much tighter coupling
- `v2_test`: first structured v2 laboratory
- `2.1_stable`: first consolidated stable baseline with config, DB, GUI, and email setup
- `2.2_stable`: major hardening and architectural refactor
- `2.3_stable`: promoted line built on top of the `2.2` runtime model

## Packaging

The repository includes Windows packaging support through PyInstaller specs and helper scripts.

The stable bundle naming now targets the `2.3_stable` line and is intended for operator-facing distribution rather than source-only usage.

## Safety And Research Boundaries

This project is best understood as an engineering study of browser automation under friction.

Its design intentionally emphasizes:

- observability over brute-force retry behavior
- explicit degraded and blocked states
- cooldowns and stop reasons
- persistent state and diagnostics
- operator review when automation should stop

That makes it useful for:

- reverse engineering of web interaction patterns
- browser automation reliability research
- internal monitoring-tool design
- applied state-machine design for unstable web environments
- Windows operator tooling around automation

## Quick Start

```powershell
pip install -r requirements.txt
python run.py init-config
python run.py doctor
python run.py fetch-live-once
```

To start the GUI:

```powershell
python run.py gui
```

To run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Technical Takeaway

Affitto 2.3 Stable demonstrates how to evolve a fragile browser-automation idea into a more professional system with:

- typed configuration
- modular architecture
- persistent local state
- runtime diagnostics
- stateful anti-bot observability
- operator-facing controls
- regression coverage

In short, it is a focused case study in production-minded reverse engineering and runtime hardening for browser-based monitoring workflows.
