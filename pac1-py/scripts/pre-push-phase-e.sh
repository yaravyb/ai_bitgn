#!/usr/bin/env bash
# Phase E pre-push anti-masking + edit-surface compliance hook.
#
# Install locally:
#   chmod +x pac1-py/scripts/pre-push-phase-e.sh
#   ln -s ../../pac1-py/scripts/pre-push-phase-e.sh .git/hooks/pre-push
# (or copy into .git/hooks/pre-push directly if symlinks are not
# supported in the filesystem.)
#
# Exits 1 on any violation; exits 0 if all five greps pass.
#
# Design: see .kiro/specs/ai-first-phase-e/design.md §Test strategy.
# Uses ripgrep (rg) when available, falls back to grep -r otherwise so
# the hook is portable across developer machines without rg installed.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

fail() { echo "pre-push-phase-e: VIOLATION — $1" >&2; exit 1; }

# Pick the grep implementation once. rg is preferred (faster, better
# globbing) but grep -rE is the portable fallback.
if command -v rg >/dev/null 2>&1; then
    _grep() {
        # $1 = pattern, rest = paths; honour the --glob exclude for outcomes.py.
        local pat="$1"; shift
        rg --quiet "$pat" "$@"
    }
    _grep_excl_outcomes() {
        local pat="$1"; shift
        rg --quiet --glob '!outcomes.py' "$pat" "$@"
    }
else
    _grep() {
        local pat="$1"; shift
        grep -rE --include='*.py' --include='*.md' "$pat" "$@" >/dev/null 2>&1
    }
    _grep_excl_outcomes() {
        local pat="$1"; shift
        grep -rE --include='*.py' --include='*.md' \
            --exclude='outcomes.py' "$pat" "$@" >/dev/null 2>&1
    }
fi

# R9 AC5 — no Phase A deletions resurrected.
# outcomes.py docstring names forbidden symbols intentionally to prevent
# reintroduction; exclude it from the grep path scope so the docstring
# itself does not trip the gate.
if _grep_excl_outcomes \
        'extract_decision_outcome|plan_compliance|set_compliance|get_compliance|_compliance' \
        pac1-py/agent/ pac1-py/tasks.py pac1-py/tools.py; then
    fail "Phase A deleted symbol reintroduced"
fi

# R9 AC6 — no alphabetical post-processor.
if _grep 'sorted alphabetically|alphabetical order|post-process: re-sorted' \
        pac1-py/agent/executor.py; then
    fail "alphabetical post-processor detected"
fi

# R9 AC7 — no inbox [SECURITY CHECK] injection.
if _grep '\[SECURITY CHECK\]|This file is from the inbox' \
        pac1-py/agent/dispatch.py; then
    fail "inbox [SECURITY CHECK] injection detected"
fi

# Phase E SCOPE BOUNDARIES item 7 — no per-task-ID hardcoding.
if _grep 'if task_id == "t[0-9]' pac1-py/; then
    fail "per-task-ID hardcoding detected"
fi

# R4 AC10 — structural check not described to LLM.
if _grep '30_knowledge|90_memory|99_system' \
        pac1-py/agent/prompts.py pac1-py/skills/; then
    fail "R4 internal-lane list leaked into LLM-visible text"
fi

echo "pre-push-phase-e: all R9 invariants clean."
exit 0
