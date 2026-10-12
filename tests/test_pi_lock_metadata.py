"""完整锁数据新入口与原 IO 切点；仅固定自有 schema 和临时合成材料。"""

import ast
import base64
import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from agentcfg import pi_lock_metadata as metadata
from agentcfg import pi_dependencies as dependencies
from agentcfg.schema import ConfigError
from agentcfg.storage import Tree
from test_pi_dependencies import fixture_repository, payload
from test_pi_capability_manifest import binding_repository, _write_manifest


_ROOT = Path(__file__).resolve().parents[1]
_MODULE = Path(metadata.__file__).read_text()
_FOREIGN_CALLS = []


@pytest.fixture(autouse=True)
def callback_sentinel():
  _FOREIGN_CALLS.clear()
  yield
  assert _FOREIGN_CALLS == []


def _sha(raw):
  return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path, version=1):
  if version == 1:
    root, manifest = fixture_repository(tmp_path)
    lock = dependencies.PiBackend(profile="pi-fixture").read_lock(root)
  else:
    workspace, manifest = binding_repository(tmp_path); root = workspace.repository
    lock = dependencies.PiBackend(family="modern").read_lock(root)
  inputs = {name: {"package_json": pair[0], "package_lock_json": pair[1]} for name, pair in lock.pairs.items()}
  return root, manifest, inputs


def _rehash(manifest):
  for piece in manifest["profile_slices"].values():
    piece["identity"] = dependencies.digest({key: value for key, value in piece.items() if key != "identity"})
  manifest["identity"] = dependencies.digest({key: value for key, value in manifest.items() if key != "identity"})


def _call(manifest, inputs, **kwargs):
  return metadata.capture_pi_lock_metadata_data(manifest, inputs, schema_version=manifest["schema_version"], **kwargs)


def _reject(function, *args, **kwargs):
  with pytest.raises(ValueError) as caught: function(*args, **kwargs)
  assert type(caught.value) is ValueError and str(caught.value) == "pi-lock-metadata"
  assert caught.value.__cause__ is None and caught.value.__context__ is None


def _no_helpers(monkeypatch):
  original = builtins.__import__; calls = []
  def guarded(name, *args, **kwargs):
    if name.startswith("pi_") or name.startswith("agentcfg"):
      calls.append(name); raise AssertionError("helper before complete capture")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", guarded)
  return calls


@pytest.mark.parametrize("version", [1, 2])
def test_original_legal_metadata_pairs_detached_two_keys_and_finite_float_npm(version, tmp_path):
  _, manifest, inputs = _fixture(tmp_path, version)
  name = next(iter(inputs)); piece = manifest["profile_slices"][name]
  package = json.loads(inputs[name]["package_json"]); lock = json.loads(inputs[name]["package_lock_json"])
  package["data_number"] = 1.5
  lock["lockfileVersion"] = 3.0
  raw_package = json.dumps(package, indent=2).encode(); raw_lock = json.dumps(lock, indent=2).encode()
  inputs[name].update(package_json=raw_package, package_lock_json=raw_lock)
  piece.update(package_json_digest=_sha(raw_package), package_lock_digest=_sha(raw_lock)); _rehash(manifest)
  before = deepcopy((manifest, inputs)); result = _call(manifest, inputs)
  assert set(result) == {"metadata", "profile_inputs"} and result["metadata"] == manifest and result["profile_inputs"] == inputs
  assert result["profile_inputs"][name]["package_json"] is raw_package
  assert type(json.loads(result["profile_inputs"][name]["package_lock_json"])["lockfileVersion"]) is float
  result["metadata"]["sources"].clear(); result["profile_inputs"][name]["package_json"] = b"changed"
  assert (manifest, inputs) == before and _call(manifest, inputs)["metadata"] == manifest


