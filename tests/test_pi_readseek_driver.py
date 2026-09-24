"""加载第一方驱动并替换所有执行边界，覆盖真实控制回调；不启动 Git/rg/Node。"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.pi_supervisor import Principal
from test_pi_activity import identity
from test_pi_readseek_prepare import setup


@pytest.mark.parametrize("selection_ok", [True, False])
def test_directory_driver_selects_then_exports_then_executes_without_passing_its_control_credential(tmp_path, monkeypatch, selection_ok):
  operations, host, principal, request = setup(tmp_path)
  host.manifest()["options"]["readseek"]["git_tool_ref"] = "build"
  request.update(tool_name="readSeek_rename", input={"path": "code.txt", "line": 1, "to": "renamed", "workspace": True})
  ticket = operations.handle(principal, "ordinary_readseek_prepare", request)
  operations.handle(principal, "ordinary_readseek_stage", {"operation_id": ticket["operation_id"]})
  command = operations.commands.command(host.store.read(ticket["lease_id"]), {"operation_id": ticket["operation_id"]})
  host.store.processes.current[203] = identity(203)
  host.store.start(ticket["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  path = Path(__file__).parents[1] / "scripts/pi-readseek.py"
  spec = importlib.util.spec_from_file_location("readseek_driver_fixture", path)
  driver = importlib.util.module_from_spec(spec); spec.loader.exec_module(driver)
  monkeypatch.setattr(driver.sys, "argv", [str(path), "--input", command.argv[-1]])
  monkeypatch.chdir(tmp_path)
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_CAPABILITY", "synthetic control secret")
  calls = []; limits = []
  def rpc(method, args):
    calls.append(method)
    if method == "authorize": return {"valid": True}
    return operations.handle(Principal("worker", ticket["lease_id"], 1), method, args)
  monkeypatch.setattr(driver, "rpc", rpc)
  monkeypatch.setattr(driver.resource, "setrlimit", lambda *args: limits.append(args))
  def run(argv, **kwargs):
    calls.append("selection")
    assert kwargs["env"]["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert "AGENTCFG_SUPERVISOR_CAPABILITY" not in kwargs["env"]
    assert kwargs["timeout"] > 0
    kwargs["preexec_fn"]()
    kwargs["stdout"].write(b"code.txt\0" if "--cached" in argv else b"")
    return SimpleNamespace(returncode=0 if selection_ok else 5)
  monkeypatch.setattr(driver.subprocess, "run", run)
  def execute(path, argv, env):
    calls.append("compute")
    assert "AGENTCFG_SUPERVISOR_CAPABILITY" not in env
    assert env["PI_OFFLINE"] == "1" and env["HF_HUB_OFFLINE"] == "1"
    assert str(Path(request["cwd"])) not in argv
    assert operations.readseek.records[ticket["operation_id"]]["state"] == "prepared"
    raise RuntimeError("fake compute exec")
  monkeypatch.setattr(driver.os, "execvpe", execute)
  if selection_ok:
    with pytest.raises(RuntimeError, match="fake compute exec"): driver.main()
    assert calls.count("selection") == 2
    assert calls.index("ordinary_readseek_export") < calls.index("compute")
  else:
    assert driver.main() == 5
    assert "ordinary_readseek_export" not in calls and "compute" not in calls
  assert all(limit[1] == (8 * 1024 * 1024, 8 * 1024 * 1024) for limit in limits)
  assert (Path(request["cwd"]) / "code.txt").read_text() == "source"
