# FoodBalance Recovery Integration Status

## Current Stage

The promo `per_user_limit` low finding is closed locally. Postgres promo
redemption/reservation now enforces `per_user_limit` as an active redemption
count per `(code, chat_id)` under the locked promo row, and migration
`202605310002` replaces the old unique active `(code, chat_id)` index with a
non-unique lookup index. Current remaining final pre-release audit findings are
`0` high, `0` medium, and `0` low. This is not final RC closure: a later
disposable-DSN final RC verification pass is still required because the
previous privacy-consent durability fix skipped Postgres integration checks
when `DIET_BOT_TEST_DATABASE_URL` was absent. Report:
`docs/recovery-integration/final-audit-low-promo-per-user-limit.md`.

Final local RC full-suite builder blocker is fixed and verified. The repeated
generation snack collision for seeds `0` and `4` was traced to rank pressure
inside the controlled recipe-window rotation score, not to recipe data. The
existing hard energy/protein/sodium window guards and `0.45` rotation tolerance
remain in place; only the guarded candidate rank pressure was reduced from
`0.02` to `0.01`. The secondary no-meat/no-fish timing failure was classified
as a brittle test wall-clock threshold after focused and grouped runs returned a
complete non-timeout week while fluctuating around the old `20.0s` limit. Final
safe local RC verification passed: full disposable-DSN `pytest -q` was
`1209 passed, 2 skipped in 1099.79s`, recipe audit had `blocking_findings=0`,
PDF recovery smoke rendered `8` PDFs, healthcheck reported `issues: none`,
controlled-QA preflight returned `result: PASS`, and `git diff --check` exited
`0` with LF-to-CRLF warnings only.

The privacy consent durability low finding is closed locally. Consent
acceptance now persists through the existing chat-state storage abstraction:
JSON state stores the consent record in the existing state file, and Postgres
chat state has the minimal `chat_privacy_consents` table. Acceptance writes
durable evidence before questionnaire collection; storage failure fails closed,
and restart can restore consent from chat state. Current remaining final
pre-release audit findings were `0` high, `0` medium, and `1` low before the
later promo `per_user_limit` closure above. Report:
`docs/recovery-integration/final-audit-low-privacy-consent-durability.md`.

The legacy JSON one-day planner event-loop low finding is closed locally. The
remaining direct one-day Telegram JSON fallback now offloads the CPU-bound
`build_one_day_plan()` call through `asyncio.to_thread()`, matching the durable
Postgres worker offload pattern while preserving JSON entitlement
consume/refund, recipe history, message delivery, payment/provider, privacy,
promo, sales follow-up, recipe data, import, and photo behavior. That step left
final pre-release audit findings at `0` high, `0` medium, and `2` low before
the later privacy consent durability closure above. Report:
`docs/recovery-integration/final-audit-low-json-one-day-offload.md`.

The low-risk hygiene/content batch is now closed locally for README/package
stale wording plus the selected-53 warning-only approximation and `r706`
calamari/protein portion findings. README/package metadata was updated, and
the selected-53 items were explicitly documented as accepted RC limitations
without changing recipe data. That batch left final pre-release audit findings
at `0` high, `0` medium, and `3` low before the later JSON one-day offload
closure above. HIGH-3 sandbox/provider acceptance and provider/live smoke were
not run. Reports:
`docs/recovery-integration/final-rc-builder-variety-fix.md` and
`docs/recovery-integration/final-audit-low-hygiene-content.md`.

Stage 18F sales follow-up cancellation and eligibility integration is complete
locally: successful monthly subscription grants, successful weekly PDF access
grants/deliveries, and successful monthly-access promo grants now cancel queued
or running-unsent `free_trial_v1` follow-up jobs, while payment order creation,
failed/unprocessed payments, pending invoice/order state, and provider error
paths do not cancel. The worker is now wired to production send-time access
checks for active paid access, weekly PDF access, and private chat when that
chat type is available, while preserving campaign enabled checks, opt-out, and
cancelled/suppressed chain/job guards. The campaign and worker flags remain
disabled by default, `FOOD20` remains inactive, and no bot process, Telegram
API, production DB, real payment/provider action, deploy, push, commit, tag,
PR, secrets/env, archive, `New project 2 CLEAN`, or recovered-bot work was
done. Report:
`docs/recovery-integration/stage18f-sales-followup-cancellation.md`.

Final pre-release audit recipe follow-up and scoped re-audit are complete for
`BLOCKER-1` production recipe data and `HIGH-1` `r678` text. The `acai_puree`
wrong-profile alias, the original final-audit hard recipe outliers, all `51`
recalculated nutrition rows, the requested food profiles, and the `r678`
OCR/source-text tail were rechecked locally with no remaining recipe/data
blocker. `HIGH-2` admin discount-list storage error handling is also re-audited
and closed locally. `HIGH-4` worker job hard timeout and `HIGH-5` worker task
supervision are re-audited and closed locally. `HIGH-6` stale release evidence
for extra-purchase reversal behavior is re-audited and closed locally. `HIGH-7`
sales follow-up is now re-audited and closed locally as a disabled-by-default
durable funnel with storage, scheduler admission, worker runtime, Telegram
rendering/opt-out, cancellation hooks, and DSN-backed store proof. `HIGH-3`
provider reversal now has a local operator apply path: the new
`scripts.ops.apply_payment_reversal` command defaults to dry-run, requires
`--apply` for writes, resolves provider/Telegram/order identifiers, calls the
existing `PaymentService.handle_payment_reversal()` path, preserves reversal
idempotency, prints redacted audit JSON, and keeps reconciliation read-only with
an apply-command pointer. The local final-audit high-finding scope is ready for
`HIGH-3` sandbox/provider acceptance; paid-launch sandbox/provider acceptance
remains pending, and this is still not a production-launch verdict. Report:
`docs/recovery-integration/final-audit-provider-reversal-operator-path.md`.

Final audit `MEDIUM-1` repeated `/start` stale questionnaire state is fixed,
re-audited, and closed locally: `/start` clears active questionnaire session
state, the questionnaire session token, and `TRIAL_CHAT_IDS` before rendering
the fresh start/subscriber menu. A stale text answer after repeated `/start` no
longer continues the old trial questionnaire. That step left the local final
pre-release audit count at `0` high, `3` medium, and `6` low. Reports:
`docs/recovery-integration/final-audit-medium-start-state-fix.md` and
`docs/recovery-integration/final-audit-medium-start-state-reaudit.md`.

Final audit `MEDIUM-4` global entitlement advisory lock contention is fixed and
closed locally: durable one-day and weekly PDF admission/start/refund paths now
use a deterministic per-chat entitlement advisory lock, while the global
entitlement map lock remains limited to whole-map save/import flows. DSN-backed
two-chat contention regressions reproduced the unrelated-chat block before the
fix and passed after it. Remaining local final pre-release audit count is
`0` high, `2` medium, and `6` low. Report:
`docs/recovery-integration/final-audit-medium-entitlement-lock.md`.

Final audit `MEDIUM-2` root-level legacy path quarantine is closed locally:
the original suspected files plus the remaining root-level Python and Node
workbook/photo utilities no longer embed local workstation workbook/photo paths,
now require explicit CLI paths, fail closed when run without arguments, and
require `--allow-external` for paths outside the repository. CI compile coverage
now includes all root `.py` utilities plus root/script `.mjs` syntax checks, and
focused regression coverage checks that the whole found root-level class stays
free of local path defaults. The local final pre-release audit count is now
`0` high, `1` medium, and `6` low. Report:
`docs/recovery-integration/final-audit-medium-legacy-paths.md`.

Final audit `MEDIUM-3` core import cycles is fixed and closed locally:
`RecipeTemplate` now lives in neutral `recipe_models`, `Entitlement` and its
serialization helpers now live in neutral `entitlement_model`, and the old
`recipe_catalog <-> curated_data` and `entitlement_storage <-> subscriptions`
local-import cycles are covered by a focused import-boundary regression test.
The local final pre-release audit count is now `0` high, `0` medium, and `6`
low. Report:
`docs/recovery-integration/final-audit-medium-import-cycles.md`.

The HIGH-3 sandbox/provider acceptance readiness plan is now prepared with the
provider/product matrix, sandbox-only credential requirements, manual smoke
checklist, reconciliation before/after gates, and operator dry-run/apply command
templates. No sandbox payment was run in this planning stage. Report:
`docs/recovery-integration/final-audit-provider-reversal-sandbox-plan.md`.

The HIGH-3 sandbox/provider acceptance smoke was attempted and stopped at hard
preflight: `DIET_BOT_SANDBOX_DATABASE_URL` was absent, the only detected bot
credential was a generic `DIET_BOT_TOKEN` that does not prove sandbox identity,
and the YooKassa sandbox/test provider token was absent. No sandbox payment,
provider API call, reconciliation report, operator dry-run/apply/replay,
production DB, live credential, real-money action, bot process, deploy, push,
commit, tag, PR, archive, `New project 2 CLEAN`, recovered-bot work, or sales
follow-up enablement was done. `HIGH-3` remains BLOCKED for sandbox/provider
acceptance. Report:
`docs/recovery-integration/final-audit-provider-reversal-sandbox-smoke.md`.

Final safe verification after the external audit blocker fixes is complete,
and the selected-53 final post-fix quality review is complete. The seven
requested recipe-data fixes for `r684`, `r685`, `r688`, `r691`, `r692`, `r705`,
and `r707` remain present, all `26` saved nutrition rows for recipes that use
`food_id=sour_cream` now match recalculation from current foods and ingredient
grams, and the `r666` through `r710` import is internally consistent. That
earlier manual-smoke readiness was superseded by the final pre-release audit
and the remaining high findings listed below. Deploy, push, commit, tag, PR,
secrets/env-file, production DB, real payment, refund, cancellation, reversal,
chargeback, archive, `New project 2 CLEAN`, and recovered-bot work remain
untouched.
The extra-purchase refund/cancel/reversal access leak found by the readonly
security check is fixed locally with focused unit coverage; DSN-backed Postgres
proof for this scoped fix was skipped because no safe disposable
`DIET_BOT_TEST_DATABASE_URL` is set in this shell.
The selected-53 approved recipe import is complete: 45 ready rows were imported
as `r666` through `r710`, 7 skipped rows were left out, local nutrition/photo
validation passed, and focused recipe/data/PDF checks passed. The follow-up
quality review blocker pass fixed the seven selected recipe-data blockers and
added focused invariant coverage, and the post-fix `sour_cream` nutrition
side effect is now fixed across all affected saved nutrition rows. Final
selected-53 post-fix quality review passed, but final manual-smoke bot restart
is superseded by the current final-audit high-finding queue. Payment
sandbox/provider smoke, safety snapshot/commit, and deploy/VPS planning remain
later stages.

## Completed Items

