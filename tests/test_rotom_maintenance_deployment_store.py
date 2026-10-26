"""实际部署核验应早于短协调事务；只读临时配置，不启动宿主。"""

from contextlib import contextmanager
import fcntl
import json

import pytest

from agentcfg import deployment, maintenance_store as store
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance_live_store import acceptance, leases_for, owners_locked
from test_rotom_maintenance_recovery import BATCH, group, ledger
from test_rotom_maintenance import checkpoint


@pytest.mark.parametrize("damage", ["missing", "pending", "generation", "runtime", "binding", "home", "file"])
def test_changed_deployment_prevents_checkpoint_and_intent_without_metadata_fallback(group, damage):
  case = group(); value = acceptance(case)
  ws = case.rows[0].workspace
  path = ws.state_root / "deployment.json"
  if damage == "missing":
    path.unlink()
  elif damage == "pending":
    with Tree(ws.state_root) as tree:
      tree.write_new("pending.json", b"")
  elif damage == "file":
    (ws.instance / "managed.txt").write_bytes(b"synthetic changed after preview\n")
  else:
    saved = json.loads(path.read_bytes())
    current = saved["current"]
    if damage == "generation": current["generation"] = "e" * 64
    elif damage == "runtime": current["launch"]["lock_identity"] = "f" * 64
    elif damage == "binding": current["binding"]["profile"] = "different-profile"
    elif damage == "home": current["launch"]["adapter_binding"]["identity"]["home"] = "/synthetic/other-home"
    path.write_bytes(deployment.json_bytes(saved))
  before = ledger(case.domain)
  with leases_for(case) as leases, pytest.raises(Conflict):
    store.accept_stop_snapshot_live(case.domain, value, leases=leases)
  assert ledger(case.domain) == before and not checkpoint(case).exists()
  owners_locked(case, held=False)


def test_all_selected_deployments_are_checked_before_domain_or_owner_locks(group, monkeypatch):
  case = group(); value = acceptance(case)
  read, transaction = Tree.read, case.domain._transaction
  events = []
  def observe_read(tree, name, *args, **kwargs):
    if name == "deployment.json":
      with Tree(case.domain.root) as independent:
        fcntl.flock(independent.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      owners_locked(case, held=False)
      events.append("deployment")
    return read(tree, name, *args, **kwargs)
  @contextmanager
  def observe_transaction(*, write=False):
    if write:
      assert events == ["deployment", "deployment"]
      events.append("domain")
    with transaction(write=write) as state:
      yield state
  with leases_for(case) as leases, monkeypatch.context() as patch:
    patch.setattr(Tree, "read", observe_read)
    patch.setattr(case.domain, "_transaction", observe_transaction)
    assert store.accept_stop_snapshot_live(case.domain, value, leases=leases) is None
  assert events == ["deployment", "deployment", "domain"]
  assert store.read_stop_snapshot(case.domain, BATCH)["intent"]["phase"] == "active"
