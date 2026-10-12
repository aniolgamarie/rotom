"""B1 的离线合成锁接线；数据预检不签发 Full 来源或安装资格。"""

import builtins
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from agentcfg import pi_capabilities as capabilities
from agentcfg import pi_dependencies as dependencies
from agentcfg import pi_vendor as vendor
from agentcfg.pi_lock_header import validate_lock_header
from agentcfg.pi_lock_resolution import validate_lock_resolution
from agentcfg.pi_modern_launcher import validate_destinations
from agentcfg.pi_runtime_files import lock_files
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from test_pi_dependencies import payload, fixture_repository
from test_pi_lock_families import generator_fixture
from test_pi_capability_manifest import runtime_declarations, _write_manifest
from test_pi_wheel_sources import _source


_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = "agents/pi/runtime/durable-python-bundle.json"
_PATH = "runtime/durable-python-bundle.json"
_NAMES = ["attrs", "jsonschema", "jsonschema-specifications", "pyyaml", "referencing", "rpds-py", "typing-extensions"]


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path, monkeypatch, *, base=True):
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  root = workspace.repository
  from test_pi_python_bundle import _fixture as synthetic_wheels
  declaration, archives, _ = synthetic_wheels()
  raw = json.dumps(declaration, ensure_ascii=False).encode()
  (root / _SOURCE).write_bytes(raw)
  wheel_ids = []
  for row in declaration["wheels"]:
    source = {"kind": "wheel", "package": row["name"], "version": row["version"], "wheel_filename": row["wheel_filename"],
      "url": "https://files.example.test/" + row["wheel_filename"], "archive_digest": row["archive_sha256"], "size": row["archive_size"],
      "license_files": sorted(row["dist_info"] + "/licenses/" + name for name in row["metadata"]["license_files"])}
    inputs["sources"][row["source_id"]] = source
    wheel_ids.append(row["source_id"])
    wheel_path = root / "locks/pi-modern/vendor/wheels" / source["archive_digest"] / source["wheel_filename"]
    wheel_path.parent.mkdir(parents=True)
    wheel_path.write_bytes(archives[row["source_id"]])
  full = deepcopy(inputs["profiles"]["pi-base"])
  full["source_ids"] += wheel_ids
  full["runtime_files"].append({"source": _SOURCE, "path": _PATH, "transform": "copy"})
  full["python_bundle"] = {"schema_version": 1, "source": _SOURCE, "path": _PATH, "sha256": _sha(raw), "size": len(raw)}
  inputs["profiles"]["pi-full"] = full
  bindings = inputs["capability_bindings"]
  # 此合成 Full 用 durable 替换旧 fixture 的额外本地能力，仍保留 required 闭包校验。
  bindings["catalog"]["capabilities"].pop("extra")
  bindings["catalog"]["source_profiles"].pop("full-feature")
  bindings["providers"].pop("extra-provider")
  bindings["catalog"]["resource_profiles"]["pi-host"] = ["pi-base", "pi-full"]
  bindings["catalog"]["capabilities"]["durable"] = {"profiles": ["pi-full"], "required": True, "contract_version": "1",
    "owner_domain": "durable", "single_owner": True, "config_fields": [], "state_owners": [], "source_ids": wheel_ids, "resource_ids": []}
  for identity in wheel_ids: bindings["catalog"]["source_profiles"][identity] = ["pi-full"]
  provider = deepcopy(bindings["providers"]["native-provider"])
  provider.update(provider_id="durable-provider", capability_id="durable", source_id=wheel_ids[0], resource_ids=[], public_entrypoints=["durable/public"])
  locked = {key: {**inputs["sources"][key], "vendor_path": "vendor/wheels/" + inputs["sources"][key]["archive_digest"] + "/" + inputs["sources"][key]["wheel_filename"]} for key in wheel_ids}
  provider.update(source_version=locked[wheel_ids[0]]["version"], source_identity=capabilities.source_identity(locked[wheel_ids[0]]),
    support_sources=[{"source_id": key, "source_version": locked[key]["version"], "source_identity": capabilities.source_identity(locked[key])} for key in wheel_ids[1:]])
  bindings["providers"]["durable-provider"] = provider
  selection = deepcopy(bindings["selections"]["pi-base"])
  selection["profile"] = "pi-full"
  selection["bindings"].append({"capability_id": "durable", "provider_id": "durable-provider"})
  bindings["selections"]["pi-full"] = selection
  if not base:
    inputs["profiles"].pop("pi-base")
    bindings["selections"].pop("pi-base")
  path.write_bytes(payload(inputs))
  return workspace, inputs, path, calls, declaration, archives


def _write_inputs(path, inputs):
  path.write_bytes(payload(inputs))


def _republish(root, manifest):
  manifest["recipe_digest"] = dependencies.recipe_digest(root, family="modern")
  _write_manifest(root, manifest)


def _wheel_path(root, source):
  return root / "locks/pi-modern/vendor/wheels" / source["archive_digest"] / source["wheel_filename"]


