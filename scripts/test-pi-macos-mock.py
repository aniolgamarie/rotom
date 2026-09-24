#!/usr/bin/env python3
"""以替身SDK编译C清点测试；不调用真实libproc/fork/kill/socket，不是macOS native证据。"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


root = Path(__file__).resolve().parents[1]
compiler = shutil.which("cc")
if not compiler:
  raise SystemExit("C compiler required for explicit helper mock check")
with tempfile.TemporaryDirectory(prefix="agentcfg-macos-mock-") as temporary:
  target = Path(temporary)
  env = {"HOME": str(target), "TMPDIR": str(target), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
  include = root / "tests/fixtures/pi/macos/include"
  binary = target / "scope-mock"
  subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-D__APPLE__", "-D_GNU_SOURCE", "-D_POSIX_C_SOURCE=200809L", "-I", str(include),
    str(root / "tests/fixtures/pi/macos/scope-harness.c"), "-ldl", "-o", str(binary)], cwd=target, env=env, check=True)
  subprocess.run([str(binary)], cwd=target, env=env, check=True)
