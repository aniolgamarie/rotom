"""启动预留代际与快照 CAS；仅使用临时协调域和合成 owner。"""

from copy import deepcopy
import json

import pytest

from agentcfg import resource_coordination as core, resource_owners as owners
from agentcfg.resource_protocol import decode, encode
from agentcfg.storage import Conflict
from test_rotom_resource_coordination import enrolled, owner, RUN_A, OP_A
from test_rotom_resource_owners import setup_case, held, attach, RUN, owner_path


def test_reservation_binds_committed_generation_and_returns_independent_receipt(tmp_path):
  domain, _, anchor = enrolled(tmp_path)
  before = domain.snapshot()
  receipt = domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=owner(tmp_path),
    resources=[anchor["resource_id"]], expected_revision=before["revision"])
  saved = domain.snapshot()
  assert receipt == saved["reservations"][RUN_A]
  assert receipt["generation"] == saved["revision"] == before["revision"] + 1
  receipt["resources"].clear()
  receipt["owner_ref"]["binding"]["profile"] = "changed-by-caller"
  assert domain.snapshot() == saved


@pytest.mark.parametrize("revision", [-1, True, "1", 1.0, 999])
def test_stale_or_invalid_generation_cannot_write_reservation(tmp_path, revision):
  domain, _, anchor = enrolled(tmp_path)
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict):
    domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=owner(tmp_path),
      resources=[anchor["resource_id"]], expected_revision=revision)
  assert (domain.root / "coordination.json").read_bytes() == before


@pytest.mark.parametrize("generation", [0, -1, True, "1", 1.0, 999])
def test_codec_rejects_invalid_or_future_reservation_generation(tmp_path, generation):
  domain, _, anchor = enrolled(tmp_path)
  domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=owner(tmp_path), resources=[anchor["resource_id"]])
  saved = domain.snapshot()
  saved["reservations"][RUN_A]["generation"] = generation
  with pytest.raises(Conflict):
    encode(saved)
  with pytest.raises(Conflict):
    decode(json.dumps(saved).encode(), kind="domain")


def test_legacy_reservation_is_read_without_inventing_a_generation(tmp_path):
  domain, _, anchor = enrolled(tmp_path)
  domain.reserve(run_id=RUN_A, op_id=OP_A, owner_ref=owner(tmp_path), resources=[anchor["resource_id"]])
  old = domain.snapshot()
  old["reservations"][RUN_A].pop("generation", None)
  raw = encode(old)
  (domain.root / "coordination.json").write_bytes(raw)
  assert "generation" not in core.Domain(domain.root).snapshot()["reservations"][RUN_A]
  assert (domain.root / "coordination.json").read_bytes() == raw


def test_owner_link_binds_reservation_generation_and_refuses_rewritten_generation(tmp_path):
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    before = owner_path(ws).read_bytes()
    state = domain.snapshot()
    entry = state["reservations"][RUN]
    assert "generation" in entry
    entry["generation"] += 1
    (domain.root / "coordination.json").write_bytes(encode(state))
    with pytest.raises(Conflict):
      owners.dispatch_owner(domain, RUN, **args)
    assert owner_path(ws).read_bytes() == before
    assert domain.snapshot()["reservations"][RUN]["phase"] == "owner_attached"


def test_legacy_owner_link_still_dispatches_without_rewriting_old_generation(tmp_path):
  ws, domain, cache, anchor = setup_case(tmp_path)
  saved = domain.snapshot()
  saved["reservations"][RUN].pop("generation", None)
  (domain.root / "coordination.json").write_bytes(encode(saved))
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    old = deepcopy(domain.snapshot()["reservations"][RUN])
    owners.dispatch_owner(domain, RUN, **args)
  assert domain.snapshot()["reservations"][RUN] == {**old, "phase": "dispatched"}
