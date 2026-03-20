"""Observability integration: register LiteLLM callbacks for Langfuse.

Leaf module: no imports from other agent/ modules.
Activates only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
"""

from __future__ import annotations

import logging
import os

import litellm

log = logging.getLogger(__name__)


def configure_observability() -> None:
    """Register Langfuse as LiteLLM callback if credentials are available.

    Activates automatically when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
    are set. Silently no-ops when credentials are missing or langfuse
    is not installed. Never raises exceptions.
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

        if "langfuse" not in litellm.success_callback:
            litellm.success_callback.append("langfuse")
        if "langfuse" not in litellm.failure_callback:
            litellm.failure_callback.append("langfuse")

        log.info("Observability active: Langfuse callbacks registered.")
    except Exception:
        log.exception("Unexpected error during observability configuration; skipping.")
