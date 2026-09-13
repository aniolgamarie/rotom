"""2.5：测试专用 JSON adapter，不代表生产支持或部署事务验收。"""

from dataclasses import dataclass, FrozenInstanceError
import json
from pathlib import Path

import pytest

from agentcfg.adapter import (
  Adapter, AdapterDeclaration, Artifact, ContractError, DependencyPlan,
  EnvironmentBinding, LaunchSpec, ManagedTarget, Ownership, SecretRef,
)
from agentcfg.paths import PathError


@dataclass(frozen=True)
class FixtureConfig:
  endpoint: str
  model: str
  credential: SecretRef
  transport: str = "stdio"


class JsonTestAdapter(Adapter[FixtureConfig, dict[str, str], dict[str, str]]):
  declaration = AdapterDeclaration("fixture-json", 1, "fixture-v1")

  def validate(self, config):
    if config.transport != "stdio":
      raise ContractError("fixture-json: transport 不支持")

  def managed_targets(self, config):
    self.validate(config)
    return (
      ManagedTarget("native/config.json", Ownership.FILE, "json"),
      ManagedTarget("native/preferences.json", Ownership.FIELDS, "json", "/theme"),
      ManagedTarget("native/preferences.json", Ownership.INITIALIZE, "json", "/welcome"),
      ManagedTarget("native/session.json", Ownership.RUNTIME, "json"),
      ManagedTarget("runtime/package.json", Ownership.PACKAGE, "json"),
    )

  def render(self, config):
    targets = self.managed_targets(config)
    data = {"endpoint": config.endpoint, "model": config.model,
            "credential_env": "FIXTURE_KEY"}
    return (
      Artifact(targets[0], json.dumps(data, ensure_ascii=False, sort_keys=True).encode()),
      Artifact(targets[1], b'"quiet"'),
      Artifact(targets[2], b"false"),
    )

  def dependency_plan(self, config):
    self.validate(config)
    return DependencyPlan(("fixture-runtime@1.0.0",))

  def launch_spec(self, config, *, cwd, runtime_root, instance_root, lock_identity):
    self.validate(config)
    return LaunchSpec(
      (str(runtime_root / "fixture-python"), "--config",
       str(instance_root / "native/config.json")),
      cwd, lock_identity,
      (EnvironmentBinding("FIXTURE_HOME", str(instance_root)),
       EnvironmentBinding("FIXTURE_KEY", config.credential)),
    )

  def capture(self, projection):
    # 只消费上游已过滤的非秘密 allowlist 投影，不读取原生文件。
    return {"theme": projection["theme"]} if "theme" in projection else {}

  def doctor(self, projection):
    return ("login-pending",) if projection.get("login") == "pending" else ()


def test_all_hooks_are_required():
  assert Adapter.__abstractmethods__ == {
    "declaration", "validate", "render", "dependency_plan", "managed_targets",
    "launch_spec", "capture", "doctor",
  }
  with pytest.raises(TypeError):
    Adapter()


def test_hooks_are_declarative_and_do_not_receive_secrets(
    isolated_environment, sentinel_factory, fake_catalog):
  adapter = JsonTestAdapter()
  config = FixtureConfig(fake_catalog["provider"]["base_url"],
                         fake_catalog["model"]["remote_id"], SecretRef("secret:selected"))
  before = sentinel_factory(isolated_environment.root)
  adapter.validate(config)
  targets = adapter.managed_targets(config)
  artifacts = adapter.render(config)
  dependencies = adapter.dependency_plan(config)
  launch = adapter.launch_spec(
    config, cwd=isolated_environment.cwd,
    runtime_root=isolated_environment.home / "uninstalled-runtime",
    instance_root=isolated_environment.home / "undeployed-instance",
    lock_identity="fixture-lock-v1",
  )
  proposal = adapter.capture({"theme": "quiet"})
  diagnostics = adapter.doctor({"login": "pending"})
  before.assert_unchanged()
  assert adapter.declaration == AdapterDeclaration("fixture-json", 1, "fixture-v1")
  assert set(target.ownership for target in targets) == set(Ownership)
  assert json.loads(artifacts[0].content) == {
    "endpoint": "https://example.invalid/v1",
    "model": "synthetic-chat-not-a-real-model", "credential_env": "FIXTURE_KEY",
  }
  assert json.loads(artifacts[1].content) == "quiet"
  assert artifacts[1].target.selector == "/theme"
  assert artifacts[2].target.ownership is Ownership.INITIALIZE
  assert dependencies.requirements == ("fixture-runtime@1.0.0",)
  assert launch.cwd == isolated_environment.cwd
  assert launch.lock_identity == "fixture-lock-v1"
  assert launch.environment[1].value == SecretRef("secret:selected")
  assert launch.environment[1].required is True
  assert proposal == {"theme": "quiet"}
  assert diagnostics == ("login-pending",)
  assert adapter.render(config) == artifacts
  for canary in fake_catalog["secrets"].values():
    assert all(canary.encode() not in artifact.content for artifact in artifacts)
    assert all(canary not in arg for arg in launch.argv)
    assert canary not in repr((config, artifacts, launch, dependencies, proposal))