def test_full_wheel_body_data_pairing_without_archive_or_zip_reads(tmp_path, monkeypatch):
  from test_pi_wheel_lock_integration import _fixture as wheel_fixture
  workspace, _, _, _, _, _ = wheel_fixture(tmp_path, monkeypatch)
  lock = dependencies.PiBackend(family="modern").resolve_lock(workspace.repository)
  manifest = lock.metadata
  inputs = {name: {"package_json": pair[0], "package_lock_json": pair[1]} for name, pair in lock.pairs.items()}
  inputs["pi-full"]["python_bundle_json"] = (workspace.repository / manifest["profile_slices"]["pi-full"]["python_bundle"]["source"]).read_bytes()
  with monkeypatch.context() as guard:
    def forbidden(*args, **kwargs): pytest.fail("metadata must not use Tree/archive/ZIP IO")
    guard.setattr(Tree, "__init__", forbidden)
    original = builtins.__import__
    imports = []
    def no_zip(name, *args, **kwargs):
      if "zipfile" in name or "pi_python_bundle_stage" in name: imports.append(name); raise AssertionError("no archive stage")
      return original(name, *args, **kwargs)
    guard.setattr(builtins, "__import__", no_zip)
    assert _call(manifest, inputs)["profile_inputs"] == inputs and imports == []
    missing = deepcopy(inputs); del missing["pi-full"]["python_bundle_json"]
    _reject(_call, manifest, missing)
    bad = deepcopy(inputs); bad["pi-full"]["python_bundle_json"] = b"{}"
    _reject(_call, manifest, bad)
    extra = deepcopy(inputs); extra["pi-base"]["python_bundle_json"] = inputs["pi-full"]["python_bundle_json"]
    _reject(_call, manifest, extra)


def test_unselected_source_slice_resource_and_build_rules_still_checked(tmp_path):
  _, original, inputs = _fixture(tmp_path, 2)
  inputs = {"pi-base": inputs["pi-base"]}
  for fault in ("source-version", "source-commit", "slice-source", "resource-capability", "slice-identity", "build-source", "build-path"):
    manifest = deepcopy(original)
    if fault == "source-version": manifest["sources"]["full-feature"]["version"] = "short"
    if fault == "source-commit": manifest["sources"]["full-feature"]["kind"] = "git"; manifest["sources"]["full-feature"]["commit"] = "bad"
    if fault == "slice-source": manifest["profile_slices"]["pi-full"]["source_ids"].append("absent")
    if fault == "resource-capability": manifest["profile_slices"]["pi-full"]["resource_manifest"]["skills"] = [{"id": "bad", "capability_id": "absent", "path": "pi-full/node_modules/fake/skill"}]
    if fault.startswith("build"):
      manifest["build_steps"] = [{"id": "fixture", "source_ids": ["absent" if fault == "build-source" else "pi-host"], "platform": "all",
        "argv": ["node", "fixture.js"], "cwd": "pi-full", "input_digests": {}, "expected_outputs": ["../bad" if fault == "build-path" else "out"],
        "output_digests": {"../bad" if fault == "build-path" else "out": "a" * 64}}]
    _rehash(manifest)
    if fault == "slice-identity": manifest["profile_slices"]["pi-full"]["identity"] = "b" * 64; manifest["identity"] = dependencies.digest({k: v for k, v in manifest.items() if k != "identity"})
    _reject(_call, manifest, inputs)


@pytest.mark.parametrize("raw", [b"", b"{", b"\xff", b'{"x":1,"x":2}', b'{"x":{"y":1,"y":2}}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e400}',
  b'{"x":9223372036854775808}', b'{"x":"\\ud800"}', b'{"x":"' + b"a" * 4097 + b'"}', b"[" * 18 + b"0" + b"]" * 18])
def test_raw_pair_strict_json_and_decoded_graph_limits(raw, tmp_path):
  _, manifest, inputs = _fixture(tmp_path); name = next(iter(inputs))
  inputs[name]["package_lock_json"] = raw; manifest["profile_slices"][name]["package_lock_digest"] = _sha(raw); _rehash(manifest)
  _reject(_call, manifest, inputs)


