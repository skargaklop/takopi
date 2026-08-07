# Task 19: Cross-Platform GitHub Actions CI Matrix — Implementation Plan

> **For agentic workers:** Execute top-to-bottom. The existing CI workflow is Linux-only; this task extends it to a three-OS matrix and closes all documented gaps without regressing the notify-release pipeline.

## Context

Task 19 requires a CI pipeline that gates `master` on every push and PR. A workflow already exists at `.github/workflows/ci.yml`, but it runs **only on `ubuntu-latest`** — the cross-platform support mandate (ROADMAP §Cross-Platform Support) requires **Windows, macOS, and Linux**. Python 3.14 is the runtime; `PYTHONUTF8=1` is mandatory on Windows (and tolerated elsewhere). The repo already passes locally on Windows: 1041 tests pass, 3 skipped (2 live-ACP probes deselected by default + 1 worktree env), `ty check src tests` is at zero diagnostics (Task 18 complete), and `ruff format --check` / `ruff check` are clean.

Task 18 (zero-diagnostic `ty`) is already complete, so the ROADMAP's "ty `continue-on-error: true` until Task 18" guidance is obsolete — `ty` can be a hard gate immediately.

### Current CI gaps

1. **No OS matrix** — only `ubuntu-latest`. Cross-platform mandate violated.
2. **No `PYTHONUTF8=1`** — Windows needs it for `ty` output, subprocess stderr decoding, and any non-ASCII path handling.
3. **`--cov-fail-under=81` runs on Linux only** — coverage gate is meaningless if Linux-only; should run on one OS (not the full matrix, to avoid triple-counting).
4. **`test_subprocess_close.py`** — historically excluded in some plans; now passes on Windows and is a mandatory cross-platform gate (ROADMAP Task 6). Must NOT be ignored in CI.
5. **Docs build step** — currently in the matrix; depends on `zensical` and `scripts/docs_prebuild.py`. Should stay Linux-only (docs tooling) to avoid triple-building.
6. **`build` step** — currently in the matrix; should run on Linux only to avoid producing three identical artifacts.
7. **Telegram commit notification** — the existing `notify-commit` job sends a Telegram message on push to `master`. Per the user's decision, remove it entirely (the job exists solely for this notification).

### Known CI hazard: Windows pipe-finalizer warnings

Under the full suite on Windows, `tests/test_telegram_bridge.py::test_run_main_loop_command_defaults_to_chat_project[asyncio]` emits `PytestUnraisableExceptionWarning` from Windows asyncio proactor pipe transport GC. This is a pre-existing platform issue (passes in isolation). The CI plan must not treat these warnings as failures via `-W error`. The existing default warning filter is sufficient.

## Approach

### 1. Extend the `checks` job to a three-OS matrix for the test-bearing tasks

Convert the single `ubuntu-latest` runner into a matrix that covers `ubuntu-latest`, `macos-latest`, and `windows-latest` for the tasks that are cross-platform: `format`, `ruff`, `ty`, `pytest`.

Keep `build` and `docs` on a single OS (Linux) — they produce identical output regardless of OS and would waste CI minutes on the matrix.

### 2. Exact workflow structure

```yaml
name: CI

on:
  push:
    branches:
      - "master"
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  lint:
    name: lint (${{ matrix.task }}/${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        task: [format, ruff, ty]
    env:
      PYTHONUTF8: "1"
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.14"
          enable-cache: true
      - run: uv sync --frozen --no-install-project
      - name: format check
        if: matrix.task == 'format'
        run: uv run --no-sync ruff format --check --diff src tests
      - name: ruff check
        if: matrix.task == 'ruff'
        run: uv run --no-sync ruff check src tests --output-format=github
      - name: ty check
        if: matrix.task == 'ty'
        run: uv run --no-sync ty check src tests

  test:
    name: test (${{ matrix.os }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    env:
      PYTHONUTF8: "1"
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.14"
          enable-cache: true
      - run: uv sync --frozen
      - name: pytest
        run: uv run --no-sync pytest tests/ -q --no-cov
      # Coverage gate on Linux only (single source of truth, not triple-counted).
      - name: coverage gate
        if: matrix.os == 'ubuntu-latest'
        run: uv run --no-sync pytest tests/ -q --cov=takopi --cov-branch --cov-report=term-missing --cov-fail-under=81

  build:
    name: build (linux)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.14"
          enable-cache: true
      - run: uv build

  docs:
    name: docs (linux)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
      - uses: astral-sh/setup-uv@v7
        with:
          python-version: "3.14"
          enable-cache: true
      - run: uv sync --frozen --no-install-project --group docs
      - run: uv run --no-sync python scripts/docs_prebuild.py && uv run --no-sync zensical build --clean

```

