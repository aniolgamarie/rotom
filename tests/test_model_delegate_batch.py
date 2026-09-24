"""批次CLI仅调用现有私有端点；socket、peer和所有进程均为替身。"""
from io import BytesIO
import json
import os
from pathlib import Path
import stat

import pytest

from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg import model_delegate_batch as batch
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree


def instance(tmp_path):
  root = tmp_path / "instance"
  binding = {"machine": "fixture", "local": str(tmp_path / "local.toml"), "profile": "pi-fixture"}
  with Tree(root, create=True) as tree: tree.write_state(".agentcfg-instance.json", json_bytes({"schema_version": 1, "binding": binding, "state_root": str(tmp_path / "state")}))
  return root, binding


def test_missing_manager_refuses_batch_without_starting_standalone_runners(tmp_path):
  root, _ = instance(tmp_path)
  with pytest.raises(DependencyError): batch.call(root, "status", {"batch_id": "batch"})


def test_batch_client_uses_private_identity_bound_socket_and_rejects_foreign_result(tmp_path, monkeypatch):
  root, binding = instance(tmp_path)
  socket_dir = tmp_path / "socket"; socket_dir.mkdir(mode=0o700)
  socket_path = socket_dir / "control.sock"; socket_path.write_bytes(b"fake socket"); socket_path.chmod(0o600)
  info = socket_path.lstat()
  endpoint = {"schema_version": 2, "instance_id": digest({"instance": str(root), "binding": binding}), "manager_activation_id": "activation",
    "socket": str(socket_path), "socket_identity": {"device": str(info.st_dev), "inode": str(info.st_ino)}, "capability": "a" * 64}
  with Tree(root) as tree: tree.write_state("pi-home/model-delegate/manager/control.json", json_bytes(endpoint))
  result = {"batch_id": "batch", "dispatch_ids": ["dispatch"], "result_refs": [], "state": "partial"}
  sent = []
  class Connection:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def settimeout(self, value): assert value == 30
    def connect(self, path): assert path == str(socket_path)
    def makefile(self, mode):
      assert mode == "rwb"
      self.reply = BytesIO(json_bytes({"ok": True, "result": result})); return self
    def write(self, body): sent.append(json.loads(body))
    def flush(self): pass
    def readline(self, limit): return self.reply.readline(limit)
  monkeypatch.setattr(batch.socket, "socket", lambda *args: Connection())
  monkeypatch.setattr(stat, "S_ISSOCK", lambda mode: stat.S_ISREG(mode))
  import agentcfg.pi_control
  monkeypatch.setattr(agentcfg.pi_control, "peer_uid", lambda _: os.geteuid())
  assert batch.call(root, "submit", {"batch_id": "batch", "items": [{"task": "审查中文"}]})["state"] == "partial"
  assert sent[0]["args"]["items"][0]["task"] == "审查中文"
  assert sent[0]["capability"] == "a" * 64
  result["batch_id"] = "other"
  with pytest.raises(Conflict, match="DELEGATE_BATCH_RESPONSE"): batch.call(root, "status", {"batch_id": "batch"})
  monkeypatch.setattr(agentcfg.pi_control, "peer_uid", lambda _: os.geteuid() + 1)
  with pytest.raises(Conflict, match="DELEGATE_BATCH_ENDPOINT"): batch.call(root, "status", {"batch_id": "batch"})


@pytest.mark.parametrize("payload", ["{broken", "[]", "{}"])
def test_batch_submit_malformed_input_fails_before_contacting_manager(tmp_path, payload, monkeypatch):
  source = tmp_path / "items.json"; source.write_text(payload)
  monkeypatch.setattr(batch, "call", lambda *args: pytest.fail("invalid input must not contact manager"))
  with pytest.raises(ConfigError): batch.main(["submit", "--instance", str(tmp_path / "unused"), "--batch-id", "batch", "--input", str(source)])


def test_large_batch_summary_keeps_the_private_complete_artifact_reference():
  from agentcfg.model_delegate import control_envelope
  data = {"batch_id": "batch", "state": "partial", "dispatch_ids": ["d" * 200] * 32, "result_refs": ["r" * 200] * 32, "artifact_ref": "batch-result-" + "a" * 64}
  raw = control_envelope(data)
  assert len(raw) <= 4096
  value = json.loads(raw)
  assert value["truncated"] and value["artifact_ref"] == data["artifact_ref"] and value["state"] == "partial"
