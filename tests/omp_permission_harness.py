"""只执行锁定 Bun 的纯模块测试；不会执行 source CLI 或构建产物。"""

import json
from pathlib import Path
import re
import signal
import shutil
import subprocess

from agentcfg.omp_permission_build import (apply_patch_bytes, deny_network, extract_inputs,
  permission_plugin_digest, stage_permission_core)
from agentcfg.omp_permission_build_inputs import read_build_input_lock, verify_build_inputs
from omp_permission_baseline import prepare_baseline_input


ROOT = Path(__file__).resolve().parents[1]


def prepare_materials(values, work):
  source = Path(values["omp-build-source"]).absolute()
  tool_cache = Path(values["omp-tool-cache"]).absolute()
  dependency_cache = Path(values["omp-dependency-cache"]).absolute()
  lock_path = ROOT / "agents/omp/patches/permission-control/build-inputs.lock.json"
  schema = json.loads((ROOT / "schemas/omp-permission-build-inputs.schema.json").read_text())
  inputs = read_build_input_lock(lock_path, schema)
  verify_build_inputs(inputs, source_archive=source, dependency_lock=ROOT / inputs["dependencyLock"]["path"],
    tool_cache=tool_cache, dependency_cache=dependency_cache)
  extract_inputs(source, work, strip_root="oh-my-pi-" + inputs["upstreamSource"]["commit"])
  for item in inputs["dependencyArtifacts"]:
    extract_inputs(dependency_cache / item["cacheKey"], work)
  patches = ROOT / "agents/omp/patches/permission-control"
  names = (patches / "series").read_text().splitlines()
  if not names or len(set(names)) != len(names) or any(Path(name).name != name or not name.endswith(".patch") for name in names):
    raise AssertionError("invalid permission patch series")
  for name in names:
    apply_patch_bytes(work, (patches / name).read_bytes())
  stage_permission_core(ROOT / "agents/omp/packages/omp-permission-control", work)
  target = work / "packages/coding-agent/test"
  target.mkdir(exist_ok=True)
  for path in (patches / "tests").glob("*.ts"):
    shutil.copyfile(path, target / path.name)
  identity_root = work / "permission-test-fixtures"
  identity_fixture = identity_root / "plugin"
  shutil.copytree(ROOT / "agents/omp/packages/omp-permission-control", identity_fixture)
  (identity_root / "digest.txt").write_text(permission_plugin_digest(ROOT) + "\n")
  prepare_baseline_input(ROOT, work)
  bun = next(item for item in inputs["tools"] if item["name"] == "bun")
  return {"source": work, "bun": tool_cache / bun["cacheKey"], "version": bun["version"], "test_dir": target}


def run_typescript(materials, paths, isolated_environment, *, preload_name="bridge.preload.ts"):
  from conftest import _REAL_POPEN, _REAL_KILL
  env = dict(isolated_environment.env)
  env.update(OMP_HOME=str(isolated_environment.home / "omp"),
    OMP_CACHE_HOME=str(isolated_environment.home / "omp-cache"), CI="1")
  for key in ("OMP_HOME", "OMP_CACHE_HOME"):
    Path(env[key]).mkdir(mode=0o700, exist_ok=True)
  if preload_name not in {"bridge.preload.ts", "identity.preload.ts"}:
    raise AssertionError("permission test preload is not allowlisted")
  preload = materials["test_dir"] / preload_name
  if not preload.is_file():
    raise AssertionError("permission test preload is required before importing host modules")
  # 只能用受校验的 Bun、固定 test 子命令与明确测试路径；不提供任意命令回调。
  command = [str(materials["bun"]), "test", "--preload", str(preload), *[str(path) for path in paths]]
  with _REAL_POPEN(command, cwd=materials["source"], env=env, stdin=subprocess.DEVNULL,
      stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=deny_network) as process:
    try:
      stdout, stderr = process.communicate(timeout=120)
    except subprocess.TimeoutExpired:
      _REAL_KILL(process.pid, signal.SIGKILL)
      process.communicate()
      raise AssertionError("permission TypeScript tests timed out") from None
    output = (stdout + stderr).decode("utf-8", errors="replace")
    counts = re.findall(r"(?m)^\s*(\d+) pass\b", output)
    if process.returncode != 0 or not counts or int(counts[-1]) == 0:
      raise AssertionError("permission TypeScript tests failed or collected zero tests\n" + output[-12000:])
    return output
