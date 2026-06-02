# FoodBalance Recovery Integration Diff Map

## Baselines
- hardened master commit: `origin/master` / `aa8336a250d0357e819904e0786abfbf1c0ea108`
- product baseline commit: `origin/codex/emergency-stabilization` / `ee24c06709a607e9e7ef2e27bf474f5eb3e9f14b`
- integration worktree: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- current branch: `codex/recover-product-ui-on-hardened-master`
- current HEAD: `aa8336a250d0357e819904e0786abfbf1c0ea108`
- status clean: `true` before creating this report

## Executive Summary
Коротко:
- Точно берем из master: runtime/storage hardening, durable Postgres-backed one-day and weekly PDF jobs, payment ledger/service/recovery spool, production preflight, Telegram send throttling/retries, media validation, redaction, strict production gates, and existing hardening tests.
- Точно берем из product branch: richer product data layer where it is a superset, new `r401`-`r610` recipe photos, PDF logo/QR assets, user-facing payment/product copy, Stars auto-renew UX, YooKassa 30-day wording, discount promo concepts, and expanded payment model tests as additive coverage.
- Требует ручной интеграции: `telegram_app.py`, `payments.py`, `subscriptions.py`, `promo_codes.py`, `pdf_renderer.py`, `runtime_config.py`, `healthcheck.py`, Postgres migrations/store shape, and payment/admin flows.
- Нельзя переносить целиком: product `telegram_app.py`, product `payments.py`, product `subscriptions.py`, product `runtime_config.py`, product `healthcheck.py`, product monolithic `postgres_store.py`, product `pyproject.toml`, and product tests as a replacement set.
- Главный риск: product baseline looks like a good product layer, but compared to hardened master it removes many safety modules. Treat product as a source of features and copy, not as an integration base.

## A. Telegram UI / Product Flow

| file | product difference | master hardening involved? | recommended action: copy / port manually / keep master / investigate | risk |
|---|---|---|---|---|
| `src/diet_bot/telegram_app.py` | Product rewrites the user-facing flow: `/promo` command, friendlier private-chat messages, `TRY_FREE_TEXT`, public payment/test-price copy, `YooKassa: разовый доступ на 30 дней`, `Telegram Stars: автопродляемая подписка`, `SUBSCRIPTION_PRICE_RUB=799`, `SUBSCRIPTION_STARS_AMOUNT=450`, extra Stars `29/141`, admin discount promo callbacks, Stars auto-renew cancel/enable buttons, analytics events, photo delivery helpers, richer paywall copy, and subscriber cabinet buttons that switch to buy-extra actions when quota is exhausted. | Yes. Master routes the same flows through async storage wrappers, entitlement/payment services, durable job admission, idempotency keys, private chat guards, `safe_telegram_send`, media validation, payment recovery spool, and Postgres worker runtime. Product drops many of these paths or replaces them with a simpler store abstraction. | port manually | High. Do not copy file. Port texts, buttons, callback IDs, and product UX into master handlers while preserving master-owned storage, worker, payment, idempotency, send, and media gates. |
| `src/diet_bot/presentation.py` | Small product polish: "Список покупок" becomes "Список продуктов"; weekly heading becomes "Общий список продуктов на неделю"; coverage dots become less strict (`green >= 95%`, `yellow >= 45%`). | No major hardening in this file. | copy | Low. Safe small patch, with snapshot/text tests. |
| `src/diet_bot/questionnaire.py` | Cooking-time question changes from three time buckets to two product choices: "Побыстрее и попроще" and "Можно чуть интереснее"; parsing delegates to `normalize_cooking_time_preference(strict=True)`. | Low. It depends on domain normalization compatibility, but does not touch runtime hardening. | port manually | Low to medium. Port with questionnaire tests because old answers and callback indexes may still exist in chat state. |
| `src/diet_bot/promo_codes.py` | Product adds `PromoCodeKind` (`monthly_access`, `discount`), `PromoRedemptionStatus`, promo definitions, discount amount calculation, disabled/expired states, audit hash/suffix metadata, and `promo_code_grant_charge_id`. It removes `release_promo_code_activation`. | Yes. Master currently rolls back a consumed promo code if entitlement grant fails. Product replaces that with transaction/store semantics, which must be proven against master storage. | port manually | High. Keep rollback/atomicity semantics. Discount promos need storage support and payment order metadata before UI exposure. |

Product layer worth preserving:
- Start menu and main menu copy, public payment/test payment messaging, and support/promo entry points.
- Callback flows for discount admin management, Stars auto-renew management, quota-exhausted extra purchases, and product-style paywalls.
- Analytics event concepts for start, questionnaire completion, paywall shown, invoice created, payment success, promo applied, ration delivered, weekly PDF delivered, Stars auto-renew changes.
- Recipe photo delivery and richer weekly planner heuristics, but only after media validation and durable job behavior are retained.

