"""Observability integration: register LiteLLM callbacks for Langfuse.

Leaf module: no imports from other project modules.
Activates only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set
and the Langfuse host is reachable.
"""

from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

import litellm

log = logging.getLogger(__name__)

_LANGFUSE_DEFAULT_HOST = "https://cloud.langfuse.com"
_CONNECT_TIMEOUT_S = 2


def _langfuse_host_reachable() -> bool:
    """Return True if the Langfuse host is accepting TCP connections."""
    host_url = os.environ.get("LANGFUSE_HOST", _LANGFUSE_DEFAULT_HOST)
    parsed = urlparse(host_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        sock = socket.create_connection((host, port), timeout=_CONNECT_TIMEOUT_S)
        sock.close()
        return True
    except (OSError, socket.timeout):
        return False


def configure_observability() -> None:
    """Register Langfuse as LiteLLM callback if credentials are available.

    Activates automatically when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
    are set **and** the Langfuse host is reachable. Silently no-ops when
    credentials are missing, langfuse is not installed, or the host is down.
    Never raises exceptions.
    """
    try:
        public_key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret_key = os.environ.get("LANGFUSE_SECRET_KEY")

        if not public_key or not secret_key:
            return

        try:
            import langfuse  # noqa: F401
        except ImportError:
            log.warning(
                "Langfuse credentials are set but the langfuse package is not installed. "
                "Install with: uv sync --group observability"
            )
            return

        if not _langfuse_host_reachable():
            log.info(
                "Langfuse credentials are set but the host is unreachable (%s); "
                "observability disabled.",
                os.environ.get("LANGFUSE_HOST", _LANGFUSE_DEFAULT_HOST),
            )
            return

        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")

        # Suppress noisy Langfuse HTTP errors from cluttering agent output
        logging.getLogger("langfuse").setLevel(logging.CRITICAL)

        log.info("Observability active: Langfuse callbacks registered.")
    except Exception:
        log.exception("Unexpected error during observability configuration; skipping.")
