"""Shell输出观察接真实准入/租约；假进程身份，真实有界capture游标，不执行命令。"""

from types import SimpleNamespace

import pytest

from agentcfg.pi_output import OutputCapture
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_admitted_shell import fixture, prepare, consume, running_worker
from test_pi_supervisor import request


def setup(tmp_path, *, started=True):
  f = fixture(tmp_path)
  bridge, operations, host, principal = f[:4]
  operations.admission_control = SimpleNamespace(shell_bridge=bridge)
  host.service.ordinary_handler = operations.handle
  prepared = prepare(f); ticket = consume(f, prepared)
  host.children = {}
  if started:
    running_worker(f, ticket)
    lease = host.store.read(ticket["lease_id"])
    capture = OutputCapture(host.root / "activity/outputs" / ticket["lease_id"])
    capture.events = [(index, "stdout", ("line-" + str(index)).encode()) for index in range(1, 7)]
    capture.sequence = 6
    host.children[ticket["lease_id"]] = {"identity": lease["process_identity"], "capture": capture}
  def output(cursor=0, who=principal, **extra):
    return host.service.handle(who, request("ordinary_shell_output", {"operation_id": prepared["operation_id"], "cursor": cursor, **extra}))
  return f, prepared, ticket, output


def test_shell_output_rpc_is_bound_and_reads_bounded_batches_without_mutation(tmp_path):
  f, prepared, ticket, output = setup(tmp_path)
  before = f[2].store.read(ticket["lease_id"])
  first = output()
  assert len(first["events"]) == 4 and first["next_cursor"] == 4 and first["has_more"] is True
  assert first["complete"] is True and first["dropped"] is False
  second = output(first["next_cursor"])
  assert [row["seq"] for row in second["events"]] == [5, 6] and second["has_more"] is False
  assert output(6)["events"] == []
  assert f[2].store.read(ticket["lease_id"]) == before
  assert before["state"] == "running"  # capture完成不是终止或Writer释放证明。


def test_unstarted_output_is_empty_and_does_not_start_or_release(tmp_path):
  f, prepared, ticket, output = setup(tmp_path, started=False)
  before = f[2].store.read(ticket["lease_id"])
  assert output() == {"events": [], "next_cursor": 0, "dropped": False, "has_more": False, "complete": False}
  assert f[2].store.read(ticket["lease_id"]) == before and not f[2].children
  with pytest.raises(ConfigError): output(1)


def test_cancel_and_input_revocation_keep_observation_available(tmp_path):
  f, prepared, ticket, output = setup(tmp_path)
  f[0].revoke(f[3], prepared["operation_id"])
  f[2].store.request_cancel(ticket["lease_id"], f[2].store.owner)
  assert output()["events"]
  assert f[2].store.read(ticket["lease_id"])["state"] == "cancel_requested"


@pytest.mark.parametrize("cursor", [-1, True, 1.5, 7, 2**53])
def test_invalid_cursor_rejected(tmp_path, cursor):
  _, _, _, output = setup(tmp_path)
  with pytest.raises(ConfigError): output(cursor)


@pytest.mark.parametrize("change", ["worker", "foreign-manager", "child-identity", "missing-child", "extra-field", "allocation"])
def test_foreign_or_unknown_output_binding_rejected(tmp_path, change, monkeypatch):
  f, prepared, ticket, output = setup(tmp_path)
  who = f[3]
  if change == "worker": who = Principal("worker", ticket["lease_id"], 1)
  elif change == "foreign-manager": who = Principal("manager", f[3].lease_id, 2)
  elif change == "child-identity": f[2].children[ticket["lease_id"]]["identity"] = {"pid": 999}
  elif change == "missing-child": f[2].children.clear()
  elif change == "allocation": f[0].records[prepared["operation_id"]]["allocation"]["attempt_id"] = "foreign"
  with pytest.raises((Conflict, ConfigError)):
    output(who=who, **({"lease_id": ticket["lease_id"]} if change == "extra-field" else {}))


def test_missing_bridge_does_not_fallback_to_legacy_output(tmp_path):
  f, _, _, output = setup(tmp_path)
  f[1].admission_control.shell_bridge = None
  with pytest.raises(Conflict, match="SHELL_BACKEND_UNAVAILABLE"): output()


def test_capture_ring_gap_is_reported_without_resubmitting_command(tmp_path):
  f, _, ticket, output = setup(tmp_path)
  f[2].children[ticket["lease_id"]]["capture"].events = [(6, "stderr", b"tail")]
  result = output()
  assert result["dropped"] is True and result["next_cursor"] == 6 and len(result["events"]) == 1
