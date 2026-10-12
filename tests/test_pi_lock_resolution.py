"""合成完整依赖图与固定旧实现基线；不启动第三方宿主。"""

import base64
import builtins
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import traceback

import pytest

from agentcfg.config import _credential_url
from agentcfg.paths import relative_path
from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi_lock_resolution import VERSION, validate_lock_resolution


# 本轮前像a051978efbe9f9a999ba07488733e8223df1b2f91bf83d782db95e888168b991。
# 固定原方法正文为独立基线；不会从当前委托入口反推出旧行为。
LEGACY_SOURCE = r"""
def _validate_resolution(self, package, resolution, piece, manifest):
  if (resolution.get("lockfileVersion") != 3 or not isinstance(package.get("dependencies"), dict)
      or resolution.get("packages", {}).get("", {}).get("dependencies") != package["dependencies"]):
    raise ValueError()
  archives = {source["vendor_path"] for source in manifest["sources"].values() if "vendor_path" in source}
  declared = {manifest["sources"][key]["package"] for key in piece["source_ids"] if manifest["sources"][key]["kind"] != "asset"}
  if set(package["dependencies"]) != declared:
    raise ValueError()
  for version in package["dependencies"].values():
    if not isinstance(version, str):
      raise ValueError()
    if version.startswith("file:"):
      path = os.path.normpath(str(Path(piece["package_path"]).parent / version[5:]))
      if path not in archives or Path(version[5:]).is_absolute():
        raise ValueError()
    elif not VERSION.fullmatch(version):
      raise ValueError()
  for name in package["dependencies"]:
    if "node_modules/" + name not in resolution["packages"]:
      raise ValueError()
  if manifest["schema_version"] == 2:
    from .pi_modern_launcher import validate_locked_ai
    validate_locked_ai(resolution, piece)
    # 能力来源必须对应真正安装的直接依赖，不能只分别验证两个自洽清单。
    for source_id in piece["source_ids"]:
      source = manifest["sources"][source_id]
      if source["kind"] == "asset": continue
      name = source["package"]
      wanted = package["dependencies"][name]
      actual = resolution["packages"]["node_modules/" + name]
      if actual.get("name", name) != name or actual.get("version") != source["version"]:
        raise ValueError()
      if source["kind"] == "npm":
        if (wanted != source["version"] or actual.get("resolved") != source["resolved"]
            or actual.get("integrity") != source["integrity"]):
          raise ValueError()
      else:
        for reference in (wanted, actual.get("resolved")):
          if (not isinstance(reference, str) or not reference.startswith("file:")
              or Path(reference[5:]).is_absolute()
              or os.path.normpath(str(Path(piece["package_path"]).parent / reference[5:])) != source["vendor_path"]):
            raise ValueError()
  for path, value in resolution["packages"].items():
    if not path:
      continue
    relative_path(path)
    if "node_modules" not in Path(path).parts:
      raise ValueError()
    if value.get("link"):
      # 本地源必须为已冻结归档，不允许workspace/link逃逸运行包。
      raise ValueError()
    required = set(value.get("dependencies", {})) - set(value.get("optionalDependencies", {}))
    required |= {name for name in value.get("peerDependencies", {}) if not value.get("peerDependenciesMeta", {}).get(name, {}).get("optional")}
    for name in required:
      # 按 Node 的祖先 node_modules 查找；锁中必须存在每个必需传递依赖。
      base = Path(path)
      candidates = []
      while base.parts:
        candidates.append((base / "node_modules" / name).as_posix())
        base = base.parent
      candidates.append("node_modules/" + name)
      if not any(candidate in resolution["packages"] for candidate in candidates):
        raise ValueError()
    if not value.get("inBundle"):
      if not {"version", "resolved", "integrity"} <= value.keys():
        raise ValueError()
      if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+=*", value["integrity"]):
        raise ValueError()
      if len(base64.b64decode(value["integrity"][7:], validate=True)) != 64 or not VERSION.fullmatch(value["version"]):
        raise ValueError()
      resolved = value["resolved"]
      if resolved.startswith("file:"):
        target = os.path.normpath(str(Path(piece["package_path"]).parent / resolved[5:]))
        if target not in archives or Path(resolved[5:]).is_absolute():
          raise ValueError()
      elif not resolved.startswith("https://") or _credential_url(resolved):
        raise ValueError()

"""


