"""代码快照使用真实临时文件/写租约；helper和物理身份均为替身。"""

from pathlib import Path
import pytest

from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict
from test_pi_operations import setup
from test_pi_activity import identity


def fixture(tmp_path):
  operations, host, cwd, manager = setup(tmp_path)
  manifest = host.manifest()
  manifest["resource_ids"] = {"extensions": {"git-checkpoint": "extension"}}
  manifest["options"]["checkpoints"] = {"paths": ["src"], "max_files": 10, "max_bytes": 10000}
  rule = manifest["permission_policy"]["rules"][0]
  rule.update(tool_ids=["read", "ls", "write", "edit"], operations=["read", "list", "write", "create", "delete"])
  project = Path(cwd); (project / "src").mkdir(); (project / "src/a.py").write_text("original")
  (project / "src/.env").write_text("synthetic-secret-not-captured")
  service = operations.checkpoints
  base = {"session_id": "session", "cwd": cwd}
  sequence = [0]
  def start(operation, **extra):
    sequence[0] += 1
    ticket = service.prepare(manager, {**base, "operation": operation, "operation_id": str(sequence[0]), **extra})
    lease = host.store.read(ticket["lease_id"])
    process = identity(300 + sequence[0]); host.store.processes.current[process["pid"]] = process
    host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: process)
    return ticket, Principal("worker", lease["lease_id"], lease["grant_generation"]), process
  def end(ticket, process):
    host.store.processes.current.pop(process["pid"])
    host.store.finish(ticket["lease_id"], host.store.owner)
  def perform(operation, **extra):
    ticket, worker, process = start(operation, **extra)
    try: return service.perform(worker, {"operation_id": ticket["operation_id"]})
    finally: end(ticket, process)
  return service, host, project, manager, base, start, end, perform


def test_capture_persists_across_controller_restart_and_excludes_secrets(tmp_path):
  from agentcfg.pi_checkpoints import Checkpoints
  service, host, _, manager, base, _, _, perform = fixture(tmp_path)
  result = perform("capture", entry_id="entry")
  restarted = Checkpoints(host)
  assert restarted.list(manager, base)["checkpoints"][0]["checkpoint_id"] == result["checkpoint_id"]
  assert restarted.list(manager, {**base, "entry_id": "missing"})["checkpoints"] == []
  body = (service.root / "objects" / (result["checkpoint_id"] + ".json")).read_text()
  import base64
  assert "synthetic-secret" not in body and base64.b64encode(b"synthetic-secret-not-captured").decode() not in body
  assert result["files"] == 1


def test_preview_restore_and_backup_cover_modified_deleted_and_new_files(tmp_path):
  service, _, project, manager, base, _, _, perform = fixture(tmp_path)
  old = perform("capture", entry_id="entry")["checkpoint_id"]
  (project / "src/a.py").write_text("edited")
  (project / "src/new.py").write_text("new")
  preview = service.preview(manager, {**base, "checkpoint_id": old})
  assert preview["write_count"] == 1 and preview["delete_count"] == 1
  result = perform("restore", **{key: preview[key] for key in ("checkpoint_id", "before_digest", "scope_digest")})
  assert result["status"] == "completed" and result["changed"] == 2
  assert (project / "src/a.py").read_text() == "original" and not (project / "src/new.py").exists()
  backup = service.preview(manager, {**base, "checkpoint_id": result["backup_id"]})
  assert perform("restore", **{key: backup[key] for key in ("checkpoint_id", "before_digest", "scope_digest")})["status"] == "completed"
  assert (project / "src/a.py").read_text() == "edited" and (project / "src/new.py").read_text() == "new"
  assert (project / "src/.env").read_text() == "synthetic-secret-not-captured"


def test_restore_preview_is_invalidated_by_changes_and_no_files_are_overwritten(tmp_path):
  service, _, project, manager, base, _, _, perform = fixture(tmp_path)
  old = perform("capture")["checkpoint_id"]
  preview = service.preview(manager, {**base, "checkpoint_id": old})
  (project / "src/a.py").write_text("changed after preview")
  with pytest.raises(Conflict, match="PREVIEW_STALE"):
    perform("restore", **{key: preview[key] for key in ("checkpoint_id", "before_digest", "scope_digest")})
  assert (project / "src/a.py").read_text() == "changed after preview"


def test_active_writer_prevents_checkpoint_and_revocation_prevents_io(tmp_path):
  service, host, project, manager, base, start, end, _ = fixture(tmp_path)
  ticket, worker, process = start("capture")
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    service.prepare(manager, {**base, "operation": "capture", "operation_id": "other"})
  host.store.request_cancel(ticket["lease_id"], host.store.owner)
  with pytest.raises(Conflict, match="CHECKPOINT_STALE"):
    service.perform(worker, {"operation_id": ticket["operation_id"]})
  assert host.store.workspaces.read(host.store.workspaces.identify(project))["state"] != "released"
  end(ticket, process)