def test_full_generated_lock_read_preserves_raw_archives_and_excludes_npm_wheels(tmp_path, monkeypatch):
  workspace, inputs, _, calls, declaration, archives = _fixture(tmp_path, monkeypatch)
  lock = dependencies.PiBackend(family="modern").resolve_lock(workspace.repository)
  assert set(lock.pairs) == {"pi-base", "pi-full"}
  assert len(calls) == 4
  full = lock.metadata["profile_slices"]["pi-full"]
  assert full["python_bundle"] == inputs["profiles"]["pi-full"]["python_bundle"]
  assert _PATH in {row["path"] for row in full["runtime_files"]}
  for pair in lock.pairs.values():
    assert set(json.loads(pair[0])["dependencies"]) == {"synthetic-host"}
    assert not any(name in json.loads(pair[1])["packages"] for name in ("node_modules/attrs", "node_modules/pyyaml"))
  for row in declaration["wheels"]:
    source = lock.metadata["sources"][row["source_id"]]
    assert (workspace.repository / "locks/pi-modern" / source["vendor_path"]).read_bytes() == archives[row["source_id"]]
    assert "resources" not in source and "source_path" not in source
  selected = dependencies.PiBackend(profile="pi-full").read_lock(workspace.repository)
  assert list(selected.pairs) == ["pi-full"] and len(selected.pairs["pi-full"]) == 2
  assert selected.validated_bindings["pi-full"].state == "candidate"


@pytest.mark.parametrize("fault", ["missing", "size", "sha", "oversize", "archive-semantics", "partial", "wrong-id", "version", "license", "ref-sha", "ref-size", "runtime", "unknown", "cross-kind"])
def test_bad_wheel_or_full_pair_fails_before_build_or_any_process(tmp_path, monkeypatch, fault):
  workspace, inputs, path, calls, _, _ = _fixture(tmp_path, monkeypatch)
  root = workspace.repository
  # 未选的本地来源也会进入原 build_archive；坏 wheel 必须先拒绝它。
  inputs["sources"]["local-preflight-control"] = {"kind": "local", "package": "local-control", "version": "1.0.0",
    "license_files": ["LICENSE"], "resources": {kind: [] for kind in ("extensions", "skills", "prompts", "themes")}}
  (root / "agents/pi/build/recipes-modern.json").write_bytes(payload({"schema_version": 1, "sources": {
    "local-preflight-control": {"kind": "local", "package": "local-control", "version": "1.0.0", "license_files": ["LICENSE"],
      "source_path": "packages/not-built", "exclude": []}}}))
  source = inputs["sources"]["durable-python-attrs"]
  archive_path = _wheel_path(root, source)
  if fault == "missing": archive_path.unlink()
  if fault == "size": archive_path.write_bytes(archive_path.read_bytes() + b"x")
  if fault == "sha": archive_path.write_bytes(b"x" * source["size"])
  if fault == "oversize": archive_path.write_bytes(b"x" * 2097153)
  if fault == "archive-semantics":
    raw = bytearray(archive_path.read_bytes()); raw[0] ^= 1
    source["archive_digest"] = _sha(raw)
    changed = _wheel_path(root, source); changed.parent.mkdir(parents=True); changed.write_bytes(raw)
    body = json.loads((root / _SOURCE).read_bytes()); body["wheels"][0]["archive_sha256"] = source["archive_digest"]
    new_body = json.dumps(body).encode(); (root / _SOURCE).write_bytes(new_body)
    ref = inputs["profiles"]["pi-full"]["python_bundle"]; ref.update(sha256=_sha(new_body), size=len(new_body))
    provider = inputs["capability_bindings"]["providers"]["durable-provider"]
    provider["source_identity"] = capabilities.source_identity({**source, "vendor_path": "vendor/wheels/" + source["archive_digest"] + "/" + source["wheel_filename"]})
  if fault == "partial": inputs["profiles"]["pi-full"]["source_ids"].pop()
  if fault == "wrong-id": inputs["sources"]["wrong-id"] = inputs["sources"].pop("durable-python-attrs")
  if fault == "version": source["version"] = "1"
  if fault == "license": source["license_files"] = [source["license_files"][0].replace("LICENSE", "OTHER")]
  if fault == "ref-sha": inputs["profiles"]["pi-full"]["python_bundle"]["sha256"] = "b" * 64
  if fault == "ref-size": inputs["profiles"]["pi-full"]["python_bundle"]["size"] += 1
  if fault == "runtime": inputs["profiles"]["pi-full"]["runtime_files"][-1]["transform"] = "ts-module"
  if fault == "unknown": source["build_record"] = {}
  if fault == "cross-kind": source["resources"] = {}
  _write_inputs(path, inputs)
  monkeypatch.setattr(vendor, "build_archive", lambda *a, **k: pytest.fail("preflight precedes old build"))
  before = (root / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError): dependencies.PiBackend(profile="pi-full").resolve_lock(root)
  assert calls == [] and (root / "locks/pi-modern/manifest.json").read_bytes() == before


