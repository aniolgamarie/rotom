"""运行源码清单与安装字节绑定；仅仓库/临时目录，不执行宿主。"""
import json
import os
from pathlib import Path

import pytest

from agentcfg.pi_runtime_files import lock_files, verify_sources, install_files, validate_files
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, ensure_private


@pytest.fixture(autouse=True)
def isolated_install_record_seam(monkeypatch):
  # 本模块的安装 fixture 只有包材料；完整 Workspace 替换接线由独立测试负责。
  from agentcfg import pi_replacement, runtime
  monkeypatch.setattr(runtime, "record", lambda *_: {})
  monkeypatch.setattr(pi_replacement, "descriptor", lambda *_: {})
  monkeypatch.setattr(pi_replacement, "record_validated", lambda *_: None)


def fixture(tmp_path):
  root, stage = tmp_path / "repo", tmp_path / "stage"
  ensure_private(root); ensure_private(stage)
  path = root / "agents/pi/runtime/official-launch.ts"; path.parent.mkdir(parents=True)
  path.write_bytes(b'import { run } from "./official-session.ts";\n')
  declarations = [{"source": "agents/pi/runtime/official-launch.ts", "path": "runtime/official-launch.mjs", "transform": "ts-module"}]
  return root, stage, declarations


def test_selected_sources_install_only_declared_transformed_bytes(tmp_path):
  root, stage, declarations = fixture(tmp_path)
  (root / "agents/pi/runtime/unselected.ts").write_text("throw new Error('must not install')")
  locked = lock_files(root, declarations)
  assert locked[0]["input_digest"] != locked[0]["digest"]
  assert locked[0]["mode"] == 0o600
  install_files(root, stage, locked)
  assert (stage / "runtime/official-launch.mjs").read_bytes() == b'import { run } from "./official-session.mjs";\n'
  assert not (stage / "runtime/unselected.mjs").exists()
  validate_files(stage, locked, generated=())


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "alias", "escape", "reserved", "legacy", "mode", "wrong-transform"])
def test_invalid_file_selection_refused_without_stage_writes(tmp_path, fault):
  root, stage, declarations = fixture(tmp_path)
  row = declarations[0]
  if fault == "unknown": row["credential"] = "synthetic-secret"
  if fault == "duplicate": declarations.append(dict(row))
  if fault == "alias": row["path"] = "runtime/other.mjs"
  if fault == "escape": row["source"] = "../secret"
  if fault == "reserved": row.update(source="agents/pi/runtime/profile.json", path="runtime/profile.json", transform="copy")
  if fault == "legacy": row.update(source="agents/pi/runtime/launch.ts", path="runtime/launch.mjs")
  if fault == "mode": row["mode"] = 0o777
  if fault == "wrong-transform": row["transform"] = "copy"
  with pytest.raises(ConfigError) as error: lock_files(root, declarations)
  assert "synthetic-secret" not in str(error.value)
  assert list(stage.iterdir()) == []


@pytest.mark.parametrize("fault", ["changed", "missing", "symlink", "hardlink"])
def test_source_drift_or_unsafe_file_refused_before_any_install(tmp_path, fault):
  root, stage, declarations = fixture(tmp_path)
  locked = lock_files(root, declarations); path = root / declarations[0]["source"]
  if fault == "changed": path.write_text("changed")
  if fault == "missing": path.unlink()
  if fault in ("symlink", "hardlink"):
    other = root / "other"; path.rename(other)
    if fault == "symlink": path.symlink_to(other)
    else: os.link(other, path)
  with pytest.raises(ConfigError): install_files(root, stage, locked)
  assert list(stage.iterdir()) == []


@pytest.mark.parametrize("fault", ["extra", "extra-empty-dir", "missing", "changed", "mode", "symlink", "hardlink", "output-digest"])
def test_installed_closure_is_exact(tmp_path, fault):
  root, stage, declarations = fixture(tmp_path)
  locked = lock_files(root, declarations); install_files(root, stage, locked)
  path = stage / locked[0]["path"]
  if fault == "extra": (path.parent / "unexpected.mjs").write_text("extra")
  if fault == "extra-empty-dir": (path.parent / "unexpected").mkdir()
  if fault == "missing": path.unlink()
  if fault == "changed": path.write_text("changed")
  if fault == "mode": path.chmod(0o700)
  if fault in ("symlink", "hardlink"):
    other = stage / "other"; path.rename(other)
    if fault == "symlink": path.symlink_to(other)
    else: os.link(other, path)
  if fault == "output-digest": locked[0]["digest"] = "f" * 64
  with pytest.raises(Conflict): validate_files(stage, locked, generated=())


