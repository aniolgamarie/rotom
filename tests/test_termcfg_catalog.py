"""公开来源、路径和目标所有权的隔离测试。"""

import json

import pytest

from termcfg.catalog import load_catalog, REPO_ROOT
from termcfg.errors import TermcfgError


def test_catalog_sources_are_fixed_and_public():
  entries = load_catalog()
  assert {item.component for item in entries} == {"zsh", "tmux", "mihomo"}
  assert all(item.bytes() for item in entries)


@pytest.mark.parametrize("destination", ["../outside", "/tmp/outside", ".config/../outside"])
def test_catalog_rejects_escaping_destinations(tmp_path, destination):
  catalog = json.loads((REPO_ROOT / "terminals/catalog.json").read_text())
  catalog["targets"][0]["destination"] = destination
  path = tmp_path / "catalog.json"
  path.write_text(json.dumps(catalog))
  with pytest.raises(TermcfgError):
    load_catalog(path)


def test_catalog_rejects_duplicate_targets(tmp_path):
  catalog = json.loads((REPO_ROOT / "terminals/catalog.json").read_text())
  catalog["targets"][1]["destination"] = catalog["targets"][0]["destination"]
  path = tmp_path / "catalog.json"
  path.write_text(json.dumps(catalog))
  with pytest.raises(TermcfgError):
    load_catalog(path)


def test_catalog_rejects_unknown_fields(tmp_path):
  catalog = json.loads((REPO_ROOT / "terminals/catalog.json").read_text())
  catalog["targets"][0]["unknown"] = "ignored?"
  path = tmp_path / "catalog.json"
  path.write_text(json.dumps(catalog))
  with pytest.raises(TermcfgError):
    load_catalog(path)


def test_asset_lock_rejects_unknown_fields(tmp_path, monkeypatch):
  from termcfg import packages
  original = packages.lock_path("mihomo")
  value = json.loads(original.read_text())
  value["assets"]["linux-x86_64"]["unknown"] = "ignored?"
  path = tmp_path / "mihomo.json"
  path.write_text(json.dumps(value))
  monkeypatch.setattr(packages, "lock_path", lambda component: path)
  with pytest.raises(TermcfgError):
    packages._read_lock_raw("mihomo")


def test_core_and_plugin_locks_have_complete_supported_assets(monkeypatch):
  from termcfg import packages
  core, _ = packages._read_lock_raw("mihomo")
  plugins, _ = packages._read_lock_raw("zsh")
  assert set(core["assets"]) == {"linux-x86_64"}
  asset = core["assets"]["linux-x86_64"]
  assert asset["size"] > 0 and len(asset["sha256"]) == 64 and asset["entry"] == "mihomo"
  assert plugins["assets"]["zsh"] and plugins["assets"]["tmux"]
  assert all(item["resources"] and item["entry"] for group in plugins["assets"].values() for item in group)
  monkeypatch.setattr(packages, "current_platform", lambda: "darwin-arm64")
  with pytest.raises(TermcfgError) as error:
    packages.core_asset()
  assert error.value.code == 5


def test_plugin_lock_unknown_field_rejected(tmp_path, monkeypatch):
  from termcfg import packages
  value = json.loads(packages.lock_path("zsh").read_text())
  value["assets"]["zsh"][0]["unknown"] = "ignored?"
  path = tmp_path / "plugins.json"
  path.write_text(json.dumps(value))
  monkeypatch.setattr(packages, "lock_path", lambda component: path)
  with pytest.raises(TermcfgError):
    packages._read_lock_raw("zsh")
