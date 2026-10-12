"""自建资产的锁、发布、安装接线；仅使用合成归档和假安装器。"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from agentcfg import pi_assets, pi_bwrap_build, pi_capabilities, pi_vendor
from agentcfg.pi_dependencies import PiBackend, recipe_digest
from agentcfg.pi_lock_layout import dependency_layout
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import ensure_private
from test_pi_built_assets import built_fixture
from test_pi_capability_manifest import binding_repository, _write_manifest
from test_pi_dependencies import payload
from test_pi_lock_families import generator_fixture


ROOT = Path(__file__).resolve().parents[1]


def attach(bindings, source, profiles):
  catalog = bindings["catalog"]
  catalog["capabilities"]["native"]["source_ids"].append("host-helper")
  catalog["source_profiles"]["host-helper"] = profiles
  bindings["providers"]["native-provider"]["support_sources"] = [{"source_id": "host-helper",
    "source_version": None, "source_identity": pi_capabilities.source_identity(source)}]


def locked_fixture(tmp_path, monkeypatch):
  workspace, manifest = binding_repository(tmp_path)
  root = workspace.repository
  source, record, archive = built_fixture(root, monkeypatch)
  manifest["sources"]["host-helper"] = source
  manifest["platforms"] = ["linux-x86_64"]
  attach(manifest["capability_bindings"], source, ["pi-base", "pi-full"])
  for piece in manifest["profile_slices"].values(): piece["source_ids"].append("host-helper")
  manifest["recipe_digest"] = recipe_digest(root, family="modern")
  _write_manifest(root, manifest)
  return workspace, manifest, source, record, archive


def generated_fixture(tmp_path, monkeypatch):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  source, record, archive = built_fixture(workspace.repository, monkeypatch)
  inputs["sources"]["host-helper"] = source
  inputs["profiles"]["pi-base"]["source_ids"].append("host-helper")
  attach(inputs["capability_bindings"], source, ["pi-base"])
  path.write_bytes(payload(inputs))
  return workspace, inputs, path, calls, source


def test_selected_helper_enters_lock_and_installed_identity_without_fake_capability(tmp_path, monkeypatch):
  workspace, manifest, source, _, _ = locked_fixture(tmp_path, monkeypatch)
  lock = PiBackend(profile="pi-base").read_lock(workspace.repository)
  selected = lock.validated_bindings["pi-base"]
  assert ("host-helper", None, pi_capabilities.source_identity(source)) in selected.source_expectations
  assert manifest["profile_slices"]["pi-base"]["capability_ids"] == ["native"]
  observed = [{"source_id": key, "version": version, "source_identity": digest}
    for key, version, digest in selected.source_expectations]
  assert pi_capabilities.check_installed(selected, observed)
  with pytest.raises(DependencyError):
    pi_capabilities.check_installed(selected, [row for row in observed if row["source_id"] != "host-helper"])


@pytest.mark.parametrize("fault", ["record", "input", "license", "archive"])
def test_selected_helper_body_drift_invalidates_lock(tmp_path, monkeypatch, fault):
  workspace, _, source, _, _ = locked_fixture(tmp_path, monkeypatch)
  root = workspace.repository; backend = PiBackend(profile="pi-base")
  backend.read_lock(root)
  if fault == "record": path = "locks/pi-modern/" + source["build_record"]["path"]
  elif fault == "archive": path = "locks/pi-modern/" + source["vendor_path"]
  elif fault == "license": path = source["license_files"][0]
  else:
    item = next(iter(pi_bwrap_build.INPUTS.values()))
    path = "locks/pi-modern/build-inputs/" + item["sha256"] + "/" + item["name"]
  (root / path).write_bytes(b"synthetic drift")
  with pytest.raises(ConfigError, match="pi-lock-missing-or-stale"): backend.read_lock(root)


@pytest.mark.parametrize("fault", ["missing", "digest", "version", "duplicate", "self", "unknown", "profile", "catalog", "slice"])
def test_support_sources_fail_closed(tmp_path, monkeypatch, fault):
  workspace, manifest, _, _, _ = locked_fixture(tmp_path, monkeypatch)
  bindings = manifest["capability_bindings"]
  provider = bindings["providers"]["native-provider"]
  row = provider["support_sources"][0]
  if fault == "missing": del provider["support_sources"]
  elif fault == "digest": row["source_identity"] = "a" * 64
  elif fault == "version": row["source_version"] = "1.0.0"
  elif fault == "duplicate": provider["support_sources"].append(deepcopy(row))
  elif fault == "self": row["source_id"] = "pi-host"
  elif fault == "unknown": row["private-token"] = "synthetic-private"
  elif fault == "profile": bindings["catalog"]["source_profiles"]["host-helper"] = ["pi-full"]
  elif fault == "catalog": bindings["catalog"]["capabilities"]["native"]["source_ids"].remove("host-helper")
  else: manifest["profile_slices"]["pi-base"]["source_ids"].remove("host-helper")
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError) as error: PiBackend(profile="pi-base").read_lock(workspace.repository)
  assert "synthetic-private" not in str(error.value)


def test_built_source_identity_tracks_record_but_not_storage_location(tmp_path, monkeypatch):
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  expected = pi_capabilities.source_identity(source)
  moved = deepcopy(source); moved["vendor_path"] = "vendor/other.tgz"
  assert pi_capabilities.source_identity(moved) == expected
  moved["build_record"].update(digest="a" * 64, path="build-records/" + "a" * 64 + ".json")
  assert pi_capabilities.source_identity(moved) != expected


@pytest.mark.parametrize("fault", ["url", "no-origin", "no-vendor", "raw", "unknown-ref", "non-asset"])
def test_schema_has_exclusive_closed_asset_origin(tmp_path, monkeypatch, fault):
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  schema = json.loads((ROOT / "schemas/pi-lock.schema.json").read_text())
  validator = Draft202012Validator(schema["properties"]["sources"]["additionalProperties"])
  assert validator.is_valid(source)
  if fault == "url": source["url"] = "https://example.invalid/binary"
  elif fault == "no-origin": del source["build_record"]
  elif fault == "no-vendor": del source["vendor_path"]
  elif fault == "raw": source["format"] = "raw"
  elif fault == "unknown-ref": source["build_record"]["unknown"] = True
  else: source["kind"] = "local"
  assert not validator.is_valid(source)


def test_legacy_schema_rejects_built_asset(tmp_path, monkeypatch):
  workspace, _, source, _, _ = locked_fixture(tmp_path, monkeypatch)
  manifest = json.loads((workspace.repository / "locks/pi/manifest.json").read_bytes())
  manifest["sources"]["host-helper"] = source
  schema = json.loads((ROOT / "schemas/pi-lock.schema.json").read_text())
  assert not Draft202012Validator(schema).is_valid(manifest)


def test_generator_publishes_built_asset_with_support_identity_as_candidate(tmp_path, monkeypatch):
  workspace, _, _, calls, source = generated_fixture(tmp_path, monkeypatch)
  backend = PiBackend(profile="pi-base")
  lock = backend.resolve_lock(workspace.repository)
  assert len(calls) == 3
  assert lock.metadata["sources"]["host-helper"] == source
  assert lock.validated_bindings["pi-base"].state == "candidate"
  assert backend.read_lock(workspace.repository).identity == lock.identity
  with pytest.raises(DependencyError): backend.sync(workspace, lock)


@pytest.mark.parametrize("fault", ["record", "input", "archive"])
def test_drift_during_npm_cannot_publish_built_asset_lock(tmp_path, monkeypatch, fault):
  workspace, _, _, calls, source = generated_fixture(tmp_path, monkeypatch)
  root = workspace.repository; backend = PiBackend(profile="pi-base")
  lock = backend.resolve_lock(root)
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  original = pi_vendor.checked; calls.clear()
  def changing(argv, *, cwd, env):
    result = original(argv, cwd=cwd, env=env)
    if argv[:2] == ["npm", "install"]:
      if fault == "record": path = source["build_record"]["path"]
      elif fault == "archive": path = source["vendor_path"]
      else:
        item = next(iter(pi_bwrap_build.INPUTS.values()))
        path = "build-inputs/" + item["sha256"] + "/" + item["name"]
      (root / "locks/pi-modern" / path).write_bytes(b"synthetic drift")
    return result
  monkeypatch.setattr(pi_vendor, "checked", changing)
  with pytest.raises(ConfigError): backend.resolve_lock(root)
  assert len(calls) == 3 and (root / "locks/pi-modern/manifest.json").read_bytes() == before
  for key, raw in zip(("package_path", "lock_path"), lock.pairs["pi-base"]):
    assert (root / "locks/pi-modern" / lock.metadata["profile_slices"]["pi-base"][key]).read_bytes() == raw


@pytest.mark.parametrize("fault", [None, "record", "input", "legacy"])
def test_install_is_offline_and_requires_complete_built_provenance(tmp_path, monkeypatch, fault):
  source, record, _ = built_fixture(tmp_path, monkeypatch)
  stage = tmp_path / "stage"; ensure_private(stage)
  monkeypatch.setattr(pi_assets, "open_download", lambda *_: pytest.fail("built asset must not download"))
  if fault == "record": (tmp_path / "locks/pi-modern" / source["build_record"]["path"]).unlink()
  if fault == "input":
    item = next(iter(pi_bwrap_build.INPUTS.values()))
    (tmp_path / "locks/pi-modern/build-inputs" / item["sha256"] / item["name"]).unlink()
  def install():
    pi_assets.install_assets(tmp_path, stage, {"source_ids": ["helper"]}, {"sources": {"helper": source}},
      "linux-x86_64", lock_family="legacy" if fault == "legacy" else "modern")
  if fault:
    with pytest.raises(DependencyError): install()
    assert not (stage / "bin/pi-bwrap").exists()
  else:
    import hashlib
    install()
    binary = stage / "bin/pi-bwrap"
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == record["binary_sha256"]
    assert binary.stat().st_mode & 0o777 == 0o700
    assert len(list((stage / "licenses/helper").iterdir())) == 2


@pytest.mark.parametrize("fault", [None, "archive", "record", "missing"])
def test_fetch_only_verifies_built_assets_even_with_force(tmp_path, monkeypatch, fault):
  source, _, archive = built_fixture(tmp_path, monkeypatch)
  path = tmp_path / "agents/pi/dependencies-modern.json"
  path.write_bytes(payload({"schema_version": 2, "sources": {"helper": source},
    "profiles": {"pi-base": {"source_ids": ["helper"]}}}))
  target = tmp_path / "locks/pi-modern" / source["vendor_path"]
  if fault == "archive": target.write_bytes(b"preserve-corrupt")
  if fault == "record": (tmp_path / "locks/pi-modern" / source["build_record"]["path"]).unlink()
  if fault == "missing": target.unlink()
  spec = importlib.util.spec_from_file_location("fetch_pi_built_assets", ROOT / "scripts/fetch-pi-assets.py")
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  monkeypatch.setattr(module, "fetch", lambda *_: pytest.fail("must not fetch built artifact"))
  monkeypatch.setattr(pi_bwrap_build, "build_candidate", lambda *_: pytest.fail("must not run compiler"))
  argv = ["--repository", str(tmp_path), "--profile", "pi-base", "--force"]
  if fault:
    with pytest.raises(ConfigError): module.main(argv)
    assert (not target.exists()) if fault == "missing" else target.read_bytes() == (b"preserve-corrupt" if fault == "archive" else archive)
  else: assert module.main(argv) == 0 and target.read_bytes() == archive


def test_license_replacement_between_record_check_and_install_is_rejected(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  source, _, _ = built_fixture(tmp_path, monkeypatch)
  stage = tmp_path / "stage"; ensure_private(stage)
  original = Tree.read; reads = 0
  def changing(self, name, *args, **kwargs):
    nonlocal reads
    if str(name) == source["license_files"][0]:
      reads += 1
      if reads == 2: (tmp_path / name).write_bytes(b"replaced license")
    return original(self, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", changing)
  with pytest.raises(DependencyError):
    pi_assets.install_assets(tmp_path, stage, {"source_ids": ["helper"]}, {"sources": {"helper": source}},
      "linux-x86_64", lock_family="modern")
  assert not (stage / "bin/pi-bwrap").exists() and not (stage / "licenses").exists()
