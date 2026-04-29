# Dockerize PAC1 Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package `pac1-py/main.py` as a reproducible Docker image, with secrets bind-mounted from `pac1-py/.env.docker` and logs persisted to `pac1-py/runs/` via a `tee` entrypoint wrapper.

**Architecture:** Single-stage Dockerfile on `ghcr.io/astral-sh/uv:python3.13-bookworm-slim`. Deps layer (`pyproject.toml` + `uv.lock`) is built separately from the source layer for cache friendliness. A non-root `app` user is created with the host UID/GID so bind-mount writes stay owned by the invoking user. `main.py` is **not** modified — `load_dotenv(override=True)` already finds `/app/.env` once the env file is bind-mounted there.

**Tech Stack:** Docker 28, Debian bookworm-slim, Python 3.13, `uv` (frozen lockfile installs), GNU Make, Bash.

**Spec:** `docs/superpowers/specs/2026-04-20-dockerize-pac1-design.md` (commit `cf6d8c4`)

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `pac1-py/.dockerignore` | create | Exclude VCS, caches, `runs/`, tests, **all env files** from build context |
| `pac1-py/docker-entrypoint.sh` | create | `tee` wrapper: run `main.py`, mirror stdout/stderr to `runs/docker_<ts>.txt` |
| `pac1-py/Dockerfile` | create | Image build: deps layer, source layer, non-root user, entrypoint |
| `pac1-py/Makefile` | modify | Add `docker-build` and `docker-run` targets |

No changes to `main.py`, `pyproject.toml`, `uv.lock`, or anything under `agent/` / `skills/`.

---

## Task 1: Create `.dockerignore`

**Why first:** The rest of the plan builds an image. `.dockerignore` must exist *before* the first `docker build` so secrets and noise never enter the build context in the first place. Missing this file = `.env.docker` could leak into an image layer on the first build.

**Files:**
- Create: `pac1-py/.dockerignore`

- [ ] **Step 1: Write `pac1-py/.dockerignore`**

```
# VCS + editor
.git
.gitignore
.vscode
.idea

# Python artefacts
__pycache__
*.pyc
.venv

# Local/test output
runs/
tests/

# Secrets — belt + braces. Never bake env files into a layer.
.env
.env.*
.env.docker
.env_batch

# Docs
*.md
```

- [ ] **Step 2: Verify the file exists and excludes env files**

Run from `/home/yaravyb/CODE/ai_bitgn/pac1-py`:
```bash
grep -E '^\.env' .dockerignore
```
Expected: prints the four env-file lines (`.env`, `.env.*`, `.env.docker`, `.env_batch`).

- [ ] **Step 3: Commit**

```bash
git add pac1-py/.dockerignore
git commit -m "add .dockerignore to keep secrets + build noise out of docker context"
```

---

## Task 2: Create `docker-entrypoint.sh`

**Files:**
- Create: `pac1-py/docker-entrypoint.sh`

- [ ] **Step 1: Write `pac1-py/docker-entrypoint.sh`**

```bash
#!/bin/bash
set -eo pipefail

mkdir -p runs
TS=$(date +%Y%m%d_%H%M%S)
LOG="runs/docker_${TS}.txt"

echo "[entrypoint] logging to ${LOG}" >&2
uv run --frozen python main.py "$@" 2>&1 | tee "${LOG}"
```

Why each line:
- `set -eo pipefail` — without `pipefail`, `tee` hides a non-zero exit from `main.py`.
- `mkdir -p runs` — the bind-mount may not exist if a user runs without `-v`; don't let the log write fail.
- `uv run --frozen` — no lockfile resolution at runtime; the venv was built once during `docker build`.
- `"$@"` — forwards positional args from `docker run … <image> t01 t03` straight into `main.py`'s `task_filter`.
- `2>&1 | tee` — both streams go to the log file *and* to `docker logs`.

- [ ] **Step 2: Make it executable and verify syntax**

```bash
chmod +x pac1-py/docker-entrypoint.sh
bash -n pac1-py/docker-entrypoint.sh && echo OK
```
Expected: prints `OK`. `bash -n` is a parse-only check — catches typos without running the script.

- [ ] **Step 3: Commit**

```bash
git add pac1-py/docker-entrypoint.sh
git commit -m "add docker entrypoint that tees main.py output to runs/docker_<ts>.txt"
```

---

## Task 3: Create `Dockerfile`

**Files:**
- Create: `pac1-py/Dockerfile`

- [ ] **Step 1: Write `pac1-py/Dockerfile`**

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# --- dependency layer (cacheable: only invalidated when lockfile changes) ---
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# --- project source ---
COPY agent/   ./agent/
COPY skills/  ./skills/
COPY main.py observability.py tools.py skills.py tasks.py ./
COPY Makefile ./

