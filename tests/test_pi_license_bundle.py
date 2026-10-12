"""默认离线许可闭包验证；虚构 npm 安装，绝不执行宿主。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.pi_dependencies import PiBackend, PiLock, digest, recipe_digest
from agentcfg.pi_license_bundle import validate_source, projection, validate_packages
from agentcfg.pi_runtime_files import lock_files
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_capability_manifest import binding_repository, _write_manifest, fake_installer
from test_pi_dependencies import payload


OWN = "agents/pi/build/licenses/pi-modern/"


def fixture(tmp_path):
  workspace, manifest = binding_repository(tmp_path)
  piece = manifest["profile_slices"]["pi-base"]
  path = workspace.repository / OWN / "REGISTRY.json"
  return workspace, manifest, piece, path, json.loads(path.read_bytes())


def freeze(workspace, manifest, piece, path, registry):
  path.write_bytes(payload(registry))
  declarations = [{key: row[key] for key in ("source", "path", "transform")} for row in piece["runtime_files"]]
  piece["runtime_files"] = lock_files(workspace.repository, declarations)
  manifest["recipe_digest"] = recipe_digest(workspace.repository, family="modern")
  _write_manifest(workspace.repository, manifest)


@pytest.mark.parametrize("fault", ["missing-row", "extra-row", "duplicate-row", "version", "sri", "resolved", "unknown", "schema-bool", "optional-int", "path", "duplicate-ref", "missing-pin", "unresolved"])
def test_registry_failures_before_guard_or_installer(tmp_path, monkeypatch, fault):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  row = registry["packages"][0]
  if fault == "missing-row": registry["packages"].pop()
  if fault == "extra-row": registry["packages"].append({**deepcopy(row), "path": "node_modules/extra"})
  if fault == "duplicate-row": registry["packages"].append(deepcopy(row))
  if fault == "version": row["version"] = "9.0.0"
  if fault == "sri": row["integrity"] = "sha512-" + "a" * 86 + "=="
  if fault == "resolved": row["resolved"] = "https://example.invalid/different.tgz"
  if fault == "unknown": row["auth"] = "synthetic-secret"
  if fault == "schema-bool": registry["schema_version"] = True
  if fault == "optional-int": row["optional"] = 0
  if fault == "path": row["archive_files"][0]["path"] = "../secret"
  if fault == "duplicate-ref": row["archive_files"].append(dict(row["archive_files"][0]))
  if fault == "missing-pin": row["evidence_files"] = [{"path": "licenses/pi-modern/SOURCE.json", "sha256": "a" * 64}]
  if fault == "unresolved": row.update(status="body-scope-unresolved", archive_files=[])
  freeze(workspace, manifest, piece, path, registry)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", lambda *args, **kwargs: pytest.fail("installer reached"))
  with pytest.raises(ConfigError) as error: PiBackend(profile="pi-base").read_lock(workspace.repository)
  assert "synthetic-secret" not in str(error.value)
  assert not (workspace.instance / "runtimes").exists()


def test_duplicate_json_keys_rejected_with_pins_refrozen(tmp_path):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  path.write_text('{"schema_version":1,"schema_version":1,"platform":"linux-x86_64","packages":[]}')
  piece["runtime_files"] = lock_files(workspace.repository, [{k: r[k] for k in ("source", "path", "transform")} for r in piece["runtime_files"]])
  manifest["recipe_digest"] = recipe_digest(workspace.repository, family="modern"); _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(workspace.repository)


def add_evidence(workspace, piece):
  path = workspace.repository / OWN / "SOURCE.json"; path.write_bytes(b'{"purpose":"synthetic source"}\n')
  piece["runtime_files"].append({"source": OWN + "SOURCE.json", "path": "licenses/pi-modern/SOURCE.json", "transform": "copy"})
  # freeze consumes declaration keys only, then pins all selected bytes.
  return {"path": "licenses/pi-modern/SOURCE.json", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def test_unresolved_candidate_readable_but_current_and_install_refused(tmp_path):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  registry["packages"][0].update(status="body-scope-unresolved", archive_files=[], evidence_files=[add_evidence(workspace, piece)])
  manifest["capability_bindings"]["selections"]["pi-base"]["state"] = "candidate"
  freeze(workspace, manifest, piece, path, registry)
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  assert lock.validated_bindings["pi-base"].state == "candidate"
  backend.runtime_identity(workspace, lock)
  from agentcfg.process import DependencyError
  with pytest.raises(DependencyError): backend.sync(workspace, lock)
  assert not (workspace.instance / "runtimes").exists()
  manifest["capability_bindings"]["selections"]["pi-base"]["state"] = "current"; _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError): backend.read_lock(workspace.repository)


@pytest.mark.parametrize("fault", ["missing", "drift"])
def test_source_revalidated_with_cached_or_forged_lock_before_guard(tmp_path, monkeypatch, fault):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  if fault == "missing": path.unlink()
  else: path.write_bytes(payload({**registry, "schema_version": 2}))
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard", lambda *a, **k: pytest.fail("guard reached"))
  with pytest.raises(ConfigError): backend.sync(workspace, PiLock(lock.identity, deepcopy(lock.metadata), dict(lock.pairs), lock.validated_bindings))


@pytest.mark.parametrize("fault", ["package-json", "original-body", "own-missing", "own-drift"])
def test_installed_license_damage_and_receipt_inventory(tmp_path, monkeypatch, fault):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  calls = []; monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  assert "licenses/pi-modern/REGISTRY.json" in receipt["files"]
  with Tree(root) as tree:
    if fault == "package-json": tree.write_state("pi-base/node_modules/synthetic-host/package.json", b'{"name":"synthetic-host","version":"1.0.0","license":"ISC"}')
    if fault == "original-body": tree.write_state("pi-base/node_modules/synthetic-host/LICENSE", b"changed")
    if fault == "own-drift": tree.write_state("licenses/pi-modern/REGISTRY.json", b"{}")
  if fault == "own-missing": (root / "licenses/pi-modern/REGISTRY.json").unlink()
  assert backend.status(workspace, result["identity"]) == "damaged"


def test_modern_npm_overlay_never_written(tmp_path, monkeypatch):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  source = workspace.repository / OWN / "LICENSE"; source.write_bytes(b"synthetic supplemental body")
  manifest["sources"]["pi-host"].update(license_files=["LICENSE"], license_sources={"LICENSE": OWN + "LICENSE"})
  from agentcfg.pi_capabilities import source_identity
  manifest["capability_bindings"]["providers"]["native-provider"]["source_identity"] = source_identity(manifest["sources"]["pi-host"])
  registry["packages"][1].update(status="fixed-source-body", archive_files=[], evidence_files=[add_evidence(workspace, piece)],
    supplemental_files=[{"path": "licenses/pi-modern/LICENSE", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}])
  piece["runtime_files"].append({"source": OWN + "LICENSE", "path": "licenses/pi-modern/LICENSE", "transform": "copy"})
  freeze(workspace, manifest, piece, path, registry)
  def installer(argv, **kwargs):
    result = fake_installer([])(argv, **kwargs)
    if argv[0] == "npm" and argv[1] == "ci": (Path(kwargs["cwd"]) / "node_modules/synthetic-host/LICENSE").unlink()
    return result
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", installer)
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  assert not (root / "pi-base/node_modules/synthetic-host/LICENSE").exists()
  assert (root / "licenses/pi-modern/LICENSE").read_bytes() == b"synthetic supplemental body"


@pytest.mark.parametrize("constraints,allowed", [({"os":["darwin"]},True), ({"cpu":["arm64"]},True), ({"os":["!linux"]},True), ({"os":["linux"],"cpu":["x64"]},False), ({"libc":["musl"]},False), ({},False)])
def test_optional_exclusion_requires_proven_os_cpu_mismatch(tmp_path, constraints, allowed):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  resolution = json.loads((workspace.repository / "locks/pi-modern" / piece["lock_path"]).read_bytes())
  record = {"version":"1.0.0", "resolved":"https://example.invalid/optional.tgz", "integrity":registry["packages"][0]["integrity"],"optional":True, **constraints}
  resolution["packages"]["node_modules/synthetic-optional"] = record
  row = projection(resolution)[-1]
  assert row["name"] == "synthetic-optional"
  registry["packages"].append({**row,"package_json_sha256":None,"declared_license":None,"status":"optional-platform-excluded","archive_files":[],"supplemental_files":[],"evidence_files":[]})
  freeze(workspace, manifest, piece, path, registry)
  if allowed:
    document = validate_source(workspace.repository,piece,resolution,allow_unresolved=False)
    with Tree(workspace.instance) as tree:
      for r in document["packages"][:-1]:
        tree.write_state(r["path"]+"/package.json", ('{"name":"%s","version":"%s","license":"MIT"}' % (r['name'],r['version'])).encode())
        tree.write_state(r["path"]+"/LICENSE", b"synthetic original MIT body\n")
      validate_packages(tree, ".", document)
      tree.write_state(row["path"]+"/package.json", b"{}")
      with pytest.raises(ValueError): validate_packages(tree,".",document)
  else:
    with pytest.raises(ConfigError):validate_source(workspace.repository,piece,resolution,allow_unresolved=False)


def test_current_platform_mismatch_rejected_before_install(tmp_path, monkeypatch):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  monkeypatch.setattr("agentcfg.pi_dependencies.platform_id", lambda: "darwin-arm64")
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(workspace.repository)


@pytest.mark.parametrize("kind", ["supplemental_files", "evidence_files"])
def test_empty_pinned_source_body_or_evidence_is_rejected(tmp_path, kind):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  evidence = add_evidence(workspace, piece)
  empty = workspace.repository / OWN / "EMPTY.txt"; empty.write_bytes(b"")
  piece["runtime_files"].append({"source": OWN + "EMPTY.txt", "path": "licenses/pi-modern/EMPTY.txt", "transform": "copy"})
  body = workspace.repository / OWN / "LICENSE"; body.write_bytes(b"synthetic fixed body")
  piece["runtime_files"].append({"source": OWN + "LICENSE", "path": "licenses/pi-modern/LICENSE", "transform": "copy"})
  row = registry["packages"][0]
  row.update(status="fixed-source-body", archive_files=[], evidence_files=[evidence],
    supplemental_files=[{"path":"licenses/pi-modern/LICENSE", "sha256":hashlib.sha256(body.read_bytes()).hexdigest()}])
  row[kind] = [{"path":"licenses/pi-modern/EMPTY.txt", "sha256":hashlib.sha256(b"").hexdigest()}]
  freeze(workspace, manifest, piece, path, registry)
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(workspace.repository)


def test_empty_pinned_original_body_is_rejected_before_descriptor(tmp_path, monkeypatch):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  registry["packages"][1]["archive_files"][0]["sha256"] = hashlib.sha256(b"").hexdigest()
  freeze(workspace,manifest,piece,path,registry)
  def installer(argv, **kwargs):
    result = fake_installer([])(argv, **kwargs)
    if argv[0] == "npm" and argv[1] == "ci": (Path(kwargs["cwd"]) / "node_modules/synthetic-host/LICENSE").write_bytes(b"")
    return result
  monkeypatch.setattr("agentcfg.pi_dependencies.checked",installer)
  backend = PiBackend(profile="pi-base");lock = backend.read_lock(workspace.repository)
  from agentcfg.process import DependencyError
  with pytest.raises(DependencyError): backend.sync(workspace,lock)
  assert not list(workspace.instance.rglob("profile.json"))
  assert not list(workspace.instance.rglob(".agentcfg-ready"))


def test_applicable_optional_package_missing_is_rejected(tmp_path, monkeypatch):
  workspace, manifest, piece, path, registry = fixture(tmp_path)
  resolution_path = workspace.repository / "locks/pi-modern" / piece["lock_path"]
  resolution = json.loads(resolution_path.read_bytes())
  resolution["packages"]["node_modules/synthetic-extra"] = {"version":"1.0.0", "resolved":"https://example.invalid/extra.tgz",
    "integrity":registry["packages"][0]["integrity"], "optional":True}
  resolution_path.write_bytes(payload(resolution)); piece["package_lock_digest"] = digest(payload(resolution))
  row = next(row for row in projection(resolution) if row["name"] == "synthetic-extra")
  raw = b'{"name":"synthetic-extra","version":"1.0.0","license":"MIT"}'
  registry["packages"].append({**row,"package_json_sha256":hashlib.sha256(raw).hexdigest(),"declared_license":"MIT","status":"archive-body",
    "archive_files":[{"path":"LICENSE","sha256":hashlib.sha256(b"synthetic original MIT body\n").hexdigest()}],"supplemental_files":[],"evidence_files":[]})
  registry["packages"].sort(key=lambda row:row["path"])
  freeze(workspace,manifest,piece,path,registry)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked",fake_installer([]))
  from agentcfg.process import DependencyError
  backend = PiBackend(profile="pi-base");lock = backend.read_lock(workspace.repository)
  with pytest.raises(DependencyError):backend.sync(workspace,lock)
  assert not list(workspace.instance.rglob(".agentcfg-ready"))


@pytest.mark.parametrize("kind,fault", [("body","missing"),("body","drift"),("evidence","missing"),("evidence","drift")])
def test_pinned_supplement_and_evidence_loss_rejected_before_guard(tmp_path,monkeypatch,kind,fault):
  workspace,manifest,piece,path,registry = fixture(tmp_path)
  evidence = add_evidence(workspace,piece)
  body = workspace.repository / OWN / "LICENSE";body.write_bytes(b"synthetic fixed body")
  piece["runtime_files"].append({"source":OWN+"LICENSE","path":"licenses/pi-modern/LICENSE","transform":"copy"})
  registry["packages"][0].update(status="fixed-source-body",archive_files=[],evidence_files=[evidence],
    supplemental_files=[{"path":"licenses/pi-modern/LICENSE","sha256":hashlib.sha256(body.read_bytes()).hexdigest()}])
  freeze(workspace,manifest,piece,path,registry)
  backend = PiBackend(profile="pi-base");lock = backend.read_lock(workspace.repository)
  target = body if kind == "body" else workspace.repository / OWN / "SOURCE.json"
  if fault == "missing":target.unlink()
  else:target.write_bytes(b"changed")
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard",lambda *a,**k:pytest.fail("guard reached"))
  with pytest.raises(ConfigError):backend.sync(workspace,lock)


def test_modern_sync_keeps_asset_license_siblings_in_receipt(tmp_path, monkeypatch):
  from test_pi_built_asset_integration import locked_fixture
  workspace, manifest, source, _, _ = locked_fixture(tmp_path, monkeypatch)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer([]))
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  siblings = {name for name in receipt["files"] if name.startswith("licenses/host-helper/") and receipt["files"][name]["kind"] == "file"}
  assert len(siblings) == len(source["license_files"])
  assert backend.status(workspace, result["identity"]) == "installed"
  with Tree(root) as tree: tree.write_state(next(iter(siblings)), b"changed asset body")
  assert backend.status(workspace, result["identity"]) == "damaged"
