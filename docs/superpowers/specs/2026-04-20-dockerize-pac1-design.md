# Design: Dockerize the PAC1 agent (`pac1-py/main.py`)

**Date:** 2026-04-20
**Scope:** Package `pac1-py/main.py` as a reproducible container image, runnable locally via `make docker-build` / `make docker-run`, with secrets supplied at runtime and benchmark output persisted on the host.

## Goals

- Reproducible image built from `pyproject.toml` + `uv.lock` — no drift between local and containerised runs.
- `main.py` runs inside the container unchanged. No code edits in `pac1-py/`.
- Secrets never live inside any image layer.
- Every container run writes a timestamped log file to a host-visible `runs/` directory, in addition to stdout.
- Bind-mounted output files are owned by the host user, not by root.

## Non-goals

- Dockerizing `main_batch.py` or `run_targeted.py` (currently untracked working-tree scripts).
- A multi-service `docker-compose` setup. This spec ships a single image and Makefile wrappers.
- Any form of distroless or multi-stage image — overkill for a benchmark runner that is iterated on.
- Running the image in CI or pushing to a registry. Local-only for now.

## Architecture

Three new files in `pac1-py/`, plus two new Makefile targets. The existing Makefile `run` / `task` targets remain for non-Docker local runs.

```
pac1-py/
├── Dockerfile                 # NEW — image build
├── docker-entrypoint.sh       # NEW — wraps main.py with tee-to-runs/
├── .dockerignore              # NEW — keeps secrets + build noise out of context
├── Makefile                   # EDIT — add docker-build / docker-run
├── .env.docker                # EXISTING — bind-mounted at runtime (never COPYed)
└── (everything else unchanged)
```

### Base image

`ghcr.io/astral-sh/uv:python3.13-bookworm-slim`

Ships Python 3.13 and `uv` pre-installed. Saves ~85 MB versus `python:3.13-slim` + a `pip install uv` layer, and keeps the `uv` version aligned with what Astral ships.

### Dockerfile structure

Single stage, layered for cache-friendliness.

```dockerfile
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# --- dependency layer (cacheable) ---
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# --- project source ---
COPY agent/   ./agent/
COPY skills/  ./skills/
COPY main.py observability.py tools.py skills.py tasks.py ./
COPY Makefile ./

# --- entrypoint wrapper ---
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/entrypoint.sh

# --- non-root user matching host UID/GID ---
ARG HOST_UID=1000
ARG HOST_GID=1000
RUN groupadd -g ${HOST_GID} app \
 && useradd -u ${HOST_UID} -g app -m -s /bin/bash app \
 && chown -R app:app /app
USER app

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD []
```

Key decisions:

- **`UV_LINK_MODE=copy`** avoids hardlink warnings when the cache and venv cross filesystems inside the image.
- **`UV_PROJECT_ENVIRONMENT=/app/.venv`** pins the venv location so the entrypoint does not need to re-resolve it.
- **Dependency layer first** (`COPY pyproject.toml uv.lock` → `uv sync --frozen --no-install-project`) means editing `main.py` or `agent/*.py` does not invalidate the deps layer — rebuilds are seconds, not minutes.
- **`COPY` is explicit** (no `COPY . .`) so stray files — `runs/`, `.env*`, `__pycache__`, local edits — cannot leak into the image even if `.dockerignore` is mis-edited.
- **Non-root user with build-arg UID/GID** means files written to the bind-mounted `runs/` appear on the host owned by the invoking user, not by root. Defaults (1000/1000) work for typical Linux desktops; the Makefile overrides them via `$(shell id -u)` / `$(shell id -g)`.

### `docker-entrypoint.sh`

```bash
#!/bin/bash
set -eo pipefail

mkdir -p runs
TS=$(date +%Y%m%d_%H%M%S)
LOG="runs/docker_${TS}.txt"

echo "[entrypoint] logging to ${LOG}" >&2
uv run --frozen python main.py "$@" 2>&1 | tee "${LOG}"
```