def test_base_recipe_raw_scan_only_no_selected_body_vendor_core_zip(tmp_path, monkeypatch):
  workspace, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
  root = workspace.repository
  manifest = dependencies.PiBackend(family="modern").resolve_lock(root).metadata
  for source in manifest["sources"].values():
    if source["kind"] == "wheel": (root / "locks/pi-modern" / source["vendor_path"]).unlink()
  state = {"recipe": False, "raw_body_reads": 0, "recipe_digest": None}
  body_raw = (root / _SOURCE).read_bytes()
  original_recipe = dependencies.recipe_digest
  original_read = Tree.read
  original_import = builtins.__import__
  original_json_loads = json.loads
  def recipe(*args, **kwargs):
    state["recipe"] = True
    try:
      state["recipe_digest"] = original_recipe(*args, **kwargs)
      return state["recipe_digest"]
    finally: state["recipe"] = False
  def read(tree, name, *args, **kwargs):
    if "durable-python-bundle.json" in str(name):
      assert state["recipe"], "Base only permits original recipe raw scan"
      state["raw_body_reads"] += 1
    assert not str(name).startswith("vendor/wheels/")
    return original_read(tree, name, *args, **kwargs)
  def no_optional(name, *args, **kwargs):
    assert not any(part in name for part in ("pi_python_bundle", "zipfile", "durable"))
    return original_import(name, *args, **kwargs)
  def no_body_parse(value, *args, **kwargs):
    assert value != body_raw and value != body_raw.decode(), "Base must not parse the optional body"
    return original_json_loads(value, *args, **kwargs)
  monkeypatch.setattr(dependencies, "recipe_digest", recipe)
  monkeypatch.setattr(Tree, "read", read)
  monkeypatch.setattr(builtins, "__import__", no_optional)
  monkeypatch.setattr(json, "loads", no_body_parse)
  lock = dependencies.PiBackend(profile="pi-base").read_lock(root)
  assert list(lock.pairs) == ["pi-base"] and state["raw_body_reads"] == 1
  assert state["recipe_digest"] == manifest["recipe_digest"]


@pytest.mark.parametrize("fault", ["archive-missing", "archive-size", "archive-sha", "archive-semantics", "body", "ref", "runtime", "license", "unknown", "base-ref"])
def test_reader_rejects_selected_body_archive_or_pair_drift(tmp_path, monkeypatch, fault):
  workspace, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
  root = workspace.repository
  manifest = dependencies.PiBackend(family="modern").resolve_lock(root).metadata
  full = manifest["profile_slices"]["pi-full"]
  source = manifest["sources"]["durable-python-attrs"]
  archive = root / "locks/pi-modern" / source["vendor_path"]
  if fault == "archive-missing": archive.unlink()
  if fault == "archive-size": archive.write_bytes(archive.read_bytes() + b"x")
  if fault == "archive-sha": archive.write_bytes(b"x" * source["size"])
  if fault == "archive-semantics":
    raw = bytearray(archive.read_bytes()); raw[0] ^= 1
    archive.write_bytes(raw)
    source["archive_digest"] = _sha(raw)
    source["vendor_path"] = "vendor/wheels/" + source["archive_digest"] + "/" + source["wheel_filename"]
    new_path = root / "locks/pi-modern" / source["vendor_path"]; new_path.parent.mkdir(parents=True); new_path.write_bytes(raw)
  if fault == "body": (root / _SOURCE).write_bytes(b"broken JSON")
  if fault == "ref": full["python_bundle"]["sha256"] = "b" * 64
  if fault == "runtime": next(row for row in full["runtime_files"] if row["path"] == _PATH)["digest"] = "b" * 64
  if fault == "license": source["license_files"][0] = source["license_files"][0].replace("LICENSE", "OTHER")
  if fault == "unknown": source["resources"] = {}
  if fault == "base-ref": manifest["profile_slices"]["pi-base"]["python_bundle"] = deepcopy(full["python_bundle"])
  _republish(root, manifest)
  with pytest.raises(ConfigError, match="pi-lock-missing-or-stale"):
    dependencies.PiBackend(profile="pi-full").read_lock(root)


def _binding(version="1", *, support=False):
  from test_pi_provider_bindings import fixture
  catalog, providers, selection, lock = fixture()
  selection["profile"] = "pi-full"
  selection["bindings"] = [{"capability_id": "delegate", "provider_id": "delegate-provider"}]
  catalog["capabilities"]["compression"]["required"] = False
  source = _source(version=version)
  identity = "durable-python-attrs"
  catalog["source_profiles"][identity] = ["pi-full"]
  capability = catalog["capabilities"]["delegate"]
  provider = providers["delegate-provider"]
  capability["resource_ids"] = []; provider["resource_ids"] = []
  capability["source_ids"] = [identity] if not support else ["delegate-source", identity]
  lock.metadata["sources"][identity] = source
  row = {"source_id": identity, "source_version": version, "source_identity": capabilities.source_identity(source)}
  if support: provider["support_sources"] = [row]
  else: provider.update(row)
  piece = {"engine": "node", "source_ids": capability["source_ids"], "capability_ids": ["delegate"], "resource_manifest": {}}
  lock.metadata["profile_slices"]["pi-full"] = piece
  bindings = {"schema_version": 1, "catalog": catalog, "providers": providers, "selections": {"pi-full": selection}}
  return bindings, {"pi-full": piece}, lock, row if support else provider


