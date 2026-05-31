# Final Audit HIGH-6 Stale Reversal Evidence Re-audit

Date: 2026-05-31

## Verdict

HIGH-6 is closed.

Updated final pre-release audit count: `0 blocker / 2 high / 4 medium / 6 low`.

This re-audit reviewed only the stale reversal release-evidence finding. It did
not validate or close HIGH-3 provider ingress/sandbox acceptance, HIGH-7, or any
other remaining paid-launch gate.

## Scope

Read-only evidence:

- `docs/recovery-integration/final-pre-release-audit.md`
- `docs/recovery-integration/final-audit-fixes.md`
- `docs/recovery-integration/final-audit-stale-reversal-evidence-fix.md`
- `docs/recovery-integration/extra-purchase-reversal-access-fix.md`
- `src/diet_bot/subscriptions.py`
- `tests/test_subscriptions.py`

Updated evidence:

- `docs/recovery-integration/final-audit-stale-reversal-evidence-reaudit.md`
- `docs/recovery-integration/recovery-status.md`

## Provenance

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c5a0459d1fd449a823cec19cb16b6f5e77`
- Initial `git status --short`: checkout was already dirty, including existing
  recovery docs, payment/runtime/subscription/test changes, selected-53 data and
  photo work, and staging docs. No existing dirty application or test file was
  reverted.

## Original Finding

`docs/recovery-integration/final-pre-release-audit.md` described HIGH-6 as
release evidence drift: `final-audit-fixes.md` still said extra one-day and
weekly PDF reversals were manual-review-only, while later evidence and current
code removed one unused extra unit.

That was a documentation contradiction, not a request to change payment behavior.

## Evidence

`docs/recovery-integration/final-audit-fixes.md` no longer contains the stale
manual-review-only claim for matching extra reversals:

- It states that current active subscription reversals revoke subscription
  access by setting the subscription end to the reversal time, zeroing monthly
  counters, and canceling managed auto-renew status when applicable.
- It states that matching extra one-day / weekly PDF reversals remove one usable
  extra unit when the reversed charge was granted and an active counter exists.
- It states that extra reversals still return `manual_review_required=True` for
  audit of consumed, superseded, partial, mismatched, or no-active-counter cases.
- It explicitly says matching unused extra reversals are no longer
  manual-review-only.

`docs/recovery-integration/extra-purchase-reversal-access-fix.md` matches that
behavior:

- Matching granted `extra_one_day` reversal decrements
  `extra_one_day_remaining` by 1 when an active unit exists.
- Matching granted `extra_weekly_pdf` reversal decrements
  `extra_weekly_pdf_remaining` by 1 when an active unit exists.
- Manual review remains required for audit/operator follow-up.
- Subscription reversal behavior was not weakened.
- Payment sandbox/provider refund/cancel/reversal smoke remains a separate
  paid-launch gate.

`src/diet_bot/subscriptions.py` matches the documents:

- `apply_payment_reversal(...)` routes `subscription_month` to
  `_apply_subscription_payment_reversal(...)`.
- Current matching subscription reversals set `subscription_period_end` to the
  reversal time, zero monthly counters, and cancel managed auto-renew status for
  Telegram Stars or canceled/reversed/chargeback statuses.
- `apply_payment_reversal(...)` routes `extra_one_day` and `extra_weekly_pdf` to
  `_apply_extra_payment_reversal(...)`, then returns
  `manual_review_required=True` with
  `reason="extra_entitlement_requires_manual_review"`.
- `_apply_extra_payment_reversal(...)` subtracts one active extra counter for
  matching `extra_one_day` or `extra_weekly_pdf` reversals.

`tests/test_subscriptions.py` matches the documents and code:

- `test_reversal_of_extra_purchase_revokes_unused_extra_access` expects
  refunded/canceled/reversed extra purchases to leave the relevant extra counter
  at `0` while manual review remains required.
- `test_refunded_current_subscription_revokes_paid_entitlement` expects a
  current subscription refund to revoke paid subscription access and zero monthly
  counters without manual review.
- `test_refund_of_old_payment_does_not_revoke_later_valid_subscription` keeps
  old payment reversals manual-review-only and preserves the later current
  subscription.
- `test_refund_of_extra_purchase_revokes_one_extra_unit_without_removing_test_access`
  expects exactly one weekly PDF extra unit to remain after reversing one of two
  matching extras, preserving independent access.

## HIGH-3 Boundary

HIGH-3 remains a separate paid-launch gate. `final-audit-fixes.md`,
`final-audit-stale-reversal-evidence-fix.md`, and
`extra-purchase-reversal-access-fix.md` all keep production provider ingress and
sandbox/provider refund/cancel/reversal/chargeback acceptance out of this
closure.

## Static Checks

- `rg -n -i "extra one-day / weekly PDF reversals are manual review only|extra one-day / weekly PDF reversals are manual-review-only|manual review only because the current model" "docs/recovery-integration/final-audit-fixes.md"`
  - Exit code `1`; no stale exact phrase remained in `final-audit-fixes.md`.
- `rg -n -i "extra one-day / weekly PDF reversals are manual review only|extra one-day / weekly PDF reversals are manual-review-only|manual review only because the current model|extra product reversals still require manual review until" "docs/recovery-integration"`
  - Context hits only:
    - `final-audit-fixes.md` says matching unused extra reversals are no longer
      manual-review-only.
    - `final-audit-stale-reversal-evidence-fix.md` records the old stale wording
      as the historical problem and includes the check command.
    - this re-audit report records the same check commands as evidence.
  - No unrelated historical note was counted as a blocker.
- `git diff --check`
  - Exit code `0`.
  - Output contained only existing LF-to-CRLF working-copy warnings.

## Not Done

- No application code changed.
- No payment behavior or tests changed.
- HIGH-3 and HIGH-7 were not fixed or reclassified.
- No bot process was started.
- No Telegram API/getUpdates call was made.
- No production DB, provider, payment, refund, reversal, chargeback, deploy,
  push, commit, tag, PR, secrets, env, archive, `New project 2 CLEAN`, or
  recovered-bot action was performed.

## Next Recommended Prompt

Re-audit the next explicitly selected remaining final pre-release high finding,
keeping HIGH-3 provider ingress/sandbox acceptance as a separate paid-launch gate
unless the next task explicitly asks to address it.
