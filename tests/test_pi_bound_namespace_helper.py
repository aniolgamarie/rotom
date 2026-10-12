"""现代固定helper交接；仅临时文件/真实FD，绝不执行任何ELF或宿主。"""
import hashlib
from importlib.machinery import SourceFileLoader
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.storage import Conflict, Tree
from test_pi_commands import fixture

ROOT = Path(__file__).resolve().parents[1]

def elf():
  data = bytearray(64)
  data[:6] = b"\x7fELF\x02\x01"
  data[16:18] = (2).to_bytes(2, "little")
  data[18:20] = (62).to_bytes(2, "little")
  return bytes(data)

def test_modern_bound_command_records_selected_verified_helper_and_missing_asset_has_no_input(tmp_path, monkeypatch):
  commands, host, args, principal = fixture(tmp_path)
  host.manifest()["profile_id"] = "pi-base"
  helper = host.runtime_root / "bin/pi-bwrap"
  with Tree(host.runtime_root) as tree:
    tree.write_state("bin/pi-bwrap", elf())
  helper.chmod(0o700)
  seen = []
  monkeypatch.setattr("agentcfg.pi_pid_namespace.host_namespace_binary", lambda selected: seen.append(selected) or helper)
  ticket = commands.prepare(principal, args)
  lease = host.store.read(ticket["lease_id"])
  commands.command(lease, {"operation_id": ticket["operation_id"]})
  document = json.loads((host.root / "activity/ordinary-command-inputs" / (lease["lease_id"] + ".json")).read_bytes())
  assert document["namespace_helper"] == {"path": str(helper), "sha256": hashlib.sha256(elf()).hexdigest()}
  assert seen == [host]
  commands2, host2, args2, principal2 = fixture(tmp_path / "other")
  host2.manifest()["profile_id"] = "pi-base"
  ticket2 = commands2.prepare(principal2, args2)
  monkeypatch.setattr("agentcfg.pi_pid_namespace.host_namespace_binary", lambda _: (_ for _ in ()).throw(Conflict("missing fixed helper")))
  with pytest.raises(Conflict):
    commands2.command(host2.store.read(ticket2["lease_id"]), {"operation_id": ticket2["operation_id"]})
  assert not (host2.root / "activity/ordinary-command-inputs").exists()

def worker():
  loader = SourceFileLoader("own_bound_namespace_worker", str(ROOT / "scripts/pi-project-check"))
  spec = importlib.util.spec_from_loader(loader.name, loader)
  module = importlib.util.module_from_spec(spec)
  loader.exec_module(module)
  return module

@pytest.mark.parametrize("fault", [None, "wrong-hash", "extra-field", "null-helper"])
def test_worker_authorizes_then_holds_verified_fd_without_path_exec_or_fallback(tmp_path, monkeypatch, fault):
  commands, host, args, principal = fixture(tmp_path)
  ticket = commands.prepare(principal, args)
  check = commands.records[ticket["operation_id"]]["check"]
  helper = tmp_path / "helper"
  helper.write_bytes(elf())
  helper.chmod(0o700)
  selection = {"path": str(helper), "sha256": hashlib.sha256(elf()).hexdigest()}
  if fault == "wrong-hash": selection["sha256"] = "f" * 64
  if fault == "extra-field": selection["fallback"] = "/usr/bin/bwrap"
  if fault == "null-helper": selection = None
  value = {"check": check, "temporary": str(tmp_path / "private-scratch"), "lease_id": ticket["lease_id"], "grant_generation": 1, "denied_paths": [], "namespace_helper": selection}
  input_path = tmp_path / "input.json"
  input_path.write_bytes(json_bytes(value))
  module = worker()
  calls = []
  monkeypatch.setattr(module, "request", lambda *a, **k: calls.append("authorize") or {"ok": True, "result": {"valid": True}})
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_ENDPOINT", str(tmp_path / "control.json"))
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_CAPABILITY", "synthetic")
  monkeypatch.setattr(sys, "argv", ["own-worker", "--input", str(input_path)])
  descriptors = []
  def execute(fd, argv, env):
    assert type(fd) is int and os.fstat(fd).st_ino == helper.stat().st_ino
    assert not os.get_inheritable(fd)
    assert argv[0] == str(helper) and env["HOME"] == str(tmp_path / "private-scratch")
    assert ("--setenv", "HOME", "/tmp") in tuple(zip(argv, argv[1:], argv[2:]))
    descriptors.append(fd)
    calls.append("fd-exec")
  monkeypatch.setattr(os, "execve", execute)
  try:
    if fault == "wrong-hash":
      with pytest.raises(Exception): module.main()
    else:
      assert module.main() == (2 if fault else 6)
    assert calls == (["authorize", "fd-exec"] if fault is None else ["authorize"])
  finally:
    for fd in descriptors: os.close(fd)
