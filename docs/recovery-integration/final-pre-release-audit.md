# FoodBalance Final Pre-Release Audit

Date: 2026-05-31

Verdict: BLOCKED.

This audit was read-only first. It was stopped after a launch blocker was found,
per the prompt stop conditions. No application code, production data, config,
secrets, production DB, Telegram API, bot runtime, payment provider action,
deploy, push, commit, tag, or PR was changed by this audit.

## 1. Executive Summary

The current release candidate is not ready for final manual-smoke bot restart
or production launch.

The blocking issue is recipe/data quality in the existing production pool
outside the selected-53 import. A read-only all-production structural scan found
severe nutrition/profile outliers, including `acai_puree` mapped to an FDC
source description for baking chocolate and recipes with user-facing saved KBJU
far beyond expected single-serving ranges. Because these recipes remain in the
production pool, user-facing generation can still produce materially distorted
nutrition.

The selected-53 range `r666` through `r710` is numerically consistent and
photo-complete, but it is not clean for launch either: `r678` contains a broken
OCR/source-text fragment in the user-facing instructions.

Other high risks were found in Telegram/admin handling, payment reversal ingress
for paid launch, and durable worker liveness. These did not replace the recipe
blocker as the first stop condition, but they should be fixed or explicitly
accepted before wider release.

## 2. Checked Version

