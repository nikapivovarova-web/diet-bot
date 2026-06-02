# Stage 18 Sales Follow-Up Chain Design

## Recommendation

Build the sales follow-up chain as a separate PostgreSQL-backed durable queue, modeled after the existing one-day and weekly PDF job runtimes. The chain should be scheduled only after successful free one-day ration delivery, not after `/start` or questionnaire completion, because the first message explicitly says "Это был один день".

The first implementation should stay behind a global disabled-by-default flag and should not seed, enable, or redeem `FOOD20` until promo storage is hardened. Follow-up storage and worker plumbing can be built first, but the full chain must not go live while the 20% discount code is backed only by the current JSON promo store.

## Trigger And Eligibility

Recommended trigger: successful free one-day ration delivery.

Concrete trigger points for future implementation:

- Durable path: one-day worker `after_success` for trial jobs where the request payload is `include_trial_subscription_cta=true` and the consumed source is `free_trial`.
- Legacy/direct path: after `_send_trial_plan()` has successfully delivered the free plan and CTA, but only if the consumed source was `free_trial`.
- Do not schedule from `/start`, privacy consent, questionnaire start, questionnaire completion, generic one-day repeat, paid one-day generation, weekly PDF generation, admin/test flows, or failed/partial plan delivery.

Eligibility at schedule time:

- chat is private;
- trigger was a successful free one-day ration delivery;
- user has no active paid access;
- user has not purchased weekly PDF/monthly access after the trigger;
- user has not opted out of follow-ups;
- global sales follow-up campaign is enabled;
- PostgreSQL storage is available.

Eligibility must be rechecked immediately before every send:

- skip if `Entitlement.is_subscription_active()` is true;
- skip if the user has active test/paid access through `_has_active_paid_access`;
- skip if a weekly PDF access/purchase has been granted;
- skip if the chain is cancelled, globally disabled, or the user opted out;
- skip if the chat is not private.

This double-check matters because the user may buy between schedule creation and the delayed message.

## Message Schedule And Button Set

All offsets are relative to the successful free one-day ration delivery timestamp, not relative to previous follow-up sends.

| Step | Offset | Purpose | Message |
| --- | ---: | --- | --- |
| `m01_two_hours` | 2 hours | One-day-to-weekly value bridge | Как тебе рацион?<br><br>Это был один день. Завтра снова вопрос что купить и что приготовить.<br><br>С подпиской всё иначе. Получаешь красиво оформленный PDF с рационом на 7 дней. Один раз открыл список продуктов, один раз сходил в магазин и вся неделя расписана. Завтраки, обеды, ужины, рецепты, КБЖУ, витамины, минералы и таблица по каждому дню. |
| `m02_one_day` | 1 day | Objection handling | Три причины почему люди откладывают подписку.<br><br>"Рецепты наверное сложные." В анкете можно выбрать простые блюда до 30 минут. Паста, омлет, курица с гарниром, каши, салаты. Ничего экзотического.<br><br>"Продукты дорогие или их не найти." Всё из обычного супермаркета. Крупы, овощи, мясо, рыба, яйца, творог, фрукты. Список продуктов на неделю в PDF помогает закупиться за один поход без лишнего.<br><br>"Не смогу придерживаться." Если какое-то блюдо не понравилось, можно заменить на другое. Рацион подстраивается под тебя, а не наоборот. |
| `m03_two_days` | 2 days | Social proof | Вот что написала одна из пользователей после первой недели:<br><br>"Я думала опять будет меню из гречки и грудки. А там нормальная еда которую реально готовишь дома. Самое удобное что список продуктов уже готов, пришла в магазин и взяла всё по списку."<br><br>Именно в этом смысл PDF рациона на неделю. Не надо каждый день решать что купить и что приготовить. Один раз получил план и просто следуешь ему. |
| `m04_three_days_food20` | 3 days | Discount offer | Если рацион на один день понравился, неделя будет такой же. Только не надо каждый день заново думать что готовить.<br><br>Для тех кто ещё думает, держи промокод на 20% скидку: FOOD20<br><br>Действует 48 часов. |
| `m05_one_week` | 7 days | Nutrient table value | Большинство людей которые следят за питанием недобирают магний, клетчатку и омега-3. Просто рацион однообразный и эти нутриенты в него не попадают.<br><br>Многие пьют добавки не зная что именно им не хватает. В недельном рационе бот подбирает блюда под твои параметры и в таблице по каждому дню видно каких витаминов и минералов тебе достаточно из еды, а какие стоит получать дополнительно. |
| `m06_two_weeks` | 14 days | Saved-profile reminder | Просто напомню что твои расчёты из анкеты сохранены.<br><br>Рацион на неделю под твои параметры можно получить прямо сейчас. |
| `m07_one_month` | 30 days | Useful free content | Три блюда которые легко готовить и которые хорошо покрывают дневную норму белка:<br><br>Омлет с творогом и зеленью: 3 яйца, 100г творога. Белок около 35г, 15 минут.<br><br>Запечённый лосось с рисом и овощами: 150г лосося, 80г риса, 100г овощей. Белок около 38г, 30 минут.<br><br>Греческий йогурт с орехами и бананом: 200г йогурта, 20г орехов, 1 банан. Белок около 14г, 5 минут. |
| `m08_six_weeks` | 45 days | Final soft reminder | За последнее время пользователи FoodBalance поделились результатами. Кто-то наконец разобрался с питанием под тренировки. Кто-то перестал каждый вечер думать что готовить. Кто-то просто стал есть вкуснее и осознаннее.<br><br>Если ты ещё не попробовал неделю, твои расчёты сохранены. Рацион соберём за минуту. |

