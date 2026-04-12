import json
import time

from bitgn.vm.pcm_connect import PcmRuntimeClientSync
from bitgn.vm.pcm_pb2 import ReadRequest
from google.protobuf.json_format import MessageToDict

from agent.config import AgentConfig
from agent.llm import call_llm
from agent.prompts import CLI_CLR, CLI_DIM, CLI_GREEN, CLI_YELLOW, build_validator_system
from tools import VALIDATION_TOOL


def validate_completion(
    config: AgentConfig,
    model: str,
    task_text: str,
    proposed_message: str,
    proposed_outcome: str,
    agents_md: str,
    execution_context: str,
    metadata: dict | None = None,
    vm: PcmRuntimeClientSync | None = None,
    files_read: list[str] | None = None,
) -> dict | None:
    """Validate proposed answer before submitting.

    Returns None if approved, or a dict with corrected outcome/message.
    """
    print(f"  {CLI_DIM}validating...{CLI_CLR}", end=" ", flush=True)

    # Provide raw file contents to the validator so it can verify executor's claims
    raw_files_section = ""
    if vm and files_read:
        file_blocks = []
        for path in files_read:
            # Normalize path: strip leading "/" for VM compatibility
            norm_path = path.lstrip("/")
            try:
                result = vm.read(ReadRequest(path=norm_path))
                content = MessageToDict(result).get("content", "") if result else ""
                if content:
                    file_blocks.append(f"<file path=\"{path}\">\n{content}\n</file>")
            except Exception as exc:
                print(f"{CLI_DIM}source-file skip {norm_path}: {exc}{CLI_CLR}", end=" ", flush=True)
                continue
        if file_blocks:
            raw_files_section = "\n\n<source-files>\n" + "\n".join(file_blocks) + "\n</source-files>"

    messages = [
        {"role": "system", "content": build_validator_system()},
        {
            "role": "user",
            "content": (
                f"<original-task>{task_text}</original-task>\n\n"
                f"<proposed-outcome>{proposed_outcome}</proposed-outcome>\n"
                f"<proposed-message>{proposed_message}</proposed-message>\n\n"
                f"<execution-context>\n{execution_context}\n</execution-context>\n\n"
                f"<agents-md>\n{agents_md[:1500]}\n</agents-md>"
                f"{raw_files_section}"
            ),
        },
    ]

    started = time.time()
    try:
        resp = call_llm(config, model, messages, [VALIDATION_TOOL], metadata)
        elapsed_ms = int((time.time() - started) * 1000)
        choice = resp.choices[0]

        if choice.message.tool_calls:
            tc = choice.message.tool_calls[0]
            args = json.loads(tc.function.arguments)
            approved = args.get("approved", True)
            corrected_outcome = args.get("corrected_outcome", proposed_outcome)
            corrected_message = args.get("corrected_message", "")
            reason = args.get("reason", "")

            if approved:
                print(f"{CLI_GREEN}approved{CLI_CLR} ({elapsed_ms} ms)")
                return None
            else:
                print(f"{CLI_YELLOW}corrected → {corrected_outcome}{CLI_CLR} ({elapsed_ms} ms): {reason}")
                return {
                    "outcome": corrected_outcome,
                    "message": corrected_message or proposed_message,
                }
        else:
            print(f"{CLI_DIM}no tool call ({elapsed_ms} ms){CLI_CLR}")
            return None

    except Exception as exc:
        elapsed_ms = int((time.time() - started) * 1000)
        print(f"{CLI_DIM}skipped ({elapsed_ms} ms): {exc}{CLI_CLR}")
        return None
