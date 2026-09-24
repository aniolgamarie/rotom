"""公共扩展的行为边界：所选就绪校验、历史运行身份与秘密叶子。"""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from agentcfg import config, deployment, runtime
from agentcfg.adapter import Artifact, LaunchSpec, ManagedTarget, Ownership
from agentcfg.render import RenderCandidate
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_config_resolution import ResolutionAdapter, resolution_inputs


def test_readiness_runs_for_selected_profile_only(tmp_path):
  catalog, local, _, _ = resolution_inputs(tmp_path)
  other = deepcopy(catalog.profiles["fixture-default"])
  other["id"] = "unbound"
  catalog.profiles["unbound"] = other
  seen = []

  def readiness(data):
    seen.append(data["profile"]["id"])
    if data["profile"]["id"] == "unbound":
      raise ConfigError("required-binding")

  bundle = catalog.adapter_schemas.bundles["fixture-json"]
  # 将新可选钩子放在真实bundle上，红阶段检验忽略钩子的行为而非导入错误。
  object.__setattr__(bundle, "validate_selected", readiness)
  resolved = config.resolve_config(catalog, local, adapter_schemas=catalog.adapter_schemas)
  assert resolved.data["profile"]["id"] == "fixture-default"
  assert seen == ["fixture-default"]
  with pytest.raises(ConfigError):
    config.resolve_config(catalog, local, profile_id="unbound", adapter_schemas=catalog.adapter_schemas)
  catalog.profiles["unbound"]["unknown_field"] = True
  with pytest.raises(ConfigError):
    config.resolve_config(catalog, local, adapter_schemas=catalog.adapter_schemas)


def test_runtime_record_uses_backend_identity_and_decode_preserves_it(tmp_path):
  captured = []

  class Backend:
    def runtime_identity(self, workspace, lock):
      return "historical-slice"

    def root(self, workspace, identity):
      captured.append(identity)
      return tmp_path / identity

  class Adapter:
    shared_files = ()

    def launch_preflight(self, lock):
      return []

    def launch_spec(self, data, *, cwd, runtime_root, instance_root, lock_identity):
      return LaunchSpec((str(runtime_root / "fake-host"),), cwd, lock_identity)

  workspace = SimpleNamespace(backend=Backend(), adapter=Adapter(), resolved=SimpleNamespace(data={"machine": {}}),
    instance=tmp_path, repository=tmp_path, local_path=tmp_path / "local.toml", profile="fixture")
  record = runtime.record(workspace, SimpleNamespace(identity="source-lock"))
  assert captured == ["historical-slice"]
  assert record["lock_identity"] == "source-lock"
  assert record["runtime_identity"] == "historical-slice"
  decoded = runtime.decode(record, tmp_path, ())
  assert decoded.runtime_identity == "historical-slice"


def candidate(token, generation):
  target = ManagedTarget("models.json", Ownership.FIELDS, "json", "/providers/fake/apiKey", (token,))
  return RenderCandidate(generation, (Artifact(target, json.dumps(token).encode()),))


def test_guarded_reference_rotates_and_rolls_back_without_capturing_other_auth(tmp_path):
  instance, state = tmp_path / "instance", tmp_path / "state"
  deployment.apply(instance, state, candidate("$OLD_KEY", "old"), {"id": "fixture"}, {})
  deployment.apply(instance, state, candidate("$NEW_KEY", "new"), {"id": "fixture"}, {})
  deployment.rollback(instance, state, {"id": "fixture"})
  assert json.loads((instance / "models.json").read_text())["providers"]["fake"]["apiKey"] == "$OLD_KEY"
  native = {"providers": {"fake": {"apiKey": "synthetic-secret-canary"}}, "auth": {"token": "unmanaged-canary"}}
  (instance / "models.json").write_text(json.dumps(native))
  before = (state / "deployment.json").read_bytes()
  with pytest.raises(Conflict) as caught:
    deployment.apply(instance, state, candidate("$NEW_KEY", "newer"), {"id": "fixture"}, {})
  assert "canary" not in str(caught.value)
  assert (state / "deployment.json").read_bytes() == before
  assert not (state / "pending.json").exists()


