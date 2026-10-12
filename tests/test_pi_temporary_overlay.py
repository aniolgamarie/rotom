"""临时overlay仅fakeexec/Host和真实自有临时文件，不挂载或启动宿主。"""
from pathlib import Path
import os
import shutil
from types import SimpleNamespace
import pytest
from test_pi_trusted_checks import fixture
from agentcfg.pi_checks import compile_check
from agentcfg.pi_guarded_files import root_identity


def overlay_fixture(tmp_path,monkeypatch):
  f=fixture(tmp_path);f.binding["execution_mode"]="temporary-overlay"
  f.manifest["plugins"]=["task-keeper"];f.manifest["options"]["task_keeper"]={"enabled":True,"check_ids":["test"]}
  runtime=tmp_path/"runtime";(runtime/"bin").mkdir(parents=True);helper=runtime/"bin/pi-bwrap"
  shutil.copyfile("/usr/bin/true",helper);helper.chmod(0o700)
  f.host.runtime_root=runtime
  monkeypatch.setattr("agentcfg.pi_pid_namespace.host_namespace_binary",lambda host:helper)
  return f


def test_overlay_host_compile_binds_mode_effect_and_original_lower_identity(tmp_path,monkeypatch):
  f=overlay_fixture(tmp_path,monkeypatch);check=f.compile()
  assert check["execution_mode"]=="temporary-overlay"
  assert check["execution_effect"]=="scratch-only"
  assert check["source_identity"]==root_identity(f.project)
  assert check["trusted_binding"]["execution_mode"]=="temporary-overlay"
