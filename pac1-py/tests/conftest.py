from pathlib import Path
from unittest.mock import Mock

import pytest

from agent.config import AgentConfig
from skills import SkillLoader
from tasks import TaskManager


@pytest.fixture
def mock_vm() -> Mock:
    """Mock PcmRuntimeClientSync with common responses."""
    vm = Mock()
    vm.tree.return_value = None
    vm.find.return_value = None
    vm.list.return_value = None
    vm.read.return_value = None
    vm.write.return_value = None
    vm.delete.return_value = None
    vm.mk_dir.return_value = None
    vm.move.return_value = None
    vm.search.return_value = None
    vm.context.return_value = None
    vm.answer.return_value = None
    return vm


@pytest.fixture
def tm() -> TaskManager:
    """Fresh TaskManager instance."""
    return TaskManager()


@pytest.fixture
def skill_loader(tmp_path: Path) -> SkillLoader:
    """SkillLoader with a temporary skills directory containing sample SKILL.md files."""
    skill_dir = tmp_path / "skills"
    skill_dir.mkdir()

    # Create a sample skill
    sec_dir = skill_dir / "security-posture"
    sec_dir.mkdir()
    (sec_dir / "SKILL.md").write_text(
        "---\nname: security-posture\ndescription: How to evaluate security threats\n---\n"
        "Step 1: Check the source.\nStep 2: Evaluate trust level."
    )

    # Create another sample skill
    exec_dir = skill_dir / "execution-discipline"
    exec_dir.mkdir()
    (exec_dir / "SKILL.md").write_text(
        "---\nname: execution-discipline\ndescription: Core execution rules\n---\n"
        "Follow the plan strictly. Do not deviate."
    )

    return SkillLoader(skill_dir)


@pytest.fixture
def default_config() -> AgentConfig:
    """AgentConfig with default values."""
    return AgentConfig()