Button set after each message:

- `Оформить подписку` -> existing subscription callback (`diet:subscribe_month`);
- `Получить PDF на неделю` -> existing weekly PDF callback (`diet:week_pdf`) or a future preferred weekly-PDF paywall callback if added;
- `Ввести промокод` -> existing promo callback (`diet:promo_code`), but only once discount promo redemption is safe for `FOOD20`;
- `Не напоминать` -> new opt-out callback, for example `diet:sales_followup_opt_out`.

Until `FOOD20` redemption is production-safe, either keep the chain disabled or suppress step `m04_three_days_food20` and the promo button in this chain. Do not send a code that the user cannot redeem.

## State Model / Storage

Use PostgreSQL only. Do not use in-memory timers. Do not add a JSON fallback for production follow-ups.

Recommended tables:

`sales_followup_chains`

- `chain_id UUID PRIMARY KEY`;
- `chat_id BIGINT NOT NULL`;
- `campaign_key TEXT NOT NULL`, for example `free_trial_v1`;
- `trigger_kind TEXT NOT NULL`, for example `free_one_day_delivery`;
- `trigger_job_id UUID NULL`;
- `trigger_idempotency_key TEXT NOT NULL`;
- `triggered_at TIMESTAMPTZ NOT NULL`;
- `status TEXT NOT NULL`, one of `active`, `completed`, `cancelled`, `opted_out`, `suppressed`;
- `cancel_reason TEXT NULL`;
- `created_at`, `updated_at`, `cancelled_at`;
- unique index on `(chat_id, campaign_key)` for non-terminal active chains, plus unique `trigger_idempotency_key`.

`sales_followup_jobs`

- `job_id UUID PRIMARY KEY`;
- `chain_id UUID NOT NULL REFERENCES sales_followup_chains(chain_id)`;
- `chat_id BIGINT NOT NULL`;
- `campaign_key TEXT NOT NULL`;
- `step_key TEXT NOT NULL`;
- `step_index INTEGER NOT NULL`;
- `scheduled_at TIMESTAMPTZ NOT NULL`;
- `next_attempt_at TIMESTAMPTZ NOT NULL`;
- `status TEXT NOT NULL`, one of `queued`, `running`, `sent`, `skipped`, `cancelled`, `failed`, `unknown`;
- `payload_json JSONB NOT NULL DEFAULT '{}'::jsonb`;
- `button_set_key TEXT NOT NULL DEFAULT 'sales_followup_default'`;
- `send_started_at`, `sent_at`, `telegram_message_id`, `skipped_at`, `finished_at`;
- `skip_reason`, `failure_reason`, `last_error`;
- `worker_id`, `leased_until`, `attempt_count`, `heartbeat_at`;
- `created_at`, `updated_at`;
- unique index on `(chain_id, step_key)`;
- claim index on `(next_attempt_at, scheduled_at, job_id)` where `status='queued'`;
- lease reclaim index on `(leased_until, job_id)` where `status='running'`.