def test_policy_change_and_cross_session_restore_are_rejected(tmp_path):
  service, host, project, manager, base, _, _, perform = fixture(tmp_path)
  old = perform("capture")["checkpoint_id"]
  with pytest.raises(Conflict, match="SCOPE_CHANGED"):
    service.preview(manager, {**base, "session_id": "different", "checkpoint_id": old})
  host.manifest()["permission_policy"]["rules"][0]["operations"].remove("delete")
  with pytest.raises(Conflict, match="SCOPE_CHANGED"):
    service.preview(manager, {**base, "checkpoint_id": old})
  assert (project / "src/a.py").read_text() == "original"


def test_partial_restore_keeps_before_backup_and_reports_failure(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  service, _, project, manager, base, _, _, perform = fixture(tmp_path)
  (project / "src/b.py").write_text("original b")
  old = perform("capture")["checkpoint_id"]
  (project / "src/a.py").write_text("edited a"); (project / "src/b.py").write_text("edited b")
  preview = service.preview(manager, {**base, "checkpoint_id": old})
  replace = Tree.replace
  def fail_second(tree, path, *args, **kwargs):
    if tree.root == project and str(path) == "src/b.py": raise OSError("synthetic disk failure")
    return replace(tree, path, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", fail_second)
  result = perform("restore", **{key: preview[key] for key in ("checkpoint_id", "before_digest", "scope_digest")})
  assert result["status"] == "partial" and result["changed"] == 1 and result["backup_id"]
  assert (project / "src/a.py").read_text() == "original" and (project / "src/b.py").read_text() == "edited b"
  assert (service.root / "objects" / (result["backup_id"] + ".json")).exists()


def test_missing_delete_permission_blocks_entire_restore_before_first_write(tmp_path):
  service, host, project, manager, base, _, _, perform = fixture(tmp_path)
  host.manifest()["permission_policy"]["rules"][0]["operations"].remove("delete")
  old = perform("capture")["checkpoint_id"]
  (project / "src/a.py").write_text("keep edited")
  (project / "src/new.py").write_text("keep new")
  preview = service.preview(manager, {**base, "checkpoint_id": old})
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    perform("restore", **{key: preview[key] for key in ("checkpoint_id", "before_digest", "scope_digest")})
  assert (project / "src/a.py").read_text() == "keep edited" and (project / "src/new.py").read_text() == "keep new"


def test_private_files_are_skipped_before_body_read_and_storage_quota_is_explicit(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  service, host, project, _, _, _, _, perform = fixture(tmp_path)
  host.manifest()["options"]["checkpoints"]["max_checkpoints"] = 1
  (project / "src/AUTH.JSON").write_text("synthetic-token")
  read = Tree.read
  def guarded(tree, path, **kwargs):
    assert not (tree.root == project and Path(path).name.casefold() in (".env", "auth.json")), "private body read"
    return read(tree, path, **kwargs)
  monkeypatch.setattr(Tree, "read", guarded)
  assert perform("capture")["files"] == 1
  with pytest.raises(Conflict, match="STORAGE_FULL"): perform("capture")
  assert (project / "src/a.py").read_text() == "original"


def test_corrupt_snapshot_cannot_restore_outside_configured_scope(tmp_path):
  import json
  from agentcfg.activity import digest
  from agentcfg.deployment import json_bytes
  from agentcfg.storage import Tree
  service, _, _, manager, base, _, _, perform = fixture(tmp_path)
  old = perform("capture")["checkpoint_id"]
  with Tree(service.root) as tree:
    path = "objects/" + old + ".json"
    value = json.loads(tree.read(path)[0])
    value["files"]["outside.txt"] = value["files"].pop("src/a.py")
    value["snapshot_digest"] = digest({key: item for key, item in value.items() if key != "snapshot_digest"})
    tree.write_state(path, json_bytes(value))
  with pytest.raises(Conflict, match="CHECKPOINT_CORRUPT"):
    service.preview(manager, {**base, "checkpoint_id": old})


def test_scope_with_many_files_never_silently_truncates_and_symlinks_fail(tmp_path):
  _, host, project, _, _, _, _, perform = fixture(tmp_path)
  host.manifest()["options"]["checkpoints"]["max_files"] = 1
  (project / "src/b.py").write_text("b")
  with pytest.raises(Conflict, match="CHECKPOINT_LIMIT"): perform("capture")
  (project / "src/b.py").unlink(); (project / "src/link").symlink_to("a.py")
  with pytest.raises(Conflict): perform("capture")


def test_storage_quota_and_theme_changes_do_not_invalidate_file_scope(tmp_path):
  service, host, _, manager, base, _, _, perform = fixture(tmp_path)
  old = perform("capture")["checkpoint_id"]
  host.manifest()["options"]["checkpoints"]["max_checkpoints"] = 200
  host.manifest()["options"]["ui"] = {"theme": "another"}
  assert service.preview(manager, {**base, "checkpoint_id": old})["write_count"] == 0
  assert service.list(manager, base)["checkpoints"][0]["checkpoint_id"] == old