@pytest.fixture
def legacy_resolution():
  namespace = {"__name__": "agentcfg.pi_dependencies", "__package__": "agentcfg",
    "Path": Path, "os": os, "re": re, "base64": base64,
    "relative_path": relative_path, "_credential_url": _credential_url,
    "VERSION": re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")}
  exec(compile(LEGACY_SOURCE, "<fixed-pre-extraction-resolution>", "exec"), namespace)
  return namespace["_validate_resolution"]


def graph(version=2, archive=False):
  integrity = "sha512-" + base64.b64encode(hashlib.sha512(b"synthetic original archive").digest()).decode()
  def row(**values):
    return {"version": "1.0.0", "resolved": "https://example.invalid/package.tgz", "integrity": integrity, **values}
  dependency = "file:../vendor/sdk.tgz" if archive else "1.0.0"
  package = {"dependencies": {"synthetic-sdk": dependency}}
  # AI在SDK的祖先node_modules中；worker的peer也必须由真实祖先满足。
  resolution = {"lockfileVersion": 3, "packages": {
    "": {"dependencies": deepcopy(package["dependencies"])},
    "node_modules/synthetic-sdk": row(resolved=dependency if archive else "https://example.invalid/package.tgz",
      dependencies={"worker": "1.0.0"}),
    "node_modules/synthetic-sdk/node_modules/worker": row(dependencies={"leaf": "1.0.0", "optional-leaf": "1.0.0"},
      optionalDependencies={"optional-leaf": "1.0.0"}, peerDependencies={"peer": "1.0.0", "optional-peer": "1.0.0"},
      peerDependenciesMeta={"optional-peer": {"optional": True}}),
    "node_modules/synthetic-sdk/node_modules/leaf": row(),
    "node_modules/peer": row(),
    "node_modules/synthetic-ai": row()}}
  source = {"kind": "local", "package": "synthetic-sdk", "version": "1.0.0", "vendor_path": "vendor/sdk.tgz"} if archive else {
    "kind": "npm", "package": "synthetic-sdk", "version": "1.0.0", "resolved": "https://example.invalid/package.tgz", "integrity": integrity}
  piece = {"source_ids": ["sdk", "asset"], "package_path": "pi-full/package.json",
    "entrypoint": "pi-full/node_modules/synthetic-sdk/index.js", "ai_package": "synthetic-ai"}
  manifest = {"schema_version": version, "sources": {"sdk": source, "asset": {"kind": "asset"}}}
  return package, resolution, piece, manifest


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("archive", [False, True])
def test_valid_complete_graph_preserves_inputs_and_old_result(version, archive, legacy_resolution):
  values = graph(version, archive)
  before = deepcopy(values)
  assert legacy_resolution(None, *values) is None
  assert validate_lock_resolution(*values) is None
  assert values == before


FAULTS = ("root", "undeclared", "bad-version", "missing-direct", "missing-worker", "missing-leaf", "missing-peer",
  "missing-ai", "wrong-ai-branch", "source-name", "source-version", "source-resolved", "source-integrity",
  "source-file", "nonrelative", "no-node-modules", "link", "missing-integrity", "bad-base64", "short-sha512",
  "transitive-version", "credential", "query-credential", "http", "absolute-archive", "unknown-archive")


def corrupt(values, fault):
  package, resolution, piece, manifest = values
  packages = resolution["packages"]
  if fault == "root": packages[""]["dependencies"] = {}
  elif fault == "undeclared": package["dependencies"]["extra"] = "1.0.0"; packages[""]["dependencies"] = deepcopy(package["dependencies"])
  elif fault == "bad-version": package["dependencies"]["synthetic-sdk"] = "latest"; packages[""]["dependencies"] = deepcopy(package["dependencies"])
  elif fault.startswith("missing-"):
    key = {"direct": "node_modules/synthetic-sdk", "worker": "node_modules/synthetic-sdk/node_modules/worker",
      "leaf": "node_modules/synthetic-sdk/node_modules/leaf", "peer": "node_modules/peer", "ai": "node_modules/synthetic-ai"}.get(fault[8:])
    if key is not None: del packages[key]
    else: packages["node_modules/peer"].pop("integrity")
  elif fault == "wrong-ai-branch": packages["node_modules/worker/node_modules/synthetic-ai"] = packages.pop("node_modules/synthetic-ai")
  elif fault.startswith("source-"):
    field = fault[7:]
    if field == "file": packages["node_modules/synthetic-sdk"]["resolved"] = "file:../vendor/other.tgz"
    else: packages["node_modules/synthetic-sdk"][field] = {
      "name": "imposter", "version": "1.0.1", "resolved": "https://example.invalid/other.tgz",
      "integrity": "sha512-" + base64.b64encode(b"x" * 64).decode()}[field]
  elif fault == "nonrelative": packages["../node_modules/escape"] = packages.pop("node_modules/peer")
  elif fault == "no-node-modules": packages["other/peer"] = packages.pop("node_modules/peer")
  elif fault == "link": packages["node_modules/peer"]["link"] = "truthy"
  elif fault in ("bad-base64", "short-sha512"):
    packages["node_modules/peer"]["integrity"] = "sha512-!!!!" if fault == "bad-base64" else "sha512-" + base64.b64encode(b"short").decode()
  elif fault == "transitive-version": packages["node_modules/peer"]["version"] = "latest"
  elif fault in ("credential", "query-credential", "http"):
    packages["node_modules/peer"]["resolved"] = {"credential": "https://user:synthetic-secret@example.invalid/pkg.tgz",
      "query-credential": "https://example.invalid/pkg.tgz?api_key=synthetic-secret", "http": "http://example.invalid/pkg.tgz"}[fault]
  elif fault in ("absolute-archive", "unknown-archive"):
    reference = "file:/vendor/sdk.tgz" if fault == "absolute-archive" else "file:../vendor/unknown.tgz"
    package["dependencies"]["synthetic-sdk"] = reference
    packages[""]["dependencies"] = deepcopy(package["dependencies"])
    packages["node_modules/synthetic-sdk"]["resolved"] = reference
  else: raise AssertionError("unknown synthetic fault")


@pytest.mark.parametrize("fault", FAULTS)
def test_invalid_graph_matches_independent_old_rejection_without_input_mutation(fault, legacy_resolution):
  values = graph(archive=fault in ("source-file", "absolute-archive", "unknown-archive"))
  corrupt(values, fault)
  before = deepcopy(values)
  with pytest.raises(Exception): legacy_resolution(None, *values)
  with pytest.raises(ValueError) as error: validate_lock_resolution(*values)
  assert error.value.args == ("pi-lock-resolution",)
  assert error.value.__cause__ is None and error.value.__context__ is None
  assert values == before


@pytest.mark.parametrize("version", [1, 2])
def test_legacy_numeric_and_truthy_semantics(version, legacy_resolution):
  values = graph(version)
  resolution = values[1]
  resolution["lockfileVersion"] = 3.0
  worker = resolution["packages"]["node_modules/synthetic-sdk/node_modules/worker"]
  worker["peerDependenciesMeta"]["optional-peer"]["optional"] = "truthy"
  resolution["packages"]["node_modules/peer"] = {"inBundle": "truthy", "link": 0}
  assert legacy_resolution(None, *values) is None
  assert validate_lock_resolution(*values) is None


def test_error_scrubs_ordinary_exception_and_does_not_catch_base_exception():
  class Broken(dict):
    def get(self, *args): raise RuntimeError("synthetic-secret")
  with pytest.raises(ValueError) as error: validate_lock_resolution({}, Broken(), {}, {})
  assert error.value.args == ("pi-lock-resolution",)
  assert error.value.__cause__ is None and error.value.__context__ is None
  class Interrupted(dict):
    def get(self, *args): raise KeyboardInterrupt("synthetic interrupt")
  with pytest.raises(KeyboardInterrupt): validate_lock_resolution({}, Interrupted(), {}, {})


def test_fixed_error_discards_active_caller_exception_context():
  try:
    raise RuntimeError("synthetic-caller-secret")
  except RuntimeError:
    with pytest.raises(ValueError) as error:
      validate_lock_resolution({}, {}, {}, {})
    assert error.value.args == ("pi-lock-resolution",)
    assert error.value.__cause__ is None and error.value.__context__ is None
    assert "synthetic-caller-secret" not in "".join(traceback.format_exception(error.value))


@pytest.mark.parametrize("version", [1, 2])
def test_no_file_process_environment_or_optional_resource_access(version, monkeypatch):
  # 先载入v2原有公开helper，哨兵覆盖校验调用而非Python模块loader。
  import agentcfg.pi_modern_launcher
  values = graph(version)
  calls = []
  def forbidden(*args, **kwargs):
    calls.append("forbidden access")
    raise AssertionError("pure validator attempted IO")
  original_import = builtins.__import__
  def guarded_import(name, *args, **kwargs):
    if name == "pi_modern_launcher" and version == 1: forbidden()
    if any(part in name for part in ("durable", "origin", "wheel")): forbidden()
    return original_import(name, *args, **kwargs)
  class NoEnvironment(dict):
    def __getitem__(self, key): return forbidden()
    def get(self, *args): return forbidden()
    def __iter__(self): return forbidden()
  with monkeypatch.context() as guard:
    guard.setattr(builtins, "open", forbidden)
    guard.setattr(builtins, "__import__", guarded_import)
    for name in ("open", "read_bytes", "read_text", "stat", "lstat", "resolve", "iterdir"):
      guard.setattr(Path, name, forbidden)
    for name in ("open", "stat", "lstat", "scandir", "listdir", "getenv", "system"):
      guard.setattr(os, name, forbidden)
    guard.setattr(os, "environ", NoEnvironment())
    guard.setattr(subprocess, "run", forbidden)
    guard.setattr(subprocess, "Popen", forbidden)
    assert validate_lock_resolution(*values) is None
  assert calls == []


def test_version_is_same_compatibility_export():
  import agentcfg.pi_dependencies as dependencies
  assert dependencies.VERSION is VERSION


@pytest.mark.parametrize("profile", ["legacy", "pi-base", "pi-full", "all"])
@pytest.mark.parametrize("state", ["current", "candidate", "accepted"])
def test_existing_fixture_full_read_lock_matches_pre_extraction_method(tmp_path, monkeypatch, legacy_resolution, profile, state):
  from test_pi_dependencies import fixture_repository
  from test_pi_capability_manifest import binding_repository, _write_manifest, proof
  if profile == "legacy":
    if state != "current": pytest.skip("v1 has no binding state")
    root, manifest = fixture_repository(tmp_path)
    backend = PiBackend()
    accepted = None
  else:
    workspace, manifest = binding_repository(tmp_path)
    root = workspace.repository
    accepted = None
    if state != "current":
      for selection in manifest["capability_bindings"]["selections"].values(): selection["state"] = state
      _write_manifest(root, manifest)
    if state == "accepted": accepted = {name: proof(manifest, name) for name in manifest["profile_slices"]}
    backend = PiBackend(family="modern") if profile == "all" else PiBackend(profile=profile)
  def snapshot(lock):
    return lock.identity, deepcopy(lock.metadata), dict(lock.pairs), dict(lock.validated_bindings)
  # 只有仓库自有方法替换成固定旧正文；不是上游宿主patch，也不是两边调用新入口。
  with monkeypatch.context() as baseline:
    baseline.setattr(PiBackend, "_validate_resolution", legacy_resolution)
    old = snapshot(backend.read_lock(root, accepted_binding_digests=accepted))
  new = snapshot(backend.read_lock(root, accepted_binding_digests=accepted))
  assert new == old
  assert new[0] == manifest["identity"] and new[1] == manifest
  assert all(isinstance(raw, bytes) for pair in new[2].values() for raw in pair)
