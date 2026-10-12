"""真实Base源码声明的离线闭包；不安装npm包、不启动SDK或模型。"""
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agentcfg import pi_capabilities, pi_runtime_files, pi_vendor
from agentcfg.pi_modern_launcher import validate_destinations
from agentcfg.schema import ConfigError
from agentcfg.storage import ensure_private


ROOT = Path(__file__).resolve().parents[1]
DIRECT = {"pi-host", "pi-ai", "pi-tui", "pi-agent-core", "pi-runtime-ui", "colorful-footer", "loop-guard", "pi-todo", "pi-bwrap-linux-x86_64", "pi-node-linux-x86_64"}


def inputs():
  return pi_vendor.read_inputs(ROOT, family="modern", current_profiles=("pi-base",))


def source_records(recipes, document):
  evidence = json.loads((ROOT / "agents/pi/build/licenses/pi-modern/SOURCE.json").read_bytes())
  sources = {}
  for key in document["profiles"]["pi-base"]["source_ids"]:
    source = document["sources"][key]
    if source["kind"] == "asset": sources[key] = source
    elif source["kind"] == "local": sources[key] = pi_vendor.build_archive(ROOT, recipes["sources"][key])[1]
    else:
      row = evidence["packages"][key]
      sources[key] = {**{name: source[name] for name in ("kind", "package", "version", "license_files", "license_sources")},
        "resolved": row["resolved"], "integrity": row["integrity"]}
  return sources


def selection_inputs():
  recipes, document = inputs()
  profile = document["profiles"]["pi-base"]
  bindings = document["capability_bindings"]
  resources = {kind: [] for kind in pi_capabilities.RESOURCE_KINDS}
  chosen = {row["provider_id"] for row in bindings["selections"]["pi-base"]["bindings"]}
  for source_id in profile["source_ids"]:
    source = document["sources"][source_id]
    for kind, paths in source.get("resources", {}).items():
      for index, path in enumerate(paths):
        resource_id = source_id if len(paths) == 1 else source_id + "-" + str(index)
        owners = [provider["capability_id"] for name, provider in bindings["providers"].items() if name in chosen and resource_id in provider["resource_ids"]]
        assert len(owners) == 1
        resources[kind].append({"id": resource_id, "capability_id": owners[0], "path": "candidate/node_modules/" + source["package"] + "/" + path})
  piece = {"engine": profile["engine"], "source_ids": profile["source_ids"], "resource_manifest": resources}
  # 仅做真实来源与能力选择的一致性投影，身份为合成值，不伪造完整npm锁。
  lock = SimpleNamespace(identity="f" * 64, metadata={"sources": source_records(recipes, document), "profile_slices": {"pi-base": piece}})
  return bindings, lock


def test_real_base_inputs_select_only_explicit_base_sources_and_runtime_ui():
  recipes, document = inputs()
  assert document["schema_version"] == 2 and "linux-x86_64" in document["platforms"]
  assert set(document["profiles"]["pi-base"]["source_ids"]) == DIRECT
  assert recipes["sources"]["pi-runtime-ui"]["source_path"] == "agents/pi/packages/runtime-ui"
  assert document["sources"]["pi-runtime-ui"]["version"] == "2.0.0"
  assert {source["package"]: source["version"] for key, source in document["sources"].items() if key in DIRECT and source["kind"] == "npm"} == {
    "@earendil-works/pi-coding-agent": "1.0.1", "@earendil-works/pi-ai": "1.0.2",
    "@earendil-works/pi-tui": "1.0.2", "@earendil-works/pi-agent-core": "1.0.2"}
  rows = pi_runtime_files.lock_files(ROOT, document["profiles"]["pi-base"]["runtime_files"])
  validate_destinations({"runtime_files": rows, "source_ids": sorted(DIRECT)}, document)
  assert not any(token in row["source"] for row in rows for token in ("pi_delegate", "pi_worker", "pi_readseek", "pi_web", "task-keeper", "durable"))


def test_real_source_archives_and_fixed_npm_identities_match_candidate_bindings():
  path = ROOT / "locks/pi-modern/manifest.json"
  before = path.read_bytes() if path.exists() else None
  bindings, lock = selection_inputs()
  selected = pi_capabilities.validate_selection(bindings["catalog"], bindings["providers"], bindings["selections"]["pi-base"],
    lock, host_version="1.0.1", engine="node")
  assert selected.state == "current" and {row[0] for row in selected.source_expectations} == DIRECT
  assert {row for kind, ids in selected.resource_expectations for row in ids} == {"colorful-footer", "loop-guard", "pi-todo"}
  assert (path.read_bytes() if path.exists() else None) == before