@pytest.mark.parametrize("support", [False, True])
@pytest.mark.parametrize("version", ["1", "1.0", "1.0.0"])
def test_wheel_binding_original_version_widths_and_selection_data(version, support):
  bindings, pieces, lock, _ = _binding(version, support=support)
  capabilities.validate_manifest_bindings(bindings, pieces, sources=lock.metadata["sources"])
  result = capabilities.validate_selection_data(bindings["catalog"], bindings["providers"], bindings["selections"]["pi-full"],
    lock.metadata, lock_identity=lock.identity, host_version="1.0.1", engine="node")
  assert ("durable-python-attrs", version, capabilities.source_identity(lock.metadata["sources"]["durable-python-attrs"])) in result.source_expectations


@pytest.mark.parametrize("support", [False, True])
@pytest.mark.parametrize("fault", ["no-sources", "missing-map", "non-wheel", "null", "drift", "invalid-wheel", "verified-host", "candidate-host"])
def test_short_binding_versions_cannot_widen_nonwheel_or_host_domain(support, fault):
  bindings, pieces, lock, row = _binding("1", support=support)
  sources = lock.metadata["sources"]
  if fault == "no-sources": sources = None
  if fault == "missing-map": sources = {}
  if fault == "non-wheel": sources["durable-python-attrs"] = {"kind": "npm", "version": "1"}
  if fault == "null": row["source_version"] = None
  if fault == "drift": row["source_version"] = "1.0"
  if fault == "invalid-wheel": sources["durable-python-attrs"]["url"] = "https://127.0.0.1/a.whl"
  if fault == "verified-host": bindings["providers"]["delegate-provider"]["verified_host_versions"] = ["1"]
  if fault == "candidate-host": bindings["providers"]["delegate-provider"]["candidate_host_versions"] = ["1.0"]
  with pytest.raises(ConfigError, match="pi-provider-binding"):
    capabilities.validate_manifest_bindings(bindings, pieces, sources=sources)


@pytest.mark.parametrize("fault", ["unknown", "url", "vendor", "float"])
def test_wheel_identity_fixed_context_boundary_and_unchanged_legacy_projection(fault):
  from agentcfg.activity import digest
  source = _source()
  if fault == "unknown": source["resources"] = {}
  if fault == "url": source["url"] = "https://K.example.test/" + source["wheel_filename"]
  if fault == "vendor": source["vendor_path"] = "wrong"
  if fault == "float": source["size"] = 1.0
  try:
    raise RuntimeError("caller-private")
  except RuntimeError:
    with pytest.raises(ConfigError) as caught: capabilities.source_identity(source)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
  npm = {"kind": "npm", "package": "example", "version": "1.0.0", "integrity": "sha512-" + "A" * 86 + "=="}
  assert capabilities.source_identity(npm) == digest({"kind": "npm", "package": "example", "version": "1.0.0", "integrity": npm["integrity"]})


@pytest.mark.parametrize("where", ["direct", "transitive", "transitive-declared", "optional-declared", "peer-declared", "declared-wheel"])
def test_wheel_vendor_not_allowed_in_npm_file_dependencies(where):
  from test_pi_lock_resolution import graph
  package, resolution, piece, manifest = graph(archive=True)
  source = _source()
  manifest["sources"]["durable-python-attrs"] = source
  piece["source_ids"].append("durable-python-attrs")
  if where == "direct":
    package["dependencies"]["synthetic-sdk"] = "file:../" + source["vendor_path"]
    resolution["packages"][""]["dependencies"] = deepcopy(package["dependencies"])
  elif where == "transitive":
    resolution["packages"]["node_modules/synthetic-sdk/node_modules/leaf"]["resolved"] = "file:../" + source["vendor_path"]
  elif where in ("transitive-declared", "optional-declared", "peer-declared"):
    group = {"transitive-declared": "dependencies", "optional-declared": "optionalDependencies", "peer-declared": "peerDependencies"}[where]
    resolution["packages"]["node_modules/synthetic-sdk/node_modules/leaf"][group] = {"worker": "file:../" + source["vendor_path"]}
  else:
    package["dependencies"]["attrs"] = "file:../" + source["vendor_path"]
    resolution["packages"][""]["dependencies"] = deepcopy(package["dependencies"])
  with pytest.raises(ValueError, match="pi-lock-resolution"):
    validate_lock_resolution(package, resolution, piece, manifest)


@pytest.mark.parametrize("kind", ["runtime", "asset"])
@pytest.mark.parametrize("target", ["supervisor/python-bundle", "supervisor/python-bundle/x", "supervisor", "SUPERVISOR/PYTHON-BUNDLE/X"])
def test_ref_reserved_namespace_exact_ancestor_descendant_casefold(kind, target):
  piece = {"runtime_files": runtime_declarations(), "source_ids": [], "python_bundle": {}}
  manifest = {"platforms": ["linux-x86_64"], "sources": {}}
  if kind == "runtime": piece["runtime_files"].append({"source": "synthetic", "path": target})
  else:
    piece["source_ids"] = ["asset"]
    manifest["sources"]["asset"] = {"kind": "asset", "target": target}
  with pytest.raises(ConfigError, match="python-bundle-collision"):
    validate_destinations(piece, manifest)
  del piece["python_bundle"]
  if kind == "runtime" or target.startswith("SUPERVISOR"):
    assert validate_destinations(piece, manifest) is None
  else:
    with pytest.raises(ConfigError, match="asset-collision"): validate_destinations(piece, manifest)


