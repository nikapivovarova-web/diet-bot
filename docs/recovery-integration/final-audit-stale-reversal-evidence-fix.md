# Final Audit HIGH-6 Stale Reversal Evidence Fix

Date: 2026-05-31

## Scope

This closes only `HIGH-6: Release Evidence Still Contains Stale Reversal Text` from `docs/recovery-integration/final-pre-release-audit.md`.

Allowed write scope used: `docs/recovery-integration/final-audit-fixes.md`, `docs/recovery-integration/recovery-status.md`, and this report.

Not touched: application code, payment/reversal behavior, tests, recipes/data/PDF, bot runtime, Telegram API/getUpdates, production DB, real payment/refund/provider actions, deploy, push, commit, tag, PR, secrets/env files, archive, `New project 2 CLEAN`, or recovered bot.

## Initial Snapshot

- Branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `13d085c`
- `git status --short`: checkout was already dirty before this scoped docs fix, including existing recovery docs, payment/runtime/subscription/test changes, selected-53 data/photo work, and staging docs.

## Root Cause

`docs/recovery-integration/final-audit-fixes.md` still carried the older B-AUDIT-4 wording that extra one-day and weekly PDF reversals were manual-review-only. That became stale after the later extra-purchase reversal access fix.

Current behavior is narrower:

- matching subscription reversal revokes current paid subscription access;
- matching granted `extra_one_day` reversal removes one usable extra one-day unit when one exists;
- matching granted `extra_weekly_pdf` reversal removes one usable weekly PDF extra unit when one exists;
- extra reversals still keep `manual_review_required=True` for audit/operator follow-up;
- old, partial, mismatched, unsupported, missing-grant, or no-active-counter cases remain manual-review-only.

## Doc Changes

- Replaced the stale `manual review only` wording for extra one-day / weekly PDF reversals in `final-audit-fixes.md`.
- Added explicit extra-counter behavior: a matching reversal removes one active extra unit while preserving independent valid extra purchases.
- Kept the manual review marker in the documented behavior for audit and edge-case handling.
- Added an explicit note that production provider ingress plus sandbox/provider refund/cancel/reversal/chargeback acceptance remains the separate HIGH-3 paid-launch gate.
- Updated `recovery-status.md` to record this scoped HIGH-6 docs fix as ready for re-audit without claiming production launch readiness.

## Proof Against Current Code And Docs

- `src/diet_bot/subscriptions.py` read-only check:
  - `apply_payment_reversal()` routes `extra_one_day` and `extra_weekly_pdf` to `_apply_extra_payment_reversal(...)`.
  - `_apply_extra_payment_reversal(...)` decrements `extra_one_day_remaining` or `extra_weekly_pdf_remaining` by one when the matching active counter is greater than zero.
  - the extra reversal result still returns `manual_review_required=True` with `reason="extra_entitlement_requires_manual_review"`.
  - current subscription reversal still revokes active paid access when the current order/charge matches.
- `tests/test_subscriptions.py` read-only check:
  - `test_reversal_of_extra_purchase_revokes_unused_extra_access` expects the extra counter to become `0` while manual review remains required.
  - `test_refund_of_extra_purchase_revokes_one_extra_unit_without_removing_test_access` expects one of two weekly PDF extras to remain after a matching refund, proving one-unit removal rather than broad access removal.
- `docs/recovery-integration/extra-purchase-reversal-access-fix.md` already states that matching granted extra reversals decrement one active extra unit and keep manual review for audit.

## Verification

- `git diff --check`
  - exit code `0`; output contained LF-to-CRLF working-copy warnings only.
- Targeted stale-text check:
  - `rg -n "Extra one-day / weekly PDF reversals are manual review only|extra one-day / weekly PDF reversals are manual-review-only|manual review only because the current model" docs/recovery-integration/final-audit-fixes.md`
  - no stale `final-audit-fixes.md` phrase remained.

No docs consistency test command was found in `pyproject.toml`, `scripts`, `tests`, or `.github`; this is a docs-only fix.

## Verdict

READY FOR RE-AUDIT.
