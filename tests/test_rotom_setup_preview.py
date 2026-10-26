"""私有 setup 计划摘要只消费已有内存，不调用宿主或读取文件。"""

import builtins
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import deployment, runtime
from agentcfg.setup_preview import setup_plan_digest
from agentcfg.storage import Conflict


@pytest.fixture
def inputs():
  workspace = SimpleNamespace(agent="omp", profile="synthetic", binding={"machine": "synthetic"},
    instance=Path("/synthetic/instance"), state_root=Path("/synthetic/state"), cache=Path("/synthetic/cache"))
  plan = deployment.Plan(current={"manifest": {"version": 1}, "launch": {"runtime": "synthetic"}},
    changes=[{"item": {"path": "settings.json", "selector": []},
      "before": {"present": True, "value": "synthetic-private-canary"},
      "after": {"present": True, "value": "new"}}], drift=[], conflicts=[])
  return workspace, SimpleNamespace(identity="lock"), SimpleNamespace(generation="generation"), plan


def test_digest_is_canonical_private_and_memory_only(inputs, monkeypatch, capsys):
  expected = setup_plan_digest(*inputs)
  def forbidden(*args, **kwargs):
    pytest.fail("unexpected filesystem or runtime access")
  with monkeypatch.context() as memory_only:
    memory_only.setattr(builtins, "open", forbidden)
    for name in ("open", "read_bytes", "read_text", "stat", "resolve"):
      memory_only.setattr(Path, name, forbidden)
    memory_only.setattr(runtime, "record", forbidden)
    assert setup_plan_digest(*inputs) == expected
    inputs[3].current = {"launch": {"runtime": "synthetic"}, "manifest": {"version": 1}}
    assert setup_plan_digest(*inputs) == expected
  assert len(expected) == 64 and set(expected) <= set("0123456789abcdef")
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("field", ["agent", "profile", "binding", "instance", "state_root", "cache",
  "lock", "generation", "current", "changes", "drift", "conflicts"])
def test_every_binding_and_plan_component_is_bound(inputs, field):
  expected = setup_plan_digest(*inputs)
  workspace, lock, candidate, plan = inputs
  if field == "lock": lock.identity = "other"
  elif field == "generation": candidate.generation = "other"
  elif field in ("current", "changes", "drift", "conflicts"):
    if field == "current": plan.current["launch"]["runtime"] = "other"
    elif field == "changes": plan.changes[0]["after"]["value"] = "other"
    else: getattr(plan, field).append("other")
  else: setattr(workspace, field, "other")
  assert setup_plan_digest(*inputs) != expected


def test_digest_binds_version_operation_and_full_payload(inputs, monkeypatch):
  from agentcfg import setup_preview
  observed = []
  original = deployment.json_bytes
  def encode(value):
    observed.append(deepcopy(value))
    return original(value)
  monkeypatch.setattr(setup_preview, "json_bytes", encode)
  setup_plan_digest(*inputs)
  value, = observed
  assert value["version"] == 1 and value["operation"] == "setup"
  assert value["plan"] == {name: getattr(inputs[3], name) for name in ("current", "changes", "drift", "conflicts")}
  assert value["workspace"]["instance"] == str(inputs[0].instance)


@pytest.mark.parametrize("invalid", [object(), {1: "synthetic-private-canary"}, ("synthetic-private-canary",),
  float("nan"), float("inf")])
def test_invalid_json_fails_with_fixed_private_safe_error(inputs, invalid, capsys):
  inputs[3].current["invalid"] = invalid
  with pytest.raises(Conflict) as caught:
    setup_plan_digest(*inputs)
  assert str(caught.value) == "setup 预览计划无法生成摘要；请重新运行 setup。"
  assert caught.value.__suppress_context__
  assert capsys.readouterr() == ("", "")


def test_duck_typed_plan_is_rejected(inputs):
  workspace, lock, candidate, plan = inputs
  with pytest.raises(Conflict):
    setup_plan_digest(workspace, lock, candidate, SimpleNamespace(**vars(plan)))


def test_failed_property_does_not_expose_private_value(inputs):
  class PrivateWorkspace:
    @property
    def agent(self):
      raise ValueError("synthetic-private-canary")
  with pytest.raises(Conflict) as caught:
    setup_plan_digest(PrivateWorkspace(), *inputs[1:])
  assert "synthetic-private-canary" not in str(caught.value)
  assert caught.value.__suppress_context__
