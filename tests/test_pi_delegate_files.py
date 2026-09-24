"""受控Codex文件代理原型：真实临时IO和租约，宿主始终为替身。"""
import base64
import json
from pathlib import Path
import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict, Tree
from test_pi_delegate import fixture


def writer(tmp_path, configure=None):
  controller, host, args, calls = fixture(tmp_path)
  source = Path(args["cwd"])
  candidate = tmp_path / "candidate"; candidate.mkdir(); (candidate / "code.txt").write_text("source")
  git = source / ".git/worktrees/candidate"; git.mkdir(parents=True)
  (candidate / ".git").write_text("gitdir: " + str(git) + "\n")
  (git / "gitdir").write_text(str(candidate / ".git") + "\n"); (git / "commondir").write_text("../..\n"); (git / "HEAD").write_text("a" * 40 + "\n")
  host.manifest()["options"]["model_delegate"].update(backends=["codex"], allowed_modes=["implement"], codex={"model": "fixture", "mode": "explicit-write", "network_route": "direct", "native_execution": {"allow_shell": True, "tool_network": "none"}})
  host.manifest()["permission_policy"]["rules"] = [{"id": "candidate", "kind": "file", "effect": "allow", "tool_ids": ["tk_read", "tk_write", "tk_edit"],
    "operations": ["read", "write", "create"], "root_ref": "project", "relative_path": ".", "match": "subtree"}]
  with Tree(host.runtime_root) as tree:
    tree.write_state("runtime/commands.json", json_bytes({"schema_version": 1, "programs": {"delegate-codex": {"entrypoint": "runtime/fake-entry", "backend_entrypoint": "bin/fake-codex", "kind": "codex", "engine": "python"}}}))
    tree.write_state("runtime/fake-entry", b"fake wrapper"); tree.write_state("bin/fake-codex", b"fake CLI")
  if configure: configure(host)
  request = controller.prepare(Principal("delegate"), {**args, "backend": "codex", "mode": "implement", "cwd": str(candidate), "model": {"provider_id": "openai", "model_id": "fixture"},
    "allow_workspace_write": True, "worktree_root": str(candidate)})
  controller.start(Principal("delegate"), request["run_id"])
  principal = Principal("worker", request["lease_id"], request["grant_generation"])
  def write(operation, path="code.txt", content=b"updated"):
    return controller.file_action(principal, {"run_id": request["run_id"], "lease_id": request["lease_id"], "grant_generation": request["grant_generation"], "operation_id": operation,
      "action": {"tool_id": "tk_write", "operation": "write", "path": path, "data_b64": base64.b64encode(content).decode(), "expected_digest": None}})
  return controller, host, source, candidate, request, write


def test_delegate_write_is_narrower_than_native_broad_write_and_never_mutates_source(tmp_path):
  controller, host, source, candidate, request, write = writer(tmp_path)
  assert write("one")["changed"]
  assert (candidate / "code.txt").read_text() == "updated" and (source / "code.txt").read_text() == "source"
  head = json.loads((controller.root / "mutations" / request["run_id"] / "head.json").read_text())
  assert head["state"] == "settled" and head["sequence"] == 1
  with pytest.raises(Conflict, match="DELEGATE_OPERATION_REPLAY"): write("one")
  with pytest.raises(Conflict): write("source", str(source / "code.txt"))
  with pytest.raises(Conflict): write("git", ".git")
  host.store.request_cancel(request["lease_id"], host.store.owner)
  with pytest.raises(Conflict, match="DELEGATE_GRANT_REVOKED"): write("revoked", content=b"forbidden")
  assert (candidate / "code.txt").read_text() == "updated"


def test_out_of_band_candidate_change_blocks_further_tool_writes(tmp_path):
  controller, host, source, candidate, request, write = writer(tmp_path)
  write("one")
  (candidate / "code.txt").write_text("outside change")
  with pytest.raises(Conflict, match="DELEGATE_MUTATION_UNSETTLED"): write("two")
  assert (candidate / "code.txt").read_text() == "outside change"


def test_mutation_verifier_replays_all_records_and_rejects_missing_or_foreign_proof(tmp_path):
  from agentcfg.pi_delegate_files import verify_mutations
  from agentcfg.pi_worker_files import snapshot
  controller, host, _, candidate, request, write = writer(tmp_path)
  assert verify_mutations(controller.root, request, snapshot(candidate))["sequence"] == 0
  write("one"); write("two", content=b"second")
  current = snapshot(candidate)
  assert verify_mutations(controller.root, request, current)["sequence"] == 2
  directory = controller.root / "mutations" / request["run_id"]
  from agentcfg.activity import digest
  record_path = digest("one") + ".json"
  with Tree(directory) as tree:
    original = tree.read(record_path)[0]
    record = json.loads(original)
    for field, bad in (("lease_id", "different-lease"), ("before_digest", "f" * 64), ("sequence", 2), ("state", "prepared")):
      tree.write_state(record_path, json_bytes({**record, field: bad}))
      with pytest.raises(Conflict, match="MUTATION_UNVERIFIED"):
        verify_mutations(controller.root, request, current)
    tree.write_state(record_path, original)
  (directory / record_path).unlink()
  with pytest.raises(Conflict, match="MUTATION_UNVERIFIED"):
    verify_mutations(controller.root, request, current)


def test_no_mutation_journal_cannot_certify_an_out_of_band_write(tmp_path):
  from agentcfg.pi_delegate_files import verify_mutations
  from agentcfg.pi_worker_files import snapshot
  controller, _, _, candidate, request, _ = writer(tmp_path)
  (candidate / "code.txt").write_text("uncontrolled write")
  with pytest.raises(Conflict, match="MUTATION_UNVERIFIED"):
    verify_mutations(controller.root, request, snapshot(candidate))