def test_install_rechecks_locked_input_and_output_digests(tmp_path):
  root, stage, declarations = fixture(tmp_path)
  locked = lock_files(root, declarations)
  locked[0]["digest"] = "f" * 64
  with pytest.raises(ConfigError): verify_sources(root, locked)
  assert list(stage.iterdir()) == []


def test_modern_sync_uses_exact_files_and_bound_runtime_identity(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import PiBackend
  from test_pi_capability_manifest import binding_repository, fake_installer
  workspace, manifest = binding_repository(tmp_path)
  calls = []; monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer(calls))
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock)
  root = backend.root(workspace, result["identity"])
  assert not (root / "runtime/launch.mjs").exists()
  assert not (root / "supervisor/src/agentcfg/pi_worker_files.py").exists()
  profile = json.loads((root / "runtime/profile.json").read_bytes())
  assert profile["runtime_identity"] == result["identity"] == backend.runtime_identity(workspace, lock)
  assert (profile["sdk_package"], profile["sdk_version"], profile["ai_package"], profile["ai_version"]) == (
    "synthetic-host", "1.0.0", "synthetic-ai", "1.0.2")
  assert profile["profile_id"] == "pi-base" and profile["package_path"] == "pi-base/package.json"
  assert backend.status(workspace, result["identity"]) == "installed"


@pytest.mark.parametrize("fault", ["missing-files", "bad-output", "file-drift", "unknown", "unsorted", "missing-ai", "wrong-ai"])
def test_modern_lock_refuses_stale_or_unclosed_runtime_inputs(tmp_path, fault):
  from agentcfg.pi_dependencies import PiBackend
  from test_pi_capability_manifest import binding_repository, _write_manifest
  workspace, manifest = binding_repository(tmp_path)
  piece = manifest["profile_slices"]["pi-base"]
  if fault == "missing-files": del piece["runtime_files"]
  if fault == "bad-output": piece["runtime_files"][0]["digest"] = "f" * 64
  if fault == "file-drift": (workspace.repository / piece["runtime_files"][0]["source"]).write_text("changed")
  if fault == "unknown": piece["runtime_files"][0]["secret"] = "synthetic-secret"
  if fault == "unsorted": piece["runtime_files"].reverse()
  if fault == "missing-ai": del piece["ai_package"]
  if fault == "wrong-ai": piece["ai_package"] = "not-locked"
  _write_manifest(workspace.repository, manifest)
  with pytest.raises(ConfigError) as error: PiBackend(profile="pi-base").read_lock(workspace.repository)
  assert "synthetic-secret" not in str(error.value)


def ai_fixture(tmp_path):
  from agentcfg.storage import Tree
  root = tmp_path / "runtime"; ensure_private(root)
  piece = {"package_path": "slice/package.json", "lock_path": "slice/package-lock.json",
    "entrypoint": "slice/node_modules/@test/host/dist/index.js", "ai_package": "@test/ai"}
  records = {"node_modules/@test/host": {"version": "1.0.1"}, "node_modules/@test/ai": {"version": "1.0.2"}}
  with Tree(root) as tree:
    tree.write_state(piece["lock_path"], json.dumps({"packages": records}).encode())
    tree.write_state("slice/node_modules/@test/host/package.json", b'{"name":"@test/host","version":"1.0.1"}')
    tree.write_state("slice/node_modules/@test/ai/package.json", b'{"name":"@test/ai","version":"1.0.2"}')
  return root, piece, records


def test_ai_uses_nearest_installed_locked_package(tmp_path):
  from agentcfg.pi_modern_launcher import packages
  from agentcfg.storage import Tree
  root, piece, records = ai_fixture(tmp_path)
  with Tree(root) as tree:
    assert packages(tree, piece)["ai_version"] == "1.0.2"
    path = "node_modules/@test/host/node_modules/@test/ai"
    records[path] = {"version": "2.0.0"}
    tree.write_state(piece["lock_path"], json.dumps({"packages": records}).encode())
    tree.write_state("slice/" + path + "/package.json", b'{"name":"@test/ai","version":"2.0.0"}')
    assert packages(tree, piece)["ai_version"] == "2.0.0"


