"""权限运行包的纯校验；资产是普通哨兵文件，不可执行宿主。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.omp_permission_runtime import (
  validate_manifest, verify_runtime_asset, combined_identity, read_permission_runtime,
)
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from jsonschema import Draft202012Validator


def manifest():
  value = {"schemaVersion": 1, "variant": "permission-control-v1", "upstreamIdentity": "a" * 64,
    "bridgeAbi": "permission-control/v1", "patches": [{"path": "patches/one.patch", "sha256": "b" * 64}],
    "buildReceiptDigest": "c" * 64, "pluginDigest": "d" * 64,
    "assets": {"linux-x64": {"cacheKey": "sha256/" + "e" * 64, "sha256": "e" * 64, "size": 42}}}
  value["identity"] = hashlib.sha256(json_bytes(value)).hexdigest()
  return value


def resign(value):
  value.pop("identity", None)
  value["identity"] = hashlib.sha256(json_bytes(value)).hexdigest()
  return value


def test_runtime_manifest_accepts_synthetic_complete_identity():
  value = manifest()
  assert validate_manifest(value) == value


def test_well_formed_unsupported_bridge_abi_is_dependency_failure():
  value = manifest()
  value["bridgeAbi"] = "permission-control/v99"
  resign(value)
  with pytest.raises(DependencyError) as error: validate_manifest(value)
  assert error.value.exit_code == 5


@pytest.mark.parametrize("change", ["unknown", "digest", "duplicate-patch", "escaping-patch",
  "absolute-cache", "wrong-cache", "newline-digest", "bool-size"])
def test_runtime_manifest_rejects_ambiguous_or_changed_structure(change):
  value = manifest()
  if change == "unknown": value["secret-key-sentinel"] = True
  elif change == "digest": value["identity"] = "f" * 64
  elif change == "duplicate-patch": value["patches"].append({**value["patches"][0], "sha256": "f" * 64})
  elif change == "escaping-patch": value["patches"][0]["path"] = "../secret-sentinel"
  elif change == "absolute-cache": value["assets"]["linux-x64"]["cacheKey"] = "/tmp/secret-sentinel"
  elif change == "wrong-cache": value["assets"]["linux-x64"]["cacheKey"] = "sha256/" + "f" * 64
  elif change == "newline-digest": value["pluginDigest"] += "\n"
  else: value["assets"]["linux-x64"]["size"] = True
  if change != "digest": resign(value)
  with pytest.raises(ConfigError) as error: validate_manifest(value)
  assert error.value.exit_code == 2
  assert "sentinel" not in str(error.value)


def test_missing_platform_is_dependency_failure(tmp_path):
  value = manifest()
  value["assets"] = {}
  resign(value)
  validate_manifest(value)
  with pytest.raises(DependencyError) as error: verify_runtime_asset(value, "linux-x64", tmp_path)
  assert error.value.exit_code == 5


@pytest.mark.parametrize("change", ["none", "changed", "link", "missing"])
def test_asset_reads_actual_bytes_without_execution(tmp_path, change):
  value = manifest()
  raw = b"inert synthetic host sentinel"
  digest = hashlib.sha256(raw).hexdigest()
  value["assets"]["linux-x64"] = {"cacheKey": "sha256/" + digest, "sha256": digest, "size": len(raw)}
  resign(value)
  path = tmp_path / "sha256" / digest
  path.parent.mkdir()
  path.write_bytes(raw)
  if change == "changed": path.write_bytes(b"secret-sentinel")
  elif change == "missing": path.unlink()
  elif change == "link":
    other = tmp_path / "redirected"
    path.rename(other)
    path.symlink_to(other)
  if change == "none":
    assert verify_runtime_asset(value, "linux-x64", tmp_path) == path
  else:
    with pytest.raises(DependencyError): verify_runtime_asset(value, "linux-x64", tmp_path)


def test_combined_identity_binds_each_delivery_component():
  original = ("a" * 64, "b" * 64, "linux-x64", "c" * 64)
  baseline = combined_identity(*original)
  assert len(baseline) == 64
  for index in range(4):
    changed = list(original)
    changed[index] = "linux-arm64" if index == 2 else "d" * 64
    assert combined_identity(*changed) != baseline


@pytest.fixture
def synthetic_runtime(tmp_path):
  from test_omp_permission_build_inputs import build_inputs
  repository, cache = tmp_path / "repository", tmp_path / "artifacts"
  def write(path, raw):
    target = repository / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()
  source = build_inputs()
  plugin_path = "agents/omp/packages/omp-permission-control/index.ts"
  plugin_entry = {"path": plugin_path, "target": "packages/omp-permission-control/index.ts",
    "sha256": write(plugin_path, b"synthetic inert plugin"), "executable": False}
  plugin_digest = hashlib.sha256(json_bytes([plugin_entry])).hexdigest()
  source["dependencyLock"] = {"path": "locks/omp/upstream/bun.lock", "sha256": write("locks/omp/upstream/bun.lock", b"synthetic dependency lock")}
  input_digest = write("agents/omp/patches/permission-control/build-inputs.lock.json", json_bytes(source))
  patch = "agents/omp/patches/permission-control/0001-host-bridge.patch"
  patches = [{"path": patch, "sha256": write(patch, b"synthetic inert patch")}]
  write("agents/omp/patches/permission-control/series", b"0001-host-bridge.patch\n")
  scripts = []
  for path in ("agents/omp/build-permission-control.py", "src/agentcfg/omp_permission_build.py",
      "src/agentcfg/omp_permission_build_inputs.py", "schemas/omp-permission-build-inputs.schema.json"):
    scripts.append({"path": path, "sha256": write(path, b"synthetic inert build source")})
  raw = b"synthetic inert standalone"
  asset_digest = hashlib.sha256(raw).hexdigest()
  asset = {"cacheKey": "sha256/" + asset_digest, "sha256": asset_digest, "size": len(raw)}
  (cache / "sha256").mkdir(parents=True)
  (cache / asset["cacheKey"]).write_bytes(raw)
  receipt = {"schemaVersion": 1, "variant": "permission-control-v1", "platform": "linux-x64",
    "bridgeAbi": "permission-control/v1", "upstreamIdentity": "a" * 64,
    "upstreamSource": source["upstreamSource"], "dependencyLock": source["dependencyLock"],
    "buildInputsDigest": input_digest, "tools": source["tools"], "dependencyArtifacts": source["dependencyArtifacts"],
    "patches": patches, "buildScripts": scripts, "pluginDigest": plugin_digest, "asset": asset,
    "networkPolicy": "linux-seccomp-no-inet",
    "manager": {"implementation": "CPython", "version": "3.11.0", "sha256": "9" * 64}}
  value = manifest()
  value.update(patches=patches, pluginDigest=plugin_digest, assets={"linux-x64": asset},
    buildReceiptDigest=write("locks/omp/permission-control/build-receipt.json", json_bytes(receipt)))
  resign(value)
  write("locks/omp/permission-control/manifest.json", json_bytes(value))
  return repository, cache, value, receipt, write


def check_delivery(repository, cache, **changes):
  value = json.loads((repository / "locks/omp/permission-control/manifest.json").read_text())
  args = {"platform": "linux-x64", "upstream_identity": "a" * 64, "plugin_digest": value["pluginDigest"],
    "artifact_cache": cache}
  args.update(changes)
  return read_permission_runtime(repository, **args)


def test_complete_synthetic_delivery_chain_is_read_only(synthetic_runtime):
  repository, cache, value, _, _ = synthetic_runtime
  before = {str(p): p.read_bytes() for folder in (repository, cache) for p in folder.rglob("*") if p.is_file()}
  result = check_delivery(repository, cache)
  assert result["identity"] == combined_identity("a" * 64, value["identity"], "linux-x64", value["pluginDigest"])
  assert before == {str(p): p.read_bytes() for folder in (repository, cache) for p in folder.rglob("*") if p.is_file()}


def test_series_cannot_follow_a_link_even_when_bytes_match(synthetic_runtime, tmp_path):
  repository, cache, *_ = synthetic_runtime
  series = repository / "agents/omp/patches/permission-control/series"
  outside = tmp_path / "unmanaged-series"
  series.rename(outside)
  series.symlink_to(outside)
  with pytest.raises(DependencyError) as error: check_delivery(repository, cache)
  assert error.value.exit_code == 5


def test_committed_fixture_is_reproducible_and_every_digest_has_actual_bytes(tmp_path):
  import shutil
  from generate_omp_permission_fixture import generate
  from agentcfg.omp_permission_build import permission_plugin_digest
  fixture = Path(__file__).parent / "fixtures/omp/permission-control/runtime"
  generated = tmp_path / "generated"
  generate(generated)
  expected = {path.relative_to(fixture).as_posix(): path.read_bytes()
    for path in fixture.rglob("*") if path.is_file() and path.name != "README.md"}
  assert expected == {path.relative_to(generated).as_posix(): path.read_bytes()
    for path in generated.rglob("*") if path.is_file()}
  receipt = json.loads(expected["build-receipt.json"])
  pairs = [("inputs/upstream-identity.json", receipt["upstreamIdentity"]),
    ("inputs/source.txt", receipt["upstreamSource"]["archiveSha256"]),
    ("inputs/manager.txt", receipt["manager"]["sha256"])]
  for group, directory in (("tools", "tools"), ("dependencyArtifacts", "dependencies")):
    for item in receipt[group]:
      path = "inputs/" + directory + "/" + item["cacheKey"]
      pairs.append((path, item["sha256"]))
      if "size" in item: assert len(expected[path]) == item["size"]
  for path, digest in pairs:
    assert hashlib.sha256(expected[path]).hexdigest() == digest
  repository = tmp_path / "repository"
  shutil.copytree(generated / "source", repository)
  lock = repository / "locks/omp/permission-control"
  lock.mkdir(parents=True)
  for name in ("manifest.json", "build-receipt.json"):
    shutil.copyfile(generated / name, lock / name)
  result = read_permission_runtime(repository, platform="linux-x64",
    upstream_identity=receipt["upstreamIdentity"], plugin_digest=permission_plugin_digest(repository),
    artifact_cache=generated / "artifacts")
  assert result["receipt"] == receipt
  assert result["asset_path"].read_bytes().startswith(b"SYNTHETIC PERMISSION STANDALONE")


@pytest.mark.parametrize("part", ["receipt", "source", "dependency-lock", "build-inputs", "series", "script", "asset"])
def test_changed_delivery_component_is_dependency_failure(synthetic_runtime, part):
  repository, cache, value, receipt, write = synthetic_runtime
  paths = {"receipt": "locks/omp/permission-control/build-receipt.json",
    "source": receipt["patches"][0]["path"], "dependency-lock": receipt["dependencyLock"]["path"],
    "build-inputs": "agents/omp/patches/permission-control/build-inputs.lock.json",
    "series": "agents/omp/patches/permission-control/series", "script": receipt["buildScripts"][0]["path"]}
  if part == "asset": (cache / receipt["asset"]["cacheKey"]).write_bytes(b"secret-sentinel")
  elif part in ("receipt", "build-inputs"):
    target = repository / paths[part]
    # 改字节但保持 JSON 有效，以区分结构错误2与身份错误5。
    target.write_bytes(target.read_bytes() + b" \n")
  else: write(paths[part], b"secret-sentinel")
  with pytest.raises(DependencyError) as error: check_delivery(repository, cache)
  assert error.value.exit_code == 5
  assert "sentinel" not in str(error.value)


@pytest.mark.parametrize("change", ["upstream_identity", "plugin_digest", "platform"])
def test_expected_runtime_identity_mismatch_fails(synthetic_runtime, change):
  repository, cache, *_ = synthetic_runtime
  with pytest.raises(DependencyError):
    check_delivery(repository, cache, **{change: "linux-arm64" if change == "platform" else "f" * 64})


def test_receipt_unknown_fields_fail_with_no_value_leak(synthetic_runtime):
  repository, cache, value, receipt, write = synthetic_runtime
  receipt["secret-sentinel"] = "secret-sentinel"
  value["buildReceiptDigest"] = write("locks/omp/permission-control/build-receipt.json", json_bytes(receipt))
  resign(value)
  write("locks/omp/permission-control/manifest.json", json_bytes(value))
  with pytest.raises(ConfigError) as error: check_delivery(repository, cache)
  assert "sentinel" not in str(error.value)


@pytest.mark.parametrize("name", ["manifest.json", "build-receipt.json"])
def test_runtime_lock_files_cannot_redirect_outside_repository(synthetic_runtime, tmp_path, name):
  repository, cache, *_ = synthetic_runtime
  path = repository / "locks/omp/permission-control" / name
  redirected = tmp_path / name
  path.rename(redirected)
  path.symlink_to(redirected)
  with pytest.raises(DependencyError): check_delivery(repository, cache)


def test_published_receipt_schema_requires_every_actual_build_input(synthetic_runtime):
  _, _, _, receipt, _ = synthetic_runtime
  root = Path(__file__).resolve().parents[1]
  schema = json.loads((root / "schemas/omp-permission-runtime.schema.json").read_text())["$defs"]["buildReceipt"]
  validator = Draft202012Validator(schema)
  assert validator.is_valid(receipt)
  for key in receipt:
    incomplete = deepcopy(receipt)
    del incomplete[key]
    assert not validator.is_valid(incomplete), key
  for path in [(), ("manager",), ("asset",), ("tools", 0), ("buildScripts", 0), ("dependencyArtifacts", 0)]:
    bad = deepcopy(receipt)
    obj = bad
    for key in path:
      obj = obj[key]
    obj["secret-sentinel"] = "secret-sentinel"
    assert not validator.is_valid(bad)


@pytest.mark.parametrize("damage", ["changed", "missing", "linked", "directory-link", "added"])
def test_runtime_checks_actual_plugin_bytes_not_supplied_digest(synthetic_runtime, damage, tmp_path):
  repository, cache, _, _, _ = synthetic_runtime
  root = repository / "agents/omp/packages/omp-permission-control"
  path = root / "index.ts"
  if damage == "changed": path.write_bytes(b"secret-sentinel")
  elif damage == "missing": path.unlink()
  elif damage == "added": (root / "unlocked.ts").write_bytes(b"secret-sentinel")
  elif damage == "directory-link": (root / "extra").symlink_to(tmp_path, target_is_directory=True)
  else:
    redirected = tmp_path / "redirected.ts"
    path.rename(redirected)
    path.symlink_to(redirected)
  with pytest.raises(DependencyError) as error: check_delivery(repository, cache)
  assert error.value.exit_code == 5
  assert "secret-sentinel" not in str(error.value)
def test_lock_prepared_runtime_checks_existing_bytes_before_writing(synthetic_runtime):
  from agentcfg.omp_permission_runtime import lock_prepared_runtime
  repository, cache, value, receipt, _ = synthetic_runtime
  (cache / "build-receipt.json").write_bytes(json_bytes(receipt))
  result = lock_prepared_runtime(repository, cache, upstream_identity=value["upstreamIdentity"])
  assert result["manifest"] == value
  assert check_delivery(repository, cache)["identity"] == result["identity"]
  before = (repository / "locks/omp/permission-control/manifest.json").read_bytes()
  (cache / receipt["asset"]["cacheKey"]).write_bytes(b"damaged")
  with pytest.raises(DependencyError):
    lock_prepared_runtime(repository, cache, upstream_identity=value["upstreamIdentity"])
  assert (repository / "locks/omp/permission-control/manifest.json").read_bytes() == before


def test_lock_publication_failure_restores_previous_receipt(synthetic_runtime, monkeypatch):
  from agentcfg.omp_permission_runtime import lock_prepared_runtime, MANIFEST_PATH, RECEIPT_PATH
  from agentcfg.storage import Tree
  repository, cache, value, receipt, _ = synthetic_runtime
  (cache / "build-receipt.json").write_bytes(json_bytes(receipt))
  previous = b"previous-receipt-sentinel"
  (repository / RECEIPT_PATH).write_bytes(previous)
  manifest_before = (repository / MANIFEST_PATH).read_bytes()
  replace = Tree.replace
  def fail_manifest(self, path, *args, **kwargs):
    if path == MANIFEST_PATH:
      raise OSError("synthetic-publication-failure")
    return replace(self, path, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", fail_manifest)
  with pytest.raises(OSError, match="synthetic-publication-failure"):
    lock_prepared_runtime(repository, cache, upstream_identity=value["upstreamIdentity"])
  assert (repository / RECEIPT_PATH).read_bytes() == previous
  assert (repository / MANIFEST_PATH).read_bytes() == manifest_before


def permission_adapter_data(synthetic_runtime, tmp_path):
  from test_omp_adapter import omp_data
  from agentcfg.adapter import RenderContext
  repository, _, manifest_value, _, _ = synthetic_runtime
  from agentcfg.omp_dependencies import OmpBackend
  # 官方插件产物与历史补丁哨兵各有身份，不能混用旧 index 入口摘要。
  entry = repository / "agents/omp/packages/omp-permission-control/standalone.ts"
  entry.write_bytes(b"// standalone adapter sentinel: never executed\n")
  (repository / "agents/omp/plugins.toml").write_text(
    '[plugins.omp-permission-control]\nentrypoints = ["standalone.ts"]\n')
  package = OmpBackend()._resources(repository)[1]["omp-permission-control"]
  data = omp_data()
  data["profile"].update(rules=[], skills=[], plugins=["omp-permission-control"])
  data["rules"], data["skills"] = {}, {}
  data["profile"]["agent_options"].update(runtime_variant="official",
    permission_control={"default_mode": "smart", "fallback_model": "local/lfm2.5-230m"},
    runtime={"tools": {"approvalMode": "write", "approval": {"bash": "prompt",
      "permission_bash": "allow", "task": "prompt", "eval": "prompt"}}})
  data["plugins"] = {"omp-permission-control": {"id": "omp-permission-control",
    "source": "agents/omp/packages/omp-permission-control", "entrypoints": ["standalone.ts"],
    "tree_digest": package["tree_digest"], "license": "MIT", "compatibility": {"omp": package["compatibility"]}}}
  identity = manifest_value["upstreamIdentity"] + "-linux-x64"
  return data, RenderContext(manifest_value["upstreamIdentity"], tmp_path / "runtimes" / identity)


def test_adapter_renders_standalone_permission_sidecar_and_owns_one_file(synthetic_runtime, tmp_path):
  from agentcfg.omp import OmpAdapter, OPTIONS
  from agentcfg.omp_settings import NATIVE_PERMISSION_CONTROL
  data, context = permission_adapter_data(synthetic_runtime, tmp_path)
  adapter = OmpAdapter(synthetic_runtime[0])
  Draft202012Validator(OPTIONS).validate(data["profile"]["agent_options"])
  rendered = adapter.render_with_context(data, context)
  from agentcfg.omp_discovery import DISABLED_PROVIDERS
  values = {item.target.selector: json.loads(item.content) for item in rendered if item.target.selector}
  assert values["/disabledProviders"] == list(DISABLED_PROVIDERS)
  assert "cursor" not in values["/disabledProviders"] and "/disabledModelProviders" not in values
  selected = [item for item in rendered if item.target.path.endswith("/permission-control.json")]
  assert len(selected) == 1
  value = json.loads(selected[0].content)
  Draft202012Validator(NATIVE_PERMISSION_CONTROL).validate(value)
  assert value["schemaVersion"] == 2 and "runtimeIdentity" not in value and "bridgeAbi" not in value
  assert value["pluginDigest"] == data["plugins"]["omp-permission-control"]["tree_digest"]
  assert value["reviewer"] == "session"
  assert value["fallback"]["installedOnly"] is True
  assert selected == [item for item in adapter.render_with_context(data, context)
    if item.target.path.endswith("/permission-control.json")]
  captured = adapter.capture_configuration({"permissionControl": {**value, "pluginDigest": "secret-sentinel"}}, data)
  assert "permissionControl" not in repr(captured) and "secret-sentinel" not in repr(captured)

  official = deepcopy(data)
  official["profile"]["plugins"], official["plugins"] = [], {}
  official["profile"]["agent_options"].pop("permission_control")
  official["profile"]["agent_options"]["runtime_variant"] = "official"
  official_selectors = {item.target.selector for item in adapter.render(official)}
  assert "/disabledModelProviders" not in official_selectors


def test_adapter_sidecar_does_not_bind_to_runtime_identity(synthetic_runtime, tmp_path):
  from agentcfg.adapter import RenderContext
  from agentcfg.omp import OmpAdapter
  data, context = permission_adapter_data(synthetic_runtime, tmp_path)
  adapter = OmpAdapter(synthetic_runtime[0])
  other = RenderContext(context.lock_identity, tmp_path / "other-official-runtime")
  get_sidecar = lambda rendered: next(item.content for item in rendered
    if item.target.path.endswith("/permission-control.json"))
  assert get_sidecar(adapter.render_with_context(data, context)) == get_sidecar(adapter.render_with_context(data, other))


def test_permission_sidecar_transactions_preserve_unmanaged_config_and_consume_rollback(tmp_path):
  import yaml
  from agentcfg.adapter import Artifact, ManagedTarget, Ownership, RenderContext
  from agentcfg import deployment
  from agentcfg.render import RenderCandidate
  from agentcfg.storage import Conflict
  from omp_permission_fixture import permission_workspace
  workspace, lock, _ = permission_workspace(tmp_path)
  data, adapter = workspace.resolved.data, workspace.adapter
  runtime_root = workspace.backend.root(workspace, workspace.backend.runtime_identity(workspace, lock))
  context = RenderContext(lock.identity, runtime_root)
  instance, state = tmp_path / "instance", tmp_path / "state"
  binding = {"machine": "synthetic", "profile": data["profile"]["id"], "local": "synthetic"}
  official = deepcopy(data)
  official["profile"]["plugins"].remove("omp-permission-control")
  official["profile"]["agent_options"].pop("permission_control")
  official["profile"]["agent_options"].pop("runtime_variant", None)
  baseline = adapter.render_with_context(official, context)
  config_target = next(item.target.path for item in baseline if item.target.path.endswith("/config.yml"))
  legacy = (Artifact(ManagedTarget(config_target, Ownership.FIELDS, "yaml", "/permissionControl"),
      json.dumps({"schemaVersion": 1, "bridgeAbi": "permission-control/v1"}).encode()),
    Artifact(ManagedTarget(config_target, Ownership.FIELDS, "yaml", "/disabledModelProviders"),
      json.dumps(["cursor"]).encode()))
  first = RenderCandidate("legacy-permission-fixture", (*baseline, *legacy))
  deployment.apply(instance, state, first, binding, {})
  selected = RenderCandidate("permission-fixture", adapter.render_with_context(data, context))
  config = instance / next(item.target.path for item in first.artifacts if item.target.path.endswith("/config.yml"))
  current = yaml.safe_load(config.read_text())
  current["nativePreference"] = "untouched-sentinel"
  config.write_text(yaml.safe_dump(current))
  auth = config.parent / "auth.db"
  auth.write_bytes(b"credential-sentinel")
  deployment.apply(instance, state, selected, binding, {})
  sidecar = config.parent / "permission-control.json"
  assert json.loads(sidecar.read_text())["defaultMode"] == "smart"
  migrated = yaml.safe_load(config.read_text())
  assert "permissionControl" not in migrated and "disabledModelProviders" not in migrated
  deployment.rollback(instance, state, binding)
  restored = yaml.safe_load(config.read_text())
  assert not sidecar.exists()
  assert restored["permissionControl"]["bridgeAbi"] == "permission-control/v1"
  assert restored["disabledModelProviders"] == ["cursor"]
  assert restored["nativePreference"] == "untouched-sentinel"
  assert auth.read_bytes() == b"credential-sentinel"
  with pytest.raises(Conflict): deployment.rollback(instance, state, binding)
  sidecar.write_text('{"native-sentinel":true}')
  before = sidecar.read_bytes()
  with pytest.raises(Conflict): deployment.apply(instance, state, selected, binding, {})
  assert sidecar.read_bytes() == before and auth.read_bytes() == b"credential-sentinel"


@pytest.mark.parametrize("interruption", [False, True])
def test_synthetic_permission_delivery_consumes_cache_through_real_manager(tmp_path, monkeypatch, fake_subprocess, interruption):
  import yaml
  from types import SimpleNamespace
  from agentcfg import commands, deployment, runtime
  from agentcfg.omp_identity import native_identity
  from agentcfg.render import RenderCandidate
  from agentcfg.storage import Conflict, Tree
  from omp_permission_fixture import permission_workspace
  from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, lock, delivery = permission_workspace(tmp_path, monkeypatch=monkeypatch)
  backend = workspace.backend
  workspace.adapter.validate(workspace.resolved.data)
  candidate = workspace.candidate(lock.identity)
  assert not workspace.instance.exists()
  plan = commands.current_plan(workspace, lock, candidate)
  assert plan.changes and not plan.conflicts
  backend.sync(workspace, lock)
  assert backend.status(workspace, delivery["identity"]) == "installed"
  # 首次先部署不含权限sidecar的基线，随后测试整文件三方转换与一次回滚。
  baseline = RenderCandidate("synthetic-before-permission", tuple(item for item in candidate.artifacts
    if not item.target.path.endswith("/permission-control.json") and item.target.selector != "/extensions"))
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, baseline, workspace.binding, {})
  identity = native_identity(workspace.profile, workspace.instance)
  sentinel = identity.agent_dir / "auth.db"
  sentinel.write_bytes(b"UNMANAGED_AUTH_SENTINEL")
  if interruption:
    with Tree(workspace.state_root) as state, Tree(workspace.instance) as target:
      old = deployment.read_state(state)
      planned = deployment.plan(target, old, candidate, workspace.binding, runtime.record(workspace, lock))
      after = {"version": 1, "current": planned.current,
        "previous": {"current": old["current"], "changes": planned.changes}, "owner": old["owner"]}
      state.write_state("pending.json", json_bytes({"after_state": after, "changes": planned.changes}))
      deployment.write_changes(target, planned.changes)
  monkeypatch.setattr(commands, "workspace", lambda _: workspace)
  assert commands.cmd_apply(SimpleNamespace()) == 0
  assert not (workspace.state_root / "pending.json").exists()
  config = identity.agent_dir / "config.yml"
  sidecar = identity.agent_dir / "permission-control.json"
  assert json.loads(sidecar.read_bytes())["schemaVersion"] == 2
  assert "permissionControl" not in yaml.safe_load(config.read_bytes())
  work = tmp_path / "work"
  work.mkdir()
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=work) == 0
  assert len(fake_subprocess.calls) == 1

  assert fake_subprocess.calls[0]["argv"][0] == str(backend.root(workspace, delivery["identity"]) / "bin/omp")
  assert sentinel.read_bytes() == b"UNMANAGED_AUTH_SENTINEL"
  deployment.rollback(workspace.instance, workspace.state_root, workspace.binding)
  assert not sidecar.exists() and "permissionControl" not in yaml.safe_load(config.read_bytes())
  assert sentinel.read_bytes() == b"UNMANAGED_AUTH_SENTINEL"
  with pytest.raises(Conflict): deployment.rollback(workspace.instance, workspace.state_root, workspace.binding)
  assert len(fake_subprocess.calls) == 1


@pytest.mark.parametrize("damage", ["missing-entry", "changed-entry", "wrong-receipt", "changed-binary"])
def test_synthetic_permission_run_rejects_runtime_damage_before_spawn(tmp_path, monkeypatch, fake_subprocess, damage):
  from agentcfg import deployment, runtime
  from omp_permission_fixture import permission_workspace
  from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, lock, delivery = permission_workspace(tmp_path, monkeypatch=monkeypatch)
  backend = workspace.backend
  backend.sync(workspace, lock)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity), workspace.binding,
      runtime.record(workspace, lock))
  root = backend.root(workspace, delivery["identity"])
  entry = root / "packages/omp-permission-control/standalone.ts"
  if damage == "missing-entry": entry.unlink()
  elif damage == "changed-entry": entry.write_bytes(b"SECRET_SENTINEL")
  elif damage == "changed-binary": (root / "bin/omp").write_bytes(b"SECRET_SENTINEL")
  else:
    receipt_path = root / ".agentcfg-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["retired_bridge_abi"] = "permission-control/v99"
    receipt_path.write_bytes(json_bytes(receipt))
  work = tmp_path / "work"
  work.mkdir()
  with pytest.raises(DependencyError) as error: runtime.run(workspace, cwd=work)
  assert error.value.exit_code == 5
  assert "SECRET_SENTINEL" not in str(error.value)
  assert not fake_subprocess.calls


def test_manager_rendered_kernel_sidecar_matches_standalone_contract(tmp_path):
  from agentcfg import deployment
  from agentcfg.omp_identity import native_identity
  from agentcfg.omp_settings import NATIVE_PERMISSION_CONTROL
  from omp_permission_fixture import permission_workspace
  workspace, lock, delivery = permission_workspace(tmp_path, profile_name="omp-kernel", local_values={
    "tf_openai_url": "https://tf-gateway.example.invalid/v1",
    "tf_anthropic_url": "https://tf-gateway.example.invalid/anthropic"})
  candidate = workspace.candidate(lock.identity)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, {})
  agent_dir = native_identity(workspace.profile, workspace.instance).agent_dir
  permission = json.loads((agent_dir / "permission-control.json").read_bytes())
  Draft202012Validator(NATIVE_PERMISSION_CONTROL).validate(permission)
  assert permission["schemaVersion"] == 2 and "runtimeIdentity" not in permission
  assert permission["pluginDigest"] == workspace.resolved.data["plugins"]["omp-permission-control"]["tree_digest"]
  assert permission["nativePatterns"] == workspace.resolved.data["profile"]["agent_options"]["runtime"]["bash"]["patterns"]
  assert delivery["identity"] == workspace.backend.runtime_identity(workspace, lock)
