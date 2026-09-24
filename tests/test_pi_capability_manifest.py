"""新清单必须闭合，旧角色只映射为用途，不进入新运行清单。"""

import json
from pathlib import Path
import tomllib

from agentcfg.pi_catalog import validate_catalog


ROOT = Path(__file__).resolve().parents[1]


def test_migration_catalog_has_explicit_source_and_disposition_for_every_capability():
  path = ROOT / "agents/pi/migration/capabilities.toml"
  assert path.is_file(), "migration capability decisions must be recorded before importing resources"
  value = tomllib.loads(path.read_text())
  catalog = {"schema_version": value["schema_version"], "sources": value["sources"],
    "capabilities": [{key: row[key] for key in ("id", "kind", "source_id", "entrypoints", "requires", "conflicts", "control_domain", "supported_engines", "evidence_cases")} for row in value["capabilities"]]}
  items = validate_catalog(catalog)
  assert {"task-keeper", "model-delegate", "pi-subagents"} <= items.keys()
  assert all(row["disposition"] in {"keep", "adapt", "merge", "replace", "optional", "exclude"} and row["reason"] for row in value["capabilities"])
  assert not any("run-codex.sh" in row.get("target_path", "") for row in value["capabilities"])


def test_seven_codex_roles_map_to_new_presets():
  path = ROOT / "agents/pi/migration/role-map.json"
  assert path.is_file(), "role migration mapping missing"
  value = json.loads(path.read_text())
  assert len(value["roles"]) == 7
  assert {row["preset"] for row in value["roles"].values()} == {"general", "context", "challenge", "plan", "research", "review", "scout"}
  assert all(row["tool"] == "model_delegate" and row["backend"] == "codex" and row["register_legacy_role"] is False for row in value["roles"].values())


def test_ordinary_profiles_select_the_promised_todo_loop_guard_and_footer_baseline():
  import tomllib
  from pathlib import Path
  root = Path(__file__).resolve().parents[1]
  for profile in ("pi-default", "pi-codex", "pi-cursor"):
    value = tomllib.loads((root / "profiles" / (profile + ".toml")).read_text())
    assert {"pi-subagents", "pi-permissions", "model-delegate", "pi-todo", "loop-guard", "colorful-footer"} <= set(value["plugins"])
    assert "task-keeper" not in value["plugins"]


def test_all_published_plugin_catalog_entries_have_real_dependency_and_resource_sources():
  catalog = tomllib.loads((ROOT / "agents/pi/plugins.toml").read_text())["plugins"]
  sources = json.loads((ROOT / "agents/pi/dependencies.json").read_text())["sources"]
  assert set(catalog) <= set(sources)
  for key in catalog:
    assert any(sources[key]["resources"].values()), key
