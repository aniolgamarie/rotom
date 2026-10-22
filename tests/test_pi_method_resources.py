"""方法资源只绑定自身来源，不隐式安装项目语义工具。"""

from pathlib import Path
import shutil

import pytest

from agentcfg.schema import ConfigError
from test_pi_reboot_dependencies import fake_npm, recipe_repository, synthetic_workspace


REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("skill,files", [
  ("cpp-bounded-investigation", {"SKILL.md", "references/evidence-levels.md"}),
  ("long-command-handoff", {"SKILL.md"}),
])
def test_method_binds_only_selected_sources_without_installing_tools(fake_npm, tmp_path, skill, files):
  root, backend, calls = fake_npm
  source = Path("shared/skills") / skill
  shutil.copytree(REPOSITORY / source, root / source, dirs_exist_ok=True)
  workspace = synthetic_workspace(root, tmp_path, selection={"skills": [skill]})
  lock = backend.resolve_lock_for(workspace)
  piece = lock.metadata["profiles"]["pi-base"]
  assert piece["dependencies"] == {"@earendil-works/pi-coding-agent": "1.3.0", "catppuccin-pi-theme": "0.1.6",
    "pi-footer": "0.5.1"}
  resources = [item for item in piece["recipe_inputs"]["resources"] if item["kind"] == "skill-file"]
  assert {item["path"] for item in resources} == {f"skills/{skill}/{path}" for path in files}
  assert all(item["mode"] == 0o600 for item in resources)
  assert not any(any(tool in str(arg) for tool in ("ast-grep", "clangd", "serena", "tmux", "processes"))
    for argv in calls for arg in argv)
  pro = synthetic_workspace(root, tmp_path, profile="pi-pro")
  pro_identity = backend.runtime_identity(pro, lock)
  (root / source / "SKILL.md").write_text("Changed method source\n")
  with pytest.raises(ConfigError): backend.runtime_identity(workspace, lock)
  assert backend.runtime_identity(pro, lock) == pro_identity