- **`set -eo pipefail`** so a non-zero exit from `main.py` propagates even though it is the left side of a pipe.
- **`2>&1 | tee`** captures both stdout and stderr into the log file while keeping `docker logs` populated.
- **`"$@"`** forwards any positional args from `docker run … <image> t01 t03` straight into `main.py`'s `task_filter`.
- **`uv run --frozen`** skips any lockfile re-resolution at container start — the venv is already populated from `uv sync --frozen` during build, so startup is a plain `exec` into the venv's Python.

### `.dockerignore`

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

The `.env.docker` line is load-bearing: the file sits inside the build context and would otherwise be reachable by a `COPY . .` in a future edit. Listing it explicitly makes the intent obvious to anyone reviewing the Dockerfile later.

### Makefile additions

```makefile
IMAGE    ?= pac1-agent
ENV_FILE ?= $(PWD)/.env.docker

.PHONY: docker-build docker-run

docker-build:
	docker build -t $(IMAGE) \
		--build-arg HOST_UID=$(shell id -u) \
		--build-arg HOST_GID=$(shell id -g) .

docker-run:
	docker run --rm -it \
		-v $(ENV_FILE):/app/.env:ro \
		-v $(PWD)/runs:/app/runs \
		$(IMAGE) $(TASKS)
```

Usage:

- `make docker-build` — one-time per deps/source change.
- `make docker-run` — full benchmark.
- `make docker-run TASKS='t01 t03'` — filtered run, forwarded as positional args.
- `make docker-run ENV_FILE=/some/other/.env` — override secrets source without editing the Makefile.

## Data flow

```
Host                                   Container
─────────────────────────────────────────────────────────────────────
pac1-py/.env.docker (secrets)  ───RO─▶  /app/.env
                                        └─ load_dotenv(override=True)   (main.py:8)
pac1-py/runs/                  ───RW─▶  /app/runs
                                        └─ tee writes docker_<ts>.txt   (entrypoint)

                                        main.py calls out to:
                                          - BENCHMARK_HOST (api.bitgn.com)
                                          - LLM_API_BASE (gpt.azati.com/llm-api)
                                          - optional: LANGFUSE_HOST
```

Nothing in `main.py` needs to change: `load_dotenv(override=True)` finds `/app/.env`, reads the same keys it already reads locally.

## Secrets handling

- `.env.docker` is **bind-mounted read-only** at runtime, never `COPY`ed. No secret values enter any image layer.
- `.dockerignore` lists every known env-file pattern so a mistaken `COPY . .` in a future edit cannot bake them in.
- The image itself has no baked-in credentials and is safe to push to an internal registry later if that ever becomes useful.

## Error handling

- `set -eo pipefail` in the entrypoint preserves `main.py`'s exit code across the `tee` pipe.
- `main.py` already catches `ConnectError` and `KeyboardInterrupt` and prints a message; no change needed.
- Missing `/app/.env`: `load_dotenv` silently no-ops, then `main.py` raises `RuntimeError("BITGN_API_KEY is not set …")` — the existing behaviour — and the container exits non-zero. Acceptable; the error message is already actionable.
- Missing `runs/` bind-mount: `mkdir -p runs` in the entrypoint creates `/app/runs` inside the container so the log write does not fail; the file is simply lost when the container exits. Acceptable.

## Testing

Manual verification after implementation:

1. `make docker-build` succeeds with no warnings about missing files.
2. `docker image inspect pac1-agent` — confirm no env values leaked into layer metadata.
3. `make docker-run TASKS='t01'` — completes one trial, prints the scoring line, exits 0.
4. `ls -la runs/` — new `docker_<ts>.txt` file owned by the host user (not root), contents match what was printed to the terminal.
5. `make docker-run` with `.env.docker` temporarily moved aside — exits with the existing `BITGN_API_KEY is not set` RuntimeError.
6. `docker run --rm pac1-agent t01` without the env bind-mount — same RuntimeError, confirming no baked-in secrets.

## Out-of-scope / future work

- **CI build**: adding a GitHub Actions job that builds and smoke-tests the image on push. Straightforward once the local flow lands.
- **`compose.yml`**: useful if a local LLM sidecar (e.g. `ollama`) is ever bundled.
- **Distroless runtime**: would shave another ~40 MB but complicates debugging; defer until image size actually matters.
- **Dockerizing `main_batch.py` / `run_targeted.py`**: wait until those scripts stabilise and are committed.
