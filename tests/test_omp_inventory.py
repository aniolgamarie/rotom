from pathlib import Path
import json
import tomllib

import pytest

from agentcfg.omp import OmpAdapter
from agentcfg import cli, commands
from agentcfg.omp_inventory import build_inventory, write_inventory
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_omp_adapter import REPO, full_data
from test_omp_runtime_foundation import runtime_workspace


@pytest.fixture
def old_source(tmp_path):
  source = tmp_path / "old-agent"
  source.mkdir(mode=0o700)
  (source / "config.yml").write_text("theme:\n  dark: rotom-dark\nmodelRoles:\n  default: gateway/large-v1\nauth:\n  token: SECRET_INVENTORY_947\n")
  (source / "models.yml").write_text("providers:\n  old:\n    apiKey: SECRET_INVENTORY_947\n    api: openai-completions\n")
  (source / "keybindings.yml").write_text("app.model.cycleForward: Ctrl+P\nunknown.action: SECRET_INVENTORY_947\n")
  skill = source / "skills/sample"
  (skill / "scripts").mkdir(parents=True)
  (skill / "SKILL.md").write_text("---\nname: sample\ndescription: Safe sample\n---\nSee scripts/check.sh\n")
  (skill / "scripts/check.sh").write_text("#!/bin/sh\nexit 99\n")
  (skill / "scripts/check.sh").chmod(0o700)
  (source / "prompts").mkdir()
  (source / "prompts/leak.md").write_text("Do not copy SECRET_INVENTORY_947")
  (source / "auth.db").write_bytes(b"DO_NOT_READ_AUTH_DATABASE")
  (source / "sessions").mkdir()
  (source / "sessions/old.json").write_bytes(b"DO_NOT_READ_SESSION")
  (source / "extensions").mkdir()
  (source / "extensions/private.ts").write_bytes(b"DO_NOT_READ_UNAPPROVED_EXTENSION")
  return source


def test_inventory_dispositions_secret_scan_and_complete_skill_without_execution(old_source, sentinel_factory, monkeypatch):
  sentinel = sentinel_factory(old_source)
  original = Tree.read
  def restricted(tree, name):
    assert not str(name).startswith(("auth.db", "sessions/", "extensions/"))
    return original(tree, name)
  monkeypatch.setattr(Tree, "read", restricted)
  report, proposal, resources = build_inventory(old_source, adapter=OmpAdapter(REPO), data=full_data())
  assert report["source_root"] == str(old_source)
  assert report["items"] and all(item["disposition"] in {"纳入", "原生保留", "替代", "排除"} and item["reason"] for item in report["items"])
  assert any(item["review_required"] for item in report["items"])
  assert {item["path"] for item in resources} == {"skills/sample/SKILL.md", "skills/sample/scripts/check.sh"}
  assert next(item for item in resources if item["path"].endswith("check.sh"))["executable"] is True
  assert proposal["overrides"]["profiles"]["omp-validation"]["roles"] == {"main": "large"}
  assert "SECRET_INVENTORY_947" not in repr((report, proposal, resources))
  assert "DO_NOT_READ" not in repr((report, proposal, resources))
  sentinel.assert_unchanged()


def test_inventory_source_link_and_secret_inside_skill_are_not_copied(old_source):
  (old_source / "skills/sample/note.txt").write_text("SECRET_INVENTORY_947")
  (old_source / "themes").mkdir()
  (old_source / "themes/outside.json").symlink_to(old_source / "auth.db")
  report, _, resources = build_inventory(old_source, adapter=OmpAdapter(REPO), data=full_data())
  assert not resources
  assert any(item["reason"] == "sensitive-resource-not-copied" for item in report["items"])
  assert any(item["reason"] == "unsafe-resource-not-copied" for item in report["items"])


def test_inventory_requires_explicit_absolute_source_and_rejects_symlink(old_source):
  with pytest.raises(ConfigError):
    build_inventory(Path("relative"), adapter=OmpAdapter(REPO), data=full_data())
  link = old_source.with_name("source-link")
  link.symlink_to(old_source, target_is_directory=True)
  with pytest.raises(Conflict):
    build_inventory(link, adapter=OmpAdapter(REPO), data=full_data())


def test_inventory_writes_only_three_private_proposal_outputs(old_source, tmp_path, sentinel_factory):
  workspace, _ = runtime_workspace(tmp_path / "new")
  # 旧主题未在bootstrap选中，提案仍须合法且不得偷建资源ID。
  sentinel = sentinel_factory(old_source)
  instance = sentinel_factory(workspace.instance)
  result = write_inventory(workspace, old_source)
  destination = Path(result["proposal"])
  assert destination.is_relative_to(workspace.cache)
  assert {path.name for path in destination.iterdir()} == {"disposition.json", "local-overrides.toml", "resources"}
  report = json.loads((destination / "disposition.json").read_bytes())
  proposal = tomllib.loads((destination / "local-overrides.toml").read_text())
  assert report["ready_to_deploy"] is False
  assert proposal["schema_version"] == 1
  for path in destination.rglob("*"):
    assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)
    if path.is_file():
      assert b"SECRET_INVENTORY_947" not in path.read_bytes()
  sentinel.assert_unchanged()
  instance.assert_unchanged()


def test_inventory_cli_only_writes_private_proposal(old_source, tmp_path, monkeypatch, capsys):
  workspace, _ = runtime_workspace(tmp_path / "new")
  workspace.agent = "omp"
  monkeypatch.setattr(cli, "resolve_selection", lambda args: None)
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  assert cli.main(["--profile", "omp-test", "inventory", "omp", "--source", str(old_source)]) == 0
  result = json.loads(capsys.readouterr().out)
  assert result["command"] == "inventory" and result["ready_to_deploy"] is False
  assert Path(result["proposal"]).is_relative_to(workspace.cache)


@pytest.mark.parametrize("name", ["agent.db-wal", "agent.db-shm", "usage.sqlite", "usage.sqlite-wal"])
def test_runtime_sidecars_inside_resource_package_are_not_read_or_copied(old_source, monkeypatch, name):
  path = "skills/sample/" + name
  (old_source / path).write_bytes(b"runtime bytes must stay at source")
  original = Tree.read
  def reject(tree, selected):
    if selected == path:
      pytest.fail("runtime resource read")
    return original(tree, selected)
  monkeypatch.setattr(Tree, "read", reject)
  report, _, resources = build_inventory(old_source, adapter=OmpAdapter(REPO), data=full_data())
  assert not resources
  assert any(item["reason"] == "unsafe-resource-not-copied" for item in report["items"])
