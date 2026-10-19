"""旧来源只读计数：不读取秘密/模型/会话正文，不生成自动迁移覆盖。"""

import json
from pathlib import Path

import pytest

from agentcfg.pi_inventory import build_inventory
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree


ROOT = Path(__file__).resolve().parents[1]


def native_home(tmp_path):
  home = tmp_path / "pi-home"
  home.mkdir()
  (home / "settings.json").write_text(json.dumps({"packages": ["npm:unreviewed@1.0.0"],
    "arbitrarySecret": "SYNTHETIC_PRIVATE_SENTINEL"}))
  for name in ("auth.json", "models.json", "trust.json"):
    (home / name).write_text("SYNTHETIC_PRIVATE_SENTINEL")
  (home / "prompts").mkdir()
  (home / "prompts/private-name.md").write_text("SYNTHETIC_PRIVATE_SENTINEL")
  (home / "tasks.sqlite").write_text("SYNTHETIC_PRIVATE_SENTINEL")
  (home / "sessions").mkdir()
  (home / "sessions/private-history.jsonl").write_text("SYNTHETIC_PRIVATE_SENTINEL")
  return home


def test_inventory_reports_counts_without_reading_private_bodies(tmp_path, monkeypatch, sentinel_factory):
  home = native_home(tmp_path)
  before = sentinel_factory(home)
  read = Tree.read
  def guarded(tree, name, *args, **kwargs):
    assert name == "settings.json"
    return read(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", guarded)
  report = build_inventory(home, repository=ROOT)
  indexed = {item["id"]: item for item in report["items"]}
  assert report["schema_version"] == 2 and report["proposed_overrides"] == {}
  assert report["ready_to_deploy"] is False and report["blockers"]
  assert indexed["resource-prompts"]["count"] == 1
  assert indexed["resource-sessions"]["count"] == 1
  assert indexed["loading-packages"]["count"] == 1
  assert indexed["authentication"]["state"] == "present"
  assert all(word not in json.dumps(report) for word in ("SYNTHETIC_PRIVATE_SENTINEL", "private-name", "private-history", "unreviewed"))
  before.assert_unchanged()


def test_package_commands_and_credential_urls_are_never_copied(tmp_path):
  home = native_home(tmp_path)
  (home / "settings.json").write_text(json.dumps({"packages": ["https://user:synthetic-password@example.invalid/pkg",
    {"source": "$(touch forbidden)"}]}))
  report = build_inventory(home)
  assert next(item for item in report["items"] if item["id"] == "loading-packages")["count"] == 2
  assert all(word not in json.dumps(report) for word in ("synthetic-password", "user:", "forbidden"))


def test_settings_symlink_cannot_read_an_unrelated_file(tmp_path):
  home = native_home(tmp_path)
  outside = tmp_path / "outside"
  outside.write_text("SYNTHETIC_PRIVATE_SENTINEL")
  (home / "settings.json").unlink()
  (home / "settings.json").symlink_to(outside)
  with pytest.raises(Conflict): build_inventory(home)


@pytest.mark.parametrize("theme,expected", [("catppuccin-frappe", "catppuccin-frappe"), ("private-theme-name", None)])
def test_theme_allowlist_does_not_create_an_adoption_proposal(tmp_path, theme, expected):
  home = native_home(tmp_path)
  (home / "settings.json").write_text(json.dumps({"theme": theme}))
  report = build_inventory(home)
  assert next(item for item in report["items"] if item["id"] == "theme-preference")["theme"] == expected
  assert report["proposed_overrides"] == {}
  assert "private-theme-name" not in json.dumps(report)


def test_starter_comparison_is_explicitly_unsupported(tmp_path):
  with pytest.raises(ConfigError): build_inventory(tmp_path, tmp_path)


def test_cli_migration_preview_is_private_counts_only_and_rejects_old_flags(tmp_path, capsys, sentinel_factory):
  from agentcfg.cli import main
  home = native_home(tmp_path)
  before = sentinel_factory(home)
  local = tmp_path / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="fixture"\n')
  prefix = ["--local", str(local), "--profile", "pi-base"]
  assert main([*prefix, "plan", "--from-pi-home", str(home)]) == 0
  result = json.loads(capsys.readouterr().out)
  proposal = Path(result["proposal"])
  assert result["mode"] == "migration-preview" and result["ready_to_deploy"] is False
  assert proposal.stat().st_mode & 0o777 == 0o600
  assert proposal.parent.stat().st_mode & 0o777 == 0o700
  assert json.loads(proposal.read_text())["proposed_overrides"] == {}
  before.assert_unchanged()
  for tail in (["plan", "--from-starter", str(tmp_path)], ["recover", "pi", "--lease", "old"]):
    with pytest.raises(SystemExit) as error: main([*prefix, *tail])
    assert error.value.code == 2
