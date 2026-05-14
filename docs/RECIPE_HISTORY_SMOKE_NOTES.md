# Recipe History Smoke Notes

Date: 2026-05-14

## Commits Covered

- `da85688` recipe history: add storage model
- `4ad6517` recipe history: record successful generations
- `0951533` recipe history: avoid recent recipes

Initial git check:

- `git status --short --branch`: clean on `codex/emergency-stabilization`, ahead of origin.
- `git log --oneline -8`: latest commits begin with `0951533`, `4ad6517`, `da85688`.

## Focused Test Commands

Storage:

```powershell
python -m pytest --basetemp .pytest-smoke-storage tests/test_storage_contract.py tests/test_json_storage.py tests/test_postgres_migrations.py tests/test_postgres_store.py tests/test_json_to_postgres_migration.py -k "storage_contract or json_recipe_history or recent_history or user_recipe_history or recipe_history or migration_imports_history"
```

Result: `4 passed, 3 skipped, 39 deselected`. PostgreSQL store cases were skipped because no `--require-postgres` test database was requested.

Telegram runtime history:

```powershell
python -m pytest tests/test_telegram_app_runtime.py -k "recipe_history or structured_recent_history or recent_recipe_avoidance"
```

Result: `7 passed, 28 deselected`.

Weekly / exclusion targeted tests:

```powershell
python -m pytest tests/test_safety_and_builder.py tests/test_weekly_optimizer_candidates.py -k "weekly_recent_history or second_weekly_generation or fallback_still_returns or weekly_generation_respects_food_exclusions or weekly_generation_with_enough_pool_has_no_repeated_recipe_id or exclusions_flow_into_candidate_generation"
```

Result: `7 passed, 87 deselected`.

Recipe effort / coverage smoke:

```powershell
python -m pytest tests/test_recipe_effort_slot_coverage.py
```

Result: `9 passed`.

Diff whitespace check:

```powershell
git diff --check
```

Result: passed with no output.

## Local Generation Harness

The sample generation used the same normal profile shape as the earlier recipe import smoke, with the requested weekly settings:

- male, 32, 178 cm, 86 kg, moderate activity
- `MAINTAIN`
- `SIMPLE`
- `5` meals
- no exclusions for the main run

The harness used temp JSON history state outside the repo, loaded recent history through `load_recent_recipe_history_from_json`, converted it with `_recent_recipe_avoidance_from_history`, generated weeks through `_build_week_plans_with_recent_fallback`, and recorded successful weeks back through `record_recipe_history_in_json`.

Consecutive weekly seeds followed the Telegram runtime weekly seed step:

- base seed: `101`
- step: `WEEK_PLAN_DAYS * WEEK_PLAN_CANDIDATE_COUNT` = `28`
- generated seeds: `101`, `129`, `157`, `185`

Imported recipe usage below means recipe IDs `r401+`.

## Main Profile Results

All four main-profile weeks produced complete `7x5` plans with `35/35` unique recipe IDs inside each week. No exact repeated week was produced.

| Week | Seed | Generated at | Avoidance phase | Shape | Unique IDs | Protein ratio min-max | Imported usage |
| --- | ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | 101 | 2026-05-14 09:00 UTC | `no_recent` | 7x5 | 35/35 | 1.277-1.505 | 12 |
| 2 | 129 | 2026-05-21 09:00 UTC | `no_recent` | 7x5 | 35/35 | 1.276-1.568 | 15 |
| 3 | 157 | 2026-05-28 09:00 UTC | `no_recent` | 7x5 | 35/35 | 1.281-1.587 | 11 |
| 4 | 185 | 2026-06-04 09:00 UTC | `no_recent` | 7x5 | 35/35 | 1.277-1.428 | 13 |

## Main Overlap Table

Recent overlap was not significantly lower than the previous `19-24/35` baseline. The recorded-history smoke stayed in the same range because every generation relaxed all the way to `no_recent`.

| Pair | Shared recipe IDs | Exact same week |
| --- | ---: | --- |
| Week 1 vs week 2 | 22/35 | no |
| Week 2 vs week 3 | 17/35 | no |
| Week 3 vs week 4 | 23/35 | no |
| Week 1 vs week 4 | 21/35 | no |

## Constrained Profile Results

Short constrained run used `MAINTAIN/simple/5` plus disliked `broccoli` as a hard excluded food.

Both weeks produced complete `7x5` plans with `35/35` unique recipe IDs inside each week. Broccoli was absent from both direct food IDs and curated recipe ingredient IDs.

| Week | Seed | Avoidance phase | Shape | Unique IDs | Exclusion violations | Protein ratio min-max | Imported usage |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | 101 | `no_recent` | 7x5 | 35/35 | 0 | 1.254-1.520 | 13 |
| 2 | 129 | `no_recent` | 7x5 | 35/35 | 0 | 1.277-1.557 | 13 |

Constrained overlap:

| Pair | Shared recipe IDs | Exact same week |
| --- | ---: | --- |
| Week 1 vs week 2 | 22/35 | no |

## Fallback Phases

Observed phases:

- Main profile: `no_recent`, `no_recent`, `no_recent`, `no_recent`
- Broccoli constrained profile: `no_recent`, `no_recent`

This means structured history was recorded and loaded, but the recent-history constraints were relaxed to no avoidance to preserve complete `7x5` weekly generation for these sampled `MAINTAIN/simple/5` profiles.

## Checks Against Smoke Criteria

| Check | Result |
| --- | --- |
| Each week is `7x5` | pass |
| `35/35` unique inside each week | pass |
| Exclusions respected | pass for broccoli constrained run |
| No exact repeated week | pass |
| Recent overlap significantly lower than prior `19-24/35` | not confirmed |
| Fallback phases recorded | pass |
| Photos generated | not run, per smoke instruction |

## Remaining Limitations

- For `MAINTAIN/simple/5`, recent history did not reduce overlap in this smoke because the weekly builder fell back to `no_recent` for every sampled follow-up week.
- Protein ratios remain materially above target on some days. The highest observed day in this smoke was `1.587x`.
- The storage tests covered JSON fallback and contract/migration shape locally; PostgreSQL store behavior remained skipped without a test database.
- This was a smoke/check slice only. No recipe photos were generated, no code cleanup/refactor was done, and no push was performed.