@pytest.mark.parametrize("fault", ["hash", "graph", "extra-profile", "missing-package", "extra-blob", "unknown-field", "host", "accepted-unknown", "accepted-proof"])
def test_selected_pair_records_profiles_host_and_accepted_map(fault, tmp_path):
  _, manifest, inputs = _fixture(tmp_path, 2); accepted = None
  if fault == "hash": inputs["pi-base"]["package_json"] = b"{}"
  if fault == "graph":
    raw = b'{"lockfileVersion":3,"packages":{"":{}}}'; inputs["pi-base"]["package_lock_json"] = raw
    manifest["profile_slices"]["pi-base"]["package_lock_digest"] = _sha(raw); _rehash(manifest)
  if fault == "extra-profile": inputs["unknown"] = inputs["pi-base"]
  if fault == "missing-package": del inputs["pi-base"]["package_json"]
  if fault == "extra-blob": inputs["pi-base"]["python_bundle_json"] = b"{}"
  if fault == "unknown-field": inputs["pi-base"]["path"] = "overlay"
  if fault == "host": manifest["profile_slices"]["pi-base"]["source_ids"] = []; _rehash(manifest)
  if fault == "accepted-unknown": accepted = {"unknown": "a" * 64}
  if fault == "accepted-proof": manifest["capability_bindings"]["selections"]["pi-base"]["state"] = "accepted"; accepted = {"pi-base": "a" * 64}; _rehash(manifest)
  _reject(_call, manifest, inputs, accepted_binding_digests=accepted)


def test_valid_selected_accepted_digest_is_only_input_data(tmp_path):
  from agentcfg.pi_capabilities import validate_selection_data
  _, manifest, inputs = _fixture(tmp_path, 2)
  manifest["capability_bindings"]["selections"]["pi-base"]["state"] = "accepted"; _rehash(manifest)
  bindings = manifest["capability_bindings"]; piece = manifest["profile_slices"]["pi-base"]
  context = validate_selection_data(bindings["catalog"], bindings["providers"], {**bindings["selections"]["pi-base"], "state": "candidate"}, manifest,
    lock_identity=manifest["identity"], host_version=manifest["sources"]["pi-host"]["version"], engine=piece["engine"]).acceptance_context_digest
  # accepted 上下文包括状态，使用原完整data resolver所给的exact原态结果计算，不生成权限。
  from agentcfg.pi_capabilities import _resolve_selection_data
  context = _resolve_selection_data(bindings["catalog"], bindings["providers"], bindings["selections"]["pi-base"], manifest,
    lock_identity=manifest["identity"], host_version=manifest["sources"]["pi-host"]["version"], engine=piece["engine"]).acceptance_context_digest
  result = _call(manifest, {"pi-base": inputs["pi-base"]}, accepted_binding_digests={"pi-base": context})
  assert set(result) == {"metadata", "profile_inputs"} and result["metadata"]["capability_bindings"]["selections"]["pi-base"]["state"] == "accepted"


class _Foreign:
  def __getattribute__(self, name): _FOREIGN_CALLS.append("attribute"); raise AssertionError("foreign callback")
  def __repr__(self): _FOREIGN_CALLS.append("repr"); raise AssertionError("foreign callback")
  def __bool__(self): _FOREIGN_CALLS.append("bool"); raise AssertionError("foreign callback")
  def __deepcopy__(self, memo): _FOREIGN_CALLS.append("deepcopy"); raise AssertionError("foreign callback")


class _ForeignKey(str):
  __hash__ = str.__hash__
  def __eq__(self, other): _FOREIGN_CALLS.append("eq"); raise AssertionError("foreign key compare")


