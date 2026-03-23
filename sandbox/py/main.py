import os
import textwrap
import time
from pathlib import Path

from bitgn.harness_connect import HarnessServiceClientSync
from bitgn.harness_pb2 import StatusRequest, GetBenchmarkRequest, StartPlaygroundRequest, EvalPolicy, EndTrialRequest
from connectrpc.errors import ConnectError

from agent import run_agent
from agent.observability import configure_observability

BITGN_URL = os.getenv("BENCHMARK_HOST") or "https://api.bitgn.com"

# Model configuration: LiteLLM provider/model format
MODEL_ID = os.getenv("MODEL_ID") or os.getenv("EXECUTOR_MODEL") or "openai/gpt-4.1"
SCOUT_MODEL = os.getenv("SCOUT_MODEL") or MODEL_ID  # defaults to executor model
SKILLS_DIR = Path(__file__).parent / "skills"

CLI_RED = "\x1B[31m"
CLI_GREEN = "\x1B[32m"
CLI_CLR = "\x1B[0m"


def main() -> None:
    configure_observability()

    # optional task ids could be included as tasks to run, e.g. `python main.py task1 task2`
    task_filter = os.sys.argv[1:]


    scores = []
    run_start = time.time()
    print(f"Model: {MODEL_ID}  (scout: {SCOUT_MODEL})")
    try:
        client = HarnessServiceClientSync(BITGN_URL)
        print("Connecting to BitGN", client.status(StatusRequest()))
        res = client.get_benchmark(GetBenchmarkRequest(benchmark_id="bitgn/sandbox"))
        print(f"{EvalPolicy.Name(res.policy)} benchmark: {res.benchmark_id} with {len(res.tasks)} tasks.\n{CLI_GREEN}{res.description}{CLI_CLR}")


        for t in res.tasks:
            if task_filter and t.task_id not in task_filter:
                continue
            print("=" * 40)
            print(f"Starting Task: {t.task_id}")

            trial = client.start_playground(StartPlaygroundRequest(
                benchmark_id="bitgn/sandbox",
                task_id=t.task_id,
            ))

            print("Task:", trial.instruction)

            task_start = time.time()
            try:
                run_agent(
                    executor_model=MODEL_ID,
                    harness_url=trial.harness_url,
                    task_text=trial.instruction,
                    scout_model=SCOUT_MODEL,
                    skills_dir=SKILLS_DIR,
                )
            except Exception as e:
                print(e)
            task_elapsed = time.time() - task_start

            result = client.end_trial(EndTrialRequest(trial_id=trial.trial_id))


            if result.score >= 0:
                scores.append((t.task_id, result.score, task_elapsed))

                style = CLI_GREEN if result.score == 1 else CLI_RED

                explain = textwrap.indent("\n".join(result.score_detail), "  ")
                print(f"\n{style}Score: {result.score:0.2f}  ({task_elapsed:.1f}s)\n{explain}\n{CLI_CLR}")

    except ConnectError as e:
        print(f"{e.code}: {e.message}")
    except KeyboardInterrupt:
        print(f"{CLI_RED}Interrupted{CLI_CLR}")

    total_elapsed = time.time() - run_start

    # print scores as table
    if scores:
        print(f"\nModel: {MODEL_ID}")
        print("-" * 40)
        for tid, score, elapsed in scores:
            style = CLI_GREEN if score == 1 else CLI_RED
            print(f"{tid}: {style}{score:0.2f}{CLI_CLR}  ({elapsed:.1f}s)")

        # print average
        avg = sum(s[1] for s in scores) / len(scores) * 100.0
        print("-" * 40)
        print(f"FINAL: {avg:0.2f}%  |  Total: {total_elapsed:.1f}s  |  Tasks: {len(scores)}")


if __name__ == "__main__":
    main()
