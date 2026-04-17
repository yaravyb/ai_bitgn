import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    # Output and context — sized so per-call prefill stays <15s on a
    # 27B quantized model (which is the threshold to avoid upstream
    # nginx 504s at their 60s cutoff).
    output_cap: int = 5_000
    auto_compact_threshold: int = 25_000
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