@pytest.mark.parametrize("fault", ["manifest", "map", "manifest-unused", "accepted", "accepted-leaf", "record", "raw", "key", "version", "cycle", "depth", "nodes", "string", "utf8", "integer", "nan", "infinity", "aggregate-utf8", "alias-nodes", "alias-depth", "blob-cap", "blob-total", "profiles", "record-alias-total"])
def test_complete_capture_before_any_helper_import_or_schema_read(fault, tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path); version, accepted = 1, None; key = next(iter(inputs))
  if fault == "manifest": manifest = _Foreign()
  if fault == "map": inputs = _Foreign()
  if fault == "manifest-unused": manifest["foreign"] = _Foreign()
  if fault == "accepted": accepted = _Foreign()
  if fault == "accepted-leaf": accepted = {key: _Foreign()}
  if fault == "record": inputs[key] = _Foreign()
  if fault == "raw": inputs[key]["package_json"] = bytearray(b"{}")
  if fault == "key": inputs = {_ForeignKey(key): inputs[key]}
  if fault == "version": version = True
  if fault == "cycle": manifest["cycle"] = manifest
  if fault == "depth":
    child = None
    for _ in range(18): child = [child]
    manifest["deep"] = child
  if fault == "nodes": manifest["huge"] = [None] * 100001
  if fault == "string": manifest["huge"] = "x" * 4097
  if fault == "utf8": manifest["huge"] = "\ud800"
  if fault == "integer": manifest["huge"] = 2 ** 63
  if fault == "nan": manifest["huge"] = float("nan")
  if fault == "infinity": manifest["huge"] = float("inf")
  if fault == "aggregate-utf8": manifest["huge"] = ["é" * 4096] * 1024
  if fault == "alias-nodes":
    child = 0
    for _ in range(14): child = [child, child]
    manifest["huge"] = [child] * 7
  if fault == "alias-depth":
    child = [1]
    deep = child
    for _ in range(15): deep = [deep]
    manifest["first"] = child; manifest["deep"] = deep
  if fault == "blob-cap": inputs[key]["package_json"] = b"x" * 1048577
  if fault == "blob-total": inputs = {"p" + str(i): {"package_json": b"x" * 1048576, "package_lock_json": b"x" * 1048576} for i in range(9)}
  if fault == "profiles": inputs = {"p" + str(i): inputs[key] for i in range(65)}
  if fault == "record-alias-total": inputs = {"p" + str(i): {"package_json": b"{}", "package_lock_json": b"{}", "python_bundle_json": b"x" * 8388608} for i in range(3)}; shared = next(iter(inputs.values())); inputs = {name: shared for name in inputs}
  calls = _no_helpers(monkeypatch)
  _reject(metadata.capture_pi_lock_metadata_data, manifest, inputs, schema_version=version, accepted_binding_digests=accepted)
  assert calls == [] and _FOREIGN_CALLS == []