- Stage 1: diff map completed.
- Stage 2: product data/assets transferred.
- Stage 3: PDF renderer/branding transferred.
- Stage 4: Telegram UI/product copy/buttons/onboarding/paywall appearance transferred.
- Stage 5: payments/promo/subscriptions transferred onto hardened master payment runtime.
- Stage 6: builder/selection flexible-slot avoidance and deterministic variety edge case fixed.
- Stage 7: hardening preservation audit completed.
- Stage 8: full safe local verification completed.
- Stage 9: final readiness report completed.
- Round 2 QA2-005: privacy consent flow fixed and verified without PDF, recipe, payment, runtime, deploy, or bot-process work.
- Final audit low privacy consent durability: accepted consent now persists through chat-state storage and fails closed if it cannot be stored.
- Final audit low promo `per_user_limit` semantics: Postgres promo claims now enforce `per_user_limit` as active `reserved`/`redeemed` rows per code/chat under the locked promo row, with migration `202605310002` replacing the old one-row unique code/chat index.
- Round 2 QA2-002: PDF photo/layout consistency fixed and verified without privacy, recipe-data, payment, runtime, deploy, or bot-process work.
- Round 2 QA2-001/QA2-003/QA2-004: recipe-content audit completed and documented without recipe-data, PDF, Telegram, payment, runtime, deploy, or bot-process work.
- Round 2 QA2-003/QA2-004: high-suspicion recipe batch fixed and verified without PDF, Telegram/privacy/questionnaire, payment, runtime, storage, deploy, or bot-process work.
- Round 2 QA2-001: approximate-measures batch fixed confident common gram-only rows and verified without PDF, Telegram/privacy/questionnaire, payment, runtime, storage, deploy, or bot-process work.
- Round 2 stale Telegram photo/menu tests: stale promo/privacy/support keyboard and command expectations fixed and verified without production code, recipe/data, PDF, payment, runtime, storage, deploy, or bot-process work.
- Stage 16 Telegram UX quick fixes completed: duplicate weekly PDF generation notice removed, calculation copy added, per-meal KBJU displayed from `Meal.nutrients`, and free-ration offer copy updated.
- Stage 17 PDF layout v2 completed: day labels restored on recipe and shopping pages, recipe photos now use one fixed right-column layout, centered photo fallback removed, and long recipes continue below the photo block or on later pages.
- Stage 18A sales follow-up chain design completed without production code, payment, promo, runtime, storage, Telegram/PDF/recipe, bot, deploy, git, or archive work.
- Stage 18B sales follow-up durable storage foundation completed: PostgreSQL
  `sales_followup_*` tables, idempotent 8-job chain creation, exact message and
  button payload storage, safe existing callback target mapping, opt-out
  preference storage, campaign disabled-by-default flag, and disabled runtime
  config were added without scheduler, worker sending, Telegram handlers,
  FOOD20 activation, payment metadata, production DB, bot, deploy, push,
  commit, tag, PR, archive, or recovered-bot work.
- Stage 18C sales follow-up scheduler admission completed: successful free
  one-day trial delivery can create one idempotent 8-job chain after existing
  trial CTA delivery when `DIET_BOT_SALES_FOLLOWUP_ENABLED=1`, Postgres
  sales follow-up storage is available, chat is private, source is `free_trial`,
  and paid/weekly-PDF/opt-out guards pass. No worker sending, follow-up
  Telegram messages, callback handlers, `FOOD20`, payment metadata, production
  DB, bot, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.
- Stage 18D sales follow-up worker runtime completed: due jobs can be claimed
  with lease/heartbeat, send-time eligibility is rechecked, successful mocked
  sends record `telegram_message_id`, known transient failures requeue with a
  bounded `next_attempt_at`, permanent send failures suppress the chain and
  cancel future jobs, unknown send outcomes mark the job `unknown` for manual
  review, expired pre-send leases can be reclaimed, and the worker remains
  disabled by default with no real Telegram/API/startup wiring.
- Stage 18E sales follow-up Telegram rendering and opt-out callback completed:
  persisted payloads render exact `message_text`, exact `button_label`, the
  stored safe CTA callback, and a `Не напоминать` opt-out row. Unresolved or
  unsafe CTA targets fail closed. The opt-out callback writes only the
  sales-follow-up preference, cancels queued/running-unsent jobs for the
  chat/campaign when a store is available, and leaves transactional/payment/
  support messages untouched. Feature and worker flags remain disabled by
  default; no campaign enablement, live Telegram API, bot run, `FOOD20`,
  payment metadata, production DB, deploy, push, commit, tag, PR, archive,
  `New project 2 CLEAN`, or recovered-bot work was done.
- Stage 18F sales follow-up cancellation and eligibility integration completed:
  successful monthly subscription grants, successful weekly PDF access
  grants/deliveries, and successful monthly-access promo grants cancel queued
  or running-unsent `free_trial_v1` follow-up jobs via the existing durable
  cancellation method. Payment order creation, failed/unprocessed payments,
  pending invoice/order state, and provider error paths do not cancel. Worker
  send-time eligibility now uses production access checks for active paid
  access and weekly PDF access, preserves opt-out and campaign/job suppression
  guards, and blocks non-private chats when chat type is available. Campaign
  and worker flags remain disabled by default; no `FOOD20`, live Telegram API,
  bot run, production DB, payment-provider action, deploy, push, commit, tag,
  PR, archive, `New project 2 CLEAN`, or recovered-bot work was done.
- Stage 19.1 B-1 worker guard completed: production Postgres startup/preflight fixtures now include both durable worker flags where the tests expect valid production config, while missing-flag guard assertions remain fail-closed.
- Stage 19.2A promo-store hardening design completed without production code, tests, promo JSON/data, payments/runtime/storage, bot, deploy, git, or archive work.
- Stage 19.2B promo Postgres schema + store foundation completed without Telegram activation/admin menu, payment/subscription semantics, sales follow-up, `FOOD20`, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2C user promo activation wiring completed for the Postgres runtime path without admin menu wiring, sales follow-up, `FOOD20`, payment/subscription semantics beyond promo activation source, PDF/recipe data, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2D admin promo menu wiring completed for the Postgres runtime path without sales follow-up, `FOOD20`, payment/subscription semantics, PDF/recipe data, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2E promo production preflight, runbook, and restore-drill gates completed without sales follow-up, `FOOD20`, Telegram activation/admin behavior changes, payment/subscription semantics, PDF/recipe data, bot, deploy, push, commit, tag, PR, archive, or recovered-bot work.
- Stage 19.2F DSN-backed promo verification completed with a disposable local `diet_bot_test` Postgres database. A real restore-drill fixture gap was fixed so the live source initializes and seeds required promo tables; no production DB, bot, deploy, push, commit, tag, PR, archive, recovered-bot, `FOOD20`, sales/payment/PDF/recipe behavior, or secrets/env-file work was done.
- Stage 19.3 M-1 one-day worker `to_thread` completed: queued one-day delivery now offloads the CPU-bound daily planner with `asyncio.to_thread`, with no promo, PDF, recipe-data, payment/subscription, sales follow-up, bot, deploy, git, archive, `New project 2 CLEAN`, or recovered-bot work.
- Stage 19.4 env example / deploy config hygiene completed: `.env.example`
  now covers production Postgres, worker flags, payment placeholders,
  Postgres promo-store requirement, privacy/support, monitoring/ops, and
  local/dev-only vars without real secrets; no runtime behavior, Telegram UX,
  payments, promo logic, PDF, recipe data, sales follow-up, bot, deploy, git,
  archive, `New project 2 CLEAN`, or recovered-bot work was done.
- Stage 20A verification blocker fixed: the production startup guard test now
  stubs and asserts worker start hooks instead of constructing real durable
  worker runtimes from `postgresql://user:secret@example/db`; no production
  code, bot, deploy, payment, PDF, recipe data, secrets/env-file, archive,
  `New project 2 CLEAN`, or recovered-bot work was done.
- Stage 20C payment-store blocker fixed: stale `400 XTR` subscription
  expectations in Postgres payment-store tests were aligned to the current
  `450 XTR` product price via `expected_payment_price(...)`; no production
  payment code, PDF, recipe/data, Telegram UI, promo, runtime/preflight worker,
  weekly PDF, bot, deploy, secrets/env-file, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.
- Stage 20D runtime-preflight worker-flags blocker fixed: stale valid
  production/Postgres fixture in the Postgres runtime-preflight integration test
  now includes `DIET_BOT_ONE_DAY_WORKER_ENABLED=1` and
  `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`; B-1 production worker guard remains
  fail-closed.
- Stage 20E weekly PDF accepted-text blocker fixed: stale durable Postgres
  admission-only expectation no longer requires the separate accepted-text
  message removed in Stage 16; the old duplicate weekly PDF text remains absent.
- Stage 20F final full verification rerun completed with full DSN-backed pytest
  coverage, final recipe/PDF/runtime/preflight smoke checks, and
  `git diff --check`; no blocker was found.
- B-AUDIT-1 fish exclusion / sardines blocker fixed: fish exclusion now expands
  to all fish and seafood-like catalog IDs found in `curated_foods.json`,
  including `sardines` and `herring`, while non-fish staples remain eligible.
  Targeted RED was reproduced before the fix; the requested safety/data/traits
  pytest command and recipe content audit passed after the fix.
- B-AUDIT-2 weekly constrained generation diagnosis completed without
  production/test/data changes. Local probes covered baseline simple, fish,
  dairy, meat, dairy+meat, dairy+fish, dairy+meat+fish, meat+fish
  vegetarian-like, and dairy+meat+fish+egg vegan-like profiles. It remains a
  launch blocker; recommended minimal fix is a fast no-recent infeasibility
  precheck with a clear unsupported result and no consumed paid weekly value.
  Report: `docs/recovery-integration/weekly-constrained-generation-diagnosis.md`.
- B-AUDIT-2 weekly constrained generation fallback fixed: constrained profiles
  now use a bounded deterministic repeat fallback instead of waiting for the
  old no-repeat weekly timeout. The fallback returns metadata, keeps exclusions
  hard, and leaves payments/refunds/reconciliation, recipe data, PDF layout,
  unrelated Telegram UX, deploy, bot, and git publishing untouched.
- B-AUDIT-3 payment double-click pending invoices fixed: payment order creation
  now uses repository-backed active-pending reuse by
  `(chat_id, product, provider, amount, currency)`, with a Postgres advisory
  transaction lock for the durable store. Telegram Stars/YooKassa invoice paths
  stop before creating a second invoice link when an active pending order is
  already open.
- B-AUDIT-3/4/5 final DSN-backed payment verification completed with a
  disposable local `diet_bot_test` Postgres database: payment store,
  payment/promo/subscription, reconciliation, and focused concurrency/reversal
  selectors all passed with no skips or failures. The disposable container was
  removed after the run; no code fixes were made.
- Final verification after audit fixes completed: full DSN-backed `pytest -q`,
  recipe content audit, PDF recovery smoke, dummy-token healthcheck,
  controlled-QA preflight against disposable local Postgres, and
  `git diff --check` all passed. No code/data changes were made.
- Extra purchase reversal access fix completed: matching refund/cancel/reversal
  for `extra_one_day` and `extra_weekly_pdf` now removes one usable extra unit
  while preserving manual review for audit. Focused RED was reproduced first,
  then the requested payments/subscriptions/reconciliation suite passed.
- Selected-53 approved recipe import completed: 45 `ready_for_import=yes` rows
  from `staging_recipes/selected-53` were imported into curated production data
  as `r666` through `r710`; the 7 user-skipped rows were not imported. All
  imported rows have local photos and `calculation_status=ok`, recipe audit has
  zero blockers, and the focused recipe/data/photo pytest passed.
- Selected-53 post-import quality review completed and blocked before final
  manual smoke: all `r666` through `r710` records were structurally checked,
  but wrong primary ingredient mappings and inflated nutrition were found in
  the new range. Report:
  `docs/recovery-integration/selected-53-post-import-quality-review.md`.
- Selected-53 post-import data blocker fix completed for the seven requested
  recipes: wrong ingredient mappings/amounts were corrected for `r684`, `r685`,
  `r688`, `r691`, `r692`, and `r705`; the `sour_cream` food profile used by
  `r707` was corrected; nutrition was recalculated only for the seven affected
  recipes; focused data/photo/traits checks, no-write recipe audit, PDF recovery
  smoke, and `git diff --check` passed. Report:
  `docs/recovery-integration/selected-53-post-import-data-blockers-fix.md`.
- Selected-53 post-fix quality review completed and blocked before final
  manual smoke: all seven requested fixes are present, but the corrected
  `sour_cream` profile left 25 other saved nutrition rows stale; in the
  selected-53 range, `r670` and `r673` no longer match recalculation from
  current foods. Report:
  `docs/recovery-integration/selected-53-post-fix-quality-review.md`.
- Selected-53 `sour_cream` nutrition side-effect fix completed: all `26`
  recipes using `food_id=sour_cream` were recalculated from the current food
  catalog and current ingredient grams; `r670`, `r673`, and `r707` now match
  saved nutrition, the seven previous fixed mappings remain present, focused
  recipe/data/photo tests passed, recipe content audit found zero blockers,
  PDF recovery smoke passed, and `git diff --check` exited `0`. Report:
  `docs/recovery-integration/selected-53-sour-cream-nutrition-fix.md`.
