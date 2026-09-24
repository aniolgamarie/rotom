"""ReadSeek 计算结果的多文件提交：先全量准入，逐文件 CAS，保留可核验的中断日志。"""
import base64
import hashlib
import json
import os
from pathlib import Path

from .activity import digest
from .deployment import json_bytes
from .pi_guarded_files import GuardedFiles, MAX_FILE_BYTES
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


def content_digest(value):
  return hashlib.sha256(value).hexdigest() if value is not None else None


def commit_changes(files, tool, changes, journal_root, operation_id):
  """调用方持有活动工作区租约；此函数不启动进程、不自动回滚或重试未完成提交。"""
  if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 200 or not isinstance(changes, list) or len(changes) > 1000:
    raise ConfigError("readseek-mutation-plan")
  files.policy.current()
  rows, seen, total = [], set(), 0
  for change in changes:
    closed(change, ("path", "before", "after"))
    path, before, after = change["path"], change["before"], change["after"]
    if (not isinstance(path, str) or before is not None and not isinstance(before, bytes) or not isinstance(after, bytes)
        or len(after) > MAX_FILE_BYTES or before is not None and len(before) > MAX_FILE_BYTES):
      raise ConfigError("readseek-mutation-plan")
    target = files.policy.authorize(tool, "write", path)
    canonical = str(target["path"])
    if canonical in seen: raise ConfigError("readseek-mutation-duplicate")
    seen.add(canonical)
    total += len(after) + len(before or b"")
    if total > 32 * 1024 * 1024: raise ConfigError("readseek-mutation-limit")
    rows.append({"path": canonical, "before_digest": content_digest(before), "after_digest": content_digest(after),
      "before_b64": base64.b64encode(before).decode() if before is not None else None,
      "after_b64": base64.b64encode(after).decode()})
  rows.sort(key=lambda row: row["path"])
  changed = sum(row["before_digest"] != row["after_digest"] for row in rows)
  authority = digest({"grant": files.policy.grant, "policy": files.policy.metadata})
  plan = {"schema_version": 1, "operation_id": operation_id, "tool": tool, "authority_digest": authority, "changes": rows}
  plan_digest = digest(plan)
  slot = digest({"operation_id": operation_id, "authority_digest": authority})
  root = Path(journal_root) / slot
  with Tree(root, create=True) as journal:
    saved = journal.read("plan.json", max_bytes=64 * 1024 * 1024)
    if saved:
      if digest(json.loads(saved[0])) != plan_digest: raise Conflict("READSEEK_OPERATION_CONFLICT")
      state = journal.read("state.json", max_bytes=4096)
      if not state or json.loads(state[0]) != {"state": "committed", "plan_digest": plan_digest, "completed": len(rows)}:
        raise Conflict("READSEEK_MUTATION_INCOMPLETE")
      for row in rows:
        if content_digest(files.read(tool, row["path"])) != row["after_digest"]: raise Conflict("READSEEK_RESULT_STALE")
      return {"changed_files": changed, "journal_id": slot, "plan_digest": plan_digest, "replayed": True}
    # 在写第一份业务文件前验证每个目标与创建目录；拒绝部分范围被允许的“半成功”。
    for row in rows:
      target = files.policy.authorize(tool, "write", row["path"])
      if row["before_digest"] is None:
        files.policy.authorize(tool, "create", row["path"])
        with Tree(target["root"], private=False) as tree:
          try:
            with tree.parent(target["relative_path"]) as (fd, name): os.stat(name, dir_fd=fd, follow_symlinks=False)
          except FileNotFoundError: pass
          else: raise Conflict("FILE_CHANGED")
      elif content_digest(files.read(tool, row["path"])) != row["before_digest"]:
        raise Conflict("FILE_CHANGED")
      cursor = target["root"]
      for part in target["path"].parent.relative_to(target["root"]).parts:
        cursor /= part
        if not cursor.exists(): files.policy.authorize(tool, "create", str(cursor))
    journal.write_new("plan.json", json_bytes(plan))
    journal.write_new("state.json", json_bytes({"state": "prepared", "plan_digest": plan_digest, "completed": 0}))
    for index, row in enumerate(rows):
      def mutation(phase, detail):
        if detail["before_digest"] != row["before_digest"] or detail["after_digest"] != row["after_digest"]:
          raise Conflict("READSEEK_MUTATION_IDENTITY")
        journal.write_new(str(index).zfill(6) + "-" + phase + ".json", json_bytes({"plan_digest": plan_digest, "index": index, "mutation": detail}))
        return str(index)
      guarded = GuardedFiles(files.policy, mutation=mutation, max_read_bytes=files.max_read_bytes)
      try:
        guarded.write(tool, row["path"], base64.b64decode(row["after_b64"], validate=True),
          expected_digest=row["before_digest"], expect_absent=row["before_digest"] is None)
        journal.write_state("state.json", json_bytes({"state": "applying", "plan_digest": plan_digest, "completed": index + 1}))
      except Exception:
        # 任何失败保留 plan 与逐文件意图；不输出文件正文，不重复已写的前缀。
        raise Conflict("READSEEK_MUTATION_INCOMPLETE") from None
    journal.write_state("state.json", json_bytes({"state": "committed", "plan_digest": plan_digest, "completed": len(rows)}))
  return {"changed_files": changed, "journal_id": slot, "plan_digest": plan_digest, "replayed": False}


def inspect_changes(files, tool, journal_root, journal_id):
  """新授权下只读检查中断位置；结果不含原文，也不会自行继续或撤销写入。"""
  if not isinstance(journal_id, str) or len(journal_id) != 64 or any(char not in "0123456789abcdef" for char in journal_id):
    raise ConfigError("readseek-journal-id")
  with Tree(Path(journal_root) / journal_id) as journal:
    raw = journal.read("plan.json", max_bytes=64 * 1024 * 1024)
    if raw is None: raise Conflict("READSEEK_JOURNAL_MISSING")
    plan = json.loads(raw[0])
    closed(plan, ("schema_version", "operation_id", "tool", "authority_digest", "changes"))
    if plan["schema_version"] != 1: raise Conflict("READSEEK_JOURNAL_IDENTITY")
    if journal_id != digest({"operation_id": plan["operation_id"], "authority_digest": plan["authority_digest"]}):
      raise Conflict("READSEEK_JOURNAL_IDENTITY")
    status = journal.read("state.json", max_bytes=4096)
    if status and json.loads(status[0]).get("plan_digest") != digest(plan): raise Conflict("READSEEK_JOURNAL_IDENTITY")
    results = []
    for row in plan["changes"]:
      closed(row, ("path", "before_digest", "after_digest", "before_b64", "after_b64"))
      before = base64.b64decode(row["before_b64"], validate=True) if row["before_b64"] is not None else None
      after = base64.b64decode(row["after_b64"], validate=True)
      if content_digest(before) != row["before_digest"] or content_digest(after) != row["after_digest"]: raise Conflict("READSEEK_JOURNAL_IDENTITY")
      try: current = content_digest(files.read(tool, row["path"]))
      except FileNotFoundError: current = None
      state = "after" if current == row["after_digest"] else "before" if current == row["before_digest"] else "diverged"
      results.append({"path": row["path"], "state": state})
    return {"journal_id": journal_id, "plan_digest": digest(plan), "files": results}