def test_unsupported_mapping_fails_without_echoing_value():
  adapter = JsonTestAdapter()
  private = "synthetic-private-transport"
  config = FixtureConfig("https://example.invalid", "fiction", SecretRef("secret:key"), private)
  for hook in (adapter.validate, adapter.render, adapter.dependency_plan, adapter.managed_targets):
    with pytest.raises(ContractError, match="fixture-json: transport") as error:
      hook(config)
    assert private not in str(error.value)


@pytest.mark.parametrize("path", ["/outside", "../outside", "a/../b", "a//b", "", "a\\b"])
def test_target_reuses_relative_path_guard(path):
  with pytest.raises(PathError):
    ManagedTarget(path, Ownership.FILE, "json")


@pytest.mark.parametrize("ownership,selector", [
  (Ownership.FILE, "/theme"), (Ownership.FIELDS, None),
  (Ownership.FIELDS, ""), (Ownership.RUNTIME, "/theme"),
  (Ownership.PACKAGE, "/theme"), (Ownership.INITIALIZE, ""),
])
def test_invalid_target_scope_is_rejected(ownership, selector):
  with pytest.raises(ContractError):
    ManagedTarget("config.json", ownership, "json", selector)


def test_selector_is_opaque_and_initialization_can_be_whole_file():
  target = ManagedTarget("config.native", Ownership.FIELDS, "fixture-codec", "row[id=x].value")
  assert target.selector == "row[id=x].value"
  Artifact(ManagedTarget("first.txt", Ownership.INITIALIZE, "text"), b"first")


@pytest.mark.parametrize("ownership", [Ownership.RUNTIME, Ownership.PACKAGE])
def test_unmanaged_targets_cannot_render(ownership):
  with pytest.raises(ContractError):
    Artifact(ManagedTarget("state.json", ownership, "json"), b"{}")


@pytest.mark.parametrize("mode", [0o644, 0o777, 0o4755, 0, True])
def test_artifact_modes_are_private(mode):
  with pytest.raises(ContractError):
    Artifact(ManagedTarget("rule.txt", Ownership.FILE, "text"), b"data", mode)


def test_artifact_bytes_and_execute_mode_are_explicit():
  target = ManagedTarget("skill/run", Ownership.FILE, "text")
  assert Artifact(target, b"script", 0o700).mode == 0o700
  with pytest.raises(ContractError):
    Artifact(target, SecretRef("secret:key"))
  with pytest.raises(FrozenInstanceError):
    target.path = "other"


@pytest.mark.parametrize("value", ["raw-canary", "env:key", "secret:", "secret:../key", 7])
def test_secret_reference_rejects_raw_values(value):
  with pytest.raises((ContractError, PathError)) as error:
    SecretRef(value)
  assert str(value) not in str(error.value)


@pytest.mark.parametrize("name", ["", "1KEY", "KEY-NAME", "KEY\n", "*"])
def test_environment_names_are_explicit(name):
  with pytest.raises(ContractError):
    EnvironmentBinding(name, "literal")


def test_launch_preserves_literals_and_separates_secret_references(isolated_environment):
  argv = ("/fixture/bin", "中文 空格", "", "$(touch no)", "`false`", 'quote"', "line\nbreak")
  launch = LaunchSpec(argv, isolated_environment.cwd, "fixture-lock", (
    EnvironmentBinding("LANG", "zh_CN.UTF-8"),
    EnvironmentBinding("KEY", SecretRef("secret:key"), required=False),
  ))
  assert launch.argv == argv
  assert launch.environment[1].required is False
  assert "$(touch no)" not in repr(launch)
  assert "zh_CN.UTF-8" not in repr(launch.environment[0])


@pytest.mark.parametrize("argv", [(), ("",), "shell command", (SecretRef("secret:key"),), ("bin", "a\0b")])
def test_launch_rejects_invalid_argv(argv, isolated_environment):
  with pytest.raises(ContractError):
    LaunchSpec(argv, isolated_environment.cwd, "fixture-lock")


def test_launch_rejects_relative_cwd_and_duplicate_env(isolated_environment):
  with pytest.raises(ContractError):
    LaunchSpec(("bin",), Path("relative"), "fixture-lock")
  with pytest.raises(ContractError):
    LaunchSpec(("bin",), isolated_environment.cwd, "fixture-lock", (
      EnvironmentBinding("KEY", "literal"),
      EnvironmentBinding("KEY", SecretRef("secret:key")),
    ))


def test_declarations_and_dependencies_are_not_registries():
  declaration = AdapterDeclaration("fixture-json", 1, "v2")
  assert declaration.schema_version == 1
  assert declaration.adapter_version == "v2"
  with pytest.raises(ContractError):
    AdapterDeclaration("fixture-json", 0, "v2")
  with pytest.raises(ContractError):
    DependencyPlan(["mutable"])