- Selected-53 final post-fix quality review completed: all `r666` through
  `r710` records are structurally consistent, the seven recipe-data fixes remain
  present, all `26` `sour_cream` nutrition rows materially match recalculation,
  the warning-only candidates remain non-blocking, focused pytest and recipe
  audit passed, PDF recovery smoke passed, and a temporary selected-53 PDF
  sample covered `r666` through `r710`. Report:
  `docs/recovery-integration/selected-53-final-post-fix-quality-review.md`.
- Final audit recipe blocker fix completed: `acai_puree` no longer maps to a
  baking-chocolate profile, the original final-audit hard recipe outliers now
  have zero remaining hard flags after corrected cooked/raw/portion mappings and
  recalculated nutrition, and `r678` no longer contains the broken
  `подде жки нкции печени` tail. Focused RED was reproduced first, then the
  requested recipe/data/traits/photo pytest block, no-write recipe audit, and
  PDF recovery smoke passed. Report:
  `docs/recovery-integration/final-audit-recipe-blocker-fix.md`.
- Final audit recipe blocker re-audit completed: `BLOCKER-1` and `HIGH-1` are
  closed in the scoped recheck. The original hard-outlier recipe list has zero
  remaining hard flags, all `51` recalculated nutrition rows match current food
  profiles, the requested food profiles pass, `r678` no longer contains the
  broken tail, recipe audit has zero blockers, and PDF recovery smoke passed.
  Remaining final-audit count is `0` blocker, `6` high, `4` medium, `6` low.
  Report:
  `docs/recovery-integration/final-audit-recipe-blocker-reaudit.md`.
- Final audit `HIGH-2` admin discount-list storage fix completed: Postgres
  admin discount listing now has a single contract, returning only active
  discount promo definitions on success and raising `EntitlementStorageError`
  on promo-store failure so the existing admin callback sends
  `ADMIN_PROMO_STORAGE_ERROR_TEXT` instead of throwing. Focused RED reproduced
  the `NoneType.discount_percent` crash first; focused GREEN, promo unit tests,
  all `test_telegram_app*.py` tests, and `git diff --check` passed. Report:
  `docs/recovery-integration/final-audit-admin-discount-storage-fix.md`.
- Final audit `HIGH-2` admin discount-list storage re-audit completed:
  storage-error, normal admin list, and non-admin guard callback tests passed;
  full `tests/test_telegram_app_runtime.py`, `tests/test_promo_codes.py`, and
  `git diff --check` passed. The final-audit count is now `0` blocker, `5`
  high, `4` medium, `6` low. Report:
  `docs/recovery-integration/final-audit-admin-discount-storage-reaudit.md`.
- Final audit `HIGH-4`/`HIGH-5` worker liveness/supervision fix completed:
  one-day and weekly PDF workers now have a hard per-job processing timeout
  that stops heartbeat extension and routes timeout through existing
  retry/failure/manual-review handling. `run_bot()` now supervises worker tasks
  with polling and fails closed by cancelling polling if a durable worker dies.
  Focused RED reproduced missing timeout/fail-closed behavior first; focused
  GREEN, worker runtime suites, targeted `run_bot` startup/supervision tests,
  weekly PDF Postgres wiring, and safe-discovered one-day/worker/queue tests
  passed. Report:
  `docs/recovery-integration/final-audit-worker-liveness-fix.md`.
- Final audit `HIGH-6` stale reversal release evidence fix completed:
  `docs/recovery-integration/final-audit-fixes.md` now states that matching
  subscription reversals revoke paid access, matching extra one-day / weekly PDF
  reversals remove one usable extra unit, and the manual review marker remains
  for audit/operator follow-up and old partial/mismatched/no-active-counter
  cases. Production provider ingress and sandbox/provider acceptance remain the
  separate HIGH-3 paid-launch gate. No runtime/payment behavior or tests were
  changed. Report:
  `docs/recovery-integration/final-audit-stale-reversal-evidence-fix.md`.
- Final audit `HIGH-6` stale reversal release evidence re-audit completed:
  `final-audit-fixes.md`, `extra-purchase-reversal-access-fix.md`,
  `subscriptions.py`, and `tests/test_subscriptions.py` agree on current
  behavior. Matching subscription reversals revoke paid access, matching extra
  reversals remove one usable extra unit, and the manual review marker remains
  for audit/old partial/mismatched/no-active-counter cases. The remaining
  final-audit count is `0` blocker, `2` high, `4` medium, `6` low. Report:
  `docs/recovery-integration/final-audit-stale-reversal-evidence-reaudit.md`.
- Final audit `HIGH-7` sales follow-up funnel re-audit completed:
  Stage 18B-F evidence and focused tests prove the timed unpaid funnel is no
  longer design-only. The implementation has durable Postgres
  `sales_followup_*` storage, exact 8-step payload preservation, scheduler
  admission after successful free trial delivery, worker runtime, Telegram
  rendering/buttons, opt-out handling, and cancellation after subscription,
  weekly PDF, and monthly-access promo grants. Feature/campaign/worker gates
  remain disabled by default, and `FOOD20` remains text-only/separate. The
  remaining final-audit count is `0` blocker, `1` high, `4` medium, `6` low.
  Report:
  `docs/recovery-integration/final-audit-sales-followup-reaudit.md`.
- Final audit `HIGH-3` provider reversal operator path completed locally:
  `scripts.ops.apply_payment_reversal` gives operators a dry-run-first,
  `--apply`-gated local path from verified provider refund/cancel/reversal/
  chargeback events into the existing `PaymentService.handle_payment_reversal()`
  and Postgres ledger/access mutation logic. Reconciliation remains read-only
  and points to the apply command. Sandbox/provider acceptance remains pending
  before paid launch. Report:
  `docs/recovery-integration/final-audit-provider-reversal-operator-path.md`.
- Final audit `MEDIUM-1` repeated `/start` stale questionnaire state fix
  completed: repeated `/start` now clears `SESSION_BY_CHAT_ID`,
  `QUESTIONNAIRE_SESSION_TOKEN_BY_CHAT_ID`, and `TRIAL_CHAT_IDS` before
  rendering the start/subscriber menu. Focused RED reproduced the stale active
  trial questionnaire first; focused GREEN, nearby `/start`/privacy/support/
  subscriber menu tests, and full `tests/test_telegram_app_runtime.py` plus
  `tests/test_telegram_app_photos.py` passed; `git diff --check` exited `0`
  with only existing LF-to-CRLF working-copy warnings. Report:
  `docs/recovery-integration/final-audit-medium-start-state-fix.md`.
- Final audit `MEDIUM-1` repeated `/start` stale questionnaire state re-audit
  completed: static review confirmed `/start` clears the active questionnaire
  session, questionnaire session token, and `TRIAL_CHAT_IDS` before rendering
  fresh start/subscriber menu state; the focused regression, full Telegram
  runtime suite, full Telegram photos suite, and `git diff --check` passed.
  Remaining local final pre-release audit count is `0` high, `3` medium, and
  `6` low. Report:
  `docs/recovery-integration/final-audit-medium-start-state-reaudit.md`.
- Final audit `MEDIUM-4` global entitlement advisory lock contention fix
  completed: durable one-day and weekly PDF one-chat admission/start/refund
  paths now use a per-chat advisory lock instead of the global entitlement map
  lock. The global lock remains only in whole-map entitlement save/import flows.
  RED DSN-backed two-chat contention tests failed while the old global lock was
  held; GREEN focused regressions, affected store suites, and nearby
  entitlement-layer tests passed. Remaining local final pre-release audit count
  is `0` high, `2` medium, and `6` low. Report:
  `docs/recovery-integration/final-audit-medium-entitlement-lock.md`.

## Changed Files

Final audit HIGH-3 provider reversal operator path:

- `scripts/ops/apply_payment_reversal.py`
- `scripts/ops/payment_reconciliation_report.py`
- `src/diet_bot/postgres_payment_store.py`
- `tests/test_payments.py`
- `tests/test_postgres_payment_store.py`
- `tests/test_payment_reconciliation_report.py`
- `docs/recovery-integration/final-audit-provider-reversal-operator-path.md`
- `docs/recovery-integration/recovery-status.md`

Stage 18C sales follow-up scheduler admission:

- `src/diet_bot/sales_followup.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_sales_followup.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/stage18c-sales-followup-scheduler.md`
- `docs/recovery-integration/recovery-status.md`

Stage 18E sales follow-up Telegram rendering and opt-out callback:

- `src/diet_bot/sales_followup.py`
- `src/diet_bot/postgres_sales_followup_store.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_sales_followup.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage18e-sales-followup-telegram.md`
- `docs/recovery-integration/recovery-status.md`

Stage 18F sales follow-up cancellation and eligibility integration:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage18f-sales-followup-cancellation.md`
- `docs/recovery-integration/recovery-status.md`

Final audit recipe blocker fix:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/final-audit-recipe-blocker-fix.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/final-audit-recipe-blocker-fix/**`

Final audit recipe blocker re-audit:

- `docs/recovery-integration/final-audit-recipe-blocker-reaudit.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/final-audit-recipe-blocker-reaudit/**`