- Working folder:
  `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Important state: this is a dirty working tree release candidate. HEAD alone
  is not the final release state.
- Initial and final `git status --short`: already dirty with expected tracked
  recovery/payment/recipe/test changes plus untracked recovery docs,
  selected-53 photos, and staging files. This audit added only this report and
  temporary artifacts under `tmp/final-pre-release-audit/**`.

## 3. Already Fixed Before This Audit

The recovery docs state that the following were completed before this audit:

- External audit blockers for fish exclusion, weekly constrained fallback,
  payment double-click pending invoices, refund/reversal subscriptions, and
  reconciliation.
- Extra-purchase refund/cancel/reversal access leak: current code decrements
  one unused extra unit and keeps manual review for audit follow-up.
- Selected-53 import as `r666` through `r710`, then seven post-import
  recipe-data fixes, then the `sour_cream` nutrition side-effect fix.
- Final selected-53 post-fix quality review previously reported
  `READY FOR FINAL MANUAL SMOKE`.

This audit found that broader production data still has blocker-level issues.

## 4. Checks Actually Performed

- Provenance capture: branch, HEAD, dirty status, recovery docs.
- Subagent split:
  - Project map / architecture.
  - Telegram UX / questionnaire / unpaid funnel / admin.
  - Recipes / ingredients / nutrition / photos.
  - Concurrency / queues / workers / reliability.
  - Payments / subscriptions / promo / reconciliation security.
  - PDF quality and DevOps agents were started or attempted, then stopped when
    the recipe blocker fired.
- Read-only recipe checks:
  - `python scripts/dev/recipe_content_audit.py --no-write-report`
    - `recipes_checked=710`
    - `ingredients_checked=6478`
    - `foods_checked=362`
    - `nutrition_rows_checked=710`
    - `blocking_findings=0`
    - `warning_findings=1322`
  - `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
    - `249 passed`
  - Extra temporary scans/contact sheets under
    `tmp/final-pre-release-audit/recipes-photos/**`.
- Telegram UX focused local tests:
  - `22 passed`.
- Payment/security focused local tests:
  - `tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py tests/test_payment_reconciliation_report.py`
    -> `74 passed`.
  - `tests/test_payment_service.py tests/test_postgres_payment_store.py tests/test_postgres_promo_store.py`
    -> `35 passed, 29 skipped` in that subagent shell because no
    `DIET_BOT_TEST_DATABASE_URL` was visible there.
  - Focused Telegram/payment/admin safety tests -> `8 passed`.
- Reliability focused local tests:
  - Synthetic high-volume rehearsal checks -> `2 passed`.
  - One-day offload/dedupe/different-chat/durable admission checks -> `11 passed`.
  - Weekly PDF admission plus runtime/preflight worker guards -> `11 passed`.
  - Worker exception/transient claim recovery checks -> `2 passed`.
  - DSN-backed store checks in that subagent shell skipped because no
    `DIET_BOT_TEST_DATABASE_URL` was visible there.
- Local disposable Postgres:
  - A disposable local container
    `foodbalance-pre-release-audit-pg-20260531143838` was started on
    `127.0.0.1`, then stopped after blocker discovery.
  - A full `pytest -q` was started with `PYTHONPATH=src` and the disposable
    DSN. It reached about 65 percent and showed one failure marker, but was
    stopped after the recipe/data blocker was found. No full-suite result is
    claimed.
- `git diff --check`:
  - exit code `0`; output contained LF-to-CRLF working-copy warnings only.

## 5. Skipped Checks

- Full pytest completion: stopped after blocker discovery.
- Fresh PDF-quality audit scenarios: stopped after blocker discovery. Prior
  recovery docs still contain successful PDF smoke evidence, but this audit did
  not complete a new PDF pass.
- DevOps/controlled-QA preflight: stopped after blocker discovery. Static
  review of `.env.example`, runbooks, healthcheck/preflight code, and Postgres
  docs was started, but no fresh controlled-QA preflight result is claimed.
- Real Telegram bot start/restart, polling, webhook, or `getUpdates`.
- Production DB, real secrets, provider sandbox/live payments, refunds,
  cancellations, reversals, chargebacks.
- Deploy, push, commit, tag, PR.
- Forbidden folders and archive/recovered snapshots.

## 6. Zone Status Table

| Zone | Status | Reason |
| --- | --- | --- |
| Project map / architecture | partial | No blocker; high maintainability/doc evidence risk found. |
| Telegram UX / unpaid / admin | problem | Admin promo list fail-closed bug and unpaid funnel scope gap. |
| Recipes / ingredients / nutrition / photos | problem | Blocking production data outliers and high r678 text issue. |
| PDF generation quality | partial | Stopped after blocker; no fresh full PDF audit. |
| Concurrency / queues / reliability | problem | High worker liveness/supervision risks found. |
| Payments / subscriptions / promo / reconciliation | partial/problem | Local tests passed; paid launch lacks reversal ingress/apply path. |
| DevOps / config / DB / backup / deploy readiness | partial | Static docs/config review only; fresh preflight stopped. |

## 7. Blocker Findings

### BLOCKER-1: Legacy Production Recipe/Food Nutrition Outliers

- severity: blocker
- zone: recipes / production data outside selected-53
- file and place:
  - `src/diet_bot/data/curated_foods.json:14`
  - `src/diet_bot/data/curated_recipe_nutrition.json:2024`
  - `src/diet_bot/data/curated_recipe_nutrition.json:5516`
  - evidence artifact:
    `tmp/final-pre-release-audit/recipes-photos/all-production-structural-scan.json`
- what is wrong:
  - `food_id=acai_puree` has source description
    `Baking chocolate, unsweetened, liquid`, with `472 kcal` and `47.7 g fat`
    per 100 g.
  - `r057_asai_boul_s_bananom_golubikoy_i_granatom` has saved nutrition
    `1485.15 kcal`, `121.92 g fat`, `150.90 g carbs`.
  - `r154_tofu_v_kislo_sladkom_souse_general_tso_s_brokkoli_i_ri` has saved
    nutrition `2010.34 kcal`, `354.67 g carbs`.
  - The structural scan reports `37` hard outlier flags across the production
    pool.
- impact:
  - The bot can generate user-facing meal plans with materially distorted KBJU.
  - Recipe selection/scoring may be biased by wrong nutrition values.
  - This invalidates a launch-readiness claim even though selected-53 itself is
    mostly internally consistent.
- how to reproduce:
  - Inspect the files above.
  - Review `tmp/final-pre-release-audit/recipes-photos/all-production-structural-scan.json`.
- how to fix:
  - Audit every hard outlier in the structural scan.
  - Correct wrong food profiles and cooked/raw/portion conversions.
  - Recalculate all affected nutrition rows.
  - Add an invariant that prevents wrong-profile aliases such as
    `acai_puree -> baking chocolate`.
- needed test:
  - A no-wrong-profile-alias test for key foods.
  - A threshold or explicit allowlist test for single-serving kcal, fat, carbs,
    protein, and single-ingredient grams.
- can defer after launch:
  - No.

## 8. High Findings

### HIGH-1: r678 Contains User-Facing OCR Garbage

- severity: high
- zone: selected-53 recipe text
- file and place: `src/diet_bot/data/curated_recipes.json:13232`
- what is wrong:
  - `r678_svekla_s_yogurtom_fistashkami_i_apelsinom` instruction ends with
    `подде жки нкции печени.`
- impact:
  - User sees broken unrelated text in a final recipe.
- how to reproduce:
  - Inspect `curated_recipes.json:13232`.
- how to fix:
  - Remove the garbage tail or replace it with a clean serving sentence.
- needed test:
  - Focused curated-data assertion that `r678` instructions do not contain
    `подде`, `нкции`, or source-note fragments.
- can defer after launch:
  - No.

### HIGH-2: Admin Discount List Can Throw Instead Of Failing Closed

- severity: high
- zone: Telegram admin `/330366`
- file and place: `src/diet_bot/telegram_app.py:6597`
- what is wrong:
  - `_list_postgres_admin_discount_promos()` is typed and consumed as returning
    `list[PromoCodeDefinition]`, but on `EntitlementStorageError` it returns
    `(None, ADMIN_PROMO_STORAGE_ERROR_TEXT)`.
- impact:
  - Admin promo callback can raise an `AttributeError` instead of answering
    with a storage error.
- how to reproduce:
  - Telegram UX subagent local probe produced
    `AttributeError: 'NoneType' object has no attribute 'discount_percent'`.
- how to fix:
  - Return only a list, or raise `EntitlementStorageError` and let the caller
    handle `ADMIN_PROMO_STORAGE_ERROR_TEXT`.
- needed test:
  - Admin list callback with unavailable promo store answers the storage error
    and does not raise.
- can defer after launch:
  - No if admin promo operations are in launch scope.

### HIGH-3: No Production Ingress For Provider Reversal Events

- severity: high
- zone: payments / refund-cancel-reversal ingress
- file and place:
  - `src/diet_bot/payment_service.py:120`
  - `src/diet_bot/postgres_payment_store.py:289`
  - `scripts/ops/payment_reconciliation_report.py:27`
- what is wrong:
  - Reversal service/store APIs exist and local tests pass, but static search
    found no production webhook, provider event consumer, or operator apply
    command calling `handle_payment_reversal()` outside tests.
  - The reconciliation report is read-only.
- impact:
  - Real provider refunds/cancellations/reversals may be detected but not
    automatically applied to revoke access.
- how to reproduce:
  - Search for `handle_payment_reversal` and `record_payment_reversal`.
- how to fix:
  - Add an authenticated provider webhook or safe operator import/apply command
    that validates events, maps statuses, calls `PaymentService.handle_payment_reversal()`,
    preserves idempotency, records audit details, and fails to manual review on
    mismatches.
- needed test:
  - Fake provider event ingress for subscription, extra one-day, extra weekly
    PDF, duplicate event replay, amount/currency mismatch, missing order, and
    DSN-backed transaction persistence.
- can defer after launch:
  - Yes only for non-payment manual smoke with payments disabled. No for paid
    launch.

### HIGH-4: Worker Jobs Have No Hard Per-Job Deadline

- severity: high
- zone: queues / durable workers
- file and place:
  - `src/diet_bot/one_day_generation_job_runtime.py:235`
  - `src/diet_bot/weekly_pdf_job_runtime.py:217`
  - `src/diet_bot/telegram_send.py:176`
- what is wrong:
  - Claimed jobs are processed through `asyncio.gather`, while prepare/send
    operations have no hard per-job deadline. Heartbeat can keep extending the
    lease while the job is stuck.
- impact:
  - One hung generation/upload can occupy a worker slot indefinitely. With low
    default concurrency, queue progress can stop.
- how to reproduce:
  - Static evidence; no hung-send test exists.
- how to fix:
  - Add per-job processing timeout around prepare/send, stop heartbeat on
    timeout, mark retryable/failure/manual-review according to send state, and
    keep the worker claiming other jobs.
- needed test:
  - Fake a hung one-day/weekly job for chat A and assert chat B still completes
    or A times out/requeues without endless lease extension.
- can defer after launch:
  - No.

### HIGH-5: Worker Task Death Is Logged But Polling Continues

- severity: high
- zone: worker supervision / restart preservation
- file and place:
  - `src/diet_bot/telegram_app.py:1959`
  - `src/diet_bot/telegram_app.py:2005`
  - `tests/test_telegram_app_photos.py:622`
- what is wrong:
  - Unexpected worker task death is only logged; polling continues.
- impact:
  - Bot can keep admitting durable jobs while no worker drains the queue until
    manual restart.
- how to reproduce:
  - Existing test asserts crash is observed/logged without restart/fail-fast.
- how to fix:
  - Fail fast by cancelling polling, or restart workers with bounded backoff
    plus alert/health signal.
- needed test:
  - Worker dies while dispatcher is polling; assert `run_bot` exits or restarts
    the worker and does not silently continue admitting jobs.
- can defer after launch:
  - No.

### HIGH-6: Release Evidence Still Contains Stale Reversal Text

- severity: high
- zone: release evidence / payment readiness docs
- file and place:
  - `docs/recovery-integration/final-audit-fixes.md:125`
  - `docs/recovery-integration/extra-purchase-reversal-access-fix.md:29`
  - `src/diet_bot/subscriptions.py:472`
- what is wrong:
  - `final-audit-fixes.md` still says extra one-day / weekly PDF reversals are
    manual-review-only, while later fix docs and current code decrement one
    unused extra unit.
- impact:
  - Payment readiness evidence is internally contradictory.
- how to reproduce:
  - Compare the docs and `_apply_extra_payment_reversal()`.
- how to fix:
  - Add an explicit addendum or update the B-AUDIT-4 note to reference
    `extra-purchase-reversal-access-fix.md` and the current behavior.
- needed test:
  - Release-evidence review checklist or docs consistency check.
- can defer after launch:
  - No for release sign-off docs.

### HIGH-7: Timed Unpaid Funnel Is Design-Only

- severity: high when timed unpaid funnel is launch scope
- zone: unpaid funnel / sales follow-up
- file and place:
  - `docs/recovery-integration/stage18-sales-followup-design.md:5`
  - `src/diet_bot/telegram_app.py:3297`
- what is wrong:
  - Timed unpaid sales follow-up exists as design only. Production code sends an
    immediate trial CTA after a successful free plan, but there is no durable
    2h/1d/2d follow-up queue, opt-out, dedupe, or cancellation implementation.
- impact:
  - If the funnel is expected at launch, it will not exist.
- how to reproduce:
  - Search `sales_followup`, `opt_out`, and `FOOD20` in `src` and tests.
- how to fix:
  - Implement a disabled-by-default durable Postgres `sales_followup_*` queue,
    or explicitly remove timed follow-up from launch scope.
- needed test:
  - Schedule once after successful free trial, never after `/start` only,
    paid access cancels, opt-out cancels, restart does not duplicate.
- can defer after launch:
  - Yes only if timed unpaid follow-up is explicitly out of launch scope.

## 9. Medium Findings

### MEDIUM-1: Repeated `/start` Leaves Questionnaire/Trial State Active

- zone: Telegram questionnaire
- file and place: `src/diet_bot/telegram_app.py:1287`
- issue: `/start` clears support/promo state but not active questionnaire
  session, token, or `TRIAL_CHAT_IDS`.
- impact: user sees fresh start menu while old text-answer session can still
  continue.
- fix prompt: clear questionnaire/trial state on `/start`, or resume the
  current question consistently.
- needed test: active trial questionnaire plus `/start` leaves no stale
  session/token or sends a clear resume.
- can defer after launch: yes.

### MEDIUM-2: Root-Level Legacy Scripts Hard-Code External Paths

- zone: repo hygiene / release artifact
- files:
  - `apply_editorial_notes.py`
  - `combine_fixed_400.py`
  - `.github/workflows/tests.yml`
- issue: many root-level workbook/photo scripts hard-code local paths such as
  `C:\Users\adck8\Documents\New project 2\outputs\...` and are outside CI
  compile coverage.
- impact: accidental execution can touch outside-repo files; release root is
  noisy and less portable.
- fix prompt: move legacy tools to a clearly marked folder, parameterize paths,
  and exclude or test them intentionally.
- can defer after launch: yes if excluded from release artifact.

### MEDIUM-3: Import Cycles Remain In Core Modules

- zone: module boundaries
- files:
  - `src/diet_bot/recipe_catalog.py`
  - `src/diet_bot/curated_data.py`
  - `src/diet_bot/entitlement_storage.py`
  - `src/diet_bot/subscriptions.py`
- issue: static import scan found cycles `curated_data <-> recipe_catalog` and
  `entitlement_storage <-> subscriptions`.
- impact: currently mitigated by local imports, but boundaries are weak.
- fix prompt: move shared recipe/entitlement models to neutral modules.
- can defer after launch: yes.

### MEDIUM-4: Global Entitlement Advisory Lock Can Cross-Block Users

- zone: durable admission / Postgres lock contention
- files:
  - `src/diet_bot/postgres_one_day_generation_job_store.py`
  - `src/diet_bot/postgres_weekly_pdf_job_store.py`
  - `src/diet_bot/postgres_entitlement_store.py`
- issue: one-day and weekly PDF admission/start paths use a single global
  entitlement advisory lock.
- impact: a slow transaction after taking the lock can block unrelated users.
- fix prompt: replace per-chat generation admission/start/refund paths with
  per-chat row/advisory locking; keep global lock only for whole-map import/save
  flows.
- needed test: DSN-backed two-chat contention test.
- can defer after launch: yes, but fix before scaling.

## 10. Low Findings

- README and package description still describe an MVP and do not map the
  current Postgres/payments/weekly-PDF/promo/admin release surface.
- Privacy consent is process-memory only; if legal/product requires durable
  acceptance, persist it.
- Selected-53 warning-only approximations remain:
  - `r670` beef tongue as generic beef and kvass as water.
  - `r673` turkey sausage as lean poultry and kvass as water.
  - `r699` kvass as water.
- `r706` keeps `400 g` calamari and high protein; internally consistent but a
  portion warning.
- `per_user_limit` is stored in Postgres promo definitions, but current claim
  logic enforces active redemption by `(code, chat_id)` and `max_redemptions`;
  fix before enabling multi-use discount campaigns such as `FOOD20`.
- Legacy JSON one-day generation path still calls the planner directly in the
  event loop; production Postgres worker guards reduce launch risk.

## 11. Recipes / Photos / PDF

Recipes and photos:

- All 710 recipes have ingredient rows and nutrition rows.
- No missing food references were found by the structural scan.
- No missing/open-broken photos were found by the structural scan.
- Selected-53 `r666` through `r710`:
  - `45/45` recipes present.
  - `45/45` photos open.
  - `0` nutrition mismatches against current food catalog and ingredient grams.
  - `0` selected-range hard KBJU outliers.

However, production data is blocked by legacy outliers, and `r678` has broken
instruction text.

PDF:

- This audit did not complete a fresh PDF-quality pass after the blocker.
- Prior recovery docs show successful `pdf_renderer_recovery_smoke.py`, but
  that is historical evidence, not a fresh complete PDF audit result for this
  run.

## 12. PDF Scenarios

- No-filter weekly PDF: skipped in this audit after blocker.
- Filtered/restricted weekly PDF: skipped in this audit after blocker.
- Narrow restrictions / concurrency: skipped in this audit after blocker.
- Selected-53 PDF sample: historical selected-53 final post-fix review says a
  temporary sample covered `r666` through `r710`; not rerun here.

## 13. Unpaid Funnel

The current production code has immediate trial CTA behavior after successful
free plan generation. The timed unpaid funnel remains design-only. If timed
follow-up is part of the launch promise, launch is not ready for that scope.
If it is explicitly out of scope, this becomes a post-launch product task.

## 14. Payments / Security

Local payment tests passed in the safe scope. Current code indicates:

- Stars/YooKassa pricing contract matches current docs/tests.
- Duplicate pending invoice reuse is implemented.
- Extra-purchase reversal decrements one unused extra unit and keeps manual
  review required.
- Current subscription reversal revokes active paid access.
- Reconciliation no longer treats refunded/canceled/reversed provider rows as
  clean granted matches.

Paid launch is still blocked until real provider reversal ingress exists and
manual sandbox/provider refund/cancel/reversal/chargeback acceptance is run.

## 15. DB / Deploy / Backup

Static review observed:

- `.env.example` keeps production storage as Postgres and JSON storage disabled.
- Production worker flags are documented.
- Payment provider secrets are placeholders and payments are disabled by
  default.
- Production and controlled-QA runbooks document safe boundaries.
- Backup/restore docs exist.

Fresh controlled-QA preflight was not run in this audit because the blocker
stopped the run. Production DB, real secrets, and deploy were not touched.

## 16. Can It Be Launched For Testing?

Not as a final user-facing manual-smoke bot restart.

Only an internal fix-verification pass should run next, focused on the recipe
data blocker and the r678 text issue. After those fixes, rerun the relevant
recipe/data tests, recipe audit, and then resume the broader verification.

## 17. Can It Be Launched To Production?

No.

Production launch is blocked by recipe/data quality. Paid production launch has
additional payment-provider gates.

## 18. What Blocks Launch

1. Legacy production recipe/food nutrition outliers.
2. r678 user-facing broken instruction text.
3. Worker liveness/supervision high risks if durable queues are used in a real
   bot session.
4. Admin promo list storage-error crash if admin promo operations are in launch
   scope.
5. Paid launch gate: no production reversal ingress/apply path and no live
   provider/sandbox reversal acceptance.

## 19. Improvements After Launch

- Refactor `telegram_app.py` into smaller handler/service modules.
- Remove or isolate root-level legacy workbook/photo scripts.
- Resolve import cycles.
- Persist privacy consent if required.
- Add explicit food profiles for kvass, beef tongue, turkey sausage, and other
  approximations.
- Tighten promo `per_user_limit` semantics before discount campaigns.
- Update README and package description for the actual release architecture.

## 20. Minimal Fix Plan

1. Fix the recipe/data blocker:
   - audit `tmp/final-pre-release-audit/recipes-photos/all-production-structural-scan.json`;
   - correct bad food profiles such as `acai_puree`;
   - review every hard outlier;
   - recalculate affected nutrition rows;
   - add guard tests.
2. Fix `r678` instruction text and add a focused regression assertion.
3. Update stale release evidence in `final-audit-fixes.md` for extra-purchase
   reversal behavior.
4. Fix admin discount-list storage error handling.
5. Add worker job timeout/supervision guards or explicitly block final manual
   smoke until durable worker failure mode is accepted.
6. Rerun focused recipe/data/photo tests, recipe audit, PDF smoke, payments
   focused tests, and then full DSN-backed pytest from a disposable local DB.

## 21. Product Quality Recommendations

- Add a permanent "production recipe sanity" test that fails on wrong FDC
  profile aliases and hard KBJU outliers unless explicitly allowlisted with
  comments.
- Treat user-facing recipe text corruption as high severity even when nutrition
  is correct.
- Keep warning-only approximations visible in a backlog so they do not become
  hidden quality debt.
- Add operator-grade payment reversal ingress before paid traffic.
- Add worker liveness telemetry and fail-fast behavior before any sustained
  manual QA window.

## 22. Launch Readiness Percent

Estimated readiness: 72%.

The codebase has substantial local verification history and many critical
payment/runtime/selected-53 fixes are present. It is not closer to 100% because
production recipe data still has blocker-level nutrition/profile outliers, one
selected-53 recipe has broken user-facing instructions, and several operational
launch gates remain incomplete or only partially audited in this run.

## Next Recommended Prompt

Fix only the final pre-release audit blocker in FoodBalance:
`docs/recovery-integration/final-pre-release-audit.md` BLOCKER-1 and HIGH-1.

Scope:
- Work only in `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`.
- Fix production recipe/food nutrition outliers from
  `tmp/final-pre-release-audit/recipes-photos/all-production-structural-scan.json`,
  starting with `acai_puree`, `r057`, and `r154`.
- Fix the broken `r678` instruction text.
- Add focused regression tests for the corrected food profiles/outlier guard and
  r678 text.
- Recalculate only affected nutrition rows.
- Do not touch Telegram bot runtime, Telegram API/getUpdates, production DB,
  real payments/refunds, deploy, push, commit, tag, PR, archive, recovered bot,
  or `New project 2 CLEAN`.
- After fixing, run focused recipe/data/photo tests, recipe content audit, and
  `git diff --check`.