def test_schema_accepts_wheel_and_raw_asset_sources():
  schema = json.loads((_ROOT / "schemas/pi-lock.schema.json").read_bytes())
  standalone = Draft202012Validator(schema["properties"]["sources"]["additionalProperties"])
  assert standalone.is_valid(_source())
  asset = {"kind": "asset", "format": "raw", "platform": "all", "url": "https://example.invalid/a", "target": "data/a",
    "archive_digest": "a" * 64, "size": 1, "license_files": []}
  assert standalone.is_valid(asset)


@pytest.mark.parametrize("fault", ["wheel", "ref", "provider-short"])
def test_legacy_v1_rejects_new_shapes(tmp_path, fault):
  root, manifest = fixture_repository(tmp_path)
  if fault == "wheel": manifest["sources"]["durable-python-attrs"] = _source(version="1")
  if fault == "ref": manifest["profile_slices"]["pi-fixture"]["python_bundle"] = {"schema_version": 1, "source": _SOURCE, "path": _PATH, "sha256": "a" * 64, "size": 1}
  if fault == "provider-short":
    bindings, _, _, _ = _binding("1")
    manifest["capability_bindings"] = bindings
  manifest["identity"] = dependencies.digest({key: value for key, value in manifest.items() if key != "identity"})
  with pytest.raises(ValueError, match="pi-lock-header"): validate_lock_header(manifest, schema_version=1)


def test_no_ref_old_generation_and_read_does_not_import_bundle(tmp_path, monkeypatch):
  workspace, _, _, _ = generator_fixture(tmp_path, monkeypatch)
  original = builtins.__import__
  calls = []
  def guarded(name, *args, **kwargs):
    if "pi_python_bundle" in name or "zipfile" in name:
      calls.append(name)
      raise AssertionError("no-ref bundle import")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  lock = dependencies.PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert set(lock.pairs) == {"pi-base"} and calls == []


def test_new_source_module_and_optional_body_remain_in_original_recipe_domain(tmp_path, monkeypatch):
  workspace, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
  root = workspace.repository
  dependencies.PiBackend(family="modern").resolve_lock(root)
  before = dependencies.recipe_digest(root, family="modern")
  copied = root / "src/agentcfg/pi_wheel_sources.py"
  copied.write_bytes(copied.read_bytes() + b"\n# synthetic recipe drift\n")
  assert dependencies.recipe_digest(root, family="modern") != before
  copied.write_bytes(copied.read_bytes().removesuffix(b"\n# synthetic recipe drift\n"))
  assert dependencies.recipe_digest(root, family="modern") == before
  body = root / _SOURCE; body.write_bytes(body.read_bytes() + b" ")
  assert dependencies.recipe_digest(root, family="modern") != before
  with pytest.raises(ConfigError, match="pi-lock-missing-or-stale"):
    dependencies.PiBackend(profile="pi-base").read_lock(root)


@pytest.mark.parametrize("location", ["package-optional", "package-peer", "root-optional", "root-peer"])
def test_root_file_reference_wheel_archive_rejected(location):
  from test_pi_lock_resolution import graph
  package, resolution, piece, manifest = graph(archive=True)
  source = _source()
  manifest["sources"]["durable-python-attrs"] = source
  piece["source_ids"].append("durable-python-attrs")
  record = package if location.startswith("package-") else resolution["packages"][""]
  group = "optionalDependencies" if location.endswith("optional") else "peerDependencies"
  record[group] = {"attrs": "file:../" + source["vendor_path"]}
  with pytest.raises(ValueError, match="pi-lock-resolution") as caught:
    validate_lock_resolution(package, resolution, piece, manifest)
  assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("kind", ["npm", "local", "git"])
@pytest.mark.parametrize("location", ["package-optional", "package-peer", "root-optional", "root-peer"])
def test_root_file_reference_original_locked_archive_controls(version, kind, location):
  from test_pi_lock_resolution import graph
  package, resolution, piece, manifest = graph(version=version, archive=kind != "npm")
  # npm 宿主维持原 registry 身份；file 引用的合法目标仍是锁内 local/git 档案。
  archive_source = manifest["sources"]["sdk"] if kind != "npm" else {
    "kind": "local", "package": "original-local-control", "version": "1.0.0", "vendor_path": "vendor/sdk.tgz"}
  archive_source.update(source_path="packages/original-control", source_tree_digest="b" * 64,
    archive_digest="a" * 64, license_files=[])
  if kind == "git": archive_source.update(kind="git", commit="c" * 40)
  if kind == "npm": manifest["sources"]["original-local-control"] = archive_source
  assert len(capabilities.source_identity(archive_source)) == 64
  record = package if location.startswith("package-") else resolution["packages"][""]
  group = "optionalDependencies" if location.endswith("optional") else "peerDependencies"
  record[group] = {"synthetic-sdk": "file:../" + archive_source["vendor_path"]}
  before = deepcopy((package, resolution, piece, manifest))
  assert validate_lock_resolution(package, resolution, piece, manifest) is None
  assert (package, resolution, piece, manifest) == before