### 3. Design decisions (rationale)

- **Split `lint` and `test` into separate jobs.** The current single-job matrix interleaves lint and test tasks under one `checks` job name. Splitting makes failure attribution clearer in the GitHub UI and lets the test job run the full `uv sync` (needed for `--cov`) while lint uses `--no-install-project` (faster).
- **`PYTHONUTF8: "1"` at the job `env:` level.** Applies to every step in every OS. Required on Windows; harmless on macOS/Linux.
- **Coverage on Linux only.** `--cov-fail-under=81` is a project gate, not a per-OS check. Running it once avoids triple-counting covered lines and keeps macOS/Windows test jobs faster (`--no-cov`).
- **Two pytest invocations in `test` on Linux.** The first runs `--no-cov` for speed and green/red clarity; the second adds coverage on Linux only. If this proves redundant in practice, consolidate to a single Linux step with coverage and keep `--no-cov` for macOS/Windows. Prefer the consolidated form if the double-run wastes CI minutes — it's the same test set.
- **`ty` is a hard gate.** Task 18 reached zero diagnostics, so no `continue-on-error: true`.
- **`test_subprocess_close.py` is NOT ignored.** It passes on Windows now and is a mandatory cross-platform gate. The ROADMAP Task 6 plan explicitly requires it.
- **`live_acp` tests are auto-skipped.** The `live_acp` marker tests require `TAKOPI_GROK_ACP_SESSION_ID` / `TAKOPI_OMP_ACP_SESSION_ID` env vars not present in CI. They skip automatically; no `--ignore` or `-m "not live_acp"` needed.
- **`build` and `docs` stay Linux-only.** Identical artifacts and docs regardless of OS; no reason to triple the minutes.
- **`fail-fast: false`.** Preserves the existing behavior — one OS failure doesn't cancel the others.
- **`setup-uv@v7` + `enable-cache: true`.** Preserves the existing caching strategy; uv's cache is keyed by `uv.lock` and is cross-platform safe.
- **`uv sync --frozen`.** Preserves the existing behavior — CI must not mutate the lockfile. If the lockfile is out of date, CI fails rather than silently resolving.
- **`notify-commit` job removed.** The existing `notify-commit` job exists solely to send a Telegram message on push to `master`. Per the user's decision, remove it entirely — no Telegram notification in CI. The `scripts/commit_notify.py` script stays in the repo (it may be useful elsewhere) but is no longer wired to CI.
- **No `-W error` anywhere.** The Windows asyncio pipe-finalizer `PytestUnraisableExceptionWarning` is pre-existing and unrelated to test correctness. The default warning filter lets the suite pass.

### 4. What NOT to change

- **`release.yml`** — the release pipeline (tag → build → PyPI publish → GitHub release → notify) is orthogonal and already correct. Do not touch it.
- **`pyproject.toml`** — the `[tool.pytest.ini_options]` `addopts` already includes `--cov-fail-under=81`. CI overrides this with `--no-cov` for non-Linux and explicit coverage flags for Linux. No pyproject change needed.
- **`conftest.py`** — no changes.
- **Test files** — no test changes needed for this task. The suite already passes on Windows.

## Critical files

