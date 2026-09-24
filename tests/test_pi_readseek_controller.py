"""监督控制器使用真实临时文件和假进程身份；不启动宿主或原生工具。"""
import base64
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_guarded_files import GuardedFiles
from agentcfg.pi_readseek_snapshot import export_snapshot
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict, Tree, ensure_private
from test_pi_activity import identity
from test_pi_operations import setup


def prepared(tmp_path, result_text="computed"):
  operations, host, cwd, principal = setup(tmp_path)
  ticket = operations.prepare(principal, {"operation_id": "readseek", "role_id": "main", "cwd": cwd,
    "tool_name": "write", "input": {"path": "code.txt", "content": "updated"}})
  record = operations.record(ticket["operation_id"])
  key = ticket["operation_id"]
  home = host.root / "activity/readseek-homes" / key; ensure_private(home)
  files = GuardedFiles(operations.policy(record, reserved=True), mutation=lambda *_: None)
  snapshot = export_snapshot(files, "write", cwd, home / "snapshot", selected_paths=["code.txt"])
  command = {**ticket, "grant_generation": record["grant"]["grant_generation"], "expires_at": record["grant"]["expires_at"]}
  operations.readseek.bind(command, record, session="session", tool="readSeek_write",
    params={"path": "code.txt", "content": "updated"}, snapshot=snapshot, home=home, permission_tool="write")
  host.store.processes.current[203] = identity(203)
  host.store.start(ticket["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  (home / "snapshot/code.txt").write_text("updated")
  output = {"schema_version": 1, "operation_id": key, "tool": "readSeek_write", "snapshot_digest": snapshot["snapshot_digest"],
    "result": {"content": [{"type": "text", "text": result_text}]},
    "anchor_events": [{"action": "mark", "path": str(home / "snapshot/code.txt")}],
    "computed_entries": [{"path": "code.txt", "size": 7, "sha256": hashlib.sha256(b"updated").hexdigest()}]}
  body = json_bytes(output)
  with Tree(home) as tree: tree.write_new("result.json", body)
  receipt = {"operation_id": key, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
  return operations, host, Path(cwd), principal, ticket, receipt


def terminate(host, ticket, exit_code=0):
  lease = host.store.read(ticket["lease_id"])
  host.store.processes.current.pop(203)
  host.store.finish(lease["lease_id"], host.store.owner)
  with Tree(host.root) as tree:
    tree.write_state("activity/exits/" + lease["lease_id"] + ".json", json_bytes({"schema_version": 1,
      "lease_id": lease["lease_id"], "process_identity": lease["process_identity"], "exit_code": exit_code}))


def test_acceptance_holds_writer_until_physical_exit_and_only_then_publishes_anchors(tmp_path):
  operations, host, cwd, principal, ticket, receipt = prepared(tmp_path)
  controller = operations.readseek
  result = controller.accept(principal, receipt)
  assert result == {"accepted": True, "operation_id": ticket["operation_id"]}
  assert (cwd / "code.txt").read_text() == "updated"
  lease = host.store.read(ticket["lease_id"])
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "active"
  assert controller.anchors == {}
  with pytest.raises(Conflict, match="TERMINATION_UNKNOWN"): controller.finalize(principal, {"operation_id": ticket["operation_id"]})
  with pytest.raises(Conflict, match="UNPUBLISHED"): controller.result(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  # 接受回复丢失可查询同一回执，不重复业务提交。
  assert controller.accept(principal, receipt) == result
  terminate(host, ticket)
  summary = controller.finalize(principal, {"operation_id": ticket["operation_id"]})
  assert summary["termination_confirmed"] and len(controller.anchors) == 1
  chunk = controller.result(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert json.loads(base64.b64decode(chunk["data_b64"])) == {"content": [{"type": "text", "text": "computed"}]}
  assert controller.discard(principal, {"operation_id": ticket["operation_id"]}) == {"discarded": True}


@pytest.mark.parametrize("kind", ["digest", "revoked", "worker", "source-changed"])
def test_invalid_acceptance_cannot_mutate_business_files(tmp_path, kind):
  operations, host, cwd, principal, ticket, receipt = prepared(tmp_path)
  if kind == "digest": receipt["sha256"] = "0" * 64
  if kind == "revoked": host.store.request_cancel(ticket["lease_id"], host.store.owner)
  if kind == "worker": principal = Principal("worker", ticket["lease_id"], 1)
  if kind == "source-changed": (cwd / "code.txt").write_text("external change")
  with pytest.raises(Conflict): operations.readseek.accept(principal, receipt)
  assert (cwd / "code.txt").read_text() == ("external change" if kind == "source-changed" else "source")
  assert operations.readseek.anchors == {}


def test_failed_exit_never_publishes_and_unknown_termination_cannot_discard(tmp_path):
  operations, host, _, principal, ticket, receipt = prepared(tmp_path)
  operations.readseek.accept(principal, receipt)
  with pytest.raises(Conflict, match="TERMINATION_UNKNOWN"):
    operations.readseek.discard(principal, {"operation_id": ticket["operation_id"]})
  terminate(host, ticket, exit_code=5)
  with pytest.raises(Conflict, match="EXIT_UNVERIFIED"):
    operations.readseek.finalize(principal, {"operation_id": ticket["operation_id"]})
  assert operations.readseek.anchors == {}


def test_large_result_is_private_and_returned_in_verified_rpc_chunks(tmp_path):
  text = "source output " * 90000
  operations, host, _, principal, ticket, receipt = prepared(tmp_path, text)
  operations.readseek.accept(principal, receipt); terminate(host, ticket)
  summary = operations.readseek.finalize(principal, {"operation_id": ticket["operation_id"]})
  assert summary["bytes"] > 1024 * 1024
  chunks = []
  for offset in range(0, summary["bytes"], 65536):
    reply = operations.readseek.result(principal, {"operation_id": ticket["operation_id"], "offset": offset, "limit": 65536})
    assert reply["sha256"] == summary["sha256"] and reply["bytes"] == summary["bytes"]
    chunks.append(base64.b64decode(reply["data_b64"]))
  assert json.loads(b"".join(chunks))["content"][0]["text"] == text
  with Tree(host.root) as tree:
    state = tree.read("activity/readseek-operations/" + ticket["operation_id"] + ".json")[0]
  assert b"source output" not in state and b"updated" not in state
