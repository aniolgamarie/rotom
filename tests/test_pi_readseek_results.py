"""用伪造计算产物覆盖真实文件提交链，不运行 Pi 或 ReadSeek。"""
import json
import hashlib
from pathlib import Path

import pytest

from agentcfg.pi_readseek_results import accept_result, ensure_mapping_unambiguous, fresh_anchors, validate_request, worker_parameters
from agentcfg.pi_readseek_snapshot import export_snapshot
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_guarded_files import fixture


def prepared(tmp_path, tool="readSeek_write"):
  root, files, state, _ = fixture(tmp_path)
  snap = export_snapshot(files, "write", root, tmp_path / "snapshot", selected_paths=["src/a.txt"])
  params = {"path": "src/a.txt", "content": "modified"} if tool == "readSeek_write" else {"path": "src/a.txt"}
  output = {"schema_version": 1, "operation_id": "fixture-call", "tool": tool, "snapshot_digest": snap["snapshot_digest"],
    "result": {"content": [{"type": "text", "text": str(tmp_path / "snapshot/src/a.txt")}]}, "anchor_events": []}
  def accept(value=output, arguments=params):
    value.setdefault("computed_entries", [{"path": path.relative_to(tmp_path / "snapshot").as_posix(),
      "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
      for path in sorted((tmp_path / "snapshot").rglob("*")) if path.is_file() and not path.is_symlink()])
    return accept_result(files, "write", snap, tool, arguments, value,
      journal_root=tmp_path / "journals", operation_id="fixture-call", anchors={})
  return root, files, state, snap, params, output, accept


def test_tool_contracts_keep_all_nine_tools_and_reject_unknown_fields():
  contracts = json.loads((Path(__file__).parents[1] / "agents/pi/runtime/readseek-tool-contracts.json").read_text())
  assert validate_request(contracts, "readSeek_write", {"path": "file", "content": "secret remains private"})["path"] == "file"
  for params in ({"path": "file", "content": "text", "bypass": True}, {"path": 3, "content": "text"}):
    with pytest.raises(ConfigError, match="arguments"): validate_request(contracts, "readSeek_write", params)
  with pytest.raises(ConfigError, match="request"): validate_request(contracts, "bash", {})


def test_fake_worker_to_verified_commit_preserves_public_paths_and_anchors(tmp_path):
  root, files, _, snap, params, output, accept = prepared(tmp_path)
  ensure_mapping_unambiguous(snap, params)
  private = tmp_path / "snapshot/src/a.txt"
  mapped = worker_parameters(snap, params)
  assert mapped == {"path": str(private), "content": "modified"}
  private.write_text("modified")
  output["anchor_events"] = [{"action": "mark", "path": str(private)}]
  result = accept()
  assert (root / "src/a.txt").read_text() == "modified"
  assert result["mutation"]["changed_files"] == 1
  assert result["result"]["content"][0]["text"] == str(root / "src/a.txt")
  assert fresh_anchors(snap, result["anchors"]) == []  # 旧副本基线不能保留新锚点。
  current = export_snapshot(files, "read", root, tmp_path / "next-snapshot", selected_paths=["src/a.txt"])
  assert fresh_anchors(current, result["anchors"]) == [str(tmp_path / "next-snapshot/src/a.txt")]


@pytest.mark.parametrize("kind", ["readonly", "wrong-file", "deleted", "symlink", "error", "anchor", "identity", "computed-digest", "stale", "revoked"])
def test_invalid_compute_results_never_change_business_files(tmp_path, kind):
  tool = "readSeek_digest" if kind == "readonly" else "readSeek_write"
  root, _, state, snap, params, output, accept = prepared(tmp_path, tool)
  private = tmp_path / "snapshot/src/a.txt"
  private.write_text("modified")
  if kind == "wrong-file": (private.parent / "other.txt").write_text("unauthorized")
  if kind == "deleted": private.unlink()
  if kind == "symlink": private.unlink(); private.symlink_to(root / "src/a.txt")
  if kind == "error": output["result"]["isError"] = True
  if kind == "anchor": output["anchor_events"] = [{"action": "mark", "path": "/outside/sentinel"}]
  if kind == "identity": output["operation_id"] = "another-call"
  if kind == "computed-digest": output["computed_entries"] = []
  if kind == "stale": (root / "src/a.txt").write_text("external change")
  if kind == "revoked": state["valid"] = False
  with pytest.raises(Conflict): accept()
  assert (root / "src/a.txt").read_text() == ("external change" if kind == "stale" else "original")
  assert not (root / "src/other.txt").exists()
  assert not (tmp_path / "journals").exists()


def test_ambiguous_prefix_and_path_escape_are_rejected_before_compute(tmp_path):
  _, _, _, snap, params, _, _ = prepared(tmp_path)
  for path in ("../sentinel", "/outside/file", "~/.secret", ".git/config"):
    with pytest.raises((ConfigError, Conflict)): worker_parameters(snap, {"path": path})
  with pytest.raises(Conflict, match="COLLISION"):
    ensure_mapping_unambiguous(snap, {**params, "content": snap["snapshot_root"]})
  assert worker_parameters(snap, {**params, "content": "/outside/source literal"})["content"] == "/outside/source literal"


def test_workspace_rename_requires_complete_scope_and_preview_cannot_write(tmp_path):
  root, files, _, snap, _, output, _ = prepared(tmp_path, "readSeek_rename")
  from agentcfg.activity import digest
  snap["scope_complete"] = False; snap["skipped"] = 1
  snap["snapshot_digest"] = digest({key: value for key, value in snap.items() if key != "snapshot_digest"})
  output["snapshot_digest"] = snap["snapshot_digest"]
  (tmp_path / "snapshot/src/a.txt").write_text("renamed symbol")
  output["computed_entries"] = [{"path": "src/a.txt", "size": len(b"renamed symbol"), "sha256": hashlib.sha256(b"renamed symbol").hexdigest()}]
  for apply in (False, True):
    with pytest.raises(Conflict): accept_result(files, "edit", snap, "readSeek_rename",
      {"path": "src/a.txt", "workspace": True, "apply": apply}, output,
      journal_root=tmp_path / "journals", operation_id="fixture-call", anchors={})
  assert (root / "src/a.txt").read_text() == "original"
