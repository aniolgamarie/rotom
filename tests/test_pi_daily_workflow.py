"""日常任务默认编排：真实自有文件准入/IO，模型与编译器结果显式为替身。"""
import hashlib
import difflib
from pathlib import Path

import pytest

from test_pi_operations import base_fixture, base_admit, base_writer
from test_pi_adapter import ROOT


CPP = ROOT / "tests/fixtures/pi/two-profiles/main.cpp"
BEFORE = "version.commit < snapshot"
AFTER = "version.commit <= snapshot"


class ScriptedCompiler:
  """只返回预先指定的检查事实；不解释C++，不启动编译器。"""
  def __init__(self, replies):
    self.replies = iter(replies)
    self.calls = []

  def check(self, root):
    self.calls.append(("c++", "-std=c++17", "main.cpp", "-o", "build/main"))
    return next(self.replies)


def perform_edit(f, content):
  original = (f[3] / "main.cpp").read_bytes()
  ticket = base_admit(f, "inclusive-fix", "edit", {"path": "main.cpp", "edits": [{"oldText": BEFORE, "newText": AFTER}]})
  worker = base_writer(f, ticket, content, hashlib.sha256(original).hexdigest())
  result = f[1].perform(worker, {"operation_id": ticket["operation_id"]})
  f[2].store.processes.current.pop(203)
  assert f[2].store.finish(ticket["lease_id"], f[2].store.owner)["state"] == "reclaimed"
  return result


def daily_cpp(f, compiler, model):
  first = compiler.check(f[3])
  if first["exit_code"] == 0:
    raise ValueError("DAILY_REPRODUCTION_MISSING")
  before = (f[3] / "main.cpp").read_text()
  proposed = model({"failure": first, "source": before, "unfinished": "inclusive-boundary"})
  if before.count(BEFORE) != 1 or proposed != before.replace(BEFORE, AFTER):
    raise ValueError("DAILY_PATCH_SCOPE")
  assert perform_edit(f, proposed)["changed"] is True
  final = compiler.check(f[3])
  if final["exit_code"] != 0 or final["checks"] < 16:
    raise ValueError("DAILY_CHECK_FAILED")
  return {"layer": "default-fake", "reproduction": first, "final": final,
    "diff": list(difflib.unified_diff(before.splitlines(), proposed.splitlines(), fromfile="main.cpp", tofile="main.cpp")),
    "native": "not-run", "live": "not-run"}


def test_fake_model_daily_cpp_reproduces_then_applies_one_real_admitted_edit(tmp_path):
  f = base_fixture(tmp_path, allow=True)
  (f[3] / "main.cpp").write_bytes(CPP.read_bytes())
  readonly = CPP.read_bytes()
  compiler = ScriptedCompiler([{"exit_code": 1, "checks": 16, "failure": "snapshot boundary"}, {"exit_code": 0, "checks": 16}])
  requests = []
  def model(request):
    requests.append(request)
    assert request["failure"]["exit_code"] == 1 and request["unfinished"] == "inclusive-boundary"
    return request["source"].replace(BEFORE, AFTER)
  report = daily_cpp(f, compiler, model)
  assert len(compiler.calls) == 2 and len(requests) == 1
  assert BEFORE not in (f[3] / "main.cpp").read_text() and AFTER in (f[3] / "main.cpp").read_text()
  changed = [line for line in report["diff"] if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
  assert len(changed) == 2 and BEFORE in changed[0] and AFTER in changed[1]
  assert CPP.read_bytes() == readonly
  assert report["layer"] == "default-fake" and report["native"] == report["live"] == "not-run"
  assert f[2].store.processes.signals == []


@pytest.mark.parametrize("fault", ["no-reproduction", "unrelated-patch"])
def test_daily_workflow_does_not_mutate_before_reproduction_and_minimal_patch_checks(tmp_path, fault):
  f = base_fixture(tmp_path, allow=True); before = CPP.read_bytes(); (f[3] / "main.cpp").write_bytes(before)
  compiler = ScriptedCompiler([{"exit_code": 0 if fault == "no-reproduction" else 1, "checks": 16}])
  model = lambda request: request["source"].replace(BEFORE, AFTER) + "\n// unrelated\n"
  with pytest.raises(ValueError, match="DAILY_REPRODUCTION_MISSING|DAILY_PATCH_SCOPE"):
    daily_cpp(f, compiler, model)
  assert (f[3] / "main.cpp").read_bytes() == before
  assert not [row for row in f[2].store.records() if row["kind"] == "external"]
