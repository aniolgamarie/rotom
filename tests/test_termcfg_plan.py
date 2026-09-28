"""预览只读、首次接管和秘密边界。"""

from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.preview import build_preview


def test_plan_has_stable_per_file_actions(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  first = build_preview(machine, ("zsh",))
  second = build_preview(machine, ("zsh",))
  assert first.plan_id == second.plan_id
  assert {item.action for item in first.targets} == {"create"}
  assert not (machine.private_state_root / "state.json").exists()


def test_custom_zshenv_needs_adoption_and_separate_confirmation(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  (isolated_environment.home / ".zshenv").write_text("export EDITOR=vi\n")
  plan = build_preview(read_machine("default"), ("zsh",))
  target = next(item for item in plan.targets if item.artifact.id == "zshenv")
  assert target.action == "adopt-required"
  assert target.custom_zshenv


def test_unknown_private_content_blocked_without_digest(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  (isolated_environment.home / ".zshenv").write_text("export API_KEY=synthetic-private\n")
  plan = build_preview(read_machine("default"), ("zsh",))
  target = next(item for item in plan.targets if item.artifact.id == "zshenv")
  assert target.action == "blocked"
  assert target.before.digest is None