def test_secret_is_rejected_before_plan_can_expose_it(tmp_path):
  instance, state = tmp_path / "instance", tmp_path / "state"
  deployment.apply(instance, state, candidate("$OLD_KEY", "old"), {"id": "fixture"}, {})
  (instance / "models.json").write_text('{"providers":{"fake":{"apiKey":"synthetic-private-value"}}}')
  with Tree(instance) as target, Tree(state) as saved:
    with pytest.raises(Conflict):
      deployment.plan(target, deployment.read_state(saved), candidate("$OLD_KEY", "next"), {"id": "fixture"}, {})


def test_adapter_reserved_environment_does_not_change_legacy_profiles(tmp_path):
  machine = {"id": "fixture", "environment": {"inherit": ["CODEX_HOME"]}}
  config._machine_layers(machine, set())
  with pytest.raises(ConfigError):
    config._machine_layers(machine, set(), reserved_environment=frozenset({"CODEX_HOME"}))


def test_invalid_saved_reference_is_rejected_before_rollback(tmp_path):
  instance, state = tmp_path / "instance", tmp_path / "state"
  deployment.apply(instance, state, candidate("$OLD_KEY", "old"), {"id": "fixture"}, {})
  deployment.apply(instance, state, candidate("$NEW_KEY", "new"), {"id": "fixture"}, {})
  path = state / "deployment.json"
  saved = json.loads(path.read_text())
  saved["previous"]["changes"][0]["before"]["value"] = "synthetic-saved-secret"
  path.write_text(json.dumps(saved))
  before = (instance / "models.json").read_bytes()
  with pytest.raises(Conflict) as caught:
    deployment.rollback(instance, state, {"id": "fixture"})
  assert "synthetic" not in str(caught.value)
  assert (instance / "models.json").read_bytes() == before


def test_render_preserves_reference_guard_and_binds_it_to_generation(tmp_path):
  from agentcfg.render import render_candidate
  catalog, local, _, _ = resolution_inputs(tmp_path)
  resolved = config.resolve_config(catalog, local, adapter_schemas=catalog.adapter_schemas)

  class GuardedAdapter(ResolutionAdapter):
    def __init__(self, tokens):
      self.tokens = tokens

    def managed_targets(self, data):
      return (ManagedTarget("models.json", Ownership.FIELDS, "json", "/provider/apiKey", self.tokens),)

    def render(self, data):
      return (Artifact(self.managed_targets(data)[0], b'"$KEY"'),)

  first = render_candidate(resolved, adapter=GuardedAdapter(("$KEY",)),
    adapter_schemas=catalog.adapter_schemas, lock_identity="test-lock")
  second = render_candidate(resolved, adapter=GuardedAdapter(("$KEY", "$OTHER")),
    adapter_schemas=catalog.adapter_schemas, lock_identity="test-lock")
  assert first.artifacts[0].target.reference_tokens == ("$KEY",)
  assert first.generation != second.generation


def test_capture_checks_deployed_reference_guard_before_native_projection(tmp_path, monkeypatch):
  from agentcfg import commands
  instance, state = tmp_path / "instance", tmp_path / "state"
  deployment.apply(instance, state, candidate("$KEY", "first"), {"id": "fixture"}, {})
  (instance / "models.json").write_text('{"providers":{"fake":{"apiKey":"synthetic-secret"}}}')
  called = []
  w = SimpleNamespace(instance=instance, state_root=state,
    adapter=SimpleNamespace(capture_projection=lambda tree: called.append(True)))
  monkeypatch.setattr(commands, "workspace", lambda args: w)
  with pytest.raises(Conflict):
    commands.cmd_capture(SimpleNamespace())
  assert not called