`sales_followup_preferences`

- `chat_id BIGINT PRIMARY KEY`;
- `opted_out_at TIMESTAMPTZ`;
- `opt_out_source TEXT`;
- `created_at`, `updated_at`.

Optional but useful: `sales_followup_campaigns`

- `campaign_key TEXT PRIMARY KEY`;
- `enabled BOOLEAN NOT NULL DEFAULT false`;
- `version TEXT NOT NULL`;
- `disabled_reason TEXT`;
- `created_at`, `updated_at`.

The job store should copy the existing durable queue pattern:

- admission is idempotent;
- duplicate scheduling is prevented by unique keys;
- worker claims due jobs with `FOR UPDATE SKIP LOCKED`;
- running jobs have leases and heartbeats;
- transient failures requeue by setting future `next_attempt_at`;
- terminal statuses are immutable except manual/admin recovery fields.

## Cancellation / Suppression Rules

Cancel all future queued jobs immediately when:

- monthly subscription/payment grant succeeds;
- weekly PDF access/purchase grant succeeds;
- monthly access promo grant succeeds;
- user presses `Не напоминать`;
- admin suppresses a user or disables the campaign globally.

Skip a specific due job, and then cancel the rest of the chain, when:

- eligibility check finds active paid access;
- eligibility check finds weekly PDF access has been purchased;
- chat is not private;
- Telegram returns a permanent send failure, such as bot blocked, user deactivated, chat not found, or forbidden.

Do not cancel on:

- transient Telegram/network failures;
- temporary PostgreSQL errors;
- payment order creation without successful grant.

Opt-out behavior:

- pressing `Не напоминать` writes `sales_followup_preferences.opted_out_at`;
- all queued/running-unsent jobs for that chat are cancelled with reason `user_opt_out`;
- the bot replies with a short confirmation, for example `Хорошо, больше не буду напоминать.`;
- opt-out applies to this sales follow-up family, not to required transactional/payment/support messages.

## Promo FOOD20 Dependency

`FOOD20` must be treated as a discount promo, not a monthly-access promo. It should eventually be represented as a durable discount campaign with:

- `code = FOOD20`;
- `kind = discount`;
- `discount_percent = 20`;
- `per_user_limit = 1`;
- a per-chat 48-hour redemption window starting when step `m04_three_days_food20` is sent;
- payment order metadata recording promo code, discount amount, original amount, final amount, campaign key, and expiry;
- audit fields for redemption attempts and successful use.

H-1 promo-store hardening is required before any launch that sends or redeems `FOOD20`.

Stage 18B follow-up storage/schema can proceed without H-1 only if it does not seed `FOOD20`, does not enable discount redemption, and keeps the campaign disabled or step 4 suppressed. If Stage 18B is expanded to include promo storage or `FOOD20` rows, then H-1 must happen first.

Reason: current promo storage is JSON-backed, direct-write, and not transactionally tied to payment orders. Discount codes are modeled but user activation rejects them as non-access codes, and payment orders do not yet carry promo metadata. Sending `FOOD20` before fixing that would create a visible offer that cannot be redeemed safely.

## Failure Handling

Worker failure handling should match the existing durable job runtimes:

- claim only due queued jobs;
- set `running`, `worker_id`, `leased_until`, and `heartbeat_at` in one transaction;
- before send, recheck cancellation and eligibility;
- mark `send_started_at` immediately before Telegram send;
- on confirmed success, store `telegram_message_id`, `sent_at`, and `status='sent'`;
- on transient send failure before confirmed delivery, requeue with exponential or bounded backoff;
- on permanent send failure, mark skipped with reason and suppress the chain;
- if send outcome is unknown after `send_started_at`, mark `status='unknown'` and require manual review rather than retrying blindly;
- after `max_attempts`, mark `failed` and leave the chain visible in ops reports.

