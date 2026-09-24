"""登录与委托不能同时修改/读取同一账号归属；不执行真实登录。"""
from agentcfg.pi_login import account_available
from agentcfg.deployment import json_bytes
from agentcfg.storage import Conflict, Tree
from test_pi_activity import make_store, identity
from types import SimpleNamespace
import pytest


def test_login_waits_for_existing_codex_runs_and_delegate_waits_for_login(tmp_path):
  store, processes = make_store(tmp_path)
  host = SimpleNamespace(store=store, root=store.root)
  args = {"kind": "codex", "task_id": None, "lock_identity": "a" * 64, "slice_identity": "b" * 64,
    "policy_digest": "c" * 64, "candidate_digest": None, "planned_workspaces": []}
  running = store.allocate(**args, execution_id="running", attempt_id="running")
  processes.current[201] = identity(201)
  store.start(running["lease_id"], store.owner, spawn=lambda _: identity(201))
  next_run = store.allocate(**args, execution_id="next", attempt_id="next")
  path = "activity/commands/" + running["lease_id"] + ".json"
  with Tree(store.root) as tree: tree.write_state(path, json_bytes({"program": "delegate-codex"}))
  account_available(host, next_run, login=False)
  with pytest.raises(Conflict, match="CODEX_ACCOUNT_BUSY"): account_available(host, next_run, login=True)
  with Tree(store.root) as tree: tree.write_state(path, json_bytes({"program": "codex-login"}))
  with pytest.raises(Conflict, match="CODEX_ACCOUNT_BUSY"): account_available(host, next_run, login=False)
  processes.current.pop(201); store.finish(running["lease_id"], store.owner)
  account_available(host, next_run, login=True)