# --- entrypoint wrapper ---
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/entrypoint.sh

# --- non-root user matching host UID/GID (defaults = typical desktop Linux) ---
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd -g ${HOST_GID} app \
 && useradd  -u ${HOST_UID} -g app -m -s /bin/bash app \
 && chown -R app:app /app
USER app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
```

Notes on specific lines:
- `UV_LINK_MODE=copy` — prevents hardlink warnings when uv's cache crosses filesystems inside the image.
- `UV_PROJECT_ENVIRONMENT=/app/.venv` — pins venv location so `uv run --frozen` inside the entrypoint finds it without re-resolving.
- `COPY pyproject.toml uv.lock` *before* source — source edits (editing `main.py`) won't invalidate the deps layer. Rebuilds take seconds.
- No `COPY . .` anywhere — explicit paths mean future stray files can't sneak in even if `.dockerignore` has a gap.
- `CMD []` — no default args; running the image with no args runs the full benchmark (just like `make run`).

- [ ] **Step 2: Verify Dockerfile syntax via `docker build --check`**

Run from `/home/yaravyb/CODE/ai_bitgn/pac1-py`:
```bash
docker build --check .
```
Expected: exits 0. No `ERROR:` lines. Warnings about `FROM` platform mismatch on ARM machines are OK. (`--check` runs BuildKit's linter without executing the build.)

- [ ] **Step 3: Commit**

```bash
git add pac1-py/Dockerfile
git commit -m "add Dockerfile for pac1 agent: uv-based image, non-root user, cacheable deps layer"
```

---

## Task 4: Build the image end-to-end

**Purpose:** Verify Tasks 1–3 compose correctly by actually building. This is the "does it run" test for the Docker files themselves. No Makefile yet — we invoke `docker build` directly so failures point at the Dockerfile, not the Makefile.

**Files:** none modified.

- [ ] **Step 1: Run the build**

From `/home/yaravyb/CODE/ai_bitgn/pac1-py`:
```bash
docker build -t pac1-agent \
  --build-arg HOST_UID=$(id -u) \
  --build-arg HOST_GID=$(id -g) \
  .
```
Expected: finishes with `Successfully tagged pac1-agent:latest` (or the BuildKit equivalent `=> naming to docker.io/library/pac1-agent`). No red error lines.

If the `uv sync` step fails with "package index unreachable", check network — the build fetches from both PyPI and `buf.build/gen/python`.

- [ ] **Step 2: Confirm no secrets leaked into any layer**

```bash
docker history --no-trunc pac1-agent | grep -iE 'bitgn_api_key|llm_api_key|LLM_API_KEY=|BITGN_API_KEY=' || echo "CLEAN"
```
Expected: prints `CLEAN`. Any other output = a secret somehow made it into the image; stop and diagnose before proceeding.

- [ ] **Step 3: Confirm image size is sane**

```bash
docker image inspect pac1-agent --format '{{.Size}}' | awk '{printf "%.0f MB\n", $1/1024/1024}'
```
Expected: 400–900 MB range (depends on whether `langfuse` / `pandas` / `boto3` pulled big wheels). Anything over 1.5 GB means the source layer accidentally included `runs/` or `.venv` — inspect `.dockerignore`.

- [ ] **Step 4: No commit**

This task only verifies; nothing was edited.

---

## Task 5: Add Makefile targets

**Files:**
- Modify: `pac1-py/Makefile`

- [ ] **Step 1: Read the current Makefile to find the insertion point**

```bash
cat pac1-py/Makefile
```
Expected: four lines under `.PHONY: sync run task` with the `sync`, `run`, `task` targets. Insertion goes at the end of the file.

- [ ] **Step 2: Append the new targets**

Edit `pac1-py/Makefile`. Change:

```makefile
.PHONY: sync run task

sync:
	uv sync

run:
	uv run python main.py

task:
	@if [ -z "$(TASKS)" ]; then echo "usage: make task TASKS='t01 t03'"; exit 1; fi
	uv run python main.py $(TASKS)
```

To:

```makefile
.PHONY: sync run task docker-build docker-run

sync:
	uv sync

run:
	uv run python main.py

task:
	@if [ -z "$(TASKS)" ]; then echo "usage: make task TASKS='t01 t03'"; exit 1; fi
	uv run python main.py $(TASKS)

# --- Docker ---

IMAGE    ?= pac1-agent
ENV_FILE ?= $(PWD)/.env.docker

docker-build:
	docker build -t $(IMAGE) \
		--build-arg HOST_UID=$(shell id -u) \
		--build-arg HOST_GID=$(shell id -g) \
		.