The worker must use the existing safe Telegram send/throttling pattern rather than raw bot sends.

## Admin/Ops Controls

Inspection:

- queue depth by `status`, `step_key`, and `scheduled_at`;
- due/overdue jobs;
- chains cancelled by reason;
- opt-out count;
- permanent Telegram failure count;
- unknown-send/manual-review rows;
- per-chat lookup showing active chain and remaining steps.

Disable controls:

- environment kill switch, for example `DIET_BOT_SALES_FOLLOWUP_ENABLED=0`, should stop new scheduling and prevent sends;
- worker flag, for example `DIET_BOT_SALES_FOLLOWUP_WORKER_ENABLED=0`, should stop the worker without deleting queued jobs;
- DB campaign flag in `sales_followup_campaigns.enabled` should allow ops to pause one campaign without deploy;
- admin command or runbook SQL can cancel queued jobs for one chat or campaign.

Duplicate prevention:

- idempotency key format should include campaign, chat, trigger, and delivery identifier, for example `sales_followup:free_trial_v1:{chat_id}:{trigger_job_id}`;
- one active chain per `(chat_id, campaign_key)`;
- one job per `(chain_id, step_key)`;
- scheduling should be transactional: create chain and all eight jobs together or no jobs at all.

## Test Plan

- Schedule is created once after successful free one-day ration delivery.
- No schedule is created after `/start`, questionnaire start, questionnaire completion without delivery, failed one-day delivery, paid one-day generation, repeat one-day generation, weekly PDF generation, or non-private chat.
- Eight jobs are created with offsets of 2 hours, 1 day, 2 days, 3 days, 7 days, 14 days, 30 days, and 45 days from trigger delivery time.
- Duplicate trigger/admission creates no duplicate chain or duplicate jobs.
- Worker sends only due jobs and preserves future jobs.
- Worker rechecks eligibility before every send.
- Active subscription cancels or skips future messages.
- Weekly PDF access/purchase cancels or skips future messages.
- Monthly access promo grant cancels future messages.
- Opt-out button writes preference and cancels queued jobs.
- Global disable prevents new schedules and prevents sends.
- Permanent Telegram send failure suppresses the chain.
- Transient Telegram send failure retries with durable `next_attempt_at`.
- Restart/recovery works: queued due jobs survive restart; expired running leases can be reclaimed safely.
- Unknown-send path is marked for manual review and does not blindly duplicate messages.
- Admin/ops queries report pending, due, failed, skipped, cancelled, and unknown jobs.
- `FOOD20` behavior is blocked pending H-1 if promo storage/order metadata is not fixed.
- After H-1, `FOOD20` tests cover 20% discount calculation, per-user 48-hour window, payment order metadata, expired code rejection, duplicate redemption prevention, and cancellation after successful discounted purchase.

## Implementation Plan

18B storage/schema:

- add PostgreSQL migrations and schema validation for chains, jobs, preferences, and optional campaign flag;
- add store/model/runtime interfaces;
- add idempotent schedule creation and cancellation primitives;
- keep feature disabled and do not seed or enable `FOOD20`.

18C scheduler/worker:

- add schedule call from successful free one-day delivery hook;
- add durable worker claim/lease/retry loop modeled after one-day generation worker;
- implement eligibility checks as injectable service calls;
- keep Telegram send mocked/stubbed in tests at this stage.

18D Telegram send/buttons:

- add message templates and default button set;
- add opt-out callback and confirmation;
- send through safe Telegram send/throttling;
- keep step 4 and promo button gated until H-1 is complete.

18E cancellation/payment integration:

- cancel queued jobs after subscription, weekly PDF, and promo monthly-access grants;
- cancel on opt-out;
- suppress on permanent Telegram failures;
- add admin/ops inspection and global disable controls.

18F tests/manual smoke:

- add unit and Postgres-backed integration coverage for scheduling, worker recovery, cancellation, opt-out, duplicate prevention, and failure handling;
- add dry-run/manual smoke checklist without live payment actions;
- add `FOOD20` tests only after promo-store hardening is complete.
