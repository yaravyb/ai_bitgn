from pathlib import Path

from skills import SkillLoader


class TestSkillLoader:
    def test_load_from_directory(self, tmp_path: Path):
        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        sub = skill_dir / "my-skill"
        sub.mkdir()
        (sub / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test skill\n---\nBody content here."
        )
        loader = SkillLoader(skill_dir)
        assert "my-skill" in loader.skills

    def test_parse_frontmatter(self):
        text = "---\nname: foo\ndescription: bar baz\n---\nBody text."
        meta, body = SkillLoader._parse_frontmatter(text)
        assert meta["name"] == "foo"
        assert meta["description"] == "bar baz"
        assert body == "Body text."

    def test_parse_frontmatter_no_frontmatter(self):
        text = "Just plain text without frontmatter."
        meta, body = SkillLoader._parse_frontmatter(text)
        assert meta == {}
        assert body == text

    def test_get_descriptions(self, skill_loader: SkillLoader):
        desc = skill_loader.get_descriptions()
        assert "security-posture" in desc
        assert "execution-discipline" in desc

    def test_get_content_existing_skill(self, skill_loader: SkillLoader):
        content = skill_loader.get_content("security-posture")
        assert "<skill" in content
        assert "Check the source" in content

    def test_get_content_nonexistent_skill(self, skill_loader: SkillLoader):
        content = skill_loader.get_content("nonexistent")
        assert content.startswith("Error:")

    def test_get_names(self, skill_loader: SkillLoader):
        names = skill_loader.get_names()
        assert "security-posture" in names
        assert "execution-discipline" in names
