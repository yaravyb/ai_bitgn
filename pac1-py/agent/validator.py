import json
import time

from agent.config import AgentConfig
from agent.llm import call_llm
from agent.prompts import CLI_CLR, CLI_DIM, CLI_GREEN, CLI_YELLOW, build_validator_system
from tasks import TaskManager
from tools import VALIDATION_TOOL


def extract_decision_outcome(execution_context: str, tm: TaskManager | None = None) -> str | None:
    """Extract outcome from structured data and VERIFY notes.

    Sources of truth (no keyword heuristics):
    1. Structured: plan_compliance tool → tm.get_compliance()
    2. Trust level: trust=admin/valid/blacklist from VERIFY notes
    3. Explicit DECISION= notes from the model
    4. CONFLICT notes

    Returns:
    - A definitive outcome when the decision-lock has high confidence
    - "NEEDS_VALIDATOR" when trust=valid + PROCEED (uncertain, needs LLM review)
    - None when no signal at all
    """
    decisions = []
    trust_level = None  # admin, valid, blacklist, unmarked, or None

    for line in execution_context.split("\n"):
        line_lower = line.lower()
        # Extract trust level from VERIFY notes
        if "trust=" in line_lower:
            if "trust=admin" in line_lower:
                trust_level = "admin"
            elif "trust=valid" in line_lower:
                trust_level = "valid"
            elif "trust=blacklist" in line_lower:
                trust_level = "blacklist"
            elif "trust=unmarked" in line_lower or "trust=unknown" in line_lower:
                trust_level = "unmarked"
        # Explicit DECISION notes
        if "DECISION=" in line:
            if "DENY_SECURITY" in line:
                decisions.append("OUTCOME_DENIED_SECURITY")
            elif "DENY_CLARIFY" in line:
                decisions.append("OUTCOME_NONE_CLARIFICATION")
            elif "PROCEED" in line:
                decisions.append("OUTCOME_OK")
        # CONFLICT detection
        if "CONFLICT" in line.upper() and ("contradict" in line_lower or "conflicting" in line_lower):
            decisions.append("OUTCOME_NONE_CLARIFICATION")

    # ── Structured compliance (from plan_compliance tool) ──
    if tm:
        compliance = tm.get_compliance()
        if compliance and compliance["cross_account"]:
            decisions.append("OUTCOME_NONE_CLARIFICATION")

    if not decisions and trust_level is None:
        return None

    # ── Channel trust enforcement ──

    if trust_level == "admin":
        # Admin channels are fully trusted — clear any DENY
        decisions = [d for d in decisions if d != "OUTCOME_DENIED_SECURITY"]
        if not decisions:
            decisions.append("OUTCOME_OK")
    elif trust_level in ("valid", "blacklist", "unmarked"):
        # Non-admin: escalate CLARIFICATION → DENY
        if "OUTCOME_NONE_CLARIFICATION" in decisions:
            decisions.append("OUTCOME_DENIED_SECURITY")
        # Non-admin + model said PROCEED → uncertain, needs LLM validator
        if "OUTCOME_DENIED_SECURITY" not in decisions and "OUTCOME_OK" in decisions:
            return "NEEDS_VALIDATOR"

    # ── Priority resolution ──

    if "OUTCOME_DENIED_SECURITY" in decisions:
        return "OUTCOME_DENIED_SECURITY"
    if "OUTCOME_NONE_CLARIFICATION" in decisions:
        return "OUTCOME_NONE_CLARIFICATION"
    if decisions:
        return "OUTCOME_OK"
    return None


def validate_completion(
    config: AgentConfig,
    model: str,
    task_text: str,
    proposed_message: str,
    proposed_outcome: str,
    agents_md: str,
    execution_context: str,
    metadata: dict | None = None,
    tm: TaskManager | None = None,
) -> dict | None:
    """Validate proposed answer before submitting.

    Returns None if approved, or a dict with corrected outcome/message.
    """
    # Code-level lock: VERIFY DECISION notes override the model's outcome
    decision_outcome = extract_decision_outcome(execution_context, tm)
    if decision_outcome and decision_outcome != "NEEDS_VALIDATOR":
        if decision_outcome != proposed_outcome:
            print(f"  {CLI_YELLOW}decision-lock: {proposed_outcome} → {decision_outcome}{CLI_CLR}")
            return {"outcome": decision_outcome, "message": proposed_message}
        else:
            print(f"  {CLI_GREEN}decision-lock: confirmed {decision_outcome}{CLI_CLR}")
            return None  # approved, skip validator
    elif decision_outcome == "NEEDS_VALIDATOR":
        print(f"  {CLI_YELLOW}decision-lock: uncertain (valid channel + PROCEED) → validator{CLI_CLR}")

    print(f"  {CLI_DIM}validating...{CLI_CLR}", end=" ", flush=True)

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
