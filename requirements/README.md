# Dependency Locks

FoodBalance uses pip-tools locks for reproducible installs:

- `prod.txt` pins runtime dependencies from `pyproject.toml`.
- `dev.txt` pins runtime plus `[project.optional-dependencies].dev`.
- `lock-tools.in` and `lock-tools.txt` pin the tooling used to refresh the
  locks.

The package metadata in `pyproject.toml` remains the dependency source of
truth. Lock files are the install source of truth for CI, staging, production,
and release artifact builds. The `pyproject.toml` build-system pins keep source
and wheel builds from resolving floating build backend versions.

## Install From Locks

Production-style install:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\prod.txt
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe -m pip check
```

Developer/test install:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
```

## Update Locks

Refresh locks after any dependency declaration changes:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements\lock-tools.txt
.\.venv\Scripts\python.exe -m piptools compile requirements\lock-tools.in --resolver=backtracking --strip-extras --no-header --no-emit-index-url --allow-unsafe --output-file=requirements\lock-tools.txt
.\.venv\Scripts\python.exe -m piptools compile pyproject.toml --resolver=backtracking --strip-extras --no-header --no-emit-index-url --output-file=requirements\prod.txt
.\.venv\Scripts\python.exe -m piptools compile pyproject.toml --resolver=backtracking --strip-extras --extra=dev --no-header --no-emit-index-url --output-file=requirements\dev.txt
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements\dev.txt
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q src scripts tests
```

CI regenerates the locks into temporary files and compares package pins with
`scripts/check_dependency_locks.py`. The check permits the committed Windows
platform pins (`colorama`, `tzdata`) when the workflow runs on Linux.