- `.github/workflows/ci.yml` — rewrite to add the three-OS matrix, split lint/test jobs, add `PYTHONUTF8=1`.
- `ROADMAP.md:700-738` — Task 19 requirements and scope (reference only; mark Task 19 DONE in the outcome section after verification).
- `changelog.md` — add a CI entry under `unreleased > features`.

## TDD execution sequence

1. **Capture the current CI green state.** Push to a branch and confirm the existing Linux-only CI passes (baseline). If CI is already green on `master`, skip.
2. **Rewrite `ci.yml`** per the structure above.
3. **Push to a feature branch** and open a PR to trigger the full three-OS matrix.
4. **Observe and fix:**
   - If `ty` fails on any OS → investigate (should not happen; Task 18 is zero-diagnostics).
   - If `ruff format --check` fails → run `uv run ruff format` and commit the result.
   - If `ruff check` fails → fix the lint error.
   - If `pytest` fails on macOS/Linux → investigate the cross-platform failure (Windows already proven green locally).
   - If `pytest` fails on Windows with `PytestUnraisableExceptionWarning` → confirm it's the known pipe-finalizer issue; do NOT add `-W error`. If the warning is treated as an error by default pytest config, verify `pyproject.toml` has no `filterwarnings = ["error"]`.
5. **Merge** after all matrix cells are green.
6. **Update `ROADMAP.md`** Task 19 outcome and `changelog.md`.

## Verification

1. **Three-OS matrix green:**
   - `lint (format/ubuntu-latest)`, `lint (ruff/ubuntu-latest)`, `lint (ty/ubuntu-latest)` — all pass.
   - `lint (format/macos-latest)`, `lint (ruff/macos-latest)`, `lint (ty/macos-latest)` — all pass.
   - `lint (format/windows-latest)`, `lint (ruff/windows-latest)`, `lint (ty/windows-latest)` — all pass.
   - `test (ubuntu-latest)`, `test (macos-latest)`, `test (windows-latest)` — all pass.
   - `build (linux)` — passes.
   - `docs (linux)` — passes.
2. **Coverage gate:** `test (ubuntu-latest)` coverage step passes `--cov-fail-under=81`.
- **No Telegram notification:** the removed `notify-commit` job does NOT fire on push to `master`. Confirm no notification job exists in the final workflow.
- **No regression:** the existing `release.yml` pipeline is untouched and still triggers on `v*` tags.
5. **`test_subprocess_close.py` runs in CI** on all three OSs and passes.

## Assumptions & contingencies

- **Python 3.14 availability on GHA runners.** Python 3.14 is in pre-release as of 2026-08. If `actions/setup-python` or `setup-uv` cannot provision 3.14 on all three OSs, use `astral-sh/setup-uv@v7` with `python-version: "3.14"` (uv downloads its own standalone Python builds). If 3.14 is unavailable on a specific OS, mark that OS cell with `continue-on-error: true` and a comment linking to the tracking issue — but this should not be necessary with uv's standalone builds.
- **macOS test compatibility.** The suite is proven on Windows (1041 pass) but has not been run on macOS/Linux in this session. POSIX subprocess behavior (`os.killpg`, `start_new_session=True`) is the Linux/macOS path and is well-tested via `test_subprocess.py`. If a macOS-specific test fails, fix it at the source (this is exactly what the cross-platform matrix is designed to catch).
- **CI minutes cost.** The matrix triples lint and test CI minutes. If this is a concern, consider running `format`/`ruff`/`ty` on Linux only (they are not OS-dependent) and running `pytest` on all three OSs. This is a reasonable optimization: **lint gates are text transformations, not OS-dependent.** If the user prefers to minimize minutes, collapse `lint` back to a single Linux job and keep only `test` on the three-OS matrix. Flag this as a decision point.
- **uv cache on Windows.** `enable-cache: true` on `setup-uv@v7` uses a platform-appropriate cache directory. No special Windows config needed.
- **`--frozen` lockfile.** If the lockfile is stale relative to `pyproject.toml`, `uv sync --frozen` will fail. This is intentional — the lockfile should be committed and up-to-date. If CI fails on `uv sync --frozen`, run `uv lock` locally and commit.