@pytest.mark.parametrize("state", ["current", "accepted"])
def test_real_unverified_provider_selection_cannot_be_promoted_by_changing_state(state):
  bindings, lock = selection_inputs()
  bindings = deepcopy(bindings)
  for provider in bindings["providers"].values():
    provider.update(verified_host_versions=[], candidate_host_versions=["1.0.1"])
  selection = deepcopy(bindings["selections"]["pi-base"]); selection["state"] = state
  with pytest.raises(ConfigError):
    pi_capabilities.validate_selection(bindings["catalog"], bindings["providers"], selection, lock,
      host_version="1.0.1", engine="node", accepted_binding_digest="a" * 64)


def test_unverified_candidate_round_trips_through_generator_schema_and_reader(tmp_path, monkeypatch):
  from agentcfg.pi_dependencies import PiBackend
  from agentcfg.process import DependencyError
  from test_pi_dependencies import payload
  from test_pi_lock_families import generator_fixture
  workspace, document, path, calls = generator_fixture(tmp_path, monkeypatch)
  provider = document["capability_bindings"]["providers"]["native-provider"]
  provider.update(verified_host_versions=[], candidate_host_versions=[document["sources"]["pi-host"]["version"]])
  path.write_bytes(payload(document))
  backend = PiBackend(profile="pi-base")
  generated = backend.resolve_lock(workspace.repository)
  reread = backend.read_lock(workspace.repository)
  assert reread.identity == generated.identity and len(calls) == 3
  assert reread.metadata["capability_bindings"]["providers"]["native-provider"]["verified_host_versions"] == []
  assert reread.validated_bindings["pi-base"].state == "candidate"
  monkeypatch.setattr("agentcfg.pi_lifecycle.guard", lambda *_: pytest.fail("candidate must fail before writes"))
  with pytest.raises(DependencyError): backend.sync(workspace, reread)


def cropped_package(tmp_path):
  _, document = inputs()
  rows = pi_runtime_files.lock_files(ROOT, document["profiles"]["pi-base"]["runtime_files"])
  stage = tmp_path / "cropped"; ensure_private(stage)
  pi_runtime_files.install_files(ROOT, stage, rows)
  pi_runtime_files.validate_files(stage, rows, generated=())
  package = "_pi_base_cropped_test"
  directory = stage / "supervisor/src/agentcfg"
  spec = importlib.util.spec_from_file_location(package, directory / "__init__.py", submodule_search_locations=[str(directory)])
  module = importlib.util.module_from_spec(spec); sys.modules[package] = module; spec.loader.exec_module(module)
  return stage, rows, package


def clear_package(package):
  for name in list(sys.modules):
    if name == package or name.startswith(package + "."): del sys.modules[name]


def test_cropped_python_tree_imports_its_own_modules_and_loads_real_permission_schemas(tmp_path):
  stage, rows, package = cropped_package(tmp_path)
  try:
    for row in rows:
      if row["source"].startswith("src/agentcfg/") and not row["source"].endswith("/__init__.py"):
        module = importlib.import_module(package + "." + Path(row["source"]).stem)
        assert Path(module.__file__).is_relative_to(stage)
    catalog = importlib.import_module(package + ".pi_catalog")
    for name in ("process-identity", "execution-lease", "workspace-write-lease", "termination-evidence",
        "stop-recovery-plan", "stop-recovery", "permission-policy", "operation-grant"):
      assert catalog.read_schema(name)["type"] == "object"
    guarded = importlib.import_module(package + ".pi_guarded_files")
    policy = guarded.FilePolicy(policy={"schema_version": 1, "default": "deny", "rules": []}, roots={},
      ceiling={"allowed_tools": [], "read_roots": [], "write_roots": []},
      grant={"executor": "managed-process", "context_mode": "fresh", "nested": False, "grant_generation": 1},
      mode="managed", verify=lambda *_: True, workspace=None)
    assert policy.policy["default"] == "deny"
  finally: clear_package(package)