@pytest.mark.parametrize("fault", ["missing", "wrong-name", "wrong-version", "unlocked-nearer", "symlink", "outside-slice"])
def test_ai_resolution_never_uses_unlocked_or_global_fallback(tmp_path, fault):
  from agentcfg.pi_modern_launcher import packages
  from agentcfg.storage import Tree
  root, piece, records = ai_fixture(tmp_path)
  path = root / "slice/node_modules/@test/ai/package.json"
  if fault == "missing": path.unlink()
  if fault == "wrong-name": path.write_text('{"name":"other","version":"1.0.2"}')
  if fault == "wrong-version": path.write_text('{"name":"@test/ai","version":"9.0.0"}')
  if fault == "unlocked-nearer":
    with Tree(root) as tree: tree.write_state("slice/node_modules/@test/host/node_modules/@test/ai/package.json", b'{"name":"@test/ai","version":"2.0.0"}')
  if fault == "symlink":
    other = root / "other.json"; path.rename(other); path.symlink_to(other)
  if fault == "outside-slice":
    path.unlink()
    with Tree(root) as tree: tree.write_state("node_modules/@test/ai/package.json", b'{"name":"@test/ai","version":"1.0.2"}')
  with Tree(root) as tree:
    with pytest.raises((ValueError, KeyError, Conflict)): packages(tree, piece)


@pytest.mark.parametrize("fault", ["extra", "generated-profile", "generated-commands", "owned-digest", "profile-identity"])
def test_resealing_inventory_cannot_hide_wrong_modern_output(tmp_path, monkeypatch, fault):
  from agentcfg.pi_dependencies import PiBackend
  from agentcfg.pi_runtime_packages import seal, inventory
  from test_pi_capability_manifest import binding_repository, fake_installer
  workspace, manifest = binding_repository(tmp_path)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer([]))
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  if fault == "extra": (root / "runtime/unselected.mjs").write_text("extra")
  if fault == "owned-digest": (root / "runtime/official-launch.mjs").write_text("modified")
  if fault == "generated-commands": (root / "runtime/commands.json").write_text('{"schema_version":1,"programs":{}}')
  if fault in ("generated-profile", "profile-identity"):
    path = root / "runtime/profile.json"; profile = json.loads(path.read_bytes())
    profile["sdk_version" if fault == "generated-profile" else "runtime_identity"] = "9.9.9" if fault == "generated-profile" else "f" * 64
    path.write_text(json.dumps(profile))
  with pytest.raises(Conflict): seal(root, result["identity"], lock.identity, receipt["slice"],
    toolchains=manifest["toolchains"], binding_identity=receipt["binding_identity"])
  # 即使外部错误刷新inventory，也必须再校验所选字节与启动绑定。
  receipt["files"] = inventory(root)
  (root / ".agentcfg-receipt.json").write_text(json.dumps(receipt))
  assert backend.status(workspace, result["identity"]) == "damaged"


