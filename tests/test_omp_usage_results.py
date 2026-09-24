import json
import os
from pathlib import Path
import subprocess

import pytest

from agentcfg import usage
from test_omp_runtime_foundation import runtime_workspace, clear_omp_identity_environment, isolate_runtime_discovery


CASES = json.loads((Path(__file__).parent / "fixtures/omp/usage-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["name"])
@pytest.mark.parametrize("mode", ["native", "managed"])
def test_native_bytes_and_exit_are_not_reinterpreted(case, mode, tmp_path, monkeypatch, capfdbinary):
  monkeypatch.setattr("shutil.which", lambda name: "/fake/omp")
  if mode == "managed":
    clear_omp_identity_environment(monkeypatch)
    isolate_runtime_discovery(monkeypatch)
    workspace, _ = runtime_workspace(tmp_path)
  seen = []
  # 写入继承的流，包含非UTF8字节，证明封装不捕获/解析/再序列化原生输出。
  stdout = case["stdout"].encode() + b"\xff\x00"
  stderr = case["stderr"].encode()
  def fake(argv, *, cwd, env, pass_fds=()):
    seen.append(argv)
    os.write(1, stdout)
    os.write(2, stderr)
    return subprocess.CompletedProcess(argv, case["exit"])
  monkeypatch.setattr(subprocess, "run", fake)
  result = usage.run_native(case["tail"]) if mode == "native" else usage.run_managed(workspace, case["tail"])
  assert result == case["exit"]
  captured = capfdbinary.readouterr()
  assert captured.out == stdout
  assert captured.err == stderr
  if mode == "native":
    assert seen == [["/fake/omp", "usage", *case["tail"]]]
  else:
    assert seen[0][3:] == ["usage", *case["tail"]]
