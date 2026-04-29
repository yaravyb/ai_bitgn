import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    # Output and context.
    # LESSON LEARNED: aggressive per-step trimming (micro_compact) breaks
    # multi-step reasoning on long tasks (agent loops because it forgets
    # what it already did). So we keep the executor's context generous
    # and rely on auto_compact (full LLM summarization) as the only
    # trimming mechanism, triggered only when truly needed.
    output_cap: int = 10_000
    auto_compact_threshold: int = 60_000
    micro_compact_enabled: bool = False
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