Final audit HIGH-2 admin discount storage fix:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/final-audit-admin-discount-storage-fix.md`
- `docs/recovery-integration/recovery-status.md`

Final audit HIGH-2 admin discount storage re-audit:

- `docs/recovery-integration/final-audit-admin-discount-storage-reaudit.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/final-audit-admin-discount-storage-reaudit/**`

Final audit HIGH-4/HIGH-5 worker liveness/supervision fix:

- `src/diet_bot/one_day_generation_job_runtime.py`
- `src/diet_bot/weekly_pdf_job_runtime.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_one_day_generation_job_runtime.py`
- `tests/test_weekly_pdf_job_runtime.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/final-audit-worker-liveness-fix.md`
- `docs/recovery-integration/recovery-status.md`

Final audit HIGH-6 stale reversal release evidence fix:

- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/final-audit-stale-reversal-evidence-fix.md`

Final audit HIGH-6 stale reversal release evidence re-audit:

- `docs/recovery-integration/final-audit-stale-reversal-evidence-reaudit.md`
- `docs/recovery-integration/recovery-status.md`

Final audit MEDIUM-1 start state re-audit:

- `docs/recovery-integration/final-audit-medium-start-state-reaudit.md`
- `docs/recovery-integration/recovery-status.md`

Final audit MEDIUM-4 entitlement lock fix:

- `src/diet_bot/postgres_entitlement_store.py`
- `src/diet_bot/postgres_one_day_generation_job_store.py`
- `src/diet_bot/postgres_weekly_pdf_job_store.py`
- `tests/test_postgres_one_day_generation_job_store.py`
- `tests/test_postgres_weekly_pdf_job_store.py`
- `docs/recovery-integration/final-audit-medium-entitlement-lock.md`
- `docs/recovery-integration/recovery-status.md`

Selected-53 approved recipe import:

- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/recipe_photos/r666.jpg` through `r710.jpg`
- `tests/test_curated_recipe_data.py`
- `tests/test_recipe_traits.py`
- `docs/recovery-integration/selected-53-import.md`
- `docs/recovery-integration/recovery-status.md`

Selected-53 post-import data blocker fix:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/selected-53-post-import-data-blockers-fix.md`
- `docs/recovery-integration/recovery-status.md`

Selected-53 sour cream nutrition side-effect fix:

- `src/diet_bot/data/curated_recipe_nutrition.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/selected-53-sour-cream-nutrition-fix.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/selected-53-sour-cream-nutrition-fix/**`

Selected-53 final post-fix quality review:

- `docs/recovery-integration/selected-53-final-post-fix-quality-review.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/selected-53-final-post-fix-review/**`

Extra purchase reversal access fix:

- `src/diet_bot/subscriptions.py`
- `tests/test_subscriptions.py`
- `tests/test_postgres_payment_store.py`
- `docs/recovery-integration/extra-purchase-reversal-access-fix.md`
- `docs/recovery-integration/recovery-status.md`

B-AUDIT-3 payment double-click pending invoices:

- `src/diet_bot/payments.py`
- `src/diet_bot/payment_service.py`
- `src/diet_bot/postgres_payment_store.py`
- `src/diet_bot/telegram_app.py`
- `tests/test_payments.py`
- `tests/test_postgres_payment_store.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`

Final DSN-backed B-AUDIT-3/4/5 payment verification:

- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`

Final verification after audit fixes:

- `docs/recovery-integration/final-verification-after-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`

B-AUDIT-2 weekly constrained repeat fallback:

- `src/diet_bot/telegram_app.py`
- `tests/test_safety_and_builder.py`
- `tests/test_weekly_pdf_postgres_wiring.py`
- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`

B-AUDIT-2 diagnosis-only docs/tmp:

- `docs/recovery-integration/weekly-constrained-generation-diagnosis.md`
- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`
- `tmp/weekly-constrained-diagnosis/weekly_constrained_probe.py`
- `tmp/weekly-constrained-diagnosis/weekly_constrained_probe_results.json`

B-AUDIT-1 final-audit fish exclusion fix:

- `src/diet_bot/safety.py`
- `tests/test_safety_and_builder.py`
- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/recovery-status.md`

Stage 2 data/assets:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `src/diet_bot/data/foodbalance_pdf_logo.png`
- `src/diet_bot/data/foodbalance_pdf_qr.png`
- `src/diet_bot/data/recipe_photos/r401.jpg` through `r610.jpg`
- `tests/test_curated_recipe_data.py`
- `tests/test_recipe_traits.py`

Stage 3 PDF:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `scripts/dev/pdf_renderer_recovery_smoke.py`

Stage 4 Telegram UI:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `src/diet_bot/questionnaire.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `tests/test_telegram_callback_owner_smoke.py`

Round 2 QA2-005 privacy-only:

- `src/diet_bot/telegram_app.py` (privacy consent flow present in current dirty state)
- `tests/test_telegram_user_journeys_smoke.py`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-002 PDF-only:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-001/QA2-003/QA2-004 recipe-audit-only:

- `scripts/dev/recipe_content_audit.py`
- `docs/recovery-integration/recipe-content-audit-round2.md`
- `docs/recovery-integration/recipe-content-audit-round2-findings.csv`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-003/QA2-004 high-suspicion recipe fixes:

- `src/diet_bot/data/curated_foods.json`
- `src/diet_bot/data/curated_recipe_ingredients.json`
- `src/diet_bot/data/curated_recipe_nutrition.json`
- `src/diet_bot/data/curated_recipes.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/recipe-content-audit-round2.md`
- `docs/recovery-integration/recipe-content-audit-round2-findings.csv`
- `docs/recovery-integration/recipe-fixes-round2.md`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 QA2-001 approximate-measures batch:

- `src/diet_bot/data/curated_recipe_ingredients.json`
- `tests/test_curated_recipe_data.py`
- `docs/recovery-integration/approximate-measures-round2.md`
- `docs/recovery-integration/manual-smoke-defects-round2.md`
- `docs/recovery-integration/recovery-status.md`

Round 2 stale Telegram photo/menu tests:

- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/recovery-status.md`

Stage 16 Telegram UX quick fixes:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/presentation.py`
- `tests/test_questionnaire_and_presentation.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/stage16-telegram-ux-fixes.md`
- `docs/recovery-integration/recovery-status.md`

Stage 17 PDF layout v2:

- `src/diet_bot/pdf_renderer.py`
- `tests/test_pdf_renderer.py`
- `docs/recovery-integration/stage17-pdf-layout-v2.md`
- `docs/recovery-integration/recovery-status.md`

Stage 18A sales follow-up chain design:

- `docs/recovery-integration/stage18-sales-followup-design.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.1 B-1 worker guard:

- `tests/test_runtime_config.py`
- `tests/test_production_preflight.py`
- `docs/recovery-integration/stage19-worker-guard.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2A promo-store hardening design:

- `docs/recovery-integration/stage19-promo-store-hardening-design.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2B promo Postgres schema + store:

- `src/diet_bot/postgres_promo_migrations.py`
- `src/diet_bot/postgres_promo_store.py`
- `tests/test_postgres_promo_store.py`
- `tests/test_postgres_migration_versions.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2C user promo activation wiring:

- `src/diet_bot/telegram_app.py`
- `src/diet_bot/postgres_promo_store.py`
- `tests/test_telegram_app_runtime.py`
- `tests/test_postgres_promo_store.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2D admin promo menu wiring:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `tests/test_telegram_user_journeys_smoke.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2E promo preflight/runbook/restore-drill:

- `src/diet_bot/production_preflight.py`
- `scripts/ops/postgres_restore_drill.py`
- `docs/production-runbook.md`
- `tests/test_production_preflight.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.2F DSN-backed promo verification:

- `tests/test_postgres_restore_drill_ops.py`
- `docs/recovery-integration/stage19-promo-store-hardening.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.3 one-day worker `to_thread`:

- `src/diet_bot/telegram_app.py`
- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage19-one-day-to-thread.md`
- `docs/recovery-integration/recovery-status.md`

Stage 19.4 env example / deploy config hygiene:

- `.env.example`
- `docs/production-runbook.md`
- `tests/test_production_deploy_files.py`
- `docs/recovery-integration/stage19-env-example.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20A verification blocker:

- `tests/test_telegram_app_runtime.py`
- `docs/recovery-integration/stage20-verification-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20C payment-store blocker:

- `tests/test_postgres_payment_store.py`
- `docs/recovery-integration/stage20-payment-store-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20D runtime-preflight worker-flags blocker:

- `tests/test_postgres_runtime_preflight.py`
- `docs/recovery-integration/stage20-runtime-preflight-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20E weekly PDF accepted-text blocker:

- `tests/test_weekly_pdf_postgres_wiring.py`
- `docs/recovery-integration/stage20-weekly-pdf-accepted-text-blocker.md`
- `docs/recovery-integration/recovery-status.md`

Stage 20F final full verification:

- `docs/recovery-integration/stage20-full-verification.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/recipe-content-audit-round2.md`
- `docs/recovery-integration/recipe-content-audit-round2-findings.csv`

Stage 5 payments/promo/subscriptions:

- `src/diet_bot/payments.py`
- `src/diet_bot/subscriptions.py`
- `src/diet_bot/promo_codes.py`
- `src/diet_bot/telegram_app.py`
- `src/diet_bot/entitlement_service.py`
- `src/diet_bot/runtime_config.py`
- `src/diet_bot/postgres_entitlement_migrations.py`
- `src/diet_bot/postgres_entitlement_store.py`
- `src/diet_bot/postgres_payment_store.py`
- `src/diet_bot/postgres_one_day_generation_job_store.py`
- `src/diet_bot/postgres_weekly_pdf_job_store.py`
- `tests/test_payments.py`
- `tests/test_payment_service.py`
- `tests/test_promo_codes.py`
- `tests/test_subscriptions.py`
- `tests/test_runtime_config.py`
- `tests/test_telegram_app_photos.py`
- `docs/recovery-integration/payments-transfer.md`

Stage 6 builder/selection:

- `src/diet_bot/builder.py`
- `tests/test_builder_recipe_cache.py`
- `docs/recovery-integration/builder-selection-fix.md`

Stage 7 hardening audit:

- `tests/test_postgres_payment_store.py`
- `docs/recovery-integration/hardening-preservation-audit.md`

Stage 8 verification cleanup:

- `tests/test_payment_scale_rehearsal.py`
- `tests/test_payment_recovery_replay.py`
- `tests/test_payment_recovery_spool.py`
- `tests/test_postgres_payment_store.py`
- `tests/test_vectors_and_shopping.py`

Docs/status:

- `docs/recovery-integration/diff-map.md`
- `docs/recovery-integration/data-assets-transfer.md`
- `docs/recovery-integration/pdf-renderer-transfer.md`
- `docs/recovery-integration/telegram-ui-transfer.md`
- `docs/recovery-integration/recovery-status.md`
- `docs/recovery-integration/final-readiness-report.md`

## Tests Run

Latest selected-53 final post-fix quality review:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `13d085c`
  - `git status --short`: existing dirty audit-recovery working tree before
    this read-only review.
- Structured selected-53 audit:
  - `r666` through `r710`: `45` recipe rows, `348` ingredient rows, `45`
    nutrition rows, `45` local JPEG photos opened successfully.
  - unique recipe IDs and titles; `0` missing food IDs; `0` material nutrition
    mismatches; `0` hard kcal/protein/fat/carbs/single-ingredient outliers.
  - all seven fixed recipes remained fixed, and `26` `sour_cream` recipe rows
    materially matched recalculation from current foods and ingredient grams.
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `249 passed in 143.87s (0:02:23)`.
- `python scripts/dev/recipe_content_audit.py --no-write-report`
  - `recipes_checked=710`, `ingredients_checked=6478`, `foods_checked=362`,
    `nutrition_rows_checked=710`, `blocking_findings=0`,
    `warning_findings=1322`.
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`, `recipes_checked=210`, output under
    `tmp/pdf-renderer-recovery-smoke`; this smoke covers `r401-r610`.
- Temporary selected-53 PDF sample:
  - `rendered_pdfs=2`, `recipes_checked=45`, output under
    `tmp/selected-53-final-post-fix-review/pdf-sample`.
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings
    only.
- No bot launch, Telegram API/getUpdates, production DB, payments/refunds,
  production data/profile/recipe/ingredient/nutrition/photo changes,
  runtime/payment/Telegram code changes, secrets/env-file changes, deploy,
  push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot work
  was done.

Latest selected-53 post-import data blocker fix:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `13d085c`
  - `git status --short`: existing dirty audit-recovery working tree before
    this scoped fix.
- Focused static-field check:
  - `r684`, `r685`, `r688`, `r691`, `r692`, `r705`, and `r707` recipe IDs,
    recipe keys, source IDs, titles, steps, and image paths stayed unchanged.
- Focused blocker validation:
  - direct local assertions for the seven corrected mappings/profiles passed.
- `pytest tests/test_curated_recipe_data.py::test_selected53_post_import_blocker_mappings_are_fixed -q`
  - `1 passed in 0.34s`.
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `248 passed in 125.31s (0:02:05)`.
- `python scripts/dev/recipe_content_audit.py --no-write-report`
  - `recipes_checked=710`, `ingredients_checked=6478`, `foods_checked=362`,
    `nutrition_rows_checked=710`, `blocking_findings=0`,
    `warning_findings=1322`.
  - The default write mode was intentionally not used because it writes
    `recipe-content-audit-round2.*`, which is outside this prompt's allowed
    file list.
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`, `recipes_checked=210`, output under
    `tmp/pdf-renderer-recovery-smoke`.
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings
    only.
- No bot launch, Telegram API/getUpdates, production DB, payments/refunds,
  payment/subscription/runtime/Telegram code changes, secrets/env-file changes,
  deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.

Latest extra purchase reversal access fix:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
  - `git status --short`: existing dirty audit-recovery working tree before
    this scoped fix.
- RED before fix:
  - `PYTHONPATH=src python -m pytest tests/test_subscriptions.py::test_reversal_of_extra_purchase_revokes_unused_extra_access tests/test_subscriptions.py::test_refund_of_extra_purchase_revokes_one_extra_unit_without_removing_test_access -q`
  - `4 failed`, showing extra counters remained usable after reversal.
- Focused GREEN:
  - same command
  - `4 passed in 0.09s`.
- Requested focused suite:
  - `PYTHONPATH=src python -m pytest tests/test_payments.py tests/test_subscriptions.py tests/test_payment_reconciliation_report.py -q`
  - `63 passed in 0.31s`.
- Postgres boundary:
  - `DIET_BOT_TEST_DATABASE_URL=unset`; `tests/test_postgres_payment_store.py`
    was not run and no DSN-backed proof is claimed for this scoped fix.
- `git diff --check`
  - exit code `0`; output contained only existing LF-to-CRLF working-copy
    warnings.

Latest final audit HIGH-6 stale reversal release evidence fix:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `13d085c`
  - `git status --short`: existing dirty audit-recovery working tree before
    this scoped docs-only fix.
- Read-only evidence checks:
  - `docs/recovery-integration/final-pre-release-audit.md` identified
    `final-audit-fixes.md` as stale because extra one-day / weekly PDF
    reversals were no longer manual-review-only.
  - `src/diet_bot/subscriptions.py` shows matching extra reversals decrement
    one active extra counter and still return `manual_review_required=True`.
  - `tests/test_subscriptions.py` expects matching extra reversals to remove
    one usable extra unit while preserving the manual review marker.
  - `docs/recovery-integration/extra-purchase-reversal-access-fix.md` already
    documents the later one-unit extra reversal behavior.
- `git diff --check`
  - exit code `0`; output contained LF-to-CRLF working-copy warnings only.
- Targeted stale-text check:
  - no stale `final-audit-fixes.md` phrase remained for extra one-day / weekly
    PDF reversals being manual-review-only.
- No docs consistency test command was found in `pyproject.toml`, `scripts`,
  `tests`, or `.github`; this was a docs-only fix.
- No application code, payment/reversal behavior, tests, recipes/data/PDF, bot,
  Telegram API, production DB, payment/refund/provider action, deploy, push,
  commit, tag, PR, secrets/env-file, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.

Latest final audit HIGH-6 stale reversal release evidence re-audit:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
  - `git status --short`: existing dirty audit-recovery working tree before
    this scoped re-audit.
- Read-only evidence checks:
  - `final-audit-fixes.md` no longer has the stale manual-review-only wording
    for matching extra one-day / weekly PDF reversals.
  - `extra-purchase-reversal-access-fix.md`, `subscriptions.py`, and
    `tests/test_subscriptions.py` all agree that matching extra reversals remove
    one usable extra unit while keeping `manual_review_required=True`.
  - Current subscription reversals revoke paid access, while old
    partial/mismatched/no-active-counter cases remain manual-review-only.
  - HIGH-3 provider ingress and sandbox/provider acceptance remain a separate
    paid-launch gate.
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings
    only.
- Targeted stale-text checks:
  - no stale exact phrase remained in `final-audit-fixes.md`.
  - repository-wide context hits were expected historical/fix-report mentions
    plus this re-audit report's command evidence and the current "no longer
    manual-review-only" statement.
- No application code, payment/reversal behavior, tests, bot, Telegram API,
  production DB, provider action, deploy, push, commit, tag, PR, secrets/env,
  archive, `New project 2 CLEAN`, or recovered-bot work was done.

Latest final verification after audit fixes:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
  - `git status --short`: existing dirty audit-recovery working tree before
    verification, with 15 modified tracked files and 10 untracked audit/staging
    paths.
- Disposable local Postgres:
  - Created `foodbalance-final-audit-pg` with database `diet_bot_test`.
  - Used `DIET_BOT_TEST_DATABASE_URL` only in the full-pytest process
    environment.
  - Used `DIET_BOT_DATABASE_URL` only in the controlled-QA preflight process
    environment after local schema initialization.
  - Removed the disposable container after verification.
- `pytest -q`
  - `1096 passed, 2 skipped in 831.01s (0:13:51)`.
  - DSN-backed integration coverage was enabled; the remaining skips were not
    caused by missing `DIET_BOT_TEST_DATABASE_URL`.
- Skips:
  - `tests/test_postgres_restore_drill_ops.py::test_backup_restore_drill_preserves_seeded_critical_tables`
    skipped because local PostgreSQL client tools are missing on PATH:
    `pg_dump`, `createdb`, `pg_restore`, and `dropdb`.
  - `tests/test_weekly_selector_scoring.py::test_live_seed_604374606_local_state_weekly_selection_finishes`
    skipped because local live QA state coverage is opt-in.
- `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`, `ingredients_checked=6130`, `foods_checked=359`,
    `nutrition_rows_checked=665`, `blocking_findings=0`,
    `warning_findings=1221`.
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`, `recipes_checked=210`, output under
    `tmp/pdf-renderer-recovery-smoke`.
- `python -m diet_bot.healthcheck`
  - Ran with `PYTHONPATH=src` and a dummy local `DIET_BOT_TOKEN`.
  - `issues: none`.
- `python -m scripts.ops.production_preflight --mode controlled-qa`
  - Ran with local dummy controlled-QA markers, payments disabled, no provider
    token, and disposable local Postgres DSN in process environment only.
  - `result: PASS`.
- `git diff --check`
  - exit code `0`.
  - Git printed LF-to-CRLF working-copy warnings only.
- No command timed out.
- No bot launch, deploy, push, commit, tag, PR, real payment, refund, cancel,
  reversal, chargeback action, secrets/env-file change, archive,
  `New project 2 CLEAN`, recovered-bot, production code, test, or data change
  was performed.

Latest B-AUDIT-3 payment double-click pending invoices:

- Initial RED before implementation:
  `pytest tests/test_payments.py::test_create_order_reuses_active_pending_order_for_same_payment_key tests/test_payments.py::test_concurrent_create_order_reuses_one_active_pending_order_for_same_payment_key tests/test_payments.py::test_create_order_allows_distinct_pending_orders_for_different_products tests/test_payments.py::test_create_order_ignores_expired_or_failed_pending_order_for_same_payment_key tests/test_payments.py::test_reused_pending_order_keeps_original_amount_currency_provider_validation tests/test_telegram_app_runtime.py::test_payment_callback_double_click_reuses_pending_order_without_second_invoice -q`
  - `5 failed, 1 passed`; duplicate pending order creation and second invoice-link creation were reproduced.
- Focused GREEN after implementation:
  same focused command after expanding mismatch cases to provider, amount, and currency
  - `8 passed in 3.49s`.
- Requested payment/promo/subscription suite:
  `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `54 passed`.
- Postgres payment store suite:
  `pytest tests/test_postgres_payment_store.py -q`
  - `20 passed, 19 skipped`.
  - `DIET_BOT_TEST_DATABASE_URL` is not configured in this session, so DSN-backed Postgres integration tests, including new pending-order concurrency checks, were skipped.
- Final DSN-backed disposable Postgres rerun:
  `pytest tests/test_postgres_payment_store.py -q`
  - `42 passed in 12.30s`; no skips.
  - Covered the durable pending-order reuse/concurrency cases that were skipped in the earlier no-DSN run.
- Telegram runtime suite:
  `pytest tests/test_telegram_app_runtime.py -q`
  - `25 passed`.
- `git diff --check`
  - exit code `0`.
  - Git printed LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No refund/cancel/reversal/reconciliation, PDF, recipe, weekly generation,
  deploy, push, commit, tag, PR, real payment/refund/chargeback action,
  secrets/env-file, archive, `New project 2 CLEAN`, or recovered-bot work was
  done.

Latest final DSN-backed B-AUDIT-3/4/5 payment verification:

- Disposable local Postgres:
  - Created a local `foodbalance-stage20-pg` Postgres container with a
    `diet_bot_test` database for this run.
  - Set `DIET_BOT_TEST_DATABASE_URL` only in the pytest process environment.
  - Removed the disposable container after verification.
- `pytest tests/test_postgres_payment_store.py -q`
  - `42 passed in 12.30s`; no skips.
- `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `59 passed in 0.33s`.
- `pytest tests/test_payment_reconciliation_report.py -q`
  - `12 passed in 0.23s`.
- Focused Postgres concurrency/reversal selector:
  `pytest tests/test_postgres_payment_store.py -q -k "concurrent or reversal"`
  - `5 passed, 37 deselected in 3.45s`.
- `git diff --check`
  - exit code `0`.
  - Git printed LF-to-CRLF working-copy warnings only.
- No skips or failures in the requested DSN-backed payment verification.
- No production DB, bot launch, deploy, push, commit, tag, PR, real payment,
  refund, cancellation, reversal, chargeback action, secrets/env-file, PDF,
  recipe, weekly generation, Telegram UX, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.

Latest B-AUDIT-2 weekly constrained repeat fallback:

- Isolated slow repeat-generation tests:
  - `pytest tests/test_safety_and_builder.py::test_repeat_generation_changes_recipes -q`
    - `1 passed in 28.84s`
  - `pytest tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_ids -q`
    - `1 passed in 89.36s`
  - `pytest tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_families -q`
    - `1 passed in 112.14s`
- Focused B-AUDIT-2 tests:
  `pytest tests/test_safety_and_builder.py::test_weekly_no_dairy_meat_fish_uses_repeats_fallback_without_excluded_foods tests/test_safety_and_builder.py::test_weekly_no_meat_fish_no_longer_waits_for_no_recent_timeout tests/test_safety_and_builder.py::test_weekly_repeats_fallback_keeps_constrained_repeats_bounded tests/test_safety_and_builder.py::test_weekly_impossible_profile_returns_structured_failure -q`
  - `4 passed in 37.23s`
- Weekly PDF/Postgres wiring:
  `pytest tests/test_weekly_pdf_postgres_wiring.py -q`
  - `25 passed in 3.43s`
- `git diff --check`
  - exit code `0`
  - output contained LF-to-CRLF working-copy warnings only.
- Full `pytest tests/test_safety_and_builder.py -q` was not rerun to
  completion after the hard-stop instruction. Earlier attempts exceeded
  practical timeouts (`240s` and `604s`) because the broad safety module
  includes existing slow full-builder coverage.
- Timing probe after fallback implementation:
  - `baseline_simple`: `7d/28 meals`, `4.103s`, phase `no_recent`, repeated recipe IDs `0`, exclusions OK.
  - `no_fish`: `7d/28 meals`, `19.263s`, phase `no_recent`, repeated recipe IDs `0`, exclusions OK.
  - `no_dairy`: `7d/28 meals`, `15.032s`, phase `no_recent`, repeated recipe IDs `0`, exclusions OK.
  - `no_meat`: `7d/28 meals`, `23.638s`, phase `no_recent`, repeated recipe IDs `0`, exclusions OK.
  - `no_dairy_no_meat`: `7d/28 meals`, `3.690s`, phase `repeats_fallback`, repeated recipe IDs `20`, exclusions OK.
  - `no_dairy_no_meat_no_fish`: `7d/28 meals`, `10.752s`, phase `repeats_fallback`, repeated recipe IDs `19`, exclusions OK.
  - `no_meat_no_fish`: `7d/28 meals`, `18.308s`, phase `repeats_fallback`, repeated recipe IDs `15`, exclusions OK.
  - `vegan_like_no_dairy_meat_fish_eggs`: structured failure in `5.742s`, phase `failed`, `failure_reason=repeats_fallback_no_valid_day_pool`, no plan consumed by generation result.
- Before-fix constrained timings from diagnosis/checkpoint:
  - `dairy + meat + fish`: `0` days in `27.090s` in diagnosis; checkpoint reproduction also observed the old path reaching about `60s`.
  - `meat + fish`: `60.026s` timeout.
  - vegan-like `dairy + meat + fish + egg`: `45.479s` failure.
- Bot was not launched.
- No payment/refund/reconciliation, recipe JSON/data, PDF layout, unrelated
  Telegram UX, deploy, push, commit, tag, PR, secrets/env-file, archive,
  `New project 2 CLEAN`, or recovered-bot work was done.

Latest B-AUDIT-2 weekly constrained generation diagnosis:

- `python -B tmp/weekly-constrained-diagnosis/weekly_constrained_probe.py`
  - `C00_baseline_simple`: generated `7d/28 meals`, `3.194s`, repeated recipe IDs `0`.
  - `C01_audit_no_dairy_meat_fish`: generated `no`, `27.090s`, phase `failed`, eligible recipes `130`.
  - `C02_no_fish`: generated `7d/28 meals`, `16.600s`, repeated recipe IDs `0`.
  - `C03_no_dairy`: generated `7d/28 meals`, `11.393s`, repeated recipe IDs `0`.
  - `C04_no_meat`: generated `7d/28 meals`, `24.503s`, repeated recipe IDs `0`.
  - `C05_vegetarian_like_no_meat_fish`: generated `no`, `60.026s`, phase `timeout`, eligible recipes `353`.
  - `C06_no_dairy_meat`: generated `7d/28 meals`, `23.254s`, repeated recipe IDs `0`.
  - `C07_no_dairy_fish`: generated `7d/28 meals`, `19.615s`, repeated recipe IDs `0`.
  - `C08_vegan_like_no_dairy_meat_fish_egg`: generated `no`, `45.479s`, phase `failed`, eligible recipes `105`.
- Additional local independent one-day probe for failed profiles:
  - `dairy + meat + fish`: `0/7` complete curated-only days, `26.946s`.
  - `meat + fish`: `4/7` complete curated-only days, `30.998s`.
  - `dairy + meat + fish + egg`: `0/7` complete curated-only days, `46.328s`.
- Bot was not launched.
- No production/test code, recipe data, PDF layout, Telegram UX, payments,
  refunds, reconciliation, deploy, push, commit, tag, PR, secrets/env-file,
  archive, `New project 2 CLEAN`, or recovered-bot work was done.

Latest Stage 20F final full verification rerun:

- Initial snapshot:
  - branch: `codex/recover-product-ui-on-hardened-master`
  - HEAD: `aa8336a250d0357e819904e0786abfbf1c0ea108`
  - `git status --short`: dirty integration worktree with 48 modified tracked
    entries and 222 untracked entries/directories reported by porcelain status.
- `DIET_BOT_TEST_DATABASE_URL` was not pre-set, so the full suite used a
  disposable local Docker Postgres database named `diet_bot_test`, bound to
  `127.0.0.1` on an ephemeral port. The DSN stayed in process environment only
  and was not printed or written to secrets/env files. Temporary PostgreSQL
  client-tool shims for restore-drill coverage were removed after the run.
- Full suite:
  `pytest -q`
  - `1067 passed, 1 skipped in 1333.36s (0:22:13)`
- Skip attribution:
  `pytest tests/test_pdf_renderer.py tests/test_weekly_selector_scoring.py -q -rs`
  - `30 passed, 1 skipped in 35.84s`
  - skip reason: `tests/test_weekly_selector_scoring.py:848: local live QA state test is opt-in`.
- Recipe content audit:
  `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`
  - `ingredients_checked=6130`
  - `foods_checked=359`
  - `nutrition_rows_checked=665`
  - `blocking_findings=0`
  - `warning_findings=1221`
- PDF renderer recovery smoke:
  `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output dir: `tmp/pdf-renderer-recovery-smoke`
- Local runtime healthcheck:
  `python -m diet_bot.healthcheck`
  - safe local dummy token/JSON-storage/payments-disabled environment
  - `issues: none`
- Controlled-QA production preflight:
  `python -m scripts.ops.production_preflight --mode controlled-qa`
  - fresh disposable local Docker Postgres with required schemas initialized
  - `result: PASS`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Timeouts: none observed.
- Bot was not launched.
- No deploy, push, commit, tag, PR, real payment/refund/chargeback action,
  secrets/env-file work, archive work, `New project 2 CLEAN`, or recovered-bot
  work was done.

Latest Stage 20E weekly PDF accepted-text blocker:

- Initial focused run:
  `pytest tests/test_weekly_pdf_postgres_wiring.py::test_postgres_admission_returns_accepted_without_entering_local_queue_or_starting -q`
  - RED: `1 failed`; actual `message.texts == []` while the stale test expected `WEEK_PDF_ACCEPTED_TEXT`.
- Focused weekly PDF Postgres wiring suite:
  `pytest tests/test_weekly_pdf_postgres_wiring.py -q`
  - `24 passed`
- Runtime and user-journey smoke subset:
  `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `36 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings only.

Latest Stage 20D runtime-preflight worker-flags blocker:

- Initial focused run:
  `pytest tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres -q`
  - `1 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set locally.
- Skip reason confirmation:
  `pytest tests/test_postgres_runtime_preflight.py::test_startup_preflight_validators_pass_against_fully_migrated_postgres -q -rs`
  - `1 skipped`; reason: `set DIET_BOT_TEST_DATABASE_URL to run Postgres runtime preflight integration tests`.
- Focused runtime preflight suite:
  `pytest tests/test_postgres_runtime_preflight.py -q`
  - `4 skipped` because `DIET_BOT_TEST_DATABASE_URL` is not set locally.
- Runtime/preflight/healthcheck regression:
  `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_production_preflight.py -q`
  - `73 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF working-copy warnings.
- Bot was not launched.
- No payment/store tests, PDF, recipe/data, Telegram UI, promo behavior, weekly
  PDF accepted-text test, deploy, push, commit, tag, PR, secrets/env-file,
  archive, `New project 2 CLEAN`, or recovered-bot work was done.

Latest Stage 20C payment-store blocker:

- Initial focused run without `DIET_BOT_TEST_DATABASE_URL`:
  `pytest tests/test_postgres_payment_store.py -q`
  - `20 passed, 15 skipped`
- Focused DSN-backed reproduction with disposable local Postgres and redacted
  DSN:
  `pytest tests/test_postgres_payment_store.py -q`
  - before fix: `4 failed, 31 passed`
  - failures were stale `400 XTR` successful subscription requests now rejected
    as `amount_mismatch` against current `450 XTR` orders.
- Focused DSN-backed rerun after the fix:
  `pytest tests/test_postgres_payment_store.py -q`
  - `35 passed`
- Payment/promo/subscription regression:
  `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `47 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No PDF, recipe/data, Telegram UI copy, promo store/admin, runtime/preflight
  worker flags, weekly PDF tests, deploy, push, commit, tag, PR, real
  payment/refund/chargeback action, secrets/env-file, archive, `New project 2
  CLEAN`, or recovered-bot work was done.

Latest Stage 20A verification blocker:

- First blocker node id as provided:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_plan_double_callback_same_chat_consumes_once -q`
  - `no tests ran`; in this checkout the test is in `tests/test_telegram_app_photos.py`.
- Focused five one-day tests individually from `tests/test_telegram_app_photos.py`
  - each passed in isolation.
- Original blocker suite before the fix:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `5 failed, 210 passed`
- Minimal leak repro before the fix:
  `pytest tests/test_telegram_app_runtime.py::test_run_bot_production_postgres_acquires_guard_before_bot_and_releases tests/test_telegram_app_photos.py::test_one_day_plan_double_callback_same_chat_consumes_once -q`
  - `1 failed, 1 passed`
- Minimal leak repro after the fix:
  same command
  - `2 passed`
- Focused five after the fix:
  `pytest tests/test_telegram_app_photos.py::test_one_day_plan_double_callback_same_chat_consumes_once tests/test_telegram_app_photos.py::test_concurrent_one_day_requests_same_chat_consume_once tests/test_telegram_app_photos.py::test_one_day_failure_releases_guard_and_allows_retry tests/test_telegram_app_photos.py::test_one_day_generation_different_chats_do_not_block_each_other tests/test_telegram_app_photos.py::test_trial_questionnaire_completion_sends_one_day_plan_and_subscription_cta -q`
  - `5 passed`
- Requested blocker suite after the fix:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `215 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No production code, deploy, push, commit, tag, PR, payment behavior, PDF,
  recipe data, secrets/env files, archive, `New project 2 CLEAN`, or
  recovered-bot work was done.

Latest Stage 19.4 env example / deploy config hygiene:

- RED before `.env.example` creation:
  `pytest tests/test_production_deploy_files.py -q`
  - `5 failed`
  - failures confirmed `.env.example` was missing and required deploy-file
    coverage could catch the gap.
- GREEN deploy-file coverage:
  `pytest tests/test_production_deploy_files.py -q`
  - `5 passed`
- Runtime config and healthcheck regression:
  `pytest tests/test_runtime_config.py tests/test_healthcheck.py -q`
  - `50 passed`
- Final hygiene check:
  `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No runtime behavior, Telegram UX, payments, promo logic, PDF, recipe data,
  sales follow-up, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`,
  recovered-bot, or real secret/env-file work was done.

Latest Stage 19.3 one-day worker `to_thread`:

- RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread -q`
  - `1 failed`
  - failure confirmed `_prepare_one_day_generation_delivery` called `build_one_day_plan(...)` synchronously instead of through the patched `asyncio.to_thread` wrapper.
- GREEN targeted regression:
  `pytest tests/test_telegram_app_runtime.py::test_one_day_generation_delivery_offloads_plan_build_to_thread -q`
  - `1 passed`
- Requested Telegram runtime suite:
  `pytest tests/test_telegram_app_runtime.py -q`
  - `24 passed`
- Relevant one-day job/runtime suite:
  `pytest tests/test_one_day_generation_job_runtime.py -q`
  - `20 passed`
- Additional one-day job store suite:
  `pytest tests/test_postgres_one_day_generation_job_store.py -q`
  - `3 passed, 32 skipped`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No promo store, PDF/recipe data, sales follow-up, payment/subscription semantics, deploy, push, commit, tag, PR, archive, `New project 2 CLEAN`, or recovered-bot work was done.

Latest Stage 19.2F DSN-backed promo verification:

- `DIET_BOT_TEST_DATABASE_URL` was not pre-set, so the run used a disposable local Docker Postgres database named `diet_bot_test`, bound to `127.0.0.1` on an ephemeral port. The DSN stayed in process environment only and was not written to secrets or env files.
- Initial DSN restore-drill run exposed a real fixture gap: the live restore source did not initialize/seed promo tables even though restore-drill now requires `promo_codes`, `promo_code_redemptions`, and `promo_import_runs`.
- Fixture fix:
  `tests/test_postgres_restore_drill_ops.py`
  - initialized `PostgresPromoStore`;
  - seeded one source row in each required promo table for source/restore row-count comparison.
- Final DSN-backed rerun:
  `pytest tests/test_postgres_promo_store.py -q`
  - `9 passed`
- `pytest tests/test_production_preflight.py -q`
  - `23 passed`
- `pytest tests/test_postgres_restore_drill_ops.py -q`
  - `17 passed`
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Disposable database/container and temporary client-tool wrappers were removed after the run.
- Bot was not launched.
- No production DB, deploy, push, commit, tag, PR, archive, recovered-bot, `FOOD20`, sales/payment/PDF/recipe behavior, or secrets/env-file work was done.

Latest Stage 19.2E promo preflight/runbook/restore-drill gates:

- RED before implementation:
  `pytest tests/test_production_preflight.py::test_production_preflight_success_reports_pass_and_uses_existing_validators tests/test_production_preflight.py::test_production_preflight_reports_missing_promo_schema_without_printing_dsn tests/test_production_preflight.py::test_restore_drill_required_tables_include_promo_tables tests/test_production_preflight.py::test_runbook_documents_promo_store_migration_import_and_restore -q`
  - `4 failed`
  - failures showed production preflight had no promo schema validator, restore-drill required tables omitted promo tables, and the runbook lacked promo migration/import/restore instructions.
- GREEN targeted Stage 19.2E preflight/runbook/restore checks:
  `pytest tests/test_production_preflight.py tests/test_postgres_migration_versions.py -q`
  - `24 passed`
- Healthcheck regression:
  `pytest tests/test_healthcheck.py -q`
  - `12 passed`
- Promo/Telegram runtime regression:
  `pytest tests/test_promo_codes.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `46 passed`
- Restore-drill ops regression:
  `pytest tests/test_postgres_restore_drill_ops.py -q`
  - `16 passed, 1 skipped`
  - skipped case requires `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No sales follow-up, `FOOD20`, Telegram activation/admin behavior, payment/subscription semantics, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were touched.

Latest Stage 19.2D admin promo menu wiring:

- RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::test_postgres_admin_monthly_code_uses_store_and_can_be_redeemed tests/test_telegram_app_runtime.py::test_postgres_admin_discount_create_list_and_disable_use_store_not_json tests/test_telegram_app_runtime.py::test_json_admin_discount_flow_remains_fallback tests/test_telegram_user_journeys_smoke.py::test_non_admin_330366_does_not_open_admin_promo_panel -q`
  - `4 failed`
  - failures showed admin helpers still lacked admin audit/Postgres wiring and bare non-admin `/330366` still returned the old status path.
- GREEN targeted Stage 19.2D regression:
  same command
  - `4 passed`
- Existing promo model/JSON tests:
  `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- Telegram runtime/user journey smoke:
  `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `35 passed`
- Promo Postgres store suite:
  `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No sales follow-up, `FOOD20`, payment/subscription semantics, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were touched.

Latest Stage 19.2C user promo activation wiring:

- RED before implementation:
  `pytest tests/test_telegram_app_runtime.py::test_postgres_promo_activation_uses_store_without_json_save tests/test_telegram_app_runtime.py::test_postgres_promo_activation_maps_store_rejections tests/test_telegram_app_runtime.py::test_postgres_promo_duplicate_activation_does_not_grant_twice tests/test_telegram_app_runtime.py::test_postgres_promo_activation_ignores_corrupt_json_state tests/test_postgres_promo_store.py::test_store_api_surface_is_ready_for_future_wiring -q`
  - `9 failed, 1 passed`
  - failures showed activation still using JSON and the store API missing finalize/release hooks.
- GREEN targeted Stage 19.2C regression:
  same command
  - `10 passed`
- Existing promo model/JSON tests:
  `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- Telegram runtime/user journey smoke:
  `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py -q`
  - `31 passed`
- Promo Postgres store suite:
  `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings only.
- Bot was not launched.
- No admin menu wiring, sales follow-up, `FOOD20`, payment/subscription semantics beyond promo activation source, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were touched.

Latest Stage 19.2B promo Postgres schema + store:

- RED before implementation:
  `pytest tests/test_postgres_promo_store.py -q`
  - failed at collection with `ModuleNotFoundError: No module named 'diet_bot.postgres_promo_migrations'`, because the promo migration/store modules did not exist yet.
- Existing promo model/JSON tests:
  `pytest tests/test_promo_codes.py -q`
  - `11 passed`
- New promo Postgres tests:
  `pytest tests/test_postgres_promo_store.py -q`
  - `2 passed, 7 skipped`
  - skipped cases require `DIET_BOT_TEST_DATABASE_URL`.
- Migration version registry:
  `pytest tests/test_postgres_migration_versions.py -q`
  - `1 passed`
- Generic Postgres store suite:
  `tests/test_postgres_store.py`
  - file is absent in this checkout, so no generic suite was run.
- `git diff --check`
  - exit code `0`
  - output contained existing LF-to-CRLF working-copy warnings.
- Bot was not launched.
- No Telegram activation/admin menu, payment/subscription semantics, sales follow-up, `FOOD20`, PDF/recipe data, deploy, push, commit, tag, PR, archive, or recovered-bot files were changed.

Latest Stage 19.2A promo-store hardening design:

- Read-only inspection of:
  - `src/diet_bot/promo_codes.py`
  - promo usage in `src/diet_bot/telegram_app.py`
  - entitlement/payment grant transaction patterns
  - Postgres migration, schema validation, preflight, backup, and restore-drill patterns
  - promo, payment, subscription, and Telegram promo tests
- No tests were run, because this stage was documentation-only and explicitly prohibited implementation/runtime work.
- Bot was not launched.
- No production code, tests, promo JSON/data, payments/runtime/storage, deploy, push, commit, tag, PR, archive, or recovered-bot files were changed.

Latest Stage 19.1 B-1 worker guard:

- Initial targeted runtime/preflight reproduction:
  `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_telegram_app_runtime.py -q`
  - `2 failed, 59 passed`; failures were stale valid production fixtures missing `DIET_BOT_ONE_DAY_WORKER_ENABLED=1` and `DIET_BOT_WEEKLY_PDF_WORKER_ENABLED=1`.
- Initial preflight reproduction:
  `pytest tests/test_production_preflight.py -q`
  - `5 failed, 15 passed`; failures were downstream checks blocked by the same stale valid production fixture.
- Final targeted suite:
  `pytest tests/test_healthcheck.py tests/test_runtime_config.py tests/test_telegram_app_runtime.py -q`
  - `61 passed`
- Final production preflight suite:
  `pytest tests/test_production_preflight.py -q`
  - `20 passed`
- `tests/test_production_deploy_files.py`
  - file is absent in this checkout, so no deploy-file suite was run.
- Local healthcheck module entrypoint:
  `PYTHONPATH=src python -m diet_bot.healthcheck` with a dummy local JSON env
  - `issues: none`
- `git diff --check`
  - exit code `0`; output contained only existing LF-to-CRLF working-copy warnings.

Latest Stage 18A sales follow-up design:

- Design-only/read-only inspection of Telegram trial flow, payments/entitlements, durable job runtime patterns, and promo durability risk.
- No tests were run, because this stage was documentation-only and explicitly prohibited implementation/runtime work.
- Bot was not launched.

Latest Stage 17 PDF layout v2:

- RED before implementation:
  `pytest tests/test_pdf_renderer.py::test_recipe_with_photo_uses_right_photo_two_column_body tests/test_pdf_renderer.py::test_long_recipe_steps_continue_below_photo_block tests/test_pdf_renderer.py::test_recipe_photo_has_no_centered_photo_fallback tests/test_pdf_renderer.py::test_day_label_is_visible_on_recipe_continuation_pages -q`
  - `4 failed`
- GREEN after implementation:
  same command
  - `4 passed`
- Full PDF renderer suite:
  `pytest tests/test_pdf_renderer.py -q`
  - `14 passed`
- Recovery PDF smoke:
  `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
  - output dir: `tmp/pdf-renderer-recovery-smoke`
- PyMuPDF visual preview output:
  - `tmp/pdf-qa-stage17-preview/p03-day1-normal-right-photo.png`
  - `tmp/pdf-qa-stage17-preview/p05-long-recipe-continuation.png`
  - `tmp/pdf-qa-stage17-preview/p20-day5-label-right-photo.png`
  - `tmp/pdf-qa-stage17-preview/p27-cod-liver-previous-example.png`
  - `tmp/pdf-qa-stage17-preview/p33-shopping-list.png`
  - `tmp/pdf-qa-stage17-preview/p34-shopping-list-continued.png`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF warnings for dirty files.

Latest Stage 16 checks:

- RED before implementation:
  `pytest tests/test_questionnaire_and_presentation.py::test_calculation_summary_adds_stage16_intro_and_follow_up tests/test_questionnaire_and_presentation.py::test_plan_response_includes_per_meal_kbju_lines_from_real_nutrients tests/test_questionnaire_and_presentation.py::test_meal_card_includes_kbju_line_from_meal_nutrients tests/test_telegram_app_photos.py::test_trial_subscription_keyboard_has_cta_button tests/test_telegram_app_photos.py::test_postgres_weekly_pdf_admission_does_not_send_duplicate_generation_message -q`
  - `5 failed`
- GREEN after implementation:
  same command
  - `5 passed`
- Regression check for long meal cards:
  `pytest tests/test_questionnaire_and_presentation.py::test_plan_response_includes_per_meal_kbju_lines_from_real_nutrients tests/test_questionnaire_and_presentation.py::test_meal_card_includes_kbju_line_from_meal_nutrients tests/test_telegram_app_photos.py::test_long_meal_card_sends_photo_without_duplicate_title -q`
  - `3 passed`
- Requested targeted suite:
  `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_app_photos.py -q`
  - `201 passed`
- `git diff --check`
  - exit code `0`; output contained existing LF-to-CRLF warnings for dirty files.

Latest Stage 5 checks:

- `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `47 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q`
  - `17 passed`
- `pytest tests/test_questionnaire_and_presentation.py -q`
  - `21 passed`
- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_payment_runtime.py tests/test_telegram_app_runtime.py -q`
  - `85 passed`
- `pytest tests/test_payments.py tests/test_payment_service.py tests/test_promo_codes.py tests/test_subscriptions.py tests/test_entitlement_service.py tests/test_entitlement_storage.py tests/test_entitlement_json_migration.py tests/test_postgres_migration_versions.py -q`
  - `96 passed`
- `pytest tests/test_payment_service.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_recovery_spool_status.py tests/test_telegram_app_photos.py -q`
  - `244 passed`
- `python -m compileall -q` on changed Stage 5 modules
  - exit code `0`
- `git diff --check`
  - exit code `0`
  - only CRLF warnings.

Latest Stage 6 checks:

- `pytest tests/test_safety_and_builder.py::test_five_repeat_generations_keep_key_meals_unique tests/test_safety_and_builder.py::test_repeat_generations_can_avoid_recent_recipe_families -q`
  - RED before fix: `2 failed`
  - GREEN after fix: `2 passed`
- `pytest tests/test_builder_recipe_cache.py::test_rank_recipes_filters_avoided_recipe_keys_by_requested_slot -q`
  - `1 passed`
- `pytest tests/test_safety_and_builder.py tests/test_builder_recipe_cache.py tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - first pass found one carbohydrate-range regression after the initial rotation change
  - final pass after tightening rotation: `131 passed`

Latest Stage 7 checks:

- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_postgres_schema_validation.py tests/test_postgres_migration_versions.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_service.py tests/test_telegram_app_runtime.py tests/test_telegram_callback_owner_smoke.py tests/test_telegram_media_validation.py -q`
  - `187 passed`
- `pytest tests/test_postgres_payment_store.py tests/test_postgres_entitlement_store.py tests/test_postgres_one_day_generation_job_store.py tests/test_postgres_weekly_pdf_job_store.py tests/test_postgres_runtime_preflight.py tests/test_postgres_single_poller_guard.py tests/test_postgres_connection.py tests/test_weekly_pdf_postgres_wiring.py -q`
  - first pass found two test-double failures from missing Stage 5 entitlement metadata columns
  - final pass after updating the fake cursor schema: `100 passed, 98 skipped`
- `python -m diet_bot.healthcheck`
  - ran with dummy local `DIET_BOT_TOKEN`
  - `issues: none`
- hardening module import/existence checks
  - 14 modules imported successfully
  - expected runtime/storage/recovery/preflight/payment/media modules present

Latest Stage 8 checks:

- `pytest tests/test_pdf_renderer.py -q`
  - `6 passed`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `238 passed`
- `pytest tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py tests/test_questionnaire_and_presentation.py -q`
  - `38 passed`
- `pytest tests/test_payments.py tests/test_payment_service.py tests/test_payment_runtime.py tests/test_payment_recovery_spool.py tests/test_payment_recovery_replay.py tests/test_payment_reconciliation_report.py tests/test_payment_recovery_spool_status.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
  - `142 passed`
- `pytest tests/test_runtime_config.py tests/test_production_preflight.py tests/test_healthcheck.py tests/test_postgres_schema_validation.py tests/test_postgres_migration_versions.py tests/test_postgres_payment_store.py tests/test_postgres_entitlement_store.py tests/test_postgres_one_day_generation_job_store.py tests/test_postgres_weekly_pdf_job_store.py tests/test_postgres_runtime_preflight.py tests/test_postgres_single_poller_guard.py tests/test_postgres_connection.py tests/test_weekly_pdf_postgres_wiring.py -q`
  - `172 passed, 98 skipped`
- `python -m diet_bot.healthcheck`
  - ran with dummy local `DIET_BOT_TOKEN`
  - `issues: none`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
- `pytest -q`
  - first full pass found two stale expectations:
    - old YooKassa subscription amount in `tests/test_payment_scale_rehearsal.py`
    - old shopping-list heading in `tests/test_vectors_and_shopping.py`
  - after aligning product expectations and related payment test fixtures: `890 passed, 115 skipped`

Latest Stage 9:

- `docs/recovery-integration/final-readiness-report.md`
  - created with changed files by stage, restored product features, preserved master hardening, test results, known risks, manual Telegram/payment smoke checklists, and approval gates before publish.
- `git diff --check`
  - exit code `0`
  - only CRLF checkout warnings.

Latest Round 2 QA2-005 privacy-only:

- `pytest tests/test_questionnaire_and_presentation.py tests/test_telegram_app_runtime.py tests/test_telegram_user_journeys_smoke.py tests/test_telegram_callback_owner_smoke.py -q`
  - first pass after adding a new assertion failed because the assertion targeted the text-only age question, which has no inline keyboard.
  - final pass after correcting the test target to a normal option question: `48 passed`

Latest Round 2 QA2-002 PDF-only:

- `pytest tests/test_pdf_renderer.py::test_recipe_media_always_uses_single_stacked_photo_layout tests/test_pdf_renderer.py::test_renderer_keeps_no_side_by_side_recipe_photo_layout_helpers tests/test_pdf_renderer.py::test_meal_photo_source_is_rendered_to_fixed_box_aspect -q`
  - RED before fix: `2 failed, 1 passed`
  - GREEN after fix: `3 passed`
- `pytest tests/test_pdf_renderer.py -q`
  - `12 passed`
- `python scripts/dev/pdf_renderer_recovery_smoke.py`
  - `rendered_pdfs=8`
  - `recipes_checked=210`
- `git diff --check`
  - exit code `0`
  - only existing CRLF checkout warnings.
- PyMuPDF preview render:
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p02-photo-after-ingredients.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p03-long-recipe-start.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p04-long-recipe-image-steps-next-page.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p28-cod-liver-salad-previous-example.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p30-shopping-list.png`
  - `tmp/pdf-qa-round2-preview/recovery-r401-r610-01-p31-shopping-list-continued.png`

Latest Round 2 QA2-001/QA2-003/QA2-004 recipe-audit-only:

- `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`
  - `ingredients_checked=6130`
  - `blocking_findings=4`
  - `warning_findings=1634`
  - report: `docs/recovery-integration/recipe-content-audit-round2.md`
  - CSV: `docs/recovery-integration/recipe-content-audit-round2-findings.csv`
- `git diff --check`
  - exit code `0`
  - only existing CRLF checkout warnings.

Latest Round 2 QA2-003/QA2-004 high-suspicion recipe fixes:

- `python scripts/dev/recipe_content_audit.py`
  - `recipes_checked=665`
  - `ingredients_checked=6130`
  - `foods_checked=359`
  - `blocking_findings=0`
  - `warning_findings=1494`
  - `title_ingredient_mismatch.warnings=0`
  - `steps_mention_missing_ingredient.warnings=0`
  - `non_cis_unclear_ingredients.warnings=0`
  - `tiny_gram_anomalies.warnings=0`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - `92 passed`
- `git diff --check`
  - exit code `0`
  - Git printed only existing CRLF checkout warnings.

Latest Round 2 QA2-001 approximate-measures batch:

- `python scripts/dev/recipe_content_audit.py`
  - before this batch: `recipes_checked=665`, `ingredients_checked=6130`, `blocking_findings=0`, `warning_findings=1494`, `missing_approximate_measures.warnings=406`
  - after this batch: `recipes_checked=665`, `ingredients_checked=6130`, `blocking_findings=0`, `warning_findings=1221`, `missing_approximate_measures.warnings=133`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py -q`
  - RED on new guard before data changes: `2 failed, 1 passed`
  - first full narrow pass found one stale raw-text expectation for `r306`
  - final pass after updating that expectation: `95 passed`
- `git diff --check`
  - exit code `0`
  - Git printed only existing CRLF checkout warnings.

Latest Round 2 stale Telegram photo/menu tests:

- `pytest tests/test_telegram_app_photos.py -q`
  - RED before fix: `16 failed, 133 passed`
  - GREEN after aligning stale menu expectations: `149 passed`
- `pytest tests/test_curated_recipe_data.py tests/test_recipe_traits.py tests/test_telegram_app_photos.py -q`
  - `244 passed`

Earlier Stage 2-4 checks are documented in their stage reports.

## Failures / Open Risks

- Payment test-price flag is production-gated but does not switch invoice amounts in this stage.
- Admin payment-event reconciliation commands remain deferred.
- Builder tests are slow because they exercise the full curated recipe pool.
- QA2-005's old in-memory consent limitation is superseded by the final-audit
  low privacy fix: consent acceptance now persists through chat state.
- QA2-002 visual overlap cannot be fully proven by unit tests; rendered PNG previews and smoke PDFs were inspected for this PDF-only pass.
- Stage 17 visual overlap cannot be fully proven by unit tests; the PyMuPDF previews listed above were rendered and inspected for this PDF-only pass.
- Stage 18A identified `FOOD20` as blocked for launch until promo storage is hardened: current promo persistence is JSON-backed/direct-write, discount codes are not safely redeemable by users, and payment order metadata does not yet carry discount details.
- Stage 19.2F closes the H-1 DSN-backed verification caveat for promo Postgres store, production preflight coverage, and restore-drill promo table comparison. Discount payment-path wiring and campaign approval remain later-stage blockers before any `FOOD20` launch.
- Stage 19.3 closes external audit M-1 for the queued one-day generation worker delivery path. Legacy non-worker one-day generation still has its existing synchronous path and was intentionally left unchanged for this scoped fix.
- Stage 19.4 closes the missing `.env.example` / deploy-config hygiene gap.
  Full verification/manual smoke is still a separate stage and was not run here.
- Stage 20A closes the placeholder-DSN verification blocker for the requested
  Telegram/questionnaire subset. Full Stage 20 verification was intentionally
  not continued after this blocker fix.
- Stage 20C closes the Postgres payment-store blocker as stale test
  expectations after product price restoration. Full Stage 20 verification was
  intentionally not continued after this blocker fix.
- Stage 20D closes the runtime-preflight worker-flags blocker as a stale
  valid production/Postgres fixture after B-1. Full Stage 20 verification was
  intentionally not continued after this blocker fix.
- Stage 20E closes the weekly PDF accepted-text blocker as a stale
  durable-admission test expectation after the Stage 16 duplicate-message
  removal. Full Stage 20 verification was intentionally not continued after
  this blocker fix.
- Stage 20F closes the full-verification rerun: full DSN-backed pytest and all
  final targeted smoke commands passed. The only skip is the opt-in local live
  QA state test.
- B-AUDIT-2 targeted blocker is fixed for the requested constrained weekly
  cases. Remaining risk: very narrow profiles can still require high repeat
  counts, and unsupported vegan-like profiles can still fail, but now return a
  structured failure quickly instead of consuming the old weekly timeout path.
- Full `tests/test_safety_and_builder.py` remains too slow for practical
  repeated local runs because of existing broad full-builder coverage. Focused
  B-AUDIT-2 tests and isolated slow repeat-generation tests passed.
- B-AUDIT-3 scoped blocker is fixed for new pending order creation and closed
  for the disposable-DSN Postgres gate. Pre-existing duplicate pending rows are
  not cleaned up retroactively.
- B-AUDIT-4/B-AUDIT-5 scoped blocker is fixed for refund/cancel/reversal
  entitlement handling and reconciliation status logic. Current matching
  subscription reversals automatically revoke paid subscription access. Current
  matching extra one-day/weekly PDF reversals now remove one usable extra unit
  and still require manual review for audit. Old charges and partial/mismatched
  reversals still require manual review.
- Latest B-AUDIT-4/B-AUDIT-5 checks:
  - Initial focused RED: `7 failed` for refunded/canceled/reversed provider
    rows still reconciling as granted and missing reversal entitlement/service
    API.
  - Focused GREEN: `7 passed`.
  - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
    -> `59 passed`.
  - `pytest tests/test_payment_reconciliation_report.py -q` -> `12 passed`.
  - `pytest tests/test_postgres_payment_store.py -q` -> `20 passed, 22 skipped`
    in the earlier no-DSN run.
- Latest disposable-DSN B-AUDIT-3/4/5 checks:
  - `pytest tests/test_postgres_payment_store.py -q` -> `42 passed in 12.30s`;
    no skips.
  - `pytest tests/test_payments.py tests/test_promo_codes.py tests/test_subscriptions.py -q`
    -> `59 passed in 0.33s`.
  - `pytest tests/test_payment_reconciliation_report.py -q` -> `12 passed in
    0.23s`.
  - `pytest tests/test_postgres_payment_store.py -q -k "concurrent or reversal"`
    -> `5 passed, 37 deselected in 3.45s`.
- Remaining B-AUDIT-4/B-AUDIT-5 risk: sandbox/provider
  refund/cancel/chargeback acceptance remains required before paid launch. No
  live provider action was performed in this scoped verification.
- Final post-audit verification closes the safe local verification gate: full
  DSN-backed `pytest -q`, recipe audit, PDF smoke, healthcheck, controlled-QA
  preflight, and `git diff --check` all passed.
- Final post-audit verification still had two expected/local-environment skips:
  the restore-drill integration test requiring local PostgreSQL client tools,
  and the opt-in local live QA state test.
- Stage 18A recommends a PostgreSQL-backed `sales_followup_*` durable queue and explicitly rejects in-memory timers for follow-up scheduling.
- QA2-001 approximate measures are fixed for confident common gram-only rows. Current recipe audit reports 0 blockers and 1221 warnings, including 133 remaining missing-approximate-measure warnings intentionally left for ambiguous categories.
- Stale Telegram photo/menu unit-test blocker is resolved; live
  Telegram/YooKassa/Stars smoke remains pending explicit user approval,
  sandbox-safe credentials/config, and a manual bot restart.
- Selected-53 final post-fix quality review no longer blocks final manual
  smoke. Remaining warning-only recipe-data approximations are documented in
  `docs/recovery-integration/selected-53-final-post-fix-quality-review.md`:
  `r670` beef tongue/generic beef and kvass/water, `r673` turkey sausage/lean
  poultry and kvass/water, `r699` kvass/water, plus high but source-preserved
  `r706` calamari/protein values. The later low hygiene/content batch closes
  those items for the final-audit low count as accepted RC limitations and
  leaves explicit food-profile additions for a separate recipe-profile task.
- Final audit recipe blocker re-audit closes the scoped recipe/data blocker and
  `r678` text issue.
- Final audit `HIGH-2` admin discount-list storage re-audit closes the scoped
  storage-error crash finding. Remaining final pre-release audit findings are
  `5` high, `4` medium, and `6` low; production launch is still not approved.
- Final audit `HIGH-4`/`HIGH-5` worker liveness/supervision re-audit closes the
  scoped worker timeout and dead-worker-admission risk locally. Remaining final
  pre-release audit findings are `3` high, `4` medium, and `6` low; production
  launch is still not approved.
- Final audit `HIGH-6` stale reversal release evidence re-audit closes the
  scoped stale release-evidence finding. The release evidence now matches
  current code, tests, and the later extra-purchase reversal access fix:
  matching extra reversals remove one usable unit while preserving manual review
  for audit. Production provider ingress/sandbox acceptance remains the separate
  HIGH-3 paid-launch gate, and production launch is still not approved.
- Final audit `HIGH-7` sales follow-up re-audit closes the scoped design-only
  finding. Storage, scheduler admission, worker runtime, Telegram
  rendering/opt-out, cancellation hooks, disabled-by-default gates, and
  FOOD20 separation were verified locally with focused tests and a disposable
  Postgres store probe. Production launch is still not approved.
- Final audit `HIGH-3` provider reversal operator path closes the local apply
  path gap: verified refund/cancel/reversal/chargeback events can be dry-run and
  then applied through existing reversal service/store logic without live
  provider actions. Sandbox/provider acceptance remains pending before paid
  launch.
- Remaining local final pre-release audit findings are `0` high, `0` medium,
  and `0` low. The promo `per_user_limit` low finding is closed locally, but
  this is not final RC closure: a later disposable-DSN final RC verification
  pass is still required because the previous privacy-consent durability fix
  skipped Postgres integration checks when `DIET_BOT_TEST_DATABASE_URL` was
  absent. `HIGH-3` sandbox/provider acceptance remains the next paid-launch
  acceptance gate.

## Next Stage

MEDIUM-1, MEDIUM-2, MEDIUM-3, and MEDIUM-4 are closed locally. No final-audit
medium findings remain, and no local final-audit low findings remain. Run the
final disposable-DSN RC verification pass before any final RC closeout. HIGH-3
sandbox/provider acceptance remains the next paid-launch acceptance gate unless
a different scoped prompt is selected. Manual-smoke bot restart, production
launch, manual sandbox refund/cancel/reversal acceptance, sales follow-up
launch, and `FOOD20` remain blocked until separately approved. Do not deploy,
push, PR, tag, commit, launch live polling/webhook, or run real payment actions
until approved.
