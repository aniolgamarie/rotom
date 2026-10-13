"""独立体验入口的离线所有权与启动边界；不启动第三方宿主。"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

from agentcfg import deployment as dep, native
from agentcfg.storage import Conflict, Tree

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("experience_entry", ROOT / "scripts/experience-dsh-auto-review.py")
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)


@pytest.fixture
def experience(tmp_path):
  runtime = tmp_path / "runtime"
  runtime.mkdir()
  (runtime / "package.json").write_text('{"name":"fake-runtime"}')
  (runtime / "pnpm-lock.yaml").write_text("fixture-lock")
  (runtime / "result.json").write_text(json.dumps({"runtime_installed": True,
    "diagnostic-frozen-install_exit": 0, "lock_unchanged": True,
    "sha256": {name: entry.digest((runtime / name).read_bytes()) for name in ("package.json", "pnpm-lock.yaml")}}))
  graph = {key: "PASS" for key in ("sdkRootMainStatus", "perryTuiMainStatus", "publicMainImport", "alpha1EvalNotLoaded")}
  graph.update(contexts={}, loadedFiles=[])
  (runtime / "actual-module-graph.json").write_text(json.dumps(graph))
  for name, version in {"@deepseek-ai/dsh": "0.2.0-rc.2", "dsh-auto-review": "0.12.17",
      "@deepseek-harness-tui/dsh-tui": "0.14.0", "@deepseek-ai/dsh-base": "0.2.0-rc.2",
      "rotom-dsh-cursor-terminal": "0.1.1", "@deepseek-ai/cordis": "4.0.5-alpha.1",
      "@deepseek-ai/schemastery": "3.18.5-alpha.1"}.items():
    path = runtime / "node_modules" / name
    path.mkdir(parents=True)
    (path / "package.json").write_text(json.dumps({"name": name, "version": version}))
  local = tmp_path / "machine.toml"
  local.write_text('schema_version=1\n[machine]\nid="offline-experience"\n'
    '[overrides.providers.fixture]\nprotocol="openai-compatible"\nbase_url="https://fixture.invalid/v1"\nauth_kind="api-key"\ncredential_ref="secret:fixture"\n'
    '[overrides.models.fixture]\nprovider="fixture"\nremote_id="fixture-model"\ninput=["text"]\n'
    '[overrides.profiles.dsh-default]\nproviders=["fixture"]\nmodels=["fixture"]\n'
    '[overrides.profiles.dsh-default.roles]\nmain="fixture"\n[secrets]\nfixture="test-shared-api-key"\n')
  local.chmod(0o600)
  return local, tmp_path / "experience", runtime


def test_fixture_policy_is_probe_only_and_bounded():
  rows = native.load((ROOT / entry.FIXTURE / "cordis.patch.yml").read_bytes())
  config = rows[0]["config"]
  assert config["toolsPolicy"] == {"default": "human", "overrides": {"rotom_review_probe": "ai"}}
  assert config["reviewerTools"] == ["rotom_review_fact"]
  assert config["reviewerProvider"] == "spawn" and config["reviewerTimeoutMs"] == 30000
  assert config["reasonMaxChars"] == 256 and config["contextBudget"]["turns"] == 0
  assert config["maxReviewsPerTurn"] == config["maxFailuresPerTurn"] == 1
  assert config["fallbackPolicy"] == "delegate" and config["allowUnmarkedAudit"] is False


def test_prepare_is_idempotent_and_keeps_native_ui_unknowns(experience):
  local, directory, runtime = experience
  before_local = local.read_bytes()
  workspace = entry.prepare(local, directory, runtime)
  profile = workspace.instance / "dsh-home/profiles/agentcfg"
  manifest = json.loads((profile / "package.json").read_bytes())
  assert manifest["dsh"]["profile"]["bundles"] == ["@deepseek-ai/dsh-base", "dsh-auto-review", entry.PACKAGE, "@deepseek-harness-tui/dsh-tui"]
  assert manifest["dependencies"][entry.PACKAGE].startswith("file:")
  with Tree(workspace.instance) as tree:
    name = workspace.adapter.shared_files[0]
    document = dep.parse_native(tree.read(name)[0], "cordis-yaml")
    document["dsh-tui"]["config"].update(whale=False, unknown={"retain": True})
    tree.write_state(name, dep.encode_native(document, "cordis-yaml"))
    tree.write_state("user-home/.dsh-tui/theme.json", b'{"theme":"rotom-poimandres","unknown":true}')
  entry.prepare(local, directory, runtime)
  with Tree(workspace.instance) as tree:
    document = dep.parse_native(tree.read(workspace.adapter.shared_files[0])[0], "cordis-yaml")
    assert document["dsh-tui"]["config"]["whale"] is False
    assert document["dsh-tui"]["config"]["unknown"] == {"retain": True}
    assert document["dsh-tui"]["config"]["recapOnOpen"] is False
  assert json.loads((workspace.instance / "user-home/.dsh-tui/theme.json").read_bytes())["unknown"]
  assert local.read_bytes() == before_local
  assert "test-shared-api-key" not in (directory / entry.OWNER).read_text()


def test_owned_drift_rejects_prepare_and_run_before_subprocess(experience, monkeypatch):
  local, directory, runtime = experience
  workspace = entry.prepare(local, directory, runtime)
  path = workspace.instance / "dsh-home/experience.patch.yml"
  changed = path.read_bytes() + b"\n# drift\n"
  path.write_bytes(changed)
  monkeypatch.setattr(entry.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("host must not start"))
  for operation in (lambda: entry.prepare(local, directory, runtime),
      lambda: entry.run_experience(local, directory, runtime, allow_host=True)):
    with pytest.raises(Conflict):
      operation()
    assert path.read_bytes() == changed


def test_run_requires_opt_in_and_uses_isolated_paths(experience, monkeypatch, capsys):
  local, directory, runtime = experience
  workspace = entry.prepare(local, directory, runtime)
  with pytest.raises(Conflict):
    entry.run_experience(local, directory, runtime)
  captured = {}
  class Child:
    def wait(self, **_kwargs):
      return 7
    def poll(self):
      return 7
  def fake(argv, **kwargs):
    captured.update(argv=argv, **kwargs)
    return Child()
  monkeypatch.setattr(entry.subprocess, "Popen", fake)
  assert entry.run_experience(local, directory, runtime, allow_host=True) == 7
  assert captured["argv"][1].endswith("experience-dsh-auto-review.mjs")
  assert captured["env"]["HOME"] == str(workspace.instance / "user-home")
  assert captured["env"]["DSH_HOME"] == str(workspace.instance / "dsh-home")
  for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
    assert captured["env"][key].startswith(str(directory) + "/environment/")
  assert "test-shared-api-key" in captured["env"].values()
  assert "test-shared-api-key" not in capsys.readouterr().out
  assert captured["start_new_session"] is True
  assert captured["cwd"] == directory / "workspace"
  assert (directory / "workspace").is_dir()


def test_runtime_or_projection_drift_blocks_run(experience, monkeypatch):
  local, directory, runtime = experience
  workspace = entry.prepare(local, directory, runtime)
  monkeypatch.setattr(entry.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("host must not start"))
  (runtime / "package.json").write_text('{"changed":true}')
  with pytest.raises(Conflict):
    entry.run_experience(local, directory, runtime, allow_host=True)



def test_root_operation_lock_blocks_prepare_and_run(experience, monkeypatch):
  from agentcfg.storage import instance_lock
  local, directory, runtime = experience
  entry.prepare(local, directory, runtime)
  monkeypatch.setattr(entry.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("host must not start"))
  with Tree(directory) as tree, instance_lock(tree):
    with pytest.raises(Conflict):
      entry.prepare(local, directory, runtime)
    with pytest.raises(Conflict):
      entry.run_experience(local, directory, runtime, allow_host=True)


def test_ctrl_c_cleanup_is_bounded_and_only_targets_child(experience, monkeypatch):
  import signal
  import subprocess
  local, directory, runtime = experience
  entry.prepare(local, directory, runtime)
  actions = []
  class Child:
    pid = 987654
    calls = 0
    def wait(self, timeout=None):
      self.calls += 1
      actions.append(("wait", timeout))
      if self.calls == 1:
        if hasattr(signal, "SIGWINCH"):
          signal.raise_signal(signal.SIGWINCH)
        raise KeyboardInterrupt()
      if self.calls in (2, 3):
        raise subprocess.TimeoutExpired("fake-child", timeout)
      return -9
    def poll(self):
      return -9
    def send_signal(self, value):
      actions.append(("signal", value))
    def terminate(self):
      actions.append(("terminate",))
    def kill(self):
      actions.append(("kill",))
  monkeypatch.setattr(entry.subprocess, "Popen", lambda *_args, **_kwargs: Child())
  monkeypatch.setattr(entry.os, "getpgid", lambda pid: pid)
  monkeypatch.setattr(entry.os, "killpg", lambda pid, value: actions.append(("group", pid, value)))
  assert entry.run_experience(local, directory, runtime, allow_host=True) == 137
  assert ("signal", signal.SIGINT) in actions
  assert ("group", Child.pid, signal.SIGTERM) in actions
  assert ("group", Child.pid, signal.SIGKILL) in actions
  if hasattr(signal, "SIGWINCH"):
    assert ("signal", signal.SIGWINCH) in actions
  assert all(timeout == 5 for label, *rest in actions if label == "wait" for timeout in rest if timeout is not None)
