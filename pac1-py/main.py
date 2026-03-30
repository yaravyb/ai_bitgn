import os
import textwrap
import time
import uuid

from dotenv import load_dotenv
load_dotenv(override=True)

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import EndTrialRequest, EvalPolicy, GetBenchmarkRequest, StartPlaygroundRequest, StatusRequest
from connectrpc.errors import ConnectError

from agent import run_agent
from observability import configure_observability

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"
BENCHMARK_ID = os.getenv("BENCHMARK_ID") or "bitgn/pac1-dev"
MODEL_ID = os.getenv("MODEL_ID") or "openai/gpt-4.1-2025-04-14"

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"
CLI_BLUE = "\x1B[34m"


def main() -> None:
    configure_observability()

    task_filter = os.sys.argv[1:]

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

        for task in res.tasks:
            if task_filter and task.task_id not in task_filter:
                continue

            print(f"{'=' * 30} Starting task: {task.task_id} {'=' * 30}")
            trial = client.start_playground(
                StartPlaygroundRequest(
                    benchmark_id=BENCHMARK_ID,
                    task_id=task.task_id,
                )
            )

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
                scores.append((task.task_id, result.score, task_elapsed))
                style = CLI_GREEN if result.score == 1 else CLI_RED
                explain = textwrap.indent("\n".join(result.score_detail), "  ")
                print(f"\n{style}Score: {result.score:0.2f}  ({task_elapsed:.1f}s)\n{explain}\n{CLI_CLR}")

    except ConnectError as exc:
        print(f"{exc.code}: {exc.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    total_elapsed = time.time() - run_start

    if scores:
        print(f"\nModel: {MODEL_ID}")
        print("-" * 40)
        for task_id, score, elapsed in scores:
            style = CLI_GREEN if score == 1 else CLI_RED
            print(f"{task_id}: {style}{score:0.2f}{CLI_CLR}  ({elapsed:.1f}s)")
        print("-" * 40)
        avg = sum(s[1] for s in scores) / len(scores) * 100.0
        print(f"FINAL: {avg:0.2f}%  |  Total: {total_elapsed:.1f}s  |  Tasks: {len(scores)}")


if __name__ == "__main__":
    main()