def test_missing_cropped_python_dependency_cannot_be_filled_from_checkout(tmp_path):
  stage, _, package = cropped_package(tmp_path)
  try:
    (stage / "supervisor/src/agentcfg/pi_guarded_files.py").unlink()
    with pytest.raises(ModuleNotFoundError): importlib.import_module(package + ".pi_operations")
  finally: clear_package(package)


SHELL_MODULES = ("pi_admitted_shell", "pi_shell_preparation", "pi_shell_sources", "pi_shell_mounts",
  "pi_shell_seccomp", "pi_shell_script", "pi_shell_argv", "pi_shell_execution", "pi_shell_worker",
  "pi_shell_handoff", "pi_shell_start", "pi_shell_identity", "pi_shell_probe_info")


def test_base_declares_and_imports_exact_shell_closure_without_activation(tmp_path):
  import inspect
  stage, rows, package = cropped_package(tmp_path)
  try:
    paths = {row["path"] for row in rows}
    assert "supervisor/scripts/pi-shell.py" in paths
    for name in SHELL_MODULES:
      assert "supervisor/src/agentcfg/" + name + ".py" in paths
      module = importlib.import_module(package + "." + name)
      assert Path(module.__file__).is_relative_to(stage)
    control = importlib.import_module(package + ".pi_admission_control")
    assert inspect.signature(control.FileAdmissionControl).parameters["shell_bridge_factory"].default is None
    assert (stage / "supervisor/scripts/pi-shell.py").read_bytes() == (ROOT / "scripts/pi-shell.py").read_bytes()
    assert (stage / "supervisor/scripts/pi-shell.py").stat().st_mode & 0o777 == 0o600
  finally: clear_package(package)


@pytest.mark.parametrize("missing", ["pi_shell_sources", "pi_shell_seccomp", "pi_shell_script", "pi_shell_argv", "pi_shell_mounts", "pi_shell_handoff"])
def test_missing_shell_transitive_dependency_never_uses_checkout(tmp_path, missing):
  stage, _, package = cropped_package(tmp_path)
  try:
    (stage / "supervisor/src/agentcfg" / (missing + ".py")).unlink()
    with pytest.raises(ModuleNotFoundError) as caught:
      importlib.import_module(package + ".pi_shell_worker")
    assert caught.value.name == package + "." + missing
  finally: clear_package(package)


def test_base_explicitly_declares_product_handoff_bootstrap_modules():
  document = json.loads((ROOT / "agents/pi/dependencies-modern.json").read_bytes())
  rows = document["profiles"]["pi-base"]["runtime_files"]
  for name in ("pi_shell_handoff", "pi_shell_start", "pi_shell_identity", "pi_shell_probe_info"):
    assert {"source": "src/agentcfg/" + name + ".py", "path": "supervisor/src/agentcfg/" + name + ".py",
      "transform": "copy"} in rows


def test_shell_bootstrap_prepends_only_fixed_dependency_path(tmp_path, monkeypatch):
  import runpy
  from types import ModuleType
  stage = tmp_path / "supervisor/scripts"; stage.mkdir(parents=True)
  entry = stage / "pi-shell.py"; entry.write_bytes((ROOT / "scripts/pi-shell.py").read_bytes())
  worker = ModuleType("agentcfg.pi_shell_worker")
  worker.main = lambda: pytest.fail("bootstrap import must not execute worker")
  monkeypatch.setitem(sys.modules, "agentcfg.pi_shell_worker", worker)
  monkeypatch.setattr(sys, "path", list(sys.path))
  monkeypatch.setattr(sys, "dont_write_bytecode", sys.dont_write_bytecode)
  monkeypatch.setenv("PYTHONPATH", str(tmp_path / "untrusted-python"))
  runpy.run_path(str(entry), run_name="_bootstrap_import_test")
  assert sys.path[:2] == [str(stage.parent / "src"), "/.rotom-shell-bootstrap/python-deps"]
  assert str(tmp_path / "untrusted-python") not in sys.path
  assert sys.dont_write_bytecode is True


@pytest.mark.parametrize("missing", ["pi_shell_handoff", "pi_shell_identity", "pi_shell_probe_info"])
def test_missing_product_start_dependency_never_uses_checkout(tmp_path, missing):
  stage, _, package = cropped_package(tmp_path)
  try:
    (stage / "supervisor/src/agentcfg" / (missing + ".py")).unlink()
    with pytest.raises(ModuleNotFoundError) as caught:
      importlib.import_module(package + ".pi_shell_start")
    assert caught.value.name == package + "." + missing
  finally: clear_package(package)