def _b2_sync_fixture(tmp_path, monkeypatch, *, legacy_kind=None):
  workspace, inputs, path, _, declaration, archives = _fixture(tmp_path, monkeypatch)
  root = workspace.repository
  for selection in inputs["capability_bindings"]["selections"].values(): selection["state"] = "current"
  _write_inputs(path, inputs)
  # B1 生成器只构建 candidate；先按原入口生成，再把合成 fixture 的 current 数据重锁。
  for selection in inputs["capability_bindings"]["selections"].values(): selection["state"] = "candidate"
  _write_inputs(path, inputs)
  manifest = dependencies.PiBackend(family="modern").resolve_lock(root).metadata
  for selection in manifest["capability_bindings"]["selections"].values(): selection["state"] = "current"
  full = manifest["profile_slices"]["pi-full"]
  if legacy_kind is not None:
    source_path = "packages/legacy-control"
    directory = root / source_path; directory.mkdir(parents=True)
    (directory / "package.json").write_bytes(b'{"name":"synthetic-legacy","version":"1.0.0"}')
    (directory / "LICENSE").write_bytes(b"Synthetic original legacy license\n")
    recipe = {"kind": legacy_kind, "source_path": source_path, "package": "synthetic-legacy", "version": "1.0.0", "license_files": ["LICENSE"], "exclude": []}
    if legacy_kind == "git": recipe["commit"] = "a" * 40
    archive, source = vendor.build_archive(root, recipe)
    source["vendor_path"] = "vendor/legacy-control.tgz"
    (root / "locks/pi-modern" / source["vendor_path"]).write_bytes(archive)
    manifest["sources"]["legacy-control"] = source
    full["source_ids"].append("legacy-control")
    bindings = manifest["capability_bindings"]
    capability = deepcopy(bindings["catalog"]["capabilities"]["durable"])
    capability.update(owner_domain="legacy-control", source_ids=["legacy-control"])
    bindings["catalog"]["capabilities"]["legacy-control"] = capability
    bindings["catalog"]["source_profiles"]["legacy-control"] = ["pi-full"]
    provider = deepcopy(bindings["providers"]["native-provider"])
    provider.update(provider_id="legacy-control-provider", capability_id="legacy-control", source_id="legacy-control", source_version="1.0.0",
      source_identity=capabilities.source_identity(source), resource_ids=[], public_entrypoints=["legacy/control"])
    bindings["providers"]["legacy-control-provider"] = provider
    bindings["selections"]["pi-full"]["bindings"].append({"capability_id": "legacy-control", "provider_id": "legacy-control-provider"})
    full["capability_ids"].append("legacy-control")
    package_path = root / "locks/pi-modern" / full["package_path"]
    lock_path = root / "locks/pi-modern" / full["lock_path"]
    package = json.loads(package_path.read_bytes()); resolution = json.loads(lock_path.read_bytes())
    package["dependencies"]["synthetic-legacy"] = "file:../" + source["vendor_path"]
    resolution["packages"][""]["dependencies"] = deepcopy(package["dependencies"])
    resolution["packages"]["node_modules/synthetic-legacy"] = {"version": "1.0.0", "resolved": package["dependencies"]["synthetic-legacy"],
      "integrity": manifest["sources"]["pi-host"]["integrity"]}
    package_path.write_bytes(payload(package)); lock_path.write_bytes(payload(resolution))
    full["package_json_digest"] = dependencies.digest(payload(package)); full["package_lock_digest"] = dependencies.digest(payload(resolution))
  _republish(root, manifest)
  lock = dependencies.PiBackend(profile="pi-full").read_lock(root)
  workspace.profile = "pi-full"
  from test_pi_dependencies import fake_installer
  process_calls = []
  installer = fake_installer(process_calls)
  def checked(argv, *, cwd, env):
    result = installer(argv, cwd=cwd, env=env)
    if argv[:2] == ["npm", "ci"]:
      (cwd / "node_modules/synthetic-host/extension.js").write_bytes(b"// synthetic inert extension\n")
      if legacy_kind is not None:
        package = cwd / "node_modules/synthetic-legacy"; package.mkdir()
        (package / "package.json").write_bytes(b'{"name":"synthetic-legacy","version":"1.0.0"}')
        (package / "LICENSE").write_bytes(b"Synthetic original legacy license\n")
    return result
  monkeypatch.setattr(dependencies, "checked", checked)
  return workspace, lock, declaration, archives, process_calls