@pytest.mark.parametrize("kind", [dict, list, str, int, float, bytes])
def test_subclasses_reject_without_method_calls(kind, tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  class Foreign(kind):
    def __len__(self): _FOREIGN_CALLS.append("len"); raise AssertionError("callback")
    def items(self): _FOREIGN_CALLS.append("items"); raise AssertionError("callback")
    def __iter__(self): _FOREIGN_CALLS.append("iter"); raise AssertionError("callback")
    def encode(self, *args): _FOREIGN_CALLS.append("encode"); raise AssertionError("callback")
  if kind is dict: manifest = Foreign(manifest)
  if kind is list: manifest["platforms"] = Foreign(manifest["platforms"])
  if kind is str: manifest["adapter_version"] = Foreign("pi-1")
  if kind is int: manifest["schema_version"] = Foreign(1)
  if kind is float: manifest["unknown"] = Foreign(1.0)
  if kind is bytes: inputs[next(iter(inputs))]["package_json"] = Foreign(b"{}")
  calls = _no_helpers(monkeypatch)
  _reject(metadata.capture_pi_lock_metadata_data, manifest, inputs, schema_version=1)
  assert calls == [] and _FOREIGN_CALLS == []


def test_owned_capture_survives_late_caller_mutation_and_alias_is_first_capture(tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  original = metadata._pairs; pairs_calls = []
  source = manifest["sources"]["host"]
  manifest["sources"]["unused-alias"] = source; _rehash(manifest)
  def after_pairs(value, cap, **kwargs):
    pairs = original(value, cap, **kwargs)
    if value is source:
      pairs_calls.append(True); source.clear(); source[_ForeignKey("kind")] = "npm"
    if value is inputs:
      inputs[_ForeignKey("late-key")] = _Foreign()
    return pairs
  monkeypatch.setattr(metadata, "_pairs", after_pairs)
  result = _call(manifest, inputs)
  assert pairs_calls == [True] and _FOREIGN_CALLS == []
  assert result["metadata"]["sources"]["host"] is result["metadata"]["sources"]["unused-alias"]
  assert result["metadata"]["sources"]["host"]["kind"] == "npm"


@pytest.mark.parametrize("control", ["keyboard", "exit", "generator", "base"])
def test_control_original_object_after_capture(control, tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  from agentcfg import pi_lock_header
  error = {"keyboard": KeyboardInterrupt(), "exit": SystemExit(4), "generator": GeneratorExit(), "base": BaseException()}[control]
  def raise_control(*args, **kwargs): raise error
  monkeypatch.setattr(pi_lock_header, "validate_lock_header", raise_control)
  with pytest.raises(BaseException) as caught: _call(manifest, inputs)
  assert caught.value is error


def test_fixed_error_cleans_ambient_context_without_mutating_original(tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  from agentcfg import pi_lock_header
  dependency_error = RuntimeError("dependency private"); dependency_cause = RuntimeError("cause private"); dependency_error.__cause__ = dependency_cause
  def raising(*args, **kwargs): raise dependency_error
  monkeypatch.setattr(pi_lock_header, "validate_lock_header", raising)
  caller = RuntimeError("caller private"); cause = RuntimeError("caller cause"); caller.__cause__ = cause
  try: raise caller
  except RuntimeError: _reject(_call, manifest, inputs)
  assert caller.__cause__ is cause and dependency_error.__cause__ is dependency_cause


def test_new_graph_caps_not_imposed_on_original_read_lock_legal_domain(tmp_path):
  root, manifest, inputs = _fixture(tmp_path)
  manifest["sources"]["unselected-local"] = {"kind": "local", "package": "original-local", "version": "1.0.0", "source_path": "x" * 5000,
    "source_tree_digest": "a" * 64, "vendor_path": "vendor/unselected.tgz", "archive_digest": "b" * 64, "license_files": []}
  package = json.loads(inputs["pi-fixture"]["package_json"]); package["extra_integer"] = 2 ** 70
  package_raw = payload(package); piece = manifest["profile_slices"]["pi-fixture"]; piece["package_json_digest"] = _sha(package_raw)
  (root / "locks/pi" / piece["package_path"]).write_bytes(package_raw); inputs["pi-fixture"]["package_json"] = package_raw; _rehash(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  assert dependencies.PiBackend(profile="pi-fixture").read_lock(root).metadata == manifest
  _reject(_call, manifest, inputs)
  del manifest["sources"]["unselected-local"]; _rehash(manifest); (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  assert dependencies.PiBackend(profile="pi-fixture").read_lock(root).pairs["pi-fixture"][0] == package_raw
  _reject(_call, manifest, inputs)


def test_old_io_cuts_and_suffix_runtime_pair_license_order_real_helpers(tmp_path, monkeypatch):
  workspace, _ = binding_repository(tmp_path); events = []
  from agentcfg import pi_capabilities, pi_runtime_files, pi_license_bundle
  original_read = Tree.read
  def read(tree, name, *args, **kwargs):
    if name == "vendor/full.tgz": events.append("archive:local")
    if name in ("pi-full/package.json", "pi-full/package-lock.json"): events.append("pair")
    return original_read(tree, name, *args, **kwargs)
  monkeypatch.setattr(Tree, "read", read)
  def watch(module, name, label):
    original = getattr(module, name)
    def wrapped(*args, **kwargs):
      value = label(*args, **kwargs) if callable(label) else label; events.append(value)
      return original(*args, **kwargs)
    monkeypatch.setattr(module, name, wrapped)
  watch(dependencies, "recipe_digest", "recipe")
  watch(pi_capabilities, "validate_manifest_bindings", "bindings")
  watch(metadata, "_validate_source_prefix", lambda source: "prefix:" + source["kind"])
  watch(metadata, "_validate_source_suffix", lambda source: "suffix:" + source["kind"])
  watch(metadata, "_validate_slice", lambda name, *args: "slice:" + name)
  watch(pi_runtime_files, "verify_sources", "runtime")
  watch(pi_license_bundle, "validate_source", "license")
  watch(pi_capabilities, "validate_selection", "selection")
  assert dependencies.PiBackend(profile="pi-full").read_lock(workspace.repository)
  assert events.index("recipe") < events.index("bindings") < events.index("prefix:local") < events.index("archive:local") < events.index("suffix:local")
  assert events.index("slice:pi-full") < events.index("runtime") < events.index("pair") < events.index("license") < events.index("selection")


def test_cold_module_only_stdlib_imports_and_no_dependencies_backedge():
  tree = ast.parse(_MODULE)
  assert {alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names} == {"base64", "hashlib", "json", "math", "re"}
  assert not any(isinstance(node, ast.ImportFrom) for node in tree.body)
  assert not any(isinstance(node, ast.ImportFrom) and node.module == "pi_dependencies" for node in ast.walk(tree))


@pytest.mark.parametrize("kind", ["local", "git", "raw", "node", "built"])
def test_all_source_kind_metadata_positive_without_source_io(kind, tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path, 2)
  if kind in ("local", "git"):
    source = {"kind": kind, "package": "unselected-control", "version": "1.0.0", "source_path": "packages/control", "source_tree_digest": "a" * 64,
      "vendor_path": "vendor/not-read.tgz", "archive_digest": "b" * 64, "license_files": []}
    if kind == "git": source["commit"] = "c" * 40
  elif kind == "raw":
    source = {"kind": "asset", "format": "raw", "platform": "all", "url": "https://example.invalid/control.data", "target": "data/control", "size": 1,
      "archive_digest": "a" * 64, "license_files": ["agents/pi/build/licenses/control/LICENSE"]}
  elif kind == "node":
    source = {"kind": "asset", "format": "node.tar.gz", "platform": "linux-x86_64", "url": "https://nodejs.org/download/release/v24.14.0/node-v24.14.0-linux-x64.tar.gz",
      "archive_digest": "a" * 64, "archive_member": "node-v24.14.0-linux-x64/bin/node", "target": "bin/pi-node", "license_files": ["agents/pi/build/licenses/node-v24.14.0/LICENSE"],
      "node_archive": {"schema": 1, "release": "v24.14.0", "platform": "linux-x86_64", "archive_sha256": "a" * 64, "binary_sha256": "b" * 64, "license_sha256": "c" * 64}}
  else:
    source = {"kind": "asset", "format": "tar.gz", "platform": "linux-x86_64", "target": "bin/pi-bwrap", "archive_member": "bin/pi-bwrap",
      "archive_digest": "a" * 64, "vendor_path": "vendor/not-read.tgz", "build_record": {"recipe": "bubblewrap-v1", "path": "build-records/" + "b" * 64 + ".json", "digest": "b" * 64},
      "license_files": ["agents/pi/build/licenses/control/COPYING", "agents/pi/build/licenses/control/LICENSE"]}
  manifest["sources"]["unselected-control"] = source; _rehash(manifest)
  with monkeypatch.context() as guard:
    def no_tree(*args, **kwargs): pytest.fail("metadata source kinds must not read actual archive/licenses/build inputs")
    guard.setattr(Tree, "__init__", no_tree)
    result = _call(manifest, {"pi-base": inputs["pi-base"]})
    assert result["metadata"]["sources"]["unselected-control"] == source


def test_profile_blob_record_alias_captured_once_and_output_detached(tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  manifest["profile_slices"]["pi-second"] = deepcopy(manifest["profile_slices"]["pi-fixture"]); _rehash(manifest)
  shared = inputs["pi-fixture"]; inputs["pi-second"] = shared
  original = metadata._pairs; calls = []
  def pairs(value, cap, **kwargs):
    captured = original(value, cap, **kwargs)
    if value is shared:
      calls.append(True); shared.clear(); shared[_ForeignKey("package_json")] = _Foreign()
    return captured
  monkeypatch.setattr(metadata, "_pairs", pairs)
  result = _call(manifest, inputs)
  assert calls == [True] and _FOREIGN_CALLS == []
  assert result["profile_inputs"]["pi-fixture"] is result["profile_inputs"]["pi-second"]
  assert type(result["profile_inputs"]["pi-fixture"]["package_json"]) is bytes


@pytest.mark.parametrize("fault", ["empty-bytes", "long-profile", "surrogate-profile"])
def test_blob_capture_no_implicit_minimum_or_json_text_cap(fault, tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  if fault == "empty-bytes": inputs["pi-fixture"]["package_json"] = b""
  if fault == "long-profile": inputs["x" * 5000] = inputs["pi-fixture"]
  if fault == "surrogate-profile": inputs["\ud800"] = inputs["pi-fixture"]
  from agentcfg import pi_lock_header
  original = pi_lock_header.validate_lock_header; calls = []
  def observed(*args, **kwargs): calls.append(True); return original(*args, **kwargs)
  monkeypatch.setattr(pi_lock_header, "validate_lock_header", observed)
  _reject(_call, manifest, inputs)
  assert calls == [True]


def test_original_raw_npm_large_string_and_integer_remain_legal_only_in_old_path(tmp_path):
  root, manifest, inputs = _fixture(tmp_path)
  name = "pi-fixture"; package = json.loads(inputs[name]["package_json"])
  package.update(extra_integer=2 ** 70, extra_string="x" * 5000)
  raw = payload(package); piece = manifest["profile_slices"][name]; piece["package_json_digest"] = _sha(raw)
  (root / "locks/pi" / piece["package_path"]).write_bytes(raw); inputs[name]["package_json"] = raw; _rehash(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  assert dependencies.PiBackend(profile=name).read_lock(root).pairs[name][0] == raw
  _reject(_call, manifest, inputs)
  del package["extra_integer"]; raw = payload(package); piece["package_json_digest"] = _sha(raw)
  (root / "locks/pi" / piece["package_path"]).write_bytes(raw); inputs[name]["package_json"] = raw; _rehash(manifest)
  (root / "locks/pi/manifest.json").write_bytes(payload(manifest))
  assert dependencies.PiBackend(profile=name).read_lock(root).pairs[name][0] == raw
  _reject(_call, manifest, inputs)


def test_new_entry_actual_io_is_only_its_fixed_header_schema(tmp_path, monkeypatch):
  _, manifest, inputs = _fixture(tmp_path)
  original = Path.read_text; reads = []
  expected = _ROOT / "schemas/pi-lock.schema.json"
  def read(path, *args, **kwargs):
    reads.append(path)
    assert path == expected
    return original(path, *args, **kwargs)
  monkeypatch.setattr(Path, "read_text", read)
  assert _call(manifest, inputs)["metadata"] == manifest
  assert reads == [expected]
