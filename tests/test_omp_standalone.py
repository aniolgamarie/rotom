"""当前独立插件验收：锁定 Bun、假模型/委派、临时 HOME；不消费宿主补丁。"""

import hashlib
import os
from pathlib import Path
import re
import signal
import stat
import subprocess

import pytest

from agentcfg.omp_permission_build import deny_network

ROOT = Path(__file__).resolve().parents[1]
BUN_SHA256 = "33d56b070be6a9e3da0ab013038b43d1645d0534ca811ecdba4472599117eb4b"
BUN = Path("/tmp/rotom-omp-build-inputs/tools/sha256") / BUN_SHA256
PACKAGE = ROOT / "agents/omp/packages/omp-permission-control"
SDK_RELATIVE = Path(".cache/omp-upgrade-1886-20261009/materials/source/oh-my-pi-f068751e2f1dbdbc195977776d47a26db8697495")
# 显式测试变量在autouse清空环境之前捕获；不继承或枚举其他调用者环境。
SDK_OVERRIDE = os.environ.get("OMP_OFFICIAL_SDK_ROOT")


def _locked_bun(request):
  value = request.config.getoption("omp_standalone_bun")
  path = Path(value) if value is not None else BUN
  if not path.is_absolute():
    path = ROOT / path
  try:
    metadata = path.lstat()
  except FileNotFoundError:
    pytest.skip("locked standalone Bun asset unavailable")
  # 先检查常规可执行文件，再读取ELF magic；绝不对任意非binary文件直接做整包hash。
  if not (stat.S_ISREG(metadata.st_mode) and metadata.st_mode & 0o111 and os.access(path, os.X_OK)):
    pytest.fail("invalid standalone Bun executable", pytrace=False)
  descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
  with os.fdopen(descriptor, "rb") as stream:
    actual = os.fstat(stream.fileno())
    if not (stat.S_ISREG(actual.st_mode) and actual.st_mode & 0o111 and
        (actual.st_dev, actual.st_ino) == (metadata.st_dev, metadata.st_ino)):
      pytest.fail("standalone Bun changed", pytrace=False)
    if stream.read(4) != b"\x7fELF":
      pytest.fail("standalone Bun is not the locked binary format", pytrace=False)
    stream.seek(0)
    if hashlib.file_digest(stream, "sha256").hexdigest() != BUN_SHA256:
      pytest.fail("standalone Bun digest mismatch", pytrace=False)
  return path


def _sdk_root():
  candidates = [Path(SDK_OVERRIDE)] if SDK_OVERRIDE is not None else [ROOT / SDK_RELATIVE]
  if SDK_OVERRIDE is None and ROOT.parent.name == "worktrees" and ROOT.parent.parent.name == ".cache":
    candidates.append(ROOT.parent.parent.parent / SDK_RELATIVE)
  for root in candidates:
    if not root.is_absolute():
      root = ROOT / root
    if (root / "packages/coding-agent/src/extensibility/extensions/wrapper.ts").is_file():
      return root
  pytest.skip("official pinned SDK source unavailable")


def _run_typescript(bun, paths, isolated_environment, *, official_sdk=None):
  from conftest import _REAL_KILL, _REAL_POPEN
  command = [str(bun), "--no-env-file", "test", *[str(path) for path in paths]]
  env = dict(isolated_environment.env)
  env["CI"] = "1"
  if official_sdk is not None:
    env["OMP_OFFICIAL_SDK_ROOT"] = str(official_sdk)
    env["OMP_OFFICIAL_WRAPPER_EVIDENCE"] = str(isolated_environment.root / "omp-official-wrapper-evidence.json")
  with _REAL_POPEN(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=deny_network) as process:
    try:
      stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
      _REAL_KILL(process.pid, signal.SIGKILL)
      process.communicate()
      pytest.fail("current standalone TypeScript suites timed out", pytrace=False)
  output = (stdout + stderr).decode("utf-8", errors="replace")
  log = isolated_environment.root / ("omp-official-wrapper-bun.log" if official_sdk is not None else "omp-standalone-bun.log")
  log.write_text(output, encoding="utf-8")
  assert process.returncode == 0, output[-16000:]
  counts = re.findall(r"(?m)^\s*(\d+) pass\b", output)
  passed = int(counts[-1]) if counts else 0
  if official_sdk is not None and passed == 0 and "official SDK" in output and "skip" in output:
    pytest.skip("official pinned SDK dependency closure unavailable")
  assert passed > 0, output[-16000:]
  assert re.search(r"(?m)^\s*0 fail\b", output)
  print(("OFFICIAL_WRAPPER_PASSED=" if official_sdk is not None else "CURRENT_STANDALONE_PASSED=") + str(passed) + " LOG=" + str(log))
  return passed


def test_current_standalone_typescript_suites(isolated_environment, request):
  """包根测试才是当前路径；历史 tests/ 与 retired fixture 不替代它。"""
  bun = _locked_bun(request)
  paths = sorted(PACKAGE.glob("*.test.ts"))
  required = {"standalone.test.ts", "standalone-lifecycle.test.ts", "standalone-reviewer.test.ts",
    "review-input.test.ts", "native-bash.test.ts"}
  assert required <= {path.name for path in paths}
  _run_typescript(bun, paths, isolated_environment)


def test_official_wrapper_typescript_sdk(isolated_environment, request):
  """官方SDK用单独Bun进程，mock.module不污染独立插件suite。"""
  root = _sdk_root()
  bun = _locked_bun(request)
  passed = _run_typescript(bun, [ROOT / "tests/omp_permission_official_wrapper.test.ts"],
    isolated_environment, official_sdk=root)
  assert passed == 12
