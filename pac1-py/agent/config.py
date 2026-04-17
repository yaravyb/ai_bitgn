import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    # Output and context
    output_cap: int = 10_000
    # Lower threshold so long-running tasks compact BEFORE context grows
    # large enough to cause 60+ second LLM inference (which triggers
    # upstream nginx 504 gateway timeouts).
    auto_compact_threshold: int = 40_000
    # Enable micro-compact by default — trims older tool results so the
    # conversation stays small without needing full LLM summarization.
    micro_compact_enabled: bool = True
    micro_compact_keep_turns: int = 5
    smart_truncation_enabled: bool = False

    # LLM
    llm_api_base: str | None = None
    llm_api_key: str | None = None
    max_retries: int = 3
    retry_base_delay: float = 1.0
    max_executor_steps: int = 50

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            output_cap=int(os.environ.get("CTX_TRUNCATION_LIMIT", "10000")),
            auto_compact_threshold=int(os.environ.get("CTX_AUTO_COMPACT_THRESHOLD", "80000")),
            llm_api_base=os.environ.get("LLM_API_BASE"),
            llm_api_key=os.environ.get("LLM_API_KEY"),
        )
