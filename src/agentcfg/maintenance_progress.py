"""持久维护进展的内部记账，不授予控制、停止完成或维护许可。

exit_confirmed 仅指同身份完整后代观察已保存，不证明 manager 或三层 SH 已释放。
调用方仍须另核实观察来源/时效、原物理 EX 门禁和维护批准；没有信号或宿主操作。
本模块只推进 accepted/stop_requested，后续失败、完成、维护和恢复阶段交给专属转换。
"""
from copy import deepcopy
from dataclasses import dataclass

from . import maintenance, maintenance_store, maintenance_wait, run_owners
from .control_deadline import ControlDeadline
from .maintenance_wait import ReleaseWaitResult
from .resource_coordination import _physical
from .storage import Conflict, Tree


_ERROR = "维护停止进展或原批次不能确认；保留已保存事实且不重试"


@dataclass(frozen=True)
class BatchReleaseWaitResult(ReleaseWaitResult):
  """携带初读或本调用最后明确保存的 CAS revision，不从未知响应读回升级。"""

  revision: int


def _load(domain, state, batch_id):
  run_owners._run_id(batch_id)
  with Tree(domain.root) as tree:
    if tree.fd is None or _physical(tree.fd) != state["physical"]:
      raise ValueError()
    saved = maintenance_store._read(state, tree, batch_id)
    if saved is None or "progress" not in saved["intent"]:
      raise ValueError()
    batch = maintenance.decode_batch(maintenance.encode_batch(saved["intent"]["progress"]))
    return saved, batch


def read_batch(domain, batch_id):
  """只读独立副本；旧 intent 缺 progress 时不从 acceptance 猜造初始进展。"""
  try:
    with domain._transaction() as state:
      return deepcopy(_load(domain, state, batch_id)[1])
  except Exception:
    raise Conflict(_ERROR) from None


def _write(domain, batch_id, expected_revision, change):
  try:
    if type(expected_revision) is not int or not 0 <= expected_revision <= 2**64 - 1:
      raise ValueError()
    with domain._transaction(write=True) as state:
      saved, batch = _load(domain, state, batch_id)
      if (saved["intent"]["phase"] not in ("active", "dispatched")
          or batch["phase"] not in ("accepted", "stop_requested")
          or batch["revision"] != expected_revision):
        raise ValueError()
      change(batch, saved["acceptance"])
      if any(item["stop_phase"] == "unknown" for item in batch["items"]):
        batch["phase"], batch["review_required"] = "unknown", True
        state["intents"][batch_id]["phase"] = "unknown"
      else:
        batch["phase"] = "stop_requested" if any(item["facts"]["stop_requested"] for item in batch["items"]) else "accepted"
      batch["revision"] += 1
      normalized = maintenance.decode_batch(maintenance.encode_batch(batch))
      state["intents"][batch_id]["progress"] = normalized
      return deepcopy(normalized)
  except Exception:
    raise Conflict(_ERROR) from None


def _item(batch, run_id):
  run_owners._run_id(run_id)
  if run_id not in batch["accepted_runs"]:
    raise ValueError()
  return next(item for item in batch["items"] if item["run_id"] == run_id)


def record_stop_requested(domain, batch_id, *, expected_revision, run_id):
  """报告当次请求事实，不能据此重发；已经保存的事实须只读核对。"""
  def change(batch, acceptance):
    item = _item(batch, run_id)
    if item["stop_phase"] != "accepted" or item["facts"]["stop_requested"]:
      raise ValueError()
    item["facts"]["stop_requested"] = True
    item["stop_phase"] = "stop_requested"
  return _write(domain, batch_id, expected_revision, change)


def record_exit(domain, batch_id, *, expected_revision, proof):
  """仅保存完整同 run/manager 观察，绝不设置 resources_released/session_sealed。"""
  def change(batch, acceptance):
    if type(proof) is not run_owners.ReleaseObservation:
      raise ValueError()
    item = _item(batch, proof.run_id)
    manager = acceptance["records"][proof.run_id]["manager_identity"]
    if item["facts"]["exit_confirmed"] or not maintenance_wait._proof_matches(proof, proof.run_id, manager):
      raise ValueError()
    item["facts"]["exit_confirmed"] = True
  return _write(domain, batch_id, expected_revision, change)


def mark_unknown(domain, batch_id, *, expected_revision, run_id):
  """保留所有已发生事实并封闭本次自动推进，不清 owner、预留或保护。"""
  def change(batch, acceptance):
    item = _item(batch, run_id)
    item["stop_phase"] = "unknown"
  return _write(domain, batch_id, expected_revision, change)


def wait_for_batch_release(domain, batch_id, *, deadline, observe):
  """共用原预算顺序 CAS 保存新观察；0 不等于停止完成、SH 释放或维护许可。

  observe 必须可信且非阻塞；record/fsync 可跨过期限，不提供硬实时中断。
  响应不明不重试，也不通过重新读回把本轮未知响应伪装为已确认。
  """
  try:
    if type(deadline) is not ControlDeadline or not callable(observe):
      raise ValueError()
    with domain._transaction() as state:
      saved, batch = _load(domain, state, batch_id)
      if (saved["intent"]["phase"] not in ("active", "dispatched")
          or batch["phase"] not in ("accepted", "stop_requested")):
        raise ValueError()
    existing = {item["run_id"] for item in batch["items"] if item["facts"]["exit_confirmed"]}
    targets = {run: deepcopy(saved["acceptance"]["records"][run]["manager_identity"])
      for run in batch["accepted_runs"] if run not in existing}
  except Exception:
    raise Conflict(_ERROR) from None
  revision = batch["revision"]
  if not targets:
    try:
      reason = "deadline-expired" if deadline.expired() else None
    except Exception:
      reason = "clock-unconfirmed"
    return BatchReleaseWaitResult(tuple(sorted(existing)), (), 4 if reason else 0, reason, revision)

  def record(proof):
    nonlocal revision
    revision = record_exit(domain, batch_id, expected_revision=revision, proof=proof)["revision"]

  result = maintenance_wait.wait_for_release(targets, deadline=deadline, observe=observe, record=record)
  return BatchReleaseWaitResult(tuple(sorted(existing | set(result.confirmed_runs))), result.pending_runs,
    result.exit_code, result.reason, revision)