def test_optional_ordinary_prompts_preserve_engineering_material_and_source_provenance():
  import hashlib
  import tomllib
  from test_pi_profile_projection import resolved
  from agentcfg.pi import PiAdapter
  names = ("commit", "debug", "docs", "explain", "perf", "pr", "refactor", "security", "test")
  manifest = json.loads((ROOT / "agents/pi/migration/resource-manifest.json").read_bytes())
  rows = {row["target_path"]: row for row in manifest["files"]}
  agent = tomllib.loads((ROOT / "agents/pi/agent.toml").read_text())
  for name in names:
    legacy_path = "agents/pi/prompts/" + name + ".md"
    ordinary_path = "agents/pi/prompts/ordinary/" + name + ".md"
    legacy = (ROOT / legacy_path).read_text()
    modern = (ROOT / ordinary_path).read_text()
    # 路由之外的工程步骤、示例和相对引用完整保留；两种profile不共用改写后的模板。
    assert modern.split("## 执行路由\n", 1)[0] == legacy.split("## 执行路由\n", 1)[0]
    assert "kernel_task" in legacy and "model_delegate" in legacy
    assert agent["resources"][name]["path"] == legacy_path
    assert agent["resources"]["ordinary-" + name]["path"] == ordinary_path
    for field in ("source_path", "source_git_blob", "source_mode"):
      assert rows[ordinary_path][field] == rows[legacy_path][field]
    for path in (legacy_path, ordinary_path):
      assert rows[path]["target_sha256"] == hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
  artifacts = PiAdapter(ROOT).render(resolved())
  paths = {a.target.path for a in artifacts if a.target.path.startswith("pi-home/prompts/")}
  assert paths == {"pi-home/prompts/" + name + ".md" for name in ("implement", "plan", "review")}


def test_real_bundle_retains_complete_registry_and_unresolved_scope():
  _, document = inputs()
  declarations = document["profiles"]["pi-base"]["runtime_files"]
  selected = {row["path"] for row in declarations}
  assert {"REGISTRY-pi-base.json", "SOURCE.json", "TRANSITIVE-SOURCE.json", "SUPPLEMENT-SOURCE.json", "LICENSE", "APACHE-2.0.txt", "ESBUILD-LICENSE.md"} <= {name.removeprefix("licenses/pi-modern/") for name in selected if name.startswith("licenses/pi-modern/")}
  registry=json.loads((ROOT/"agents/pi/build/licenses/pi-modern/REGISTRY-pi-base.json").read_bytes())
  assert len(registry["packages"]) == 145
  assert sum(row["status"] == "optional-platform-excluded" for row in registry["packages"]) == 25
  assert not any(row["status"] == "body-scope-unresolved" for row in registry["packages"])
  # Base声明已选择独立完整许可清单；保留旧全量审计，不能把Full未决来源算作Base依赖。
  historical = json.loads((ROOT/"agents/pi/build/licenses/pi-modern/REGISTRY.json").read_bytes())
  assert {(row["name"], row["version"]) for row in historical["packages"] if row["status"] == "body-scope-unresolved"} == {("proxy-agent-negotiate", "1.1.0")}
  assert not any(row["name"] == "proxy-agent-negotiate" for row in registry["packages"])
  standard = next(row for row in registry["packages"] if row["name"] == "standardwebhooks")
  assert standard["status"] == "fixed-source-body" and standard["archive_files"] == []
  assert standard["supplemental_files"] == [{"path":"licenses/pi-modern/STANDARDWEBHOOKS-1.1.1-LICENSE.txt", "sha256":"5ec8c7b26b64d881a6706617bed25c049f97f2f35de034c756de8546fd6dbe27"}]
  assert declarations.count({"source":"agents/pi/build/licenses/pi-modern/STANDARDWEBHOOKS-1.1.1-LICENSE.txt", "path":"licenses/pi-modern/STANDARDWEBHOOKS-1.1.1-LICENSE.txt", "transform":"copy"}) == 1
  assert all(not row["resolved"].startswith("file:") for row in registry["packages"])
