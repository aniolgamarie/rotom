"""公开来源、路径和目标所有权的隔离测试。"""

import json
from pathlib import Path

import pytest

from termcfg.catalog import GeneratedTemplate, SourceArtifact, load_catalog, REPO_ROOT
from termcfg.errors import TermcfgError


def test_catalog_sources_are_fixed_and_public():
  entries = load_catalog()
  assert {item.component for item in entries} == {"zsh", "tmux", "herdr"}
  static = [item for item in entries if isinstance(item, SourceArtifact)]
  generated = [item for item in entries if isinstance(item, GeneratedTemplate)]
  assert static and all(item.bytes() for item in static)
  assert len(static) + len(generated) == len(entries)
  assert len(generated) == 1
  binding = generated[0]
  assert (binding.kind, binding.id, binding.component, binding.destination, binding.mode, binding.generator_version) == (
    "rotom-entry-binding", "rotom-entry-binding", "zsh", Path(".local/share/rotom/entry.json"), 0o600, 1)


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


def test_plugin_locks_have_complete_assets():
  from termcfg import packages
  plugins, _ = packages._read_lock_raw("zsh")
  assert plugins["assets"]["zsh"] and plugins["assets"]["tmux"]
  assert all(item["resources"] and item["entry"] for group in plugins["assets"].values() for item in group)


def test_plugin_lock_unknown_field_rejected(tmp_path, monkeypatch):
  from termcfg import packages
  value = json.loads(packages.lock_path("zsh").read_text())
  value["assets"]["zsh"][0]["unknown"] = "ignored?"
  path = tmp_path / "plugins.json"
  path.write_text(json.dumps(value))
  monkeypatch.setattr(packages, "lock_path", lambda component: path)
  with pytest.raises(TermcfgError):
    packages._read_lock_raw("zsh")


def generated_declaration():
  return {"kind": "rotom-entry-binding", "id": "rotom-entry-binding", "component": "zsh",
    "destination": ".local/share/rotom/entry.json", "mode": "0600", "generator_version": 1}


def write_catalog(tmp_path, value):
  path = tmp_path / "catalog.json"
  path.write_text(json.dumps(value), encoding="utf-8")
  return path


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("explicit_kind", [False, True])
def test_catalog_keeps_static_v1_and_v2_compatible(tmp_path, version, explicit_kind):
  from termcfg.catalog import SourceArtifact
  static = json.loads((REPO_ROOT / "terminals/catalog.json").read_text())["targets"][0]
  if explicit_kind:
    static["kind"] = "static"
  entries = load_catalog(write_catalog(tmp_path, {"version": version, "targets": [static]}))
  assert len(entries) == 1 and isinstance(entries[0], SourceArtifact)
  assert entries[0].bytes()


def test_generated_declaration_is_fixed_metadata_without_materialization(tmp_path, monkeypatch):
  from pathlib import Path
  from termcfg.catalog import GeneratedTemplate
  def forbidden(*args, **kwargs):
    pytest.fail("catalog parsing must not generate or inspect target HOME")
  monkeypatch.setattr(GeneratedTemplate, "materialize", forbidden)
  entries = load_catalog(write_catalog(tmp_path, {"version": 2, "targets": [generated_declaration()]}))
  assert len(entries) == 1 and isinstance(entries[0], GeneratedTemplate)
  declaration = entries[0]
  assert (declaration.kind, declaration.id, declaration.component, declaration.destination,
    declaration.mode, declaration.generator_version) == (
    "rotom-entry-binding", "rotom-entry-binding", "zsh", Path(".local/share/rotom/entry.json"), 0o600, 1)
  assert not hasattr(declaration, "bytes") and not hasattr(declaration, "source")


@pytest.mark.parametrize("version", [0, 3, True, 1.0, 2.0, "2", None])
def test_catalog_unknown_or_inexact_version_rejected(tmp_path, version):
  with pytest.raises(TermcfgError) as caught:
    load_catalog(write_catalog(tmp_path, {"version": version, "targets": []}))
  assert caught.value.code == 2


def test_catalog_v1_cannot_enable_generated_targets(tmp_path):
  with pytest.raises(TermcfgError) as caught:
    load_catalog(write_catalog(tmp_path, {"version": 1, "targets": [generated_declaration()]}))
  assert caught.value.code == 2


@pytest.mark.parametrize("key,value", [
  ("kind", "shell"), ("id", "custom-generator"), ("component", "tmux"),
  ("destination", ".config/arbitrary.json"), ("mode", "0700"),
  ("generator_version", 2), ("generator_version", True), ("generator_version", 1.0),
  ("command", "never-execute"), ("shell", "never-execute"),
  ("argv", ["never-execute"]), ("generator", "arbitrary-generator"),
  ("source", "terminals/zsh/zshenv"), ("payload", "arbitrary bytes"),
])
def test_catalog_generated_contract_rejects_arbitrary_generation(tmp_path, key, value):
  declaration = generated_declaration()
  declaration[key] = value
  with pytest.raises(TermcfgError) as caught:
    load_catalog(write_catalog(tmp_path, {"version": 2, "targets": [declaration]}))
  assert caught.value.code == 2


@pytest.mark.parametrize("payload", [
  '{"version":2,"version":2,"targets":[]}',
  '{"version":2,"targets":[],"targets":[]}',
  '{"version":2,"targets":[{"kind":"rotom-entry-binding","id":"rotom-entry-binding",'
    '"id":"rotom-entry-binding","component":"zsh","destination":".local/share/rotom/entry.json",'
    '"mode":"0600","generator_version":1}]}',
  '{"version":2,"targets":[{"kind":"rotom-entry-binding","id":"rotom-entry-binding",'
    '"component":"zsh","destination":".local/share/rotom/entry.json","mode":"0600",'
    '"generator_version":1,"generator_version":1}]}',
])
def test_catalog_duplicate_json_fields_rejected_at_every_depth(tmp_path, payload):
  path = tmp_path / "catalog.json"
  path.write_text(payload)
  with pytest.raises(TermcfgError) as caught:
    load_catalog(path)
  assert caught.value.code == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["version", "generator_version"])
def test_catalog_nonfinite_values_rejected(tmp_path, value, field):
  document = {"version": 2, "targets": [generated_declaration()]}
  if field == "version":
    document["version"] = value
  else:
    document["targets"][0][field] = value
  with pytest.raises(TermcfgError) as caught:
    load_catalog(write_catalog(tmp_path, document))
  assert caught.value.code == 2
