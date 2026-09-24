"""只读盘点：存在、选择与运行证据不是一回事。"""

import json
from pathlib import Path

import pytest

from agentcfg.pi_inventory import build_inventory
from agentcfg.storage import Tree


ROOT = Path(__file__).resolve().parents[1]


def native_home(tmp_path):
  home = tmp_path / "pi-home"
  home.mkdir()
  (home / "settings.json").write_text(json.dumps({
    "packages": ["npm:@tintinweb/pi-subagents@0.19.0", "npm:pi-subagents@0.63.0"],
    "arbitrarySecret": "synthetic-private-value",
  }))
  (home / "auth.json").write_text("synthetic-auth-never-read")
  (home / "prompts").mkdir()
  (home / "prompts/implement.md").write_text("current-only prompt")
  return home


def test_inventory_distinguishes_declared_selected_present_and_unverified(tmp_path, monkeypatch, sentinel_factory):
  home = native_home(tmp_path)
  sentinel = sentinel_factory(home)
  read = Tree.read

  def guarded(tree, name):
    assert name not in {"auth.json", "trust.json"}, "authentication must not be read"
    return read(tree, name)

  monkeypatch.setattr(Tree, "read", guarded)
  report = build_inventory(home, repository=ROOT)
  indexed = {item["id"]: item for item in report["items"]}
  assert indexed["pi-subagents"]["selected"] is True
  assert indexed["pi-subagents"]["load_evidence"] == "not-run"
  assert indexed["legacy-subagents"]["disposition"] == "exclude"
  assert indexed["prompt-implement"]["disk_state"] == "present"
  assert indexed["prompt-implement"]["target_path"] == "agents/pi/prompts/implement.md"
  assert all(item["execution_evidence"] == "not-run" for item in report["items"])
  assert "synthetic-private" not in json.dumps(report)
  sentinel.assert_unchanged()


def test_unknown_and_credential_bearing_package_specs_are_never_copied(tmp_path):
  home = native_home(tmp_path)
  (home / "settings.json").write_text(json.dumps({"packages": ["https://user:synthetic-password@example.invalid/pkg"]}))
  report = build_inventory(home, repository=ROOT)
  assert report["blockers"]
  assert "synthetic-password" not in json.dumps(report)
  assert "user:" not in json.dumps(report)


def test_settings_symlink_cannot_read_an_unrelated_file(tmp_path):
  home = native_home(tmp_path)
  secret = tmp_path / "secret"
  secret.write_text("synthetic-secret")
  (home / "settings.json").unlink()
  (home / "settings.json").symlink_to(secret)
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict):
    build_inventory(home, repository=ROOT)


def test_unknown_current_resources_are_preserved_as_explicit_exclusions(tmp_path):
  home = native_home(tmp_path)
  (home / "prompts/user-custom.md").write_text("do not delete")
  report = build_inventory(home, repository=ROOT)
  extras = [item for item in report["items"] if item["id"].startswith("current-extra-")]
  assert any(item["disposition"] == "exclude" and item["reason"] == "unmanaged-preserved" for item in extras)


def test_model_proposal_excludes_literal_key_and_requires_manual_binding(tmp_path):
  home = native_home(tmp_path)
  (home / "settings.json").write_text('{"defaultProvider":"fictional","defaultModel":"fake-model"}')
  (home / "models.json").write_text(json.dumps({"providers": {"fictional": {
    "api": "openai-completions", "baseUrl": "https://example.invalid/v1", "apiKey": "synthetic-password",
    "models": [{"id": "fake-model", "input": ["text"]}],
  }}}))
  report = build_inventory(home, repository=ROOT)
  assert "synthetic-password" not in json.dumps(report)
  assert len(report["proposed_overrides"]["providers"]) == 1
  assert len(report["proposed_overrides"]["models"]) == 1
  assert any(row["code"] == "credential-binding-required" for row in report["blockers"])


def test_cli_migration_preview_never_starts_host_or_reads_auth(tmp_path, capsys, sentinel_factory):
  from agentcfg.cli import main
  home = native_home(tmp_path)
  sentinel = sentinel_factory(home)
  local = tmp_path / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="fixture"\n')
  assert main(["--local", str(local), "--profile", "pi-default", "plan", "--from-pi-home", str(home)]) == 0
  result = json.loads(capsys.readouterr().out)
  assert result["mode"] == "migration-preview"
  assert result["ready_to_deploy"] is False
  proposal = Path(result["proposal"])
  assert proposal.stat().st_mode & 0o777 == 0o600
  assert "synthetic" not in proposal.read_text()
  sentinel.assert_unchanged()
  assert main(["--local", str(local), "plan", "--from-starter", str(tmp_path)]) == 2


def test_known_theme_is_proposed_and_undetermined_selection_stays_unknown(tmp_path):
  home = native_home(tmp_path)
  (home / "settings.json").write_text('{"theme":"Everforest Dark"}')
  report = build_inventory(home, repository=ROOT)
  assert report["proposed_overrides"]["profiles"]["pi-default"]["agent_options"] == {"ui": {"theme": "everforest-dark"}}
  item = next(row for row in report["items"] if row["id"] == "role-scout")
  assert item["selected"] is None


def test_duplicate_model_ids_are_not_silently_overwritten(tmp_path):
  home = native_home(tmp_path)
  (home / "models.json").write_text(json.dumps({"providers": {"fictional": {
    "api": "openai-completions", "baseUrl": "https://example.invalid/v1",
    "models": [{"id": "duplicate"}, {"id": "duplicate"}, {"id": "duplicate"}],
  }}}))
  report = build_inventory(home, repository=ROOT)
  assert "models" not in report["proposed_overrides"]
  assert any(item["code"] == "duplicate-native-model" for item in report["blockers"])
