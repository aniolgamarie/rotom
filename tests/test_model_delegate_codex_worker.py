"""固定 Codex wrapper 的完整控制流；Popen、监督通道和 stdout 均为替身。"""

from io import BytesIO
import json
import os
from pathlib import Path
import runpy

import pytest

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.storage import Tree
from test_model_delegate_contract import request

ROOT = Path(__file__).resolve().parents[1]


def test_rejected_event_diagnostic_contains_only_local_enumerations():
  module = runpy.run_path(str(ROOT / "scripts/pi-delegate-codex.py"))
  from agentcfg.schema import ConfigError
  result = module["rejected_event"](ConfigError("delegate-codex-item-type"), {"type": "item.completed", "item": {"type": "reasoning", "text": "synthetic-private-reasoning"}})
  assert result == {"schema_version": 1, "event_type": "item.completed", "item_type": "reasoning", "failure_code": "delegate-codex-item-type"}
  unknown = module["rejected_event"](ConfigError("synthetic-private-error"), {"type": "synthetic-private-event", "item": {"type": ["private"]}})
  assert "private" not in json.dumps(unknown)


@pytest.mark.parametrize("scenario", ["success", "malformed", "blocked"])
def test_codex_wrapper_preserves_identity_and_discards_private_stream_content(tmp_path, monkeypatch, scenario):
  malformed = scenario == "malformed"
  module = runpy.run_path(str(ROOT / "scripts/pi-delegate-codex.py"))
  main = module["main"]
  root, temporary, reports = tmp_path / "project", tmp_path / "worker", tmp_path / "reports"
  root.mkdir(); temporary.mkdir(mode=0o700); monkeypatch.chdir(root)
  value = request("codex"); value["cwd"] = str(root)
  data = {"schema_version": 2, "request": value, "prompt": "bounded fixture", "grant": {}, "route": {"mode": "direct"}}
  data["execution_policy"] = {"boundary": "native-sandbox", "file_policy": {"schema_version": 1, "default": "deny", "rules": []}, "native_execution": {"allow_shell": True, "tool_network": "none"}}
  data["execution_policy"]["root_limits"] = {"bindings": {}, "readonly_roots": [], "denied_roots": []}
  data["execution_policy"]["configuration_admission"] = "official-cli-restricted-v1"
  value["policy_digest"] = digest(data["execution_policy"]["file_policy"])
  value["execution_policy_digest"] = digest(data["execution_policy"])
  data["definition_digest"] = digest(data)
  worker = {"schema_version": 2, "input": data, "reports": str(reports), "runtime_root": str(tmp_path / "runtime"), "instance_root": str(tmp_path / "instance"),
    "temporary": str(temporary), "backend_executable": "/fixture/codex", "native_permissions": {":root": "deny", ":minimal": "read", str(root): "read"}}
  with Tree(tmp_path) as tree:
    tree.write_state("input.json", json_bytes(worker))
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_ENDPOINT", str(tmp_path / "endpoint")); monkeypatch.setenv("AGENTCFG_SUPERVISOR_CAPABILITY", "private-fixture")
  monkeypatch.setenv("CODEX_HOME", str(tmp_path / "instance/codex-home"))
  calls = []
  def control(_endpoint, _capability, message):
    method = message["method"]; calls.append(method)
    if method == "handshake":
      result = {"role": "worker", "lease_id": value["lease_id"], "process_identity": {"pid": os.getpid()}, "runtime_identity": value["runtime_identity"]}
    elif method == "authorize": result = {"valid": True}
    elif method == "delegate_abort": result = {"accepted": True, "termination_confirmed": False}
    else: raise AssertionError("unexpected control")
    return {"ok": True, "result": result}
  monkeypatch.setitem(main.__globals__, "control_request", control)
  def admit(home):
    assert home == str(tmp_path / "instance/codex-home")
    calls.append("configuration-admission")
    if scenario == "blocked": raise module["CodexAdmissionError"]("CODEX_SYSTEM_CONFIG_PRESENT")
    return {"policy": "fixture", "atomic_config_binding": False}
  monkeypatch.setitem(main.__globals__, "admit_codex_execution", admit)
  events = [{"type": "thread.started", "thread_id": "fixture-thread"}, {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "thought", "type": "reasoning", "text": "synthetic-private-reasoning"}},
    {"type": "item.completed", "item": {"id": "answer", "type": "agent_message", "text": "fixture final"}},
    {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}]
  raw = b"bad-json\n" if malformed else b"".join(json_bytes(event) for event in events)
  class Fake:
    def __init__(self, argv, **options):
      assert scenario != "blocked" and calls[-2:] == ["configuration-admission", "authorize"]
      assert argv[0] == "/fixture/codex"
      assert "AGENTCFG_SUPERVISOR_CAPABILITY" not in options["env"]
      assert options["start_new_session"] is False
      self.stdin, self.stdout, self.stderr = BytesIO(), BytesIO(raw), BytesIO(b"synthetic-private-error-token")
      (temporary / "native-final.md").write_text("fixture final")
    def wait(self): return 0
  monkeypatch.setattr(module["subprocess"], "Popen", Fake)
  monkeypatch.setattr(module["sys"], "argv", ["worker", "--input", str(tmp_path / "input.json")])
  if scenario == "blocked":
    with pytest.raises(module["CodexAdmissionError"], match="CODEX_SYSTEM_CONFIG_PRESENT"): main()
    assert not (reports / "ready.json").exists() and not (temporary / "native-final.md").exists()
    return
  assert main() == (5 if malformed else 0)
  result = json.loads((reports / "result.json").read_text())
  assert result["host_completed"] is (not malformed)
  assert result["observed_model"] is None and result["usage"]["cost"] is None
  text = "\n".join(path.read_text() for path in reports.glob("*.json"))
  assert "synthetic-private-reasoning" not in text and "synthetic-private-error-token" not in text
  assert (reports / "final.md").exists() is (not malformed)
  assert ("delegate_abort" in calls) is malformed
