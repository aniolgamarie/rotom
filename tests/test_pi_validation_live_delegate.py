"""实网委托编排仅用 CLI/Git/控制通道替身；不接触真实宿主或账号。"""
from contextlib import nullcontext
import json
from pathlib import Path
import re
from types import SimpleNamespace
import pytest

from agentcfg.deployment import json_bytes
from agentcfg.storage import Tree, ensure_private
import agentcfg.pi_validation_live_delegate as live


def fixture(tmp_path, monkeypatch, capability="cursor", fault=None):
  instance, state, project = (tmp_path / name for name in ("instance", "state", "project"))
  for path in (instance, state, project): ensure_private(path)
  (project / ".git").mkdir(); (project / "source.txt").write_text("source must remain")
  route = "proxy" if capability == "proxy" else "direct"
  provider = "cursor" if capability == "cursor" else "agentcfg-provider"
  manifest = {"allowed_models": [{"provider": provider, "model": "selected-model"}], "model_bindings": {"scout": {"provider": provider, "model": "selected-model"}},
    "options": {"model_delegate": {"enabled": True, "backends": ["pi", "codex"], "max_run_seconds": 30, "allowed_modes": ["investigate", "implement"], "presets": ["general"],
      "pi": {"model_roles": ["scout"], "network_route": "selected"}, "codex": {"mode": "explicit-write", "model": "selected-model", "network_route": "selected"}},
      "network": {"routes": {"selected": {"mode": route, "provider_ids": [provider.removeprefix("agentcfg-")]}}}}}
  with Tree(instance) as tree: tree.write_new("pi-home/agentcfg-manifest.json", json_bytes(manifest))
  workspace = SimpleNamespace(instance=instance, state_root=state, local_path=tmp_path / "local.toml")
  profile = "pi-codex" if capability == "codex" else "pi-cursor" if capability == "cursor" else "pi-default"
  context = {"workspace": workspace, "runtime": SimpleNamespace(root=tmp_path / "runtime", engine="bun" if capability == "cursor" else "node"),
    "project": project, "item": {"capability_id": capability, "scenario_id": profile + ".live-" + capability},
    "native_transports": [route], "identity": {"fixture": True}, "scope_digest": "a" * 64}
  monkeypatch.setattr(live, "guard", lambda *_args, **_kwargs: nullcontext())
  monkeypatch.setattr(live, "assert_inactive", lambda _: None)
  monkeypatch.setattr(live.shutil, "which", lambda _: "/fixture/git")
  ids, canceled, commands = [], set(), []
  monkeypatch.setattr(live, "endpoint_call", lambda _i, _m, value: canceled.add(value["run_id"]))
  monkeypatch.setattr(live, "DelegationRuns", lambda _: SimpleNamespace(read=lambda run_id: {"request": {"continuation_of": ids[0]}}))
  marker = None
  def run(argv, **kwargs):
    nonlocal marker
    assert "OPENAI_API_KEY" not in kwargs["env"]
    if argv[0] != live.sys.executable:
      assert "core.hooksPath=/dev/null" in argv and "core.fsmonitor=false" in argv
      if "rev-parse" in argv: return SimpleNamespace(returncode=0, stdout=(str(project) + "\n").encode(), stderr=b"")
      assert "--no-checkout" in argv and "--detach" in argv
      candidate = Path(argv[-2]); candidate.mkdir(mode=0o700); (candidate / ".git").write_text("fixture pointer, not executed")
      return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    action = argv[4]; commands.append(action)
    if "--prompt-file" in argv:
      prompt = Path(argv[argv.index("--prompt-file") + 1]).read_text()
      marker = re.search(r"AGENTCFG_LIVE_[a-f0-9]{32}", prompt)[0]
    if action == "probe": value = {"capabilities": [{"execution": "not-run"}]}
    elif action in ("start", "resume"):
      run_id = "run-" + f"{len(ids) + 1:032x}"
      ids.append(run_id); value = {"run_id": run_id, "state": "running"}
      if "--mode" in argv and argv[argv.index("--mode") + 1] == "implement":
        cwd = Path(argv[argv.index("--cwd") + 1]); probe = cwd / "agentcfg-live-probe.txt"
        if fault == "symlink": probe.unlink(); probe.symlink_to(project / "source.txt")
        else: probe.write_text(marker + "_WRITTEN\n")
        if fault == "extra-file": (cwd / "unrequested.txt").write_text("extra")
    elif action == "cancel":
      canceled.add(argv[argv.index("--run-id") + 1]); value = {"accepted": True}
    elif action == "poll": value = {"events": [{"kind": "completed"}]}
    elif action == "result": value = {"content": "synthetic-private-result " + ("wrong marker" if fault == "response" else marker)}
    else:
      run_id = argv[argv.index("--run-id") + 1]
      value = {"state": "canceled" if run_id in canceled else "completed", "verification": "verified-execution"}
    return SimpleNamespace(returncode=0, stdout=json.dumps(value).encode(), stderr=b"synthetic-private-diagnostic")
  return context, run, commands


@pytest.mark.parametrize("capability", ["codex", "cursor", "proxy"])
def test_live_delegate_exercises_controls_and_only_explicit_codex_probe_write(tmp_path, monkeypatch, capability):
  monkeypatch.setenv("OPENAI_API_KEY", "never-inherit")
  context, run, commands = fixture(tmp_path, monkeypatch, capability)
  result = live.execute_delegate(context, recheck=lambda: context, run=run)
  assert result["status"] == "passed"
  assert result["facts"]["write_verified"] is (capability == "codex")
  assert result["facts"]["source_preserved"] and result["facts"]["termination_confirmed"]
  assert set(commands) == {"probe", "start", "status", "poll", "wait", "result", "resume", "cancel"}
  assert "synthetic-private" not in json.dumps(result)
  assert "synthetic-private" not in (Path(result["artifact_directory"]) / "summary.json").read_text()


@pytest.mark.parametrize("fault", ["response", "symlink", "extra-file"])
def test_live_delegate_rejects_wrong_response_or_unrequested_candidate_changes(tmp_path, monkeypatch, fault):
  context, run, _ = fixture(tmp_path, monkeypatch, "codex", fault)
  result = live.execute_delegate(context, recheck=lambda: context, run=run)
  assert result["status"] == "failed" and result["facts"]["source_preserved"]
  assert (context["project"] / "source.txt").read_text() == "source must remain"


def test_live_selection_does_not_borrow_direct_native_evidence_for_proxy(tmp_path, monkeypatch):
  context, run, calls = fixture(tmp_path, monkeypatch, "proxy")
  context["native_transports"] = ["direct"]
  result = live.execute_delegate(context, recheck=lambda: context, run=run)
  assert result["status"] == "not-run" and result["reason"] == "live-native-transport-not-covered"
  assert calls == []


def test_changed_scope_prevents_start_and_never_turns_probe_into_execution(tmp_path, monkeypatch):
  context, run, calls = fixture(tmp_path, monkeypatch)
  result = live.execute_delegate(context, recheck=lambda: {"reason": "scope changed"}, run=run)
  assert result["status"] == "failed" and calls == ["probe"]
  assert not result["facts"]["service_response_verified"]
