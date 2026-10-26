"""合作 OMP 的原始 child 观察必须同步 owner 双向摘要；不启动真实宿主。"""
from copy import deepcopy
import json

import pytest

from agentcfg import resource_owners as owners, run_owners, spawned_host
from agentcfg.storage import Conflict, Tree
from test_rotom_resource_owners import IDENTITY, MANAGER, RUN, attach, held, owner_path, setup_case


HOST = {"identity": {"pid": 3133714, "birth_id": "synthetic-child"},
  "manager_identity": MANAGER, "source": "linux-spawn-pidfd",
  "relationship": "reported-by-current-run"}


@pytest.fixture
def host(monkeypatch):
  handle = object.__new__(spawned_host.SpawnedHost)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", lambda self: deepcopy(HOST))
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  return handle


def bind(domain, lease, host):
  from agentcfg.omp_run_observation import bind_current_host
  return bind_current_host(domain, RUN, host=host, **lease)


def test_host_observation_updates_link_and_preserves_original_release(tmp_path, monkeypatch, host):
  ws, domain, cache, anchor = setup_case(tmp_path)
  phases = []
  replace = Tree.replace
  def writing(tree, name, data, *args, **kwargs):
    if name == "coordination.json":
      phases.append(json.loads(data)["reservations"][RUN]["phase"])
    return replace(tree, name, data, *args, **kwargs)
  with held(ws, cache, anchor) as lease:
    attach(domain, lease)
    owners.dispatch_owner(domain, RUN, **lease)
    before = json.loads(owner_path(ws).read_bytes())
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", writing)
      bind(domain, lease, host)
    record = json.loads(owner_path(ws).read_bytes())
    entry = domain.snapshot()["reservations"][RUN]
    assert phases == ["owner_pending", "dispatched"]
    assert record["host_identity"] == HOST
    assert record["coordination_domain"] == before["coordination_domain"]
    assert record["session_observation"] is None and record["protocol"]["control"] is None
    assert entry["owner_link"]["record_digest"] == owners._digest(record)
    assert "observation_update" not in entry
    observation = run_owners.ReleaseObservation(RUN, deepcopy(MANAGER), True, True)
    owners.finish_owner(domain, RUN, observation=observation, **lease)
    assert domain.snapshot()["reservations"][RUN]["phase"] == "released"


@pytest.mark.parametrize("fault", ["pending-after", "owner-before", "owner-after", "commit-before", "commit-after"])
def test_partial_observation_never_retries_or_clears_protection(tmp_path, monkeypatch, host, fault):
  ws, domain, cache, anchor = setup_case(tmp_path)
  replace = Tree.replace
  with held(ws, cache, anchor) as lease:
    attach(domain, lease)
    owners.dispatch_owner(domain, RUN, **lease)
    count = {"owner": 0}
    def writing(tree, name, data, *args, **kwargs):
      phase = json.loads(data)["reservations"][RUN]["phase"] if name == "coordination.json" else None
      kind = "pending" if phase == "owner_pending" else "commit" if phase == "dispatched" else "owner"
      if name == RUN + ".json": count["owner"] += 1
      if fault == kind + "-before": raise OSError("synthetic private failure")
      result = replace(tree, name, data, *args, **kwargs)
      if fault == kind + "-after": raise OSError("synthetic private failure")
      return result
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", writing)
      with pytest.raises(Conflict) as caught: bind(domain, lease, host)
    assert "synthetic private failure" not in str(caught.value)
    entry = domain.snapshot()["reservations"][RUN]
    assert entry["phase"] == ("dispatched" if fault == "commit-after" else "owner_pending")
    assert count["owner"] <= 1
    with pytest.raises(Conflict): bind(domain, lease, host)
    assert domain.snapshot()["reservations"][RUN] == entry
    with pytest.raises(Conflict): domain.check_runtime(cache, IDENTITY,
      lease_fd=next(iter(lease["runtime_fds"].values())), idle=True)


@pytest.mark.parametrize("fault", ["serialized-host", "different-manager", "replayed-host"])
def test_invalid_host_observation_has_no_writes(tmp_path, monkeypatch, host, fault):
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as lease:
    attach(domain, lease)
    owners.dispatch_owner(domain, RUN, **lease)
    if fault == "replayed-host": bind(domain, lease, host)
    before = domain.snapshot(), owner_path(ws).read_bytes()
    if fault == "different-manager":
      monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 99, "birth_id": "other"})
    with pytest.raises(Conflict): bind(domain, lease, HOST if fault == "serialized-host" else host)
    assert (domain.snapshot(), owner_path(ws).read_bytes()) == before
