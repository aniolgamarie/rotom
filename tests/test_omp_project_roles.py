"""原生套件切换仅开放当前项目模型角色，保持其他发现来源默认拒绝。"""

import hashlib
import stat

import pytest

from agentcfg.omp_discovery import SourcePolicy, inspect_project_sources
from agentcfg.omp_project_roles import project_role_policy
from agentcfg.storage import Conflict


@pytest.fixture(autouse=True)
def isolate_source_roots(monkeypatch, tmp_path):
  monkeypatch.setattr("agentcfg.omp_discovery.source_present", lambda path:
    path.is_relative_to(tmp_path) and (path.exists() or path.is_symlink()))


def data(cursor=True):
  roles = {role: "model:" + level for role, level in {
    "main": "high", "smol": "low", "slow": "max", "plan": "high", "task": "high",
    "advisor": "max", "vision": "high"}.items()}
  if cursor:
    roles["smol"] = "cursor/composer-2.5:low"
  roles["tiny"] = "local/lfm2.5-230m"
  return {"profile": {"roles": {"main": "model"}, "models": ["model"],
    "providers": ["official"] + (["cursor"] if cursor else []),
    "agent_options": {"model_presets": {"example": {"roles": roles}},
      "role_thinking": {"main": "high"}, "runtime": {"modelRoleStorage": "project"}}},
    "providers": {"official": {"protocol": "anthropic-messages"},
      **({"cursor": {"protocol": "oauth-dynamic", "auth_kind": "oauth"}} if cursor else {})},
    "models": {"model": {"provider": "official", "remote_id": "model",
      "reasoning": True, "reasoning_efforts": ["low", "high", "max"], "input": ["text", "image"]}}}


def inspect(project, value=None, resources=False):
  policy = SourcePolicy.from_options({"project_resources": resources,
    "project_roots": [str(project)] if resources else []})
  return inspect_project_sources(project, policy, project_model_roles=project_role_policy(value or data()))


def config(project, content):
  path = project / ".omp/config.yml"
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(content)
  return path


def test_valid_role_file_is_read_only_and_report_has_only_path_and_digest(tmp_path):
  path = config(tmp_path / "project", "modelRoles:\n  default: official/model:high\n  smol: cursor/composer-2.5:low\n  tiny: local/lfm2.5-230m\n")
  before = path.read_bytes(), path.stat().st_mtime_ns
  report = inspect(path.parent.parent)
  assert report == ({"category": "model-roles", "path": str(path),
    "sha256": hashlib.sha256(before[0]).hexdigest()},)
  assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("content", ["", "{}", "modelRoles: {}\n"])
def test_native_empty_role_file_can_restore_global_defaults(tmp_path, content):
  path = config(tmp_path / "project", content)
  assert inspect(path.parent.parent)[0]["category"] == "model-roles"


@pytest.mark.parametrize("content", [
  "modelRoles: []\n", "modelRoles:\n  unknown: official/model\n",
  "modelRoles:\n  default: missing/model\n", "modelRoles:\n  default: official/model:turbo\n",
  "modelRoles:\n  default: local/lfm2.5-230m\n", "modelRoles:\n  tiny: official/model\n",
  "modelRoles:\n  default: cursor/model:high:low\n", "modelRoles:\n  default: cursor/$TOKEN\n",
  "modelRoles:\n  default: cursor/gpt-5.6-sol:high\n", "modelRoles:\n  default: cursor/*:high\n",
  "modelRoles:\n  default: official/model\n  default: cursor/kimi-k3\n",
  "modelRoles: {}\nmodelRoles: {}\n", "modelRoles: &roles {}\n",
  "modelRoles: {}\ncopy: *roles\n", "modelRoles:\n  default: SECRET_CANARY\n",
  "auth:\n  broker: SECRET_CANARY\n", "tools:\n  approvalMode: yolo\n",
  "modelRoles: {}\nextensions: []\n", "modelRoles: {}\nproviders: {}\n",
  "modelRoles: {}\npermissionControl: {}\n", "modelRoles: {}\ndefaultThinkingLevel: low\n",
])
def test_invalid_project_settings_are_quarantined_without_value_disclosure(tmp_path, content):
  path = config(tmp_path / "project", content)
  report = inspect(path.parent.parent)
  backup = path.with_name("config.yml.agentcfg-backup")
  assert not path.exists()
  assert backup.read_bytes() == content.encode()
  assert stat.S_IMODE(backup.stat().st_mode) == 0o600
  assert report == ({"category": "model-roles-quarantine", "path": str(backup),
    "sha256": hashlib.sha256(content.encode()).hexdigest()},)
  assert "SECRET_CANARY" not in str(report)


@pytest.mark.parametrize("change", ["no-presets", "global-storage", "no-cursor"])
def test_feature_and_cursor_provider_must_be_explicitly_enabled(tmp_path, change):
  path = config(tmp_path / "project", "modelRoles:\n  default: cursor/kimi-k3:high\n")
  value = data(cursor=change != "no-cursor")
  if change == "no-presets":
    value["profile"]["agent_options"].pop("model_presets")
  if change == "global-storage":
    value["profile"]["agent_options"]["runtime"]["modelRoleStorage"] = "global"
  if change == "no-cursor":
    assert inspect(path.parent.parent, value)[0]["category"] == "model-roles-quarantine"
    assert not path.exists()
  else:
    with pytest.raises(Conflict):
      inspect(path.parent.parent, value)


