import pytest

from app.skills.loader import (
    parse_frontmatter,
    split_frontmatter,
    scan_skills,
    load_skill,
    SkillParseError,
)


def _make_skill(root, skill_id, body="# Title\nDo the thing.\n", frontmatter=None):
    d = root / skill_id
    d.mkdir(parents=True)
    fm = frontmatter or {"name": skill_id, "description": f"{skill_id} does X"}
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {v}")
    lines.append("---")
    (d / "SKILL.md").write_text("\n".join(lines) + "\n\n" + body)
    return d


class TestParseFrontmatter:
    def test_parses_simple_fields(self):
        text = (
            "---\n"
            "name: test-driven-development\n"
            "description: RED-GREEN-REFACTOR cycle\n"
            "---\n\n"
            "# Body\n"
        )
        fm = parse_frontmatter(text)
        assert fm["name"] == "test-driven-development"
        assert fm["description"] == "RED-GREEN-REFACTOR cycle"

    def test_strips_quotes(self):
        fm = parse_frontmatter('---\nname: "quoted"\ndescription: \'single\'\n---\n')
        assert fm["name"] == "quoted"
        assert fm["description"] == "single"

    def test_no_frontmatter_returns_empty(self):
        assert parse_frontmatter("# no frontmatter") == {}

    def test_split_frontmatter(self):
        fm, body = split_frontmatter(
            "---\nname: x\ndescription: y\n---\n\n# Real Body\n\ntext"
        )
        assert fm["name"] == "x"
        assert body == "# Real Body\n\ntext"

    def test_exported_parse_error_symbol(self):
        assert SkillParseError is SkillParseError


class TestScanAndLoad:
    def test_scan_finds_all_skills(self, tmp_path):
        _make_skill(tmp_path, "alpha")
        _make_skill(tmp_path, "beta")
        _make_skill(tmp_path, "gamma", frontmatter={"name": "renamed", "description": "d"})
        (tmp_path / "not-a-skill").mkdir()
        (tmp_path / "no-md-dir").mkdir()

        skills = scan_skills(str(tmp_path))
        ids = {s.name for s in skills}
        assert ids == {"alpha", "beta", "renamed"}

    def test_load_skill_collects_files(self, tmp_path):
        d = _make_skill(tmp_path, "alpha")
        (d / "references").mkdir()
        (d / "references" / "guide.md").write_text("ref")
        (d / "scripts").mkdir()
        (d / "scripts" / "run.sh").write_text("x")

        meta = load_skill(str(tmp_path), "alpha")
        assert meta is not None
        assert meta.name == "alpha"
        assert "Do the thing." in meta.body
        assert "references/guide.md" in meta.files
        assert "scripts/run.sh" in meta.files
        assert "SKILL.md" not in meta.files

    def test_load_missing_returns_none(self, tmp_path):
        assert load_skill(str(tmp_path), "missing") is None

    def test_scan_empty_root(self, tmp_path):
        assert scan_skills(str(tmp_path)) == []
        assert scan_skills("/nonexistent-path-xyz") == []