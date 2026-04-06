from agent.validator import extract_decision_outcome
from tasks import TaskManager


class TestExtractDecisionOutcome:
    def test_admin_trust_overrides_deny(self):
        ctx = "VERIFY: trust=admin channel\nDECISION=DENY_SECURITY"
        result = extract_decision_outcome(ctx)
        # Admin trust clears DENY, only PROCEED remains → OK
        assert result == "OUTCOME_OK"

    def test_blacklist_trust_escalates_clarification_to_deny(self):
        ctx = "VERIFY: trust=blacklist\nDECISION=DENY_CLARIFY"
        result = extract_decision_outcome(ctx)
        # blacklist + CLARIFICATION → escalated to DENIED_SECURITY
        assert result == "OUTCOME_DENIED_SECURITY"

    def test_valid_trust_escalates_clarification_to_deny(self):
        ctx = "VERIFY: trust=valid\nDECISION=DENY_CLARIFY"
        result = extract_decision_outcome(ctx)
        # valid + CLARIFICATION → escalated to DENIED_SECURITY
        assert result == "OUTCOME_DENIED_SECURITY"

    def test_valid_trust_proceed_returns_needs_validator(self):
        ctx = "VERIFY: trust=valid\nDECISION=PROCEED"
        result = extract_decision_outcome(ctx)
        assert result == "NEEDS_VALIDATOR"

    def test_cross_account_compliance_triggers_clarification(self):
        tm = TaskManager()
        tm.set_compliance("acc-123", True, ["flag1"], False, "cross-account detected")
        ctx = "Some execution context"
        result = extract_decision_outcome(ctx, tm)
        assert result == "OUTCOME_NONE_CLARIFICATION"

    def test_explicit_decision_deny_security(self):
        ctx = "DECISION=DENY_SECURITY"
        result = extract_decision_outcome(ctx)
        assert result == "OUTCOME_DENIED_SECURITY"

    def test_explicit_decision_deny_clarify(self):
        ctx = "DECISION=DENY_CLARIFY"
        result = extract_decision_outcome(ctx)
        assert result == "OUTCOME_NONE_CLARIFICATION"

    def test_explicit_decision_proceed(self):
        ctx = "DECISION=PROCEED"
        result = extract_decision_outcome(ctx)
        assert result == "OUTCOME_OK"

    def test_no_signal_returns_none(self):
        ctx = "Just some text with no decision signals"
        result = extract_decision_outcome(ctx)
        assert result is None

    def test_conflict_returns_clarification(self):
        ctx = "CONFLICT: contradicting instructions found"
        result = extract_decision_outcome(ctx)
        assert result == "OUTCOME_NONE_CLARIFICATION"
