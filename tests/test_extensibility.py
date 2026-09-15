"""非 DSH 测试适配器复用部署和上一版恢复，不代表新增产品支持。"""

import json
import pytest

from agentcfg import deployment as dep
from agentcfg.adapter import Artifact, ManagedTarget, Ownership
from agentcfg.render import RenderCandidate
from test_adapter import JsonTestAdapter, FixtureConfig
from agentcfg.adapter import SecretRef


def test_json_adapter_instances_and_backups_are_independent(tmp_path):
  adapter = JsonTestAdapter()
  config = FixtureConfig("https://example.invalid/v1", "fictional", SecretRef("secret:test"))
  first = RenderCandidate("one", adapter.render(config))
  a, b = tmp_path / "first", tmp_path / "second"
  sa, sb = tmp_path / "state-first", tmp_path / "state-second"
  dep.apply(a, sa, first, {"id": "a"}, {"lock": "fixture"})
  dep.apply(b, sb, first, {"id": "b"}, {"lock": "fixture"})
  before = (sb / "deployment.json").read_bytes()
  altered = FixtureConfig("https://changed.example.invalid/v1", "fictional", SecretRef("secret:test"))
  dep.apply(a, sa, RenderCandidate("two", adapter.render(altered)), {"id": "a"}, {"lock": "fixture"})
  dep.rollback(a, sa, {"id": "a"})
  assert json.loads((a / "native/config.json").read_bytes())["endpoint"] == config.endpoint
  assert (sb / "deployment.json").read_bytes() == before


def test_explicit_codec_extension_does_not_silently_use_yaml(tmp_path, monkeypatch):
  monkeypatch.setattr(dep, "NATIVE_CODECS", dict(dep.NATIVE_CODECS))
  dep.register_codec("fixture-format", json.loads, dep.json_bytes)
  target = ManagedTarget("config.fixture", Ownership.FIELDS, "fixture-format", "/enabled")
  candidate = RenderCandidate("custom", (Artifact(target, b"false"),))
  dep.apply(tmp_path / "instance", tmp_path / "state", candidate, {"id": "custom"}, {})
  assert json.loads((tmp_path / "instance/config.fixture").read_text()) == {"enabled": False}


@pytest.mark.parametrize("actual", ["fixture 1", "synthetic-private-token"])
def test_non_npm_backend_drives_public_commands_and_launch(tmp_path, monkeypatch, fake_subprocess, capsys, actual):
  from types import SimpleNamespace
  from pathlib import Path
  from agentcfg import commands
  from agentcfg.adapter import EnvironmentBinding, LaunchSpec
  from agentcfg.storage import Tree, ensure_private, instance_lock
  from agentcfg.workspace import load_workspace
  path = tmp_path / "local.toml"
  path.write_text('schema_version=1\n[machine]\nid="backend-test"\n')
  real = load_workspace(path)
  calls = []
  lock = SimpleNamespace(identity="fixture-package", metadata={"platforms": {}})

  class Backend:
    def read_lock(self, repository):
      calls.append("read")
      return lock

    def resolve_lock(self, repository):
      calls.append("resolve")

    def root(self, w, identity):
      return w.instance / "native-packages" / identity

    def status(self, w, identity):
      return "installed" if (self.root(w, identity) / "ready").exists() else "missing"

    def sync(self, w, lock):
      calls.append("sync")
      with Tree(w.state_root, create=True) as tree, instance_lock(tree):
        ensure_private(self.root(w, lock.identity))
        (self.root(w, lock.identity) / "ready").write_text("synthetic package")
      return {"installed": True}

    def executable_paths(self, root):
      return (root / "native-bin",)

    def toolchain(self, lock):
      return {"fixture-tool": "1"}

  class Adapter:
    shared_files = ()

    def launch_preflight(self, lock):
      return [{"argv": ["fixture-tool", "--version"], "version": "fixture 1"}]

    def launch_spec(self, data, *, cwd, runtime_root, instance_root, lock_identity):
      return LaunchSpec((str(runtime_root / "native-bin/fixture-tool"),), cwd, lock_identity,
        (EnvironmentBinding("HOME", str(instance_root / "home")),))

    def prepare_runtime(self, w, root):
      ensure_private(w.instance / "home")

    def doctor(self, projection):
      return ()

  w = SimpleNamespace(repository=real.repository, local_path=path, profile="fixture-profile", agent="fixture-tool",
    resolved=real.resolved, secret_store=real.secret_store, instance=tmp_path / "instance", state_root=tmp_path / "state",
    cache=tmp_path / "cache", binding={"machine": "fixture"}, backend=Backend(), adapter=Adapter(),
    candidate=lambda identity: RenderCandidate("fixture-generation", (Artifact(ManagedTarget("config.json", Ownership.FILE, "json"), b"{}"),)))
  monkeypatch.setattr(commands, "workspace", lambda args: w)
  args = SimpleNamespace(cwd=tmp_path, passthrough=["--literal"], live=False)
  for name in ("validate", "plan", "lock", "sync", "apply", "doctor"):
    assert getattr(commands, "cmd_" + name)(args) == 0
  fake_subprocess.queue(returncode=0, stdout=actual)
  if actual != "fixture 1":
    from agentcfg.process import DependencyError
    with pytest.raises(DependencyError) as caught:
      commands.cmd_run(args)
    assert actual not in str(caught.value)
    assert len(fake_subprocess.calls) == 1
    return
  fake_subprocess.queue(returncode=0)
  assert commands.cmd_run(args) == 0
  call = fake_subprocess.calls[-1]
  assert "native-packages" in call["argv"][0]
  assert "node_modules" not in call["env"]["PATH"]
  assert call["argv"][-1] == "--literal"
  assert commands.cmd_rollback(args) == 0
  assert "sync" in calls and "resolve" in calls