def test_b2_original_sync_producers_hook_real_seal_and_later_readback(tmp_path, monkeypatch):
  workspace, lock, declaration, archives, calls = _b2_sync_fixture(tmp_path, monkeypatch)
  from agentcfg import pi_native_build, pi_python_bundle_runtime, pi_runtime_packages
  original_helpers = pi_native_build.install_platform_helpers
  original_install = pi_python_bundle_runtime.install_locked_python_bundle_stage
  original_seal = pi_runtime_packages.seal
  events = []
  def producer(repository, stage, platform):
    events.append("producer")
    assert (stage / "install-home").is_dir()
    return original_helpers(repository, stage, platform)
  def hook(stage, piece, sources):
    events.append("hook")
    assert not (stage / "install-home").exists()
    assert Path(piece["package_path"]).parent != Path(".")
    for row in declaration["wheels"]:
      source = sources[row["source_id"]]
      assert (stage / source["vendor_path"]).read_bytes() == archives[row["source_id"]]
      assert not (stage / Path(piece["package_path"]).parent / source["vendor_path"]).exists()
    return original_install(stage, piece, sources)
  def seal(*args, **kwargs):
    events.append("seal")
    return original_seal(*args, **kwargs)
  monkeypatch.setattr(pi_native_build, "install_platform_helpers", producer)
  monkeypatch.setattr(pi_python_bundle_runtime, "install_locked_python_bundle_stage", hook)
  monkeypatch.setattr(pi_runtime_packages, "seal", seal)
  overlays = []
  original_license = vendor.install_source_licenses
  def license_call(source, target, prefix, record):
    overlays.append(record["kind"])
    return original_license(source, target, prefix, record)
  monkeypatch.setattr(vendor, "install_source_licenses", license_call)
  backend = dependencies.PiBackend(profile="pi-full")
  result = backend._sync(workspace, lock)
  root = backend.root(workspace, result["identity"])
  assert result["installed"] and events == ["producer", "hook", "seal"]
  assert len(calls) == 3 and overlays == []
  assert backend.status(workspace, result["identity"]) == "installed"
  piece = lock.metadata["profile_slices"]["pi-full"]
  assert pi_runtime_packages.validate_installed(root, piece) is None
  inventory = json.loads((root / ".agentcfg-receipt.json").read_bytes())["files"]
  assert "supervisor/python-bundle/inventory.json" in inventory
  assert all("supervisor/python-bundle/site-packages/" + member["path"] in inventory for row in declaration["wheels"] for member in row["members"])
  target = root / "supervisor/python-bundle/site-packages/attr/__init__.py"
  target.write_bytes(b"drift after original seal")
  assert backend.status(workspace, result["identity"]) == "damaged"
  from agentcfg.storage import Conflict
  with pytest.raises(Conflict): pi_runtime_packages.validate_installed(root, piece)


@pytest.mark.parametrize("fault", ["missing-member", "hash-drift", "extra-empty", "prefix-blocker", "hook-no-output"])
def test_b2_sync_ref_without_precise_physical_bundle_cannot_seal_or_publish(tmp_path, monkeypatch, fault):
  workspace, lock, _, _, _ = _b2_sync_fixture(tmp_path, monkeypatch)
  from agentcfg import pi_python_bundle_runtime, pi_runtime_packages
  original = pi_python_bundle_runtime.install_locked_python_bundle_stage
  original_seal = pi_runtime_packages.seal
  sealed = []
  def hook(stage, piece, sources):
    prefix = stage / "supervisor/python-bundle"
    if fault == "prefix-blocker": prefix.mkdir(mode=0o700)
    if fault == "hook-no-output": return None
    original(stage, piece, sources)
    if fault == "missing-member": (prefix / "site-packages/attr/__init__.py").unlink()
    if fault == "hash-drift": (prefix / "site-packages/attr/__init__.py").write_bytes(b"stage drift")
    if fault == "extra-empty": (prefix / "extra").mkdir(mode=0o700)
  def seal(*args, **kwargs):
    sealed.append(True)
    return original_seal(*args, **kwargs)
  monkeypatch.setattr(pi_python_bundle_runtime, "install_locked_python_bundle_stage", hook)
  monkeypatch.setattr(pi_runtime_packages, "seal", seal)
  backend = dependencies.PiBackend(profile="pi-full")
  identity = backend.runtime_identity(workspace, lock)
  with pytest.raises(DependencyError): backend._sync(workspace, lock)
  assert sealed == [] and not backend.root(workspace, identity).exists()
  assert not any(workspace.instance.rglob(".agentcfg-ready"))


@pytest.mark.parametrize("kind", ["local", "git"])
def test_b2_modern_license_loop_keeps_local_git_and_never_wheel_overlay(tmp_path, monkeypatch, kind):
  workspace, lock, _, _, _ = _b2_sync_fixture(tmp_path, monkeypatch, legacy_kind=kind)
  original = vendor.install_source_licenses
  calls = []
  def observed(source, target, prefix, record):
    calls.append(record["kind"])
    assert record["kind"] == kind
    return original(source, target, prefix, record)
  monkeypatch.setattr(vendor, "install_source_licenses", observed)
  result = dependencies.PiBackend(profile="pi-full")._sync(workspace, lock)
  assert result["installed"] and calls == [kind]


def test_b2_candidate_ref_retains_original_candidate_denial(tmp_path, monkeypatch):
  workspace, _, _, _, _, _ = _fixture(tmp_path, monkeypatch)
  lock = dependencies.PiBackend(family="modern").resolve_lock(workspace.repository)
  workspace.profile = "pi-full"
  calls = []
  monkeypatch.setattr(dependencies, "checked", lambda *a, **k: calls.append(a))
  with pytest.raises(DependencyError, match="候选能力选择"):
    dependencies.PiBackend(profile="pi-full")._sync(workspace, lock)
  assert calls == []


