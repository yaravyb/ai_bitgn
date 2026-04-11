import os
import re
import textwrap
import time
import uuid

from dotenv import load_dotenv
load_dotenv(override=True)

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import (
    EndTrialRequest,
    EvalPolicy,
    GetBenchmarkRequest,
    StartRunRequest,
    StartTrialRequest,
    StatusRequest,
    SubmitRunRequest,
)
from connectrpc.errors import ConnectError

from agent import run_agent
from observability import configure_observability

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
MODEL_ID = os.getenv("MODEL_ID") or "openai/gpt-4.1-2025-04-14"
BITGN_API_KEY = os.getenv("BITGN_API_KEY") or ""

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"
CLI_BLUE = "\x1B[34m"

_QUANT_SUFFIX_RE = re.compile(r"(?:[-:][qQ]\d+_[A-Z0-9_]+|[-:]bf16|[-:]fp16|[-:]fp32)$")


def _run_display_name(model_id: str) -> str:
    """Derive the BitGN run display name from MODEL_ID.

    Strips the provider prefix and any trailing quantization/format suffix
    (e.g. "-q4_K_M", "-bf16", ":Q8_0"), then prefixes with the Azati team URL.
    Examples:
        openai/qwen3.5:27b-q4_K_M   → "https://azati.ai/ - qwen3.5:27b"
        openrouter/qwen/qwen3.5-27b  → "https://azati.ai/ - qwen3.5-27b"
        bedrock/us.meta.llama4-...    → "https://azati.ai/ - us.meta.llama4-..."
    """
    # Strip known provider prefixes; for openrouter/ also strip the org segment
    if model_id.startswith("openrouter/"):
        # openrouter/qwen/qwen3.5-27b → qwen3.5-27b (drop provider + org)
        parts = model_id.split("/", 2)
        short = parts[2] if len(parts) > 2 else parts[-1]
    else:
        short = model_id.split("/", 1)[-1]
    short = _QUANT_SUFFIX_RE.sub("", short)
    return f"https://azati.ai/ - {short}"


def main() -> None:
    configure_observability()

    task_filter = os.sys.argv[1:]

    if not BITGN_API_KEY:
        raise RuntimeError("BITGN_API_KEY is not set in the environment (.env)")

    run_name = _run_display_name(MODEL_ID)

    scores: list[tuple[str, float, float]] = []
    run_start = time.time()
    print(f"Model: {MODEL_ID}  benchmark: {BENCHMARK_ID}")
    try:
        client = HarnessServiceClientSync(BITGN_URL)
        print("Connecting to BitGN", client.status(StatusRequest()))
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id=BENCHMARK_ID))
        print(
            f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} "
            f"with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}"
        )

        run = client.start_run(StartRunRequest(
            benchmark_id=BENCHMARK_ID,
            name=run_name,
            api_key=BITGN_API_KEY,
        ))
        print(f"Run: {run.run_id} ({len(run.trial_ids)} trials)")

        try:
            for trial_id in run.trial_ids:
                trial = client.start_trial(StartTrialRequest(trial_id=trial_id))

                if task_filter and trial.task_id not in task_filter:
                    continue

                print(f"{'=' * 30} Starting task: {trial.task_id} {'=' * 30}")
                print(f"{CLI_BLUE}{trial.instruction}{CLI_CLR}\n{'-' * 80}")

                trace_metadata = {
                    "trace_id": str(uuid.uuid4()),
                    "trace_name": "run_agent",
                    "session_id": os.environ.get("SESSION_ID", ""),
                    "trace_metadata": {
                        "model": MODEL_ID,
                        "task": trial.instruction[:200],
                    },
                }

                task_start = time.time()
                try:
                    run_agent(MODEL_ID, trial.harness_url, trial.instruction, metadata=trace_metadata)
                except Exception as exc:
                    print(exc)
                task_elapsed = time.time() - task_start

                result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))
                if result.score >= 0:
                    scores.append((trial.task_id, result.score, task_elapsed))
                    style = CLI_GREEN if result.score == 1 else CLI_RED
                    explain = textwrap.indent("\n".join(result.score_detail), "  ")
                    print(f"\n{style}Score: {result.score:0.2f}  ({task_elapsed:.1f}s)\n{explain}\n{CLI_CLR}")
        finally:
            client.submit_run(SubmitRunRequest(run_id=run.run_id, force=True))

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    total_elapsed = time.time() - run_start

    if scores:
        print(f"\nModel: {MODEL_ID}")
        rows_per_col = 10
        cols = [scores[i:i + rows_per_col] for i in range(0, len(scores), rows_per_col)]
        col_width = 28
        # header separator
        print("─" * (col_width * len(cols)))
        for row_idx in range(rows_per_col):
            parts = []
            for col in cols:
                if row_idx < len(col):
                    task_id, score, elapsed = col[row_idx]
                    style = CLI_GREEN if score == 1 else CLI_RED
                    # visible text length: "t01: 1.00  (123.4s)" — pad to col_width
                    cell = f"{task_id}: {style}{score:0.2f}{CLI_CLR}  ({elapsed:.1f}s)"
                    visible_len = len(f"{task_id}: {score:0.2f}  ({elapsed:.1f}s)")
                    cell += " " * max(0, col_width - visible_len)
                    parts.append(cell)
                else:
                    parts.append(" " * col_width)
            print("".join(parts))
        print("─" * (col_width * len(cols)))
        avg = sum(s[1] for s in scores) / len(scores) * 100.0
        print(f"FINAL: {avg:0.2f}%  |  Total: {total_elapsed:.1f}s  |  Tasks: {len(scores)}")


if __name__ == "__main__":
    main()
