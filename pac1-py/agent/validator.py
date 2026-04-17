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
    virtual_date: str = "",
) -> dict | None:
    """Validate proposed answer before submitting.

    Returns None if approved, or a dict with corrected outcome/message.
    """
    print(f"  {CLI_DIM}validating...{CLI_CLR}", end=" ", flush=True)

    # Provide raw file contents to the validator so it can verify executor's claims.
    # Balanced caps: big enough to verify typical finance records (bills,
    # invoices, entity files are ~1.5-2KB), small enough that a validator
    # call stays under ~30s prefill on a 27B quantized model so we stay
    # clear of the upstream nginx 504 cutoff.
    raw_files_section = ""
    PER_FILE_CAP = 2000
    TOTAL_CAP = 20000
    if vm and files_read:
        file_blocks = []
        total_size = 0
        for path in files_read:
            if total_size >= TOTAL_CAP:
                file_blocks.append(f"<file path=\"...(+{len(files_read) - len(file_blocks)} more omitted for context size)...\"/>")
                break
            # Normalize path: strip leading "/" for VM compatibility
            norm_path = path.lstrip("/")
            try:
                result = vm.read(ReadRequest(path=norm_path))
                content = MessageToDict(result).get("content", "") if result else ""
                if content:
                    if len(content) > PER_FILE_CAP:
                        content = content[:PER_FILE_CAP] + f"\n...[truncated {len(content) - PER_FILE_CAP} chars]"
                    block = f"<file path=\"{path}\">\n{content}\n</file>"
                    file_blocks.append(block)
                    total_size += len(block)
            except Exception as exc:
                print(f"{CLI_DIM}source-file skip {norm_path}: {exc}{CLI_CLR}", end=" ", flush=True)
                continue
        if file_blocks:
            raw_files_section = "\n\n<source-files>\n" + "\n".join(file_blocks) + "\n</source-files>"

    virtual_date_section = ""
    if virtual_date:
        virtual_date_section = (
            f"\n\n<virtual-current-date>{virtual_date}</virtual-current-date>\n"
            "IMPORTANT: The date above is the ONLY authoritative current date for "
            "this task. Do NOT use your own knowledge of today's date. All date "
            "calculations (birthdays, deadlines, 'N days ago') must be verified "
            "against this date, not any other."
        )

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
                f"{virtual_date_section}"
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
