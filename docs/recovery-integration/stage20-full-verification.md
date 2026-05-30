# Stage 20F Final Full Verification

## Scope

Final safe verification rerun after the Stage 20A/20C/20D/20E blockers were
fixed. No production bot, deploy, push, commit, tag, PR, payment action,
refund, chargeback, secrets/env-file change, archive work, `New project 2
CLEAN` work, or recovered-bot work was performed.

## Git Snapshot

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `aa8336a250d0357e819904e0786abfbf1c0ea108`
- `git status --short` before tests: dirty integration worktree with 48
  modified tracked entries and 222 untracked entries/directories reported by
  porcelain status.
- The dirty status was pre-existing integration scope. This verification rerun
  changed docs only after all required checks passed.

## DSN-Backed Coverage

- `DIET_BOT_TEST_DATABASE_URL` was not pre-set in the shell.
- Full `pytest -q` used a disposable local Docker Postgres database named
  `diet_bot_test`, bound to `127.0.0.1` on an ephemeral host port.
- The DSN lived only in the test process environment and was not printed,
  written to an env/secrets file, or persisted.
- Temporary PostgreSQL client shims were created in the system temp directory
  so the restore-drill integration test could find `pg_dump`, `createdb`,
  `pg_restore`, and `dropdb`; they were removed after the run.
- The disposable Postgres container was stopped and removed after the run.

## Full Pytest Result

Command:

```powershell
pytest -q
```

Result:

- `1067 passed, 1 skipped in 1333.36s (0:22:13)`
- Exit code: `0`

Skip attribution was checked with:

```powershell
pytest tests/test_pdf_renderer.py tests/test_weekly_selector_scoring.py -q -rs
```

Result:

- `30 passed, 1 skipped in 35.84s`
- Skip reason: `tests/test_weekly_selector_scoring.py:848: local live QA state test is opt-in`

## Targeted Smoke Results

```powershell
python scripts/dev/recipe_content_audit.py
```

- Exit code: `0`
- `recipes_checked=665`
- `ingredients_checked=6130`
- `foods_checked=359`
- `nutrition_rows_checked=665`
- `blocking_findings=0`
- `warning_findings=1221`
- Known warning backlog includes `ingredient_missing_from_steps.warnings=917`,
  `truncation_fragments.warnings=171`, and
  `missing_approximate_measures.warnings=133`.

```powershell
python scripts/dev/pdf_renderer_recovery_smoke.py
```

- Exit code: `0`
- `rendered_pdfs=8`
- `recipes_checked=210`
- Output directory: `tmp/pdf-renderer-recovery-smoke`

```powershell
python -m diet_bot.healthcheck
```

- Exit code: `0`
- Ran with safe local `PYTHONPATH=src`, dummy local bot token, JSON storage,
  payments disabled, and no database/provider token.
- Result: `issues: none`

```powershell
python -m scripts.ops.production_preflight --mode controlled-qa
```

- Exit code: `0`
- Ran against a fresh disposable local Docker Postgres database with required
  schemas initialized locally.
- Payments were disabled, provider token absent, controlled-QA markers set, and
  tester scope present.
- Result: `result: PASS`

```powershell
git diff --check
```

- Exit code: `0`
- Output contained existing LF-to-CRLF working-copy warnings only.

## Skips And Timeouts

- Full suite skips: `1`.
- Skip reason: local live QA state test is opt-in.
- Timeouts: none observed.

## Remaining Known Risks

- Live Telegram manual smoke remains unrun by this verification pass and still
  requires explicit user approval before any bot restart.
- No live YooKassa/Telegram Stars payment, refund, chargeback, deploy, or
  production database action was performed.
- Recipe audit still reports non-blocking warning backlog: `1221` warnings,
  including `133` remaining missing-approximate-measure warnings.
- PDF visual overlap cannot be fully proven by unit tests alone, but the
  recovery renderer smoke completed and produced the expected eight PDFs.
- Sales follow-up launch and `FOOD20` remain blocked until their separately
  approved stages.

## Verdict

Ready for manual-smoke bot restart, subject to explicit user approval and the
existing no-deploy/no-payment safety gates.