Master hardening that must not be lost:
- `_one_day_*_idempotency_key`, `_weekly_pdf_*_idempotency_key`, durable one-day and weekly PDF admission, in-flight/queue recovery, and refund-on-generation-failure behavior.
- `safe_telegram_send`, Telegram message/media validation, private chat rejection, payment ledger validation, successful payment recovery spool, and DB call wrappers.

## B. PDF / Branding / Assets

| file | product difference | master hardening involved? | recommended action: copy / port manually / keep master / investigate | risk |
|---|---|---|---|---|
| `src/diet_bot/pdf_renderer.py` | Product grows from about 1034 to 2146 lines. Adds cover PageTemplates, QR block, logo handling, content page header, brand color `#2F6B48`, `Food Balance` cover text, PIL-based transparent logo cleanup, metric cards, notice boxes, recipe steps layout, shopping pagination helpers, photo sizing constants, and richer card/table design. | Yes. Master renderer is simpler but already connected to master media preflight and current weekly PDF job flow. Product code assumes assets and different layout behavior; full copy could bypass master payload-size/media protections. | port manually | High. Port visual pieces in slices. Keep master PDF generation contract and media validation. Render/verify before enabling. |
| `src/diet_bot/data/foodbalance_pdf_logo.png` | New product asset, 444713 bytes, used by product cover logo path. | No code hardening, but media preflight should verify asset exists, size, and format before production. | copy | Low. Copy asset as-is after binary/media check. |
| `src/diet_bot/data/foodbalance_pdf_qr.png` | New product asset, 3838 bytes, used by product cover QR block with caption `@FOODBALANCERU_BOT`. | No code hardening, but QR destination and bot handle should be manually confirmed before release. | copy / investigate | Low to medium. Copy if handle is correct; otherwise regenerate asset and keep renderer path stable. |
| `logo / QR / fonts / image assets` | Product adds PDF-specific logo/QR assets. Both branches use system fonts (`Arial`, `Calibri`, DejaVu fallback, Segoe UI Emoji on Windows). No new bundled font files found in compared data tree. Product also depends on Pillow behavior for logo transparency. | Master dependency/runtime gates must continue to verify PDF renderability on target host. Product `pyproject.toml` changes dependency shape and should not be copied wholesale. | investigate | Medium. Keep dependency lock/build-system from master unless a specific product PDF dependency is missing. |

Can transfer whole?
- Assets can be copied whole after media checks.
- `pdf_renderer.py` should not be copied whole. Port cover, logo/QR, layout, and shopping pagination manually into master renderer.

## C. Recipes / Curated Data / Photos

| file | product difference | master hardening involved? | recommended action: copy / port manually / keep master / investigate | risk |
|---|---|---|---|---|
| `src/diet_bot/data/curated_foods.json` | Product is a superset: 361 foods vs 348 in master, 13 added, 0 removed. Added examples include `chicken_liver`, `cod_liver_canned_drained`, `cornmeal`, `falafel_prepared`, `grapes`, `herring`, `korean_carrot`, `pumpkin`, `rice_noodles`, `sardines`, `split_peas`, `sprats`, `udon_noodles`. Structure appears compatible with master fields. | Low. Loader/schema tests still matter. | copy | Low to medium. Safe candidate for whole-file data copy, then run curated data and builder tests. |
| `src/diet_bot/data/curated_recipes.json` | Product is a superset: 665 recipe ids vs 455 in master, 210 added, 0 removed. Added ids are `r401` through `r610`. Adds at least `coverage_priority` field while preserving existing fields. | Medium. Recipe selection/scoring and PDF/photo references depend on schema tolerance. | copy / investigate | Medium. Whole-file copy looks reasonable only after confirming loaders ignore/consume new fields and tests cover new recipes. |
| `src/diet_bot/data/curated_recipe_ingredients.json` | Product has 6157 rows vs 4541 in master, 665 recipe ids vs 455. Adds rows for `r401`-`r610` and introduces `recipe_key` on 1580 rows. | Medium. Builders may depend on exact ingredient fields and nutrition matching. | copy / investigate | Medium. Copy together with recipes/nutrition/foods, never alone. |
| `src/diet_bot/data/curated_recipe_nutrition.json` | Product is a superset: 665 recipe nutrition rows vs 455, 210 added, 0 removed. Adds `recipe_key` field. | Medium. Nutrition validation and PDF totals depend on consistency. | copy / investigate | Medium. Copy with recipe and ingredient files, then run nutrition/schema tests. |
| `src/diet_bot/data/recipe_photos/r401.jpg` to `r610.jpg` | Product adds 210 matching recipe photos. Master already has many recipe photos, but these product additions fill the `r401`-`r610` range. Product data tree has 668 images vs master 456. | Yes, indirectly. Master media validation should gate photo size/path before Telegram/PDF usage. | copy | Low to medium. Copy photos with media preflight and Telegram photo tests. |
| recipe photo/media references | Product recipes reference the newly added photo range and product PDF/Telegram photo flows use `resolve_local_meal_image_path` style paths under `src/diet_bot/data`. | Yes, through media validation and PDF limits. | investigate | Medium. Verify every `image_url` resolves and no remote URL slips into production send/PDF paths unexpectedly. |