@pytest.mark.parametrize("relative", [".omp/settings.json", ".omp/config.yaml", ".omp/extensions/plugin.ts",
  ".omp/skills/x/SKILL.md", ".omp/mcp.json", ".env", ".cursor/rules/private.mdc"])
def test_role_file_does_not_enable_other_project_sources(tmp_path, relative):
  project = tmp_path / "project"
  config(project, "modelRoles: {}\n")
  path = project / relative
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text("SECRET_CANARY")
  with pytest.raises(Conflict) as error:
    inspect(project)
  assert "SECRET_CANARY" not in str(error.value)


def test_safe_ancestor_role_file_is_validated_without_blocking_subdirectories(tmp_path):
  project = tmp_path / "project"
  config(project, "modelRoles: {}\n")
  child = project / "child"
  child.mkdir()
  report = inspect(child)
  assert report[0]["path"] == str(project / ".omp/config.yml")
  assert report[0]["category"] == "model-roles"
  config(project, "modelRoles: {}\nextensions: []\n")
  assert inspect(child)[0]["category"] == "model-roles-quarantine"
  assert not (project / ".omp/config.yml").exists()


@pytest.mark.parametrize("kind", ["file-link", "directory-link", "hardlink", "fifo", "oversize"])
def test_non_regular_linked_and_oversized_role_files_are_rejected(tmp_path, kind):
  import os
  project = tmp_path / "project"
  path = config(project, "modelRoles: {}\n")
  original = tmp_path / "original"
  original.write_bytes(path.read_bytes())
  if kind == "directory-link":
    path.unlink()
    path.parent.rmdir()
    path.parent.symlink_to(tmp_path, target_is_directory=True)
  elif kind == "oversize":
    path.write_text("#" + "x" * (64 * 1024))
  else:
    path.unlink()
    if kind == "file-link":
      path.symlink_to(original)
    elif kind == "hardlink":
      os.link(original, path)
    else:
      os.mkfifo(path)
  with pytest.raises(Conflict):
    inspect(project)


def test_declared_skills_and_role_config_coexist_without_enabling_extensions(tmp_path):
  project = tmp_path / "project"
  config(project, "modelRoles:\n  default: official/model:high\n")
  skill = project / ".omp/skills/review"
  skill.mkdir(parents=True)
  (skill / "SKILL.md").write_text("# review\n")
  assert {item["category"] for item in inspect(project, resources=True)} == {"model-roles", "skill"}


def test_pool_only_paid_model_cannot_become_a_project_default(tmp_path):
  value = data()
  value["profile"]["models"].append("pro")
  value["models"]["pro"] = {**value["models"]["model"], "remote_id": "deepseek-v4-pro"}
  path = config(tmp_path / "project", "modelRoles:\n  default: official/deepseek-v4-pro:high\n")
  assert inspect(path.parent.parent, value)[0]["category"] == "model-roles-quarantine"
  assert not path.exists()
  # 私人配置主动将该模型声明为初始角色后，项目才能持久化同一赋值。
  value["profile"]["roles"]["main"] = "pro"
  config(tmp_path / "project", "modelRoles:\n  default: official/deepseek-v4-pro:high\n")
  assert inspect(path.parent.parent, value)[0]["category"] == "model-roles"


def test_private_cursor_bootstrap_is_explicit_and_role_specific(tmp_path):
  value = data()
  value["profile"]["agent_options"]["native_model_roles"] = {"main": "cursor/custom-model:high"}
  path = config(tmp_path / "project", "modelRoles:\n  default: cursor/custom-model:high\n")
  assert inspect(path.parent.parent, value)[0]["category"] == "model-roles"
  path.write_text("modelRoles:\n  smol: cursor/custom-model:high\n")
  assert inspect(path.parent.parent, value)[0]["category"] == "model-roles-quarantine"


def test_known_model_with_an_undeclared_role_effort_is_quarantined(tmp_path):
  path = config(tmp_path / "project", "modelRoles:\n  default: official/model:max\n")
  assert inspect(path.parent.parent)[0]["category"] == "model-roles-quarantine"
  assert not path.exists()


def test_repeated_conflicts_keep_only_the_latest_backup(tmp_path):
  project = tmp_path / "project"
  path = config(project, "modelRoles:\n  default: missing/model\n")
  inspect(project)
  backup = path.with_name("config.yml.agentcfg-backup")
  assert backup.read_text() == "modelRoles:\n  default: missing/model\n"
  config(project, "modelRoles:\n  default: also/missing\n")
  assert inspect(project)[0]["category"] == "model-roles-quarantine"
  assert backup.read_text() == "modelRoles:\n  default: also/missing\n"
  assert sorted(child.name for child in (project / ".omp").iterdir()) == ["config.yml.agentcfg-backup"]
