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