docker-run:
	docker run --rm -it \
		-v $(ENV_FILE):/app/.env:ro \
		-v $(PWD)/runs:/app/runs \
		$(IMAGE) $(TASKS)
```

Exactly two lines change outside the new block: `.PHONY` gets `docker-build docker-run` appended.

- [ ] **Step 3: Verify Make parses the new targets**

```bash
cd pac1-py && make -n docker-build
```
Expected: prints the `docker build -t pac1-agent --build-arg HOST_UID=<your-uid> --build-arg HOST_GID=<your-gid> .` line with your actual UID/GID expanded. No "No rule to make target" errors.

```bash
cd pac1-py && make -n docker-run
```
Expected: prints the `docker run --rm -it -v /home/yaravyb/CODE/ai_bitgn/pac1-py/.env.docker:/app/.env:ro -v /home/yaravyb/CODE/ai_bitgn/pac1-py/runs:/app/runs pac1-agent` line.

- [ ] **Step 4: Commit**

```bash
git add pac1-py/Makefile
git commit -m "add docker-build and docker-run make targets"
```

---

## Task 6: End-to-end run with one task

**Purpose:** Exercise the full flow — build via Make, run a single benchmark task, confirm the log file appears with correct ownership.

**Files:** none modified.

- [ ] **Step 1: Rebuild via Make to confirm the target works**

```bash
cd pac1-py && make docker-build
```
Expected: same outcome as Task 4 Step 1, but invoked through Make. The `--build-arg`s should be filled in from `$(shell id -u)` / `$(shell id -g)`.

- [ ] **Step 2: Run one task end-to-end**

```bash
cd pac1-py && make docker-run TASKS='t01'
```

Expected terminal output (trimmed):
- `[entrypoint] logging to runs/docker_<ts>.txt` (on stderr)
- `Model: openai/qwen3.6:35b-a3b-q4_K_M  benchmark: bitgn/pac1-prod` (from `main.py`)
- `Connecting to BitGN …`
- `…tasks.` line with benchmark description
- `Run: <run-id> (<n> trials)`
- `======…====== Starting task: t01 ======…======`
- Trial executes, ends with a `Score: X.XX (Ys)` line
- Clean exit (shell prompt returns, no non-zero error code)

If it exits with `RuntimeError: BITGN_API_KEY is not set in the environment (.env)`: the bind-mount path is wrong. Re-check that `pac1-py/.env.docker` exists and is not empty.

- [ ] **Step 3: Confirm the log file exists, is non-empty, and is host-user-owned**

```bash
ls -l pac1-py/runs/docker_*.txt | tail -1
```
Expected: file shown, owner = `yaravyb` (or whatever `id -un` prints — NOT `root`), size > 1 KB.

- [ ] **Step 4: Confirm log content matches what appeared on the terminal**

```bash
tail -20 "$(ls -1t pac1-py/runs/docker_*.txt | head -1)"
```
Expected: last ~20 lines of the run (the scoring summary). Colour escape codes may be present — that's fine; they render when `cat`-ing in a terminal.

- [ ] **Step 5: No commit**

This task only verifies.

---

## Task 7: Failure-mode verification

**Purpose:** Confirm the image fails *correctly* when its dependencies are missing. Catches the class of bugs where a misconfigured image silently "works" by using baked-in secrets.

**Files:** none modified.

- [ ] **Step 1: Run without bind-mounting the env file**

```bash
docker run --rm pac1-agent t01
```
Expected: exits non-zero with Python traceback ending in `RuntimeError: BITGN_API_KEY is not set in the environment (.env)`. This proves no secrets were baked into the image — the container genuinely has no credentials of its own.

- [ ] **Step 2: Run with env file but invalid task id**

```bash
cd pac1-py && make docker-run TASKS='t-does-not-exist'
```
Expected: image starts, connects to BitGN (shows `Connecting to BitGN … status: OK`), iterates through trials but skips all of them because none match the filter, then exits 0 (matches non-Docker behaviour of `make task TASKS='t-does-not-exist'`).

- [ ] **Step 3: Confirm no commit needed**

End of plan. No file changes in this task.

---

## Post-Implementation Summary

After all tasks land, the repository gains:
- 3 new files in `pac1-py/`: `.dockerignore`, `docker-entrypoint.sh`, `Dockerfile`
- 2 new Make targets: `docker-build`, `docker-run`
- Unchanged: `main.py`, all existing Make targets, `pyproject.toml`, `uv.lock`, `agent/`, `skills/`

Workflow after this plan:
- Local dev unchanged — `make run` still works.
- Containerised run — `make docker-build` once, then `make docker-run TASKS='t01 t03'`.
- Each container run writes a timestamped file to `runs/docker_<ts>.txt`, owned by the host user.
