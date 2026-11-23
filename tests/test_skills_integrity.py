import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / "skills"
INSTALL_SCRIPT = REPO_ROOT / "install.sh"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
MD_LINK_RE = re.compile(r"\[[^\]]+\]\((\./[^)#]+)(?:#[^)]+)?\)")


class TestSkillsIntegrity(unittest.TestCase):
    def test_all_skills_are_self_contained_with_valid_frontmatter_and_links(self) -> None:
        skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
        self.assertGreaterEqual(len(skill_dirs), 2)

        for skill_dir in skill_dirs:
            skill_md = skill_dir / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"Missing SKILL.md in {skill_dir}")
            content = skill_md.read_text(encoding="utf-8")

            match = FRONTMATTER_RE.match(content)
            self.assertIsNotNone(match, f"Missing YAML frontmatter in {skill_md}")
            fm = match.group(1)

            name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", fm, re.MULTILINE)
            self.assertIsNotNone(name_match, f"Invalid or missing skill name in {skill_md}")
            self.assertEqual(name_match.group(1), skill_dir.name)
            self.assertIn("description:", fm, f"Missing description in {skill_md}")

            # Verify every relative markdown link stays inside skill_dir and resolves cleanly
            for rel_target in MD_LINK_RE.findall(content):
                resolved = (skill_dir / rel_target).resolve()
                self.assertTrue(resolved.exists(), f"Broken link {rel_target} in {skill_md}")
                self.assertTrue(
                    resolved.is_relative_to(skill_dir.resolve()),
                    f"Skill {skill_dir.name} links outside its self-contained directory: {rel_target}",
                )

            # Verify every Python CLI in scripts/ executes --help cleanly
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.is_dir():
                for py_script in sorted(scripts_dir.glob("*.py")):
                    res = subprocess.run(
                        [sys.executable, str(py_script), "--help"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(res.returncode, 0, f"{py_script} --help failed: {res.stderr}")

    def test_install_and_uninstall_in_sandbox_home(self) -> None:
        with tempfile.TemporaryDirectory() as fake_home:
            env = os.environ.copy()
            env["HOME"] = fake_home

            for mode in ("--symlink", "--copy"):
                res_install = subprocess.run(
                    ["bash", str(INSTALL_SCRIPT), "--target", "antigravity", mode],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(res_install.returncode, 0, res_install.stderr)

                dest_root = Path(fake_home) / ".gemini" / "config" / "skills"
                for skill_name in ("vibe-observability", "vibe-observability-loop"):
                    installed = dest_root / skill_name
                    self.assertTrue(installed.exists(), f"{installed} not installed ({mode})")
                    self.assertTrue((installed / "SKILL.md").is_file())
                    if mode == "--symlink":
                        self.assertTrue(installed.is_symlink())
                # Verify self-contained examples copied along with skill
                self.assertTrue((dest_root / "vibe-observability" / "examples").is_dir())

                res_uninstall = subprocess.run(
                    ["bash", str(INSTALL_SCRIPT), "--target", "antigravity", "--uninstall"],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(res_uninstall.returncode, 0, res_uninstall.stderr)
                for skill_name in ("vibe-observability", "vibe-observability-loop"):
                    self.assertFalse((dest_root / skill_name).exists())


if __name__ == "__main__":
    unittest.main()