Where product data is better:
- Product has more complete recipe coverage, especially the missing `r401`-`r610` block.
- Product appears additive, not destructive, for recipe ids, nutrition ids, and food ids.
- Product adds data needed by UI/PDF/photo-rich experience.

Can transfer data files whole?
- Likely yes for the four curated JSON files as a coordinated data bundle, not one by one.
- Required gate: validate JSON schema/loader compatibility, recipe id/nutrition/ingredient consistency, photo references, recipe selection tests, and PDF render smoke.

## D. Payments / Promo / Subscriptions

| file | product difference | master hardening involved? | recommended action: copy / port manually / keep master / investigate | risk |
|---|---|---|---|---|
| `src/diet_bot/payments.py` | Product expands from 215 to 2988 lines. Adds enums for provider/product/currency/status/code, order creation results, pre-checkout validation, successful payment input/results, reversals, reconciliation, redaction, discount metadata, invoice metadata, order reuse, test-smoke pricing, Stars recurring subscription handling, YooKassa receipt metadata, refund/chargeback/cancel subscription events, orphan success reconciliation, and pending reversal reconciliation. Prices shift to Stars `450/29/141` and YooKassa subscription `79_900` kopecks. | Yes. Master has smaller payment payload checksum model plus separate `payment_runtime.py`, `payment_service.py`, Postgres payment store, recovery spool/replay, and runtime gates. Product deletes many of those modules in the direct diff. | port manually / investigate | Critical. Treat product payment model as feature source. Do not replace master payment stack without preserving recovery spool, durable ledger semantics, and production gates. |
| `src/diet_bot/subscriptions.py` | Product adds `subscription_source`, `auto_renew_status`, `stars_subscription_charge_id`, `last_subscription_payment_charge_id`, `current_period_payment_order_id`, `has_active_managed_stars_subscription`, `apply_monthly_access_promo_grant`, and managed subscription fields. It keeps attempt consumption/refund concepts. | Yes. Master entitlement/service/storage layers own durable grant behavior and duplicate charge handling. | port manually | High. Extend master entitlement model carefully, with migration/backward-compatible JSON/Postgres fields. |
| payment handlers in `src/diet_bot/telegram_app.py` | Product has public payments flag, test-price visibility, dynamic payment keyboards, reusable invoice orders, discount promo pricing preview, Stars auto-renew management, admin `/payment_event` reversal/reconciliation commands, and successful payment paths through `_runtime_store().apply_successful_payment`. | Yes. Master handlers call `PaymentService`, validate order payloads against ledger, spool failed successful payments, and enforce Postgres/payment runtime startup checks. | port manually | Critical. Merge behavior by flow, not by file. Successful payment must remain idempotent and recoverable if storage is temporarily unavailable. |
| `src/diet_bot/promo_codes.py` plus promo handlers | Product supports monthly access promos and discount promos. Monthly promo grant uses `promo_code_grant_charge_id`; discount promos are remembered per chat and applied to subscription payment amount. Admin can create/list/disable discount promos if store supports it. | Yes. Master rollback after entitlement grant failure must be preserved or replaced by a proven atomic transaction. | port manually | High. Discount promo storage, redemption limits, audit hash, and payment order metadata must line up before exposing UI. |
| `tests/test_payments*.py` | Product deletes master `tests/test_payments.py` and adds `tests/test_payments_model.py` with 73 tests covering pre-checkout, nonce validation, recurring Stars, YooKassa metadata, discounts, duplicates, refunds, chargebacks, cancellation, orphan reconciliation, and redaction. | Yes. Master payment/runtime/recovery tests elsewhere are deleted by product in the direct diff and must not be lost. | keep master / copy | High. Add product tests as new coverage, but do not delete master tests. Update expectations to the integrated model. |
| `tests/test_promo_codes.py` | Product changes from 6 to 9 tests, adding promo definition validation, discount calculation, disabled/expired monthly access, and discount-not-access behavior. It removes tests for `release_promo_code_activation`. | Yes. Master rollback behavior still needs coverage unless replaced by atomic store tests. | port manually | Medium to high. Keep rollback or add transaction proof. |
| `tests/test_subscriptions.py` | Product adds managed subscription round-trip tests and verifies extra payments do not mutate managed subscription fields. | Yes. Entitlement persistence migration is sensitive. | copy / port manually | Medium. Good additive tests after model fields are integrated. |

Payment/product requirements captured from product branch:
- Stars subscription/autorenewal: Stars monthly invoice uses subscription period, recurring payment metadata, `auto_renew_status`, cancel/reenable UI, and active managed Stars subscription guard.
- YooKassa 30-day one-time access: product copy and invoice metadata make this explicit; YooKassa monthly access is not auto-renewing.
- Prices: product subscription is `799 ₽` / `450 Stars`; extras stay `50 ₽` and `250 ₽`, but Stars extras become `29` and `141`; test-smoke subscription is `100 ₽` / `1 Star`.
- Promo/admin discount flow: discount promo definitions, admin create/list/disable, pending discount per chat, discounted order metadata, audit hash/suffix.
- Pre-checkout validation: product validates order id/nonce/user/currency/amount/provider/product/status/expiration and records approval.
- Successful payment application: product validates successful payment against order, records events, handles recurring renewals, duplicates, orphan successes, and extra attempt grants.
- Idempotency: product uses charge aliases and processed provider charges; master also has service-level order payload and recovery idempotency. Integrated model needs both durable order idempotency and recovery replay.
- Refunds/chargebacks/reconciliation: product has model-level reversal/reconciliation; master has separate reconciliation/recovery scripts. These must be reconciled, not replaced blindly.

Master hardening pieces not to lose:
- `payment_runtime.py`, `payment_service.py`, `postgres_payment_store.py`, `payment_recovery_spool.py`, `payment_recovery_replay.py`, `payment_reconciliation.py`, payment recovery spool config in `runtime_config.py`, and production preflight checks.
- Existing ledger unavailable handling and successful payment spooling after grant failure.
- Redaction of identifiers and payment payloads in logs/reports.

## E. Runtime / Storage / Hardening

| file / zone | product difference | master hardening involved? | recommended action: copy / port manually / keep master / investigate | risk |
|---|---|---|---|---|
| `src/diet_bot/runtime_config.py` | Product rewrites config around `RuntimeConfigError`, mandatory DB unless `DIET_BOT_ALLOW_JSON_STORAGE=1`, Postgres statement/lock/pool settings, `DIET_BOT_PUBLIC_PAYMENTS_ENABLED`, `DIET_BOT_PAYMENT_TEST_PRICES_ENABLED`, and production test-price/provider-token safety. It drops many master worker/payment recovery settings. | Yes. Master config owns worker settings, payment recovery spool path, strict production validation, storage backend validation, safe summaries, and healthcheck integration. | port manually | High. Add product flags to master config; do not replace master config. |
| `src/diet_bot/healthcheck.py` | Product healthcheck expands to package import/data checks and optional Postgres connectivity. Master healthcheck focuses on runtime config startup/strict production summary and has console script entry. Product `pyproject.toml` removes `diet-bot-healthcheck`. | Yes. Healthcheck is a production gate. | port manually | Medium to high. Combine package-data/Postgres checks with master strict production checks and keep CLI entrypoint. |
| Postgres/storage modules | Product deletes split master modules (`postgres_connection.py`, chat state/entitlement/payment/job stores, schema validation, single poller guard) and adds monolithic `postgres_store.py`, `postgres_migrations.py`, `storage.py`. | Yes. Master split modules are the hardened storage architecture. | keep master / investigate | Critical. Do not replace with monolith. Mine product store/migrations for missing payment promo/reversal/analytics fields and port them into master-owned stores. |
| durable queues and recovery | Product deletes master `one_day_generation_job_runtime.py`, `one_day_generation_jobs.py`, `weekly_pdf_job_runtime.py`, `weekly_pdf_jobs.py`. Product still has in-process weekly queue helpers in `telegram_app.py`. | Yes. Master durable queue workers are production hardening. | keep master | Critical. Product in-process queue must not replace durable job runtime. |
| payment recovery and monitoring | Product deletes master `payment_recovery_spool.py`, `payment_recovery_replay.py`, `payment_reconciliation.py`, and ops reports. Product adds model-level reconciliation/admin command concepts. | Yes. Master recovery tooling is the safety net for paid users. | keep master / port manually | Critical. Integrate product reconciliation semantics into master tools, not the reverse. |
| production preflight | Product deletes `production_preflight.py`. | Yes. This is a stop gate for release. | keep master | Critical. Keep and extend with product payment flags/assets/data checks. |
| Telegram throttling | Product deletes `telegram_send.py`; master imports `safe_telegram_send` and retry/limiter behavior. | Yes. Protects against Telegram API failures and rate behavior. | keep master | High. Product send/photo UX must call through master-safe send paths or equivalent wrappers. |
| media preflight | Product deletes `telegram_media_validation.py`; product adds more PDF/photo assets. | Yes. Asset size/path/text limits protect runtime delivery. | keep master / port manually | High. Add product assets to validation coverage before enabling richer photo/PDF delivery. |
| dependency locks / `pyproject.toml` | Product changes dependencies from `psycopg[binary,pool]` to `psycopg[binary]` plus `psycopg-pool`, adds `openpyxl`, removes `diet-bot-healthcheck` script, removes pinned build-system, and changes pytest markers. | Yes. Dependency/build metadata is a deployment gate. | investigate | Medium. Port only necessary dependencies and keep master build/entrypoints unless a specific change is justified. |
| analytics/runtime store | Product adds `analytics.py`, `json_storage.py`, `storage.py`, `postgres_store.py` and user attribution/support/analytics events. | Some. Analytics is product value, but storage abstraction overlaps master hardening. | port manually / investigate | Medium to high. Port analytics event schema and calls into master storage boundaries after deciding owner module. |

