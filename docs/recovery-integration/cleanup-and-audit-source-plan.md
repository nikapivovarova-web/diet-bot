# Cleanup And Audit Source Plan

Inventory date: 2026-05-30.

Scope: source inventory only. No folders were moved, deleted, archived, committed, pushed, tagged, deployed, started, or stopped during this check.

## Final Candidate

- path: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`
- git top-level: `C:/Users/adck8/Documents/FoodBalance-INTEGRATION-release`
- branch: `codex/recover-product-ui-on-hardened-master`
- HEAD: `aa8336a250d0357e819904e0786abfbf1c0ea108`
- status summary: dirty worktree, `270` porcelain entries total:
  - `48` modified tracked files
  - `222` untracked files
- Stage 20 report present: `docs/recovery-integration/stage20-full-verification.md`
- latest verification result from Stage 20 report:
  - full suite: `1067 passed, 1 skipped in 1333.36s (0:22:13)`
  - additional reported check: `30 passed, 1 skipped in 35.84s`
- manual smoke bot path confirmation:
  - running process `PID 38096` uses executable `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\.venv\Scripts\python.exe`
  - command line is `-m diet_bot.telegram_app`
  - this confirms the currently running manual smoke bot is using the integration candidate path.

## Git Worktree Dependency

- integration worktree git dir: `C:/Users/adck8/Documents/New project 2/.git/worktrees/FoodBalance-INTEGRATION-release`
- common git dir: `C:/Users/adck8/Documents/New project 2/.git`
- can `C:\Users\adck8\Documents\New project 2` be archived now? no.
- why:
  - `FoodBalance-INTEGRATION-release` is a linked git worktree.
  - Its git administrative directory lives under `C:\Users\adck8\Documents\New project 2\.git\worktrees\FoodBalance-INTEGRATION-release`.
  - Its common git dir is `C:\Users\adck8\Documents\New project 2\.git`.
  - Moving or archiving `New project 2` as an ordinary folder may break the integration worktree, because the integration checkout depends on git admin files stored there.

## Running Bot Processes

- integration process:
  - `PID 38096`, parent `42112`, `python.exe`
  - executable: `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\.venv\Scripts\python.exe`
  - command line: `"C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release\.venv\Scripts\python.exe" -m diet_bot.telegram_app`
- integration child process:
  - `PID 46528`, parent `38096`, `python.exe`
  - executable: `C:\Users\adck8\AppData\Local\Programs\Python\Python312\python.exe`
  - command line: `"C:\Users\adck8\AppData\Local\Programs\Python\Python312\python.exe" -m diet_bot.telegram_app`
  - because its parent is the integration process, treat it as part of the integration bot process tree.
- recovered process:
  - no separate process containing `FoodBalance-RECOVERED-emergency-stabilization` was found.
  - no separate recovered bot process was identified from the `diet_bot.telegram_app` process list.
- action recommendation:
  - do not stop anything during cleanup planning.
  - do not move or archive the integration worktree while this process tree is running.
  - if a future snapshot or archive step needs process quiescence, schedule that explicitly as a separate approved action.

## Folder Inventory

| path | classification | reason | safe action |
| --- | --- | --- | --- |
| `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release` | `KEEP_FINAL`; `KEEP_RUNNING_DO_NOT_TOUCH` | Final candidate worktree. Contains Stage 20 verification report with `1067 passed, 1 skipped`. Running manual smoke bot uses this path. Also depends on git admin files in `New project 2`. | Keep as current source of truth until an approved snapshot/audit commit exists. Do not move, archive, or delete. |
| `C:\Users\adck8\Documents\New project 2` | `KEEP_GIT_ADMIN_ROOT` | Common git dir/admin root for linked worktrees, including `FoodBalance-INTEGRATION-release`. It is also itself a worktree on branch `pdf-redesign-weekly-ration` and has dirty/untracked state. | Do not archive now. Before any future cleanup, preserve or migrate git worktree administration using git-aware operations, not manual folder moves. |
| `C:\Users\adck8\Documents\FoodBalance-ARCHIVE-DO-NOT-USE-WITHOUT-PERMISSION` | `ALREADY_ARCHIVED_DO_NOT_TOUCH` | Existing archive root. `git worktree list --porcelain` shows many locked archived worktrees under this folder with lock reason `ARCHIVED: do not use without explicit user permission`. | Leave untouched. No additional archive action needed now. |
| `C:\Users\adck8\Documents\FoodBalance-RECOVERED-emergency-stabilization` | `UNKNOWN_NEEDS_USER_DECISION` | Recovery/emergency worktree listed by git, detached at `ee24c06709a607e9e7ef2e27bf474f5eb3e9f14b`. No separate running recovered bot process was found, but the user explicitly said not to touch recovered bot. | Do not move, archive, or delete now. Future retirement requires explicit user approval and git-worktree-aware cleanup. |
| `C:\Users\adck8\Documents\New project 2 CLEAN` | `ALREADY_ARCHIVED_DO_NOT_TOUCH` | Listed by git as a locked worktree on branch `codex/entitlement-storage-boundary` with lock reason `ARCHIVED IN PLACE: Docker/WSL holds this path; do not use without explicit user permission`. User also explicitly said not to touch it. | Leave in place. Do not archive, move, or delete unless a separate Docker/WSL and git worktree plan is approved. |

No top-level `diet-bot*` folders were found under `C:\Users\adck8\Documents` during this inventory.

## Recommended Cleanup Plan

Do not execute these steps yet.

1. Keep `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release` as the final candidate path for now.
2. Mark `C:\Users\adck8\Documents\New project 2` as `DO NOT ARCHIVE YET - git common dir/admin root`.
3. Keep the running integration bot process tree untouched until a separate approved operation says otherwise.
4. Before external audit, create an immutable local audit snapshot from the integration candidate.
5. After the audit snapshot exists, audit that exact snapshot instead of the mutable dirty worktree.
6. Only after audit source is frozen, revisit cleanup of non-final folders.
7. For any folder that appears in `git worktree list --porcelain`, use git-worktree-aware cleanup. Do not manually move linked worktrees or their common admin root.
8. Leave `FoodBalance-ARCHIVE-DO-NOT-USE-WITHOUT-PERMISSION`, `New project 2 CLEAN`, and `FoodBalance-RECOVERED-emergency-stabilization` untouched unless the user explicitly approves a separate cleanup plan.

Current archive candidates:

- None are safe to archive immediately from this inventory.
- `FoodBalance-RECOVERED-emergency-stabilization` may be a future retirement candidate only after explicit user decision and git-worktree-safe handling.

## Recommended Audit Source

Recommended option: B. First create a local safety commit/snapshot, then audit that exact commit.

Recommended source path before snapshot:

- `C:\Users\adck8\Documents\FoodBalance-INTEGRATION-release`

Recommended snapshot method:

- With explicit approval in a later step, create a local-only safety commit or equivalent immutable git snapshot from the current integration worktree.
- Include the intended tracked modifications and required untracked files.
- Review secrets and environment files before staging.
- Do not push, tag, deploy, or create a PR merely to create the local audit source.
- Audit the resulting exact commit or immutable snapshot identifier.

Why this is safest:

- Option A, auditing the current dirty integration worktree directly, matches the running candidate but is mutable. Any file edit after the audit starts can change the audited source.
- Option B gives the external audit a reproducible, immutable source while preserving git lineage.
- Option C, creating a standalone copied audit snapshot, avoids changing git history but creates a second tree that can drift from the real worktree and is easier to miscompare.

Why the old `origin/master aa8336a` audit prompt is no longer valid:

- `aa8336a250d0357e819904e0786abfbf1c0ea108` is still the HEAD commit of the integration worktree, but the final candidate is not just that commit.
- The integration candidate currently has `48` modified tracked files and `222` untracked files on top of that HEAD.
- The Stage 20 verification result belongs to this integration candidate state, not to a clean `origin/master aa8336a` baseline.
- Auditing only `origin/master aa8336a` would miss the current final candidate changes and would not represent the bot currently used for manual smoke.