def test_generator_checks_selected_source_outside_broad_recipe_before_publication(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import PiBackend, recipe_digest
  import agentcfg.pi_vendor as vendor
  from test_pi_lock_families import generator_fixture
  from test_pi_dependencies import payload
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  source = "schemas/pi-lock.schema.json"
  inputs["profiles"]["pi-base"]["runtime_files"].append({"source": source, "path": "supervisor/" + source, "transform": "copy"})
  path.write_bytes(payload(inputs))
  original = vendor.checked; old_recipe = recipe_digest(workspace.repository, family="modern")
  old_manifest = (workspace.repository / "locks/pi-modern/manifest.json").read_bytes()
  def mutate(argv, **kwargs):
    result = original(argv, **kwargs)
    if argv[0:2] == ["npm", "install"]: (workspace.repository / source).write_text("changed selected source")
    return result
  monkeypatch.setattr(vendor, "checked", mutate)
  with pytest.raises(ConfigError, match="pi-runtime-files-stale"):
    PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert len(calls) == 3 and recipe_digest(workspace.repository, family="modern") == old_recipe
  assert (workspace.repository / "locks/pi-modern/manifest.json").read_bytes() == old_manifest


def test_invalid_declared_source_fails_before_resolver(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import PiBackend
  from test_pi_lock_families import generator_fixture
  from test_pi_dependencies import payload
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  inputs["profiles"]["pi-base"]["runtime_files"][0]["source"] = "agents/pi/runtime/missing.ts"
  path.write_bytes(payload(inputs)); before = (workspace.repository / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError): PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert calls == [] and (workspace.repository / "locks/pi-modern/manifest.json").read_bytes() == before


@pytest.mark.parametrize("target", ["runtime", "supervisor", "runtime/official-launch.mjs", "runtime/profile.json", "supervisor/scripts/pi-control.py"])
def test_assets_cannot_collide_with_repository_owned_file_namespaces(target):
  from agentcfg.pi_modern_launcher import REQUIRED, REQUIRED_SCHEMAS, validate_destinations
  piece = {"runtime_files": [{"path": path} for path in REQUIRED | REQUIRED_SCHEMAS], "source_ids": ["asset"]}
  manifest = {"platforms": ["darwin-arm64"], "sources": {"asset": {"kind": "asset", "target": target}}}
  with pytest.raises(ConfigError): validate_destinations(piece, manifest)
  manifest["sources"]["asset"]["target"] = "bin/selected-helper"
  validate_destinations(piece, manifest)


def test_missing_ai_lock_record_never_publishes_generated_manifest(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import PiBackend
  from test_pi_lock_families import generator_fixture
  from test_pi_dependencies import payload
  workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
  inputs["profiles"]["pi-base"]["ai_package"] = "absent-ai"
  path.write_bytes(payload(inputs)); before = (workspace.repository / "locks/pi-modern/manifest.json").read_bytes()
  with pytest.raises(ConfigError, match="pi-runtime-ai-missing"): PiBackend(profile="pi-base").resolve_lock(workspace.repository)
  assert len(calls) == 3 and (workspace.repository / "locks/pi-modern/manifest.json").read_bytes() == before


LIFECYCLE_SCHEMAS = tuple("supervisor/agents/pi/schemas/" + name + ".schema.json" for name in (
  "process-identity", "execution-lease", "workspace-write-lease", "termination-evidence", "stop-recovery-plan", "stop-recovery", "permission-policy", "operation-grant", "options"))
LINUX_LIFECYCLE = ("supervisor/scripts/pi-namespace-exec.py", "supervisor/src/agentcfg/pi_pid_namespace.py", "supervisor/src/agentcfg/pi_assets.py")


@pytest.mark.parametrize("missing", [*LIFECYCLE_SCHEMAS, *LINUX_LIFECYCLE])
def test_modern_linux_lifecycle_file_is_mandatory(missing):
  from agentcfg.pi_modern_launcher import REQUIRED, validate_destinations
  paths = REQUIRED | set(LIFECYCLE_SCHEMAS) | set(LINUX_LIFECYCLE)
  piece = {"runtime_files": [{"path": path} for path in sorted(paths - {missing})], "source_ids": []}
  with pytest.raises(ConfigError, match="pi-runtime-entrypoints-missing"):
    validate_destinations(piece, {"platforms": ["linux-x86_64"], "sources": {}})


def test_darwin_requires_schemas_but_not_linux_namespace_files():
  from agentcfg.pi_modern_launcher import REQUIRED, validate_destinations
  piece = {"runtime_files": [{"path": path} for path in sorted(REQUIRED | set(LIFECYCLE_SCHEMAS))], "source_ids": []}
  validate_destinations(piece, {"platforms": ["darwin-arm64"], "sources": {}})
  with pytest.raises(ConfigError): validate_destinations(piece, {"platforms": ["darwin-arm64", "linux-arm64"], "sources": {}})


@pytest.mark.parametrize("missing", [LIFECYCLE_SCHEMAS[0], LINUX_LIFECYCLE[0], "supervisor/scripts/pi-shell.py", "supervisor/agents/pi/schemas/options.schema.json"])
@pytest.mark.parametrize("phase", ["read-lock", "generate", "install"])
def test_missing_lifecycle_file_rejected_by_each_modern_entry(tmp_path, monkeypatch, missing, phase):
  from agentcfg.pi_dependencies import PiBackend
  from agentcfg.pi_modern_launcher import install_launcher
  from agentcfg.process import DependencyError
  from test_pi_capability_manifest import binding_repository, _write_manifest
  if phase == "generate":
    from test_pi_lock_families import generator_fixture
    from test_pi_dependencies import payload
    workspace, inputs, path, calls = generator_fixture(tmp_path, monkeypatch)
    rows = inputs["profiles"]["pi-base"]["runtime_files"]
    inputs["profiles"]["pi-base"]["runtime_files"] = [row for row in rows if row["path"] != missing]
    path.write_bytes(payload(inputs))
    manifest_path = workspace.repository / "locks/pi-modern/manifest.json"; previous = manifest_path.read_bytes()
    with pytest.raises(ConfigError, match="pi-runtime-entrypoints-missing"):
      PiBackend(profile="pi-base").resolve_lock(workspace.repository)
    assert manifest_path.read_bytes() == previous
  else:
    workspace, manifest = binding_repository(tmp_path)
    piece = manifest["profile_slices"]["pi-base"]
    piece["runtime_files"] = [row for row in piece["runtime_files"] if row["path"] != missing]
    if phase == "read-lock":
      _write_manifest(workspace.repository, manifest)
      with pytest.raises(ConfigError): PiBackend(profile="pi-base").read_lock(workspace.repository)
    else:
      stage = tmp_path / "stage"; ensure_private(stage)
      with pytest.raises(DependencyError): install_launcher(workspace.repository, stage, piece, manifest, runtime_identity="a" * 64)
      assert list(stage.iterdir()) == []


def test_shell_entry_is_explicit_and_generated_command_matches_receipt(tmp_path, monkeypatch):
  import hashlib
  from agentcfg.pi_dependencies import PiBackend
  from agentcfg.pi_modern_launcher import COMMANDS
  from test_pi_capability_manifest import binding_repository, fake_installer
  workspace, _ = binding_repository(tmp_path)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer([]))
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  commands = json.loads((root / "runtime/commands.json").read_bytes())
  assert commands == COMMANDS
  assert commands["programs"]["ordinary-shell"] == {
    "entrypoint": "supervisor/scripts/pi-shell.py", "kind": "external", "engine": "python"}
  receipt = json.loads((root / ".agentcfg-receipt.json").read_bytes())
  for path in ("runtime/commands.json", "supervisor/scripts/pi-shell.py"):
    file = root / path
    assert receipt["files"][path] == {"kind": "file", "mode": 0o600, "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}
    assert file.stat().st_mode & 0o777 == 0o600
  assert (root / "supervisor/scripts/pi-shell.py").read_bytes() == (workspace.repository / "scripts/pi-shell.py").read_bytes()


@pytest.mark.parametrize("fault", ["missing", "drift"])
def test_installed_shell_entry_drift_is_damaged(tmp_path, monkeypatch, fault):
  from agentcfg.pi_dependencies import PiBackend
  from test_pi_capability_manifest import binding_repository, fake_installer
  workspace, _ = binding_repository(tmp_path)
  monkeypatch.setattr("agentcfg.pi_dependencies.checked", fake_installer([]))
  backend = PiBackend(profile="pi-base"); lock = backend.read_lock(workspace.repository)
  result = backend.sync(workspace, lock); root = backend.root(workspace, result["identity"])
  entry = root / "supervisor/scripts/pi-shell.py"
  assert entry.exists()
  if fault == "missing": entry.unlink()
  else: entry.write_bytes(b"synthetic drift")
  assert backend.status(workspace, result["identity"]) == "damaged"


def test_missing_shell_entry_is_rejected_before_install():
  from agentcfg.pi_modern_launcher import REQUIRED, REQUIRED_SCHEMAS, LINUX_REQUIRED, validate_destinations
  paths = (REQUIRED | REQUIRED_SCHEMAS | LINUX_REQUIRED) - {"supervisor/scripts/pi-shell.py"}
  piece = {"runtime_files": [{"path": path} for path in sorted(paths)], "source_ids": []}
  with pytest.raises(ConfigError, match="pi-runtime-entrypoints-missing"):
    validate_destinations(piece, {"platforms": ["linux-x86_64"], "sources": {}})


def test_product_handoff_files_are_explicit_byte_bound_runtime_inputs(tmp_path):
  repository = Path(__file__).resolve().parents[1]
  declarations = json.loads((repository / "agents/pi/dependencies-modern.json").read_bytes())["profiles"]["pi-base"]["runtime_files"]
  expected = {"supervisor/src/agentcfg/" + name + ".py" for name in
    ("pi_shell_handoff", "pi_shell_start", "pi_shell_identity", "pi_shell_probe_info")}
  selected = [row for row in declarations if row["path"] in expected]
  assert {row["path"] for row in selected} == expected
  rows = lock_files(repository, selected)
  stage = tmp_path / "stage"; ensure_private(stage)
  install_files(repository, stage, rows)
  validate_files(stage, rows, generated=())
  for row in rows:
    target = stage / row["path"]
    assert target.read_bytes() == (repository / row["source"]).read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("target", ["runtime/official-file-resolution.mjs", "supervisor/src/agentcfg/pi_policy_approval.py",
  "supervisor/src/agentcfg/pi_shell_approval.py"])
def test_approval_modules_are_byte_bound_in_installed_base_closure(tmp_path, target):
  import hashlib
  import importlib
  import re
  from test_pi_base_recipe import cropped_package, clear_package
  stage, rows, package = cropped_package(tmp_path)
  repository = Path(__file__).resolve().parents[1]
  try:
    verify_sources(repository, rows)
    if target.startswith("runtime/"):
      admission = stage / "runtime/official-file-admission.mjs"
      assert b'"./official-file-resolution.mjs"' in admission.read_bytes()
      for relative in re.findall(rb'["\x27](\./[a-z0-9_-]+\.mjs)["\x27]', admission.read_bytes()):
        assert (admission.parent / relative.decode("ascii")).is_file()
    else:
      # 独立包名只搜索安装树；不能借用checkout中的agentcfg模块补齐缺失。
      module = importlib.import_module(package + "." + Path(target).stem)
      assert Path(module.__file__) == stage / target
      if target.endswith("pi_policy_approval.py"):
        assert module.aggregate_approval(["deterministic-policy", "reviewer"]) == "reviewer"
        assert module.aggregate_approval(["reviewer", "human"]) == "human"
      else:
        bridge = importlib.import_module(package + ".pi_admitted_shell")
        assert Path(bridge.__file__).is_relative_to(stage)
        assert bridge.classify_shell_approval is module.classify_shell_approval
      importlib.import_module(package + ".pi_operations")
    row = next(row for row in rows if row["path"] == target)
    raw = (repository / row["source"]).read_bytes()
    transformed = re.sub(rb'(["\x27]\./[a-z0-9_-]+)\.ts(["\x27])', rb'\1.mjs\2', raw) if row["transform"] == "ts-module" else raw
    assert row["input_digest"] == hashlib.sha256(raw).hexdigest()
    assert row["digest"] == hashlib.sha256(transformed).hexdigest()
    assert (stage / target).read_bytes() == transformed
    assert (stage / target).stat().st_mode & 0o777 == 0o600
  finally:
    clear_package(package)


def test_official_shell_ts_sources_are_explicit_and_transformed_byte_bound(tmp_path):
  repository = Path(__file__).resolve().parents[1]
  declarations = json.loads((repository / "agents/pi/dependencies-modern.json").read_bytes())["profiles"]["pi-base"]["runtime_files"]
  names = ("official-shell-tool", "shell-operation-executor")
  expected = [{"source": "agents/pi/runtime/" + name + ".ts", "path": "runtime/" + name + ".mjs", "transform": "ts-module"} for name in names]
  assert all(row in declarations for row in expected)
  selected = [row for row in declarations if row["source"].startswith("agents/pi/runtime/")]
  locked = lock_files(repository, selected)
  stage = tmp_path / "shell-ts-stage"; ensure_private(stage)
  install_files(repository, stage, locked)
  validate_files(stage, locked, generated=())
  import re
  for row in locked:
    target = stage / row["path"]
    raw = (repository / row["source"]).read_bytes()
    assert target.read_bytes() == re.sub(rb'([\"\x27]\./[a-z0-9_-]+)\.ts([\"\x27])', rb'\1.mjs\2', raw)
    assert target.stat().st_mode & 0o777 == 0o600
    # Base 不安装 Full 条件动态入口；静态 import/from 必须在本切片完整存在。
    for _, relative in re.findall(rb'(?:\bfrom\s+|\bimport\s*)([\"\x27])(\./[a-z0-9_-]+\.mjs)\1', target.read_bytes()):
      assert (target.parent / relative.decode("ascii")).is_file()
  assert b'"./shell-operation-executor.mjs"' in (stage / "runtime/official-shell-tool.mjs").read_bytes()
  assert b'"./private-files.mjs"' in (stage / "runtime/shell-operation-executor.mjs").read_bytes()
  assert not any("node_modules" in row["path"] for row in locked)


@pytest.mark.parametrize("missing", ["runtime/official-shell-tool.mjs", "runtime/shell-operation-executor.mjs"])
def test_official_shell_ts_missing_or_drifted_install_is_rejected(tmp_path, missing):
  repository = Path(__file__).resolve().parents[1]
  declarations = json.loads((repository / "agents/pi/dependencies-modern.json").read_bytes())["profiles"]["pi-base"]["runtime_files"]
  selected = [row for row in declarations if row["source"].startswith("agents/pi/runtime/")]
  rows = lock_files(repository, selected)
  assert missing in {row["path"] for row in rows}
  stage = tmp_path / "stage"; ensure_private(stage); install_files(repository, stage, rows)
  target = stage / missing
  target.write_text("synthetic drift")
  with pytest.raises(Conflict): validate_files(stage, rows, generated=())
  target.unlink()
  with pytest.raises(Conflict): validate_files(stage, rows, generated=())


def test_cropped_base_shell_options_schema_is_real_and_byte_bound(tmp_path):
  import importlib
  from test_pi_base_recipe import cropped_package, clear_package
  stage, rows, package = cropped_package(tmp_path)
  target = "supervisor/agents/pi/schemas/options.schema.json"
  try:
    row = next(row for row in rows if row["path"] == target)
    assert row["source"] == "agents/pi/schemas/options.schema.json" and row["transform"] == "copy"
    assert (stage / target).read_bytes() == (Path(__file__).resolve().parents[1] / row["source"]).read_bytes()
    catalog = importlib.import_module(package + ".pi_catalog")
    staged_error = importlib.import_module(package + ".schema").ConfigError
    catalog.validate("options", {"external_tools": {"shell": {"executable": "/usr/bin/bash", "version": "synthetic-probe"}}})
    with pytest.raises(staged_error):
      catalog.validate("options", {"external_tools": {"shell": {"executable": "/usr/bin/bash", "unknown": "synthetic"}}})
    (stage / target).unlink()
    with pytest.raises(staged_error): catalog.read_schema("options")
  finally: clear_package(package)


@pytest.mark.parametrize("fault", ["alias", "transform", "escape", "nested"])
def test_license_namespace_requires_exact_copy_mapping(tmp_path, fault):
  root, stage, declarations = fixture(tmp_path)
  source = root / "agents/pi/build/licenses/pi-modern/LICENSE"; source.parent.mkdir(parents=True); source.write_bytes(b"synthetic body")
  row = {"source":"agents/pi/build/licenses/pi-modern/LICENSE", "path":"licenses/pi-modern/LICENSE", "transform":"copy"}
  if fault == "alias":row["path"]="licenses/pi-modern/OTHER"
  if fault == "transform":row["transform"]="ts-module"
  if fault == "escape":row["source"]="agents/pi/build/licenses/pi-modern/../LICENSE"
  if fault == "nested":row["source"]="agents/pi/build/licenses/pi-modern/sub/LICENSE"
  with pytest.raises(ConfigError):lock_files(root,[row])
  assert list(stage.iterdir())==[]


def test_own_license_directory_has_exact_selected_closure(tmp_path):
  root, stage, declarations = fixture(tmp_path)
  source = root / "agents/pi/build/licenses/pi-modern/LICENSE";source.parent.mkdir(parents=True);source.write_bytes(b"synthetic body")
  declarations.append({"source":"agents/pi/build/licenses/pi-modern/LICENSE", "path":"licenses/pi-modern/LICENSE", "transform":"copy"})
  rows=lock_files(root,declarations);install_files(root,stage,rows);validate_files(stage,rows,generated=())
  from agentcfg.storage import Tree
  with Tree(stage) as tree:tree.write_state("licenses/pi-modern/extra",b"unselected")
  with pytest.raises(Conflict):validate_files(stage,rows,generated=())


@pytest.mark.parametrize("fault", ["ancestor-symlink", "own-symlink", "extra-file", "extra-directory"])
def test_own_license_closure_rejects_unsafe_or_extra_entries_with_asset_sibling(tmp_path, fault):
  root, stage, declarations = fixture(tmp_path)
  source = root / "agents/pi/build/licenses/pi-modern/LICENSE"
  source.parent.mkdir(parents=True);source.write_bytes(b"synthetic own body")
  declarations.append({"source":"agents/pi/build/licenses/pi-modern/LICENSE", "path":"licenses/pi-modern/LICENSE", "transform":"copy"})
  rows = lock_files(root,declarations);install_files(root,stage,rows)
  from agentcfg.storage import Tree
  with Tree(stage) as tree:tree.write_state("licenses/fixture-asset/0-LICENSE",b"synthetic asset body")
  validate_files(stage,rows,generated=())
  if fault == "ancestor-symlink":
    (stage / "licenses").rename(stage / "other-licenses")
    (stage / "licenses").symlink_to("other-licenses",target_is_directory=True)
  elif fault == "own-symlink":
    (stage / "licenses/pi-modern").rename(stage / "licenses/other-modern")
    (stage / "licenses/pi-modern").symlink_to("other-modern",target_is_directory=True)
  elif fault == "extra-file":
    with Tree(stage) as tree:tree.write_state("licenses/pi-modern/extra",b"unselected")
  else:(stage / "licenses/pi-modern/extra").mkdir(mode=0o700)
  with pytest.raises(Conflict):validate_files(stage,rows,generated=())


def test_full_original_delegate_assets_are_normal_declared_install_inputs(tmp_path):
  from agentcfg.pi_runtime_files import DELEGATE_ASSETS
  from agentcfg.pi_delegate import DelegateController
  from agentcfg.pi_supervisor import Principal
  from test_pi_delegate import fixture as controller_fixture
  root = Path(__file__).resolve().parents[1]
  controller, host, args, _ = controller_fixture(tmp_path)
  rows = [{"source": name, "path": "supervisor/" + name, "transform": "copy"} for name in sorted(DELEGATE_ASSETS)]
  stage = tmp_path / "installed-assets"; ensure_private(stage)
  locked = lock_files(root, rows); install_files(root, stage, locked); validate_files(stage, locked, generated=())
  # 原controller仍调用原完整v2 validator，读取正常安装的原schema；不替换validator。
  selected = DelegateController(host, schemas=stage / "supervisor/shared/skills/model-delegate/schemas")
  request = selected.prepare(Principal("manager"), args)
  assert request["schema_version"] == 2
  assert all((stage / row["path"]).read_bytes() == (root / row["source"]).read_bytes() for row in rows)


@pytest.mark.parametrize("fault", ["unknown-source", "wrong-target"])
def test_full_delegate_asset_mapping_remains_exact_closed(tmp_path, fault):
  root, stage, rows = fixture(tmp_path)
  row = {"source": "shared/skills/model-delegate/presets/general.md", "path": "supervisor/shared/skills/model-delegate/presets/general.md", "transform": "copy"}
  if fault == "unknown-source": row["source"] = "shared/skills/model-delegate/presets/unknown.md"
  else: row["path"] = "runtime/general.md"
  with pytest.raises(ConfigError): lock_files(root, [row])
  assert list(stage.iterdir()) == []

def test_modern_task_auxiliary_is_full_only_normal_declared_closure():
  from agentcfg.pi_modern_launcher import commands
  root = Path(__file__).resolve().parents[1]
  document = json.loads((root / "agents/pi/dependencies-modern.json").read_bytes())
  base = document["profiles"]["pi-base"]["runtime_files"]
  full = document["profiles"]["pi-full"]["runtime_files"]
  modules = "model_delegate model_delegate_context pi_delegate pi_delegate_files pi_delegate_policy pi_lock_metadata pi_modern_launcher pi_node_archive pi_node_asset pi_owner_origin pi_runtime_files pi_runtime_packages pi_task_keeper_sources runtime_packages pi_delegate_spawn model_delegate_backends pi_worker_protocol".split()
  sources = {"src/agentcfg/pi_auxiliary.py", "src/agentcfg/pi_trusted_checks.py", "src/agentcfg/pi_worker_files.py", "agents/pi/runtime/workspace-main.ts",
    "agents/pi/schemas/runtime-receipt.schema.json", *("src/agentcfg/" + name + ".py" for name in modules)}
  assert not sources & {row["source"] for row in base}
  assert sources <= {row["source"] for row in full}
  plain = commands({"capability_ids": ["native-tools"]})
  assert not {"workspace", "check"} & plain["programs"].keys()
  selected = commands({"capability_ids": ["native-tools", "task-workflow"]})
  assert selected["programs"]["workspace"] == {"entrypoint": "runtime/workspace-main.mjs", "kind": "external", "engine": "node"}
  assert selected["programs"]["check"] == {"entrypoint": "supervisor/scripts/pi-project-check", "kind": "check", "engine": "python"}