def _b2_receipt_document(*, version=2, profile="pi-full", reference=True):
  piece = {"engine": "node", "source_ids": ["pi-host"], "package_path": "pi-full/package.json", "lock_path": "pi-full/package-lock.json",
    "package_json_digest": "a" * 64, "package_lock_digest": "b" * 64, "entrypoint": "pi-full/node_modules/synthetic-host/index.js",
    "resource_manifest": {kind: [] for kind in ("extensions", "skills", "prompts", "themes")}, "resource_manifest_digest": "c" * 64,
    "capability_ids": ["native"], "identity": "d" * 64}
  if version == 2:
    piece.update(ai_package="synthetic-ai", runtime_files=[{"source": "scripts/pi-supervisor.py", "path": "supervisor/scripts/pi-supervisor.py",
      "transform": "copy", "input_digest": "a" * 64, "digest": "a" * 64, "mode": 384}])
  if reference: piece["python_bundle"] = {"schema_version": 1, "source": _SOURCE, "path": _PATH, "sha256": "e" * 64, "size": 1}
  receipt = {"schema_version": version, "status": "installed", "identity": "f" * 64, "lock_identity": "a" * 64,
    "slice_identity": piece["identity"], "slice": piece, "files": {}, "platform": "linux-x86_64",
    "toolchains": {"node": "v24.14.0", "npm": "11.19.1", "bun": "1.4.0"}, "toolchain_identity": "b" * 64}
  if version == 2:
    receipt["binding_identity"] = {**{key: "a" * 64 for key in ("selection", "catalog", "bindings", "lock", "slice", "binding_context", "runtime")},
      "profile": profile, "adapter_version": "pi-1", "platform": "linux-x86_64"}
  return receipt


def _b2_receipt_validator():
  return Draft202012Validator(json.loads((_ROOT / "agents/pi/schemas/runtime-receipt.schema.json").read_bytes()))


def test_b2_receipt_schema_accepts_only_full_v2_ref_and_preserves_old_noref_shapes():
  validator = _b2_receipt_validator()
  assert validator.is_valid(_b2_receipt_document())
  assert not validator.is_valid(_b2_receipt_document(version=1))
  assert not validator.is_valid(_b2_receipt_document(profile="pi-base"))
  for version, profile in ((1, "pi-full"), (2, "pi-base"), (2, "pi-full")):
    assert validator.is_valid(_b2_receipt_document(version=version, profile=profile, reference=False))


@pytest.mark.parametrize("key", ["schema_version", "source", "path", "sha256", "size"])
def test_b2_receipt_schema_missing_reference_fields_reject(key):
  receipt = _b2_receipt_document(); del receipt["slice"]["python_bundle"][key]
  assert not _b2_receipt_validator().is_valid(receipt)


@pytest.mark.parametrize("key,value", [("schema_version", True), ("schema_version", 1.5), ("schema_version", 2),
  ("source", "overlay.json"), ("path", "../runtime/durable-python-bundle.json"), ("sha256", "A" * 64),
  ("sha256", "a" * 63), ("size", True), ("size", 1.5), ("size", 0), ("size", 8388609), ("unknown", None)])
def test_b2_receipt_schema_bad_reference_shape_reject(key, value):
  receipt = _b2_receipt_document(); receipt["slice"]["python_bundle"][key] = value
  assert not _b2_receipt_validator().is_valid(receipt)


def test_b2_receipt_schema_null_reference_reject():
  receipt = _b2_receipt_document(); receipt["slice"]["python_bundle"] = None
  assert not _b2_receipt_validator().is_valid(receipt)


@pytest.mark.parametrize("field", ["schema_version", "size"])
def test_b2_receipt_json_integer_shape_vs_native_float_before_any_fd(field, tmp_path, monkeypatch):
  receipt = _b2_receipt_document(); reference = receipt["slice"]["python_bundle"]; reference[field] = float(reference[field])
  assert _b2_receipt_validator().is_valid(receipt)
  from agentcfg import pi_python_bundle_runtime
  io = []
  def opened(*args, **kwargs): io.append(True); raise AssertionError("FD before native float rejection")
  monkeypatch.setattr(pi_python_bundle_runtime.os, "open", opened)
  with pytest.raises(ValueError, match="pi-python-bundle-runtime") as caught:
    pi_python_bundle_runtime.validate_installed_python_bundle(tmp_path, reference)
  assert caught.value.__cause__ is None and caught.value.__context__ is None and io == []


def test_b2_receipt_schema_uses_same_b1_reference():
  schema = json.loads((_ROOT / "agents/pi/schemas/runtime-receipt.schema.json").read_bytes())
  lock_schema = json.loads((_ROOT / "schemas/pi-lock.schema.json").read_bytes())
  assert schema["properties"]["slice"]["properties"]["python_bundle"] == lock_schema["properties"]["profile_slices"]["additionalProperties"]["properties"]["python_bundle"]