What should stay master-owned:
- Storage backend ownership, Postgres connection/pooling, schema validation, single poller guard, job stores, payment service/store, recovery spool/replay, production preflight, healthcheck CLI, send limiter/retry, media validation, and redaction.

What from product may conflict:
- Monolithic store/migrations, runtime config assumptions, JSON transaction model, payment model repository protocols, public payment flags, payment test-price flags, admin reconciliation command shape, and analytics storage.

## Suggested Safe Implementation Order

1. Keep integration branch based on hardened master. Do not merge product branch.
2. Add product data/assets first: PDF logo/QR, `r401`-`r610` photos, and the four curated JSON files as one data bundle.
3. Run data gates: JSON load, recipe id/nutrition/ingredient consistency, photo reference resolution, curated recipe tests, recipe builder tests, and PDF smoke.
4. Port low-risk product polish: `presentation.py` text/thresholds and `questionnaire.py` cooking preference copy/parsing.
5. Port PDF visual layer in slices: cover, logo/QR, recipe card layout, shopping pagination, then render visual PDF samples and media-limit checks.
6. Port Telegram UI copy/buttons/callbacks into master handlers while preserving master private-chat, storage, durable jobs, idempotency, send, and media wrappers.
7. Extend promo model: monthly access plus discount definitions, audit metadata, admin create/list/disable, and rollback/transaction proof.
8. Integrate payment model by behavior: invoice metadata and prices, order create/reuse, pre-checkout validation, successful payment idempotency, Stars recurring, YooKassa one-time, refunds/chargebacks, reconciliation, and admin commands.
9. Extend master runtime config/healthcheck/preflight with product flags and assets checks.
10. Only after each slice passes tests, wire the next visible UI entry point.

## Stop Gates

- Do not auto-copy `telegram_app.py`, `payments.py`, `subscriptions.py`, `runtime_config.py`, `healthcheck.py`, `postgres_store.py`, `postgres_migrations.py`, or `pyproject.toml`.
- Do not delete master hardening modules or tests because product branch lacks them.
- Do not expose public payment buttons until pre-checkout, successful payment, duplicate payment, refund, chargeback, cancellation, orphan reconciliation, discount promo, and Stars renewal flows are tested against durable storage.
- Do not enable discount promos until promo redemption, payment order metadata, max redemption/per-user limits, and rollback/atomicity are verified.
- Do not transfer curated data partially. Recipes, ingredients, nutrition, foods, and photos must move as one coordinated bundle.
- Do not ship PDF changes until logo/QR, all local recipe images, PDF byte-size limits, Telegram media limits, and visual render checks pass.
- Do not remove or bypass payment recovery spool/replay/reconciliation. Paid-user access recovery is master-owned.
- Do not replace durable job workers with product's in-process queue behavior.
- Do not remove production preflight or healthcheck entrypoint.
- Do not enable production test prices; production must fail if test-price flags are on.
- Do not run `origin/master` as final bot and do not stop or modify the recovered bot during this integration.
- Do not do a blind merge from the product branch.
