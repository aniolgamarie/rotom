"""独立合成冷进程测量；不属于默认 pytest，不启动第三方宿主。

运行：.venv/bin/python -B tests/benchmarks/rotom_cli.py --output NEW_PRIVATE_DIR
列表须显式追加 --phase list；默认只测 help 和 completion。
单场景重测使用 --scenario FIXTURE_ID，样本数仍固定为约定中的 30。
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import time


REPOSITORY = Path(__file__).resolve().parents[2]
CONVENTION = REPOSITORY / "tests/fixtures/rotom/performance.json"
PUBLIC_PATTERNS = ("rotom", "src/**/*.py", "schemas/**/*.json", "shared/*.toml",
  "shared/defaults/*.toml", "agents/*/*.toml", "agents/pi/schemas/*.json")
BOOTSTRAP = ("import sys; assert getattr(sys, '_rotom_benchmark_guard', False); "
  "import runpy; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')")
CHILD_GUARD = '''"""仅为基准冷进程安装阻断，不修改业务逻辑或所有权校验。"""
import os
import sys

def audit(event, args):
  if (event.startswith("socket.") or event.startswith("subprocess.")
      or event.startswith("os.exec") or event.startswith("os.spawn")
      or event.startswith("os.posix_spawn")
      or event in ("os.system", "os.fork", "os.forkpty", "os.kill", "os.killpg",
        "os.remove", "os.rmdir", "os.mkdir", "os.rename", "os.link", "os.symlink",
        "os.chmod", "os.chown", "os.truncate", "os.utime")):
    raise RuntimeError("benchmark forbidden effect")
  if event == "open":
    path, mode, flags = args
    if isinstance(path, (str, bytes)):
      value = os.fsdecode(path)
      if value == "/proc" or value.startswith("/proc/"):
        raise RuntimeError("benchmark process inspection forbidden")
    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
      raise RuntimeError("benchmark filesystem write forbidden")

sys.addaudithook(audit)
sys._rotom_benchmark_guard = True
'''


def private_directory(path):
  path.mkdir(mode=0o700, parents=True, exist_ok=True)


def validate_output(path, repository):
  """原始 argv/env 只能进入仓库外的新私人目录；链接别名也不能绕过。"""
  try:
    if not path.is_absolute() or ".." in path.parts or str(path).startswith("//"):
      raise ValueError()
    canonical = path.resolve(strict=False)
    repository = repository.resolve()
    roots = [repository]
    marker = repository / ".git"
    if marker.is_file():
      # 仅本项目的标准 worktree 指针可证明主树；不盘点输出祖先的无关 .git。
      pointer = marker.read_text(encoding="utf-8").strip()
      if not pointer.startswith("gitdir: ") or "\n" in pointer:
        raise ValueError()
      gitdir = Path(pointer.removeprefix("gitdir: "))
      gitdir = (repository / gitdir).resolve()
      if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
        raise ValueError()
      roots.append(gitdir.parent.parent.parent)
    if path.exists() or path.is_symlink() or any(canonical.is_relative_to(root) for root in roots):
      raise ValueError()
  except (OSError, RuntimeError):
    raise ValueError("benchmark output must be new, absolute and outside repositories") from None
  return path


def private_file(path, content):
  private_directory(path.parent)
  with path.open("xb") as stream:
    stream.write(content)
  path.chmod(0o600)


def encode(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def copy_public_checkout(repository, checkout, venv):
  """显式来源清单，不遍历仓库私人目录，也不复制上游宿主或缓存。"""
  private_directory(checkout)
  manifest = {}
  paths = sorted({path for pattern in PUBLIC_PATTERNS for path in repository.glob(pattern)})
  for path in paths:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
      raise ValueError("benchmark source must be a regular public file")
    relative = path.relative_to(repository)
    content = path.read_bytes()
    private_file(checkout / relative, content)
    manifest[str(relative)] = hashlib.sha256(content).hexdigest()
  (checkout / ".venv").symlink_to(venv, target_is_directory=True)
  private_directory(checkout / "profiles")
  return manifest


def build_workload(repository, root, definition, venv):
  """只创建虚构资料；不导入运行器、不登记当前进程、不读取任何原生存储。"""
  private_directory(root)
  checkout = root / "checkout"
  manifest = copy_public_checkout(repository, checkout, venv)
  paths = {"HOME": root / "home", "XDG_CONFIG_HOME": root / "config",
    "XDG_DATA_HOME": root / "data", "XDG_CACHE_HOME": root / "cache",
    "XDG_STATE_HOME": root / "state", "TMPDIR": root / "tmp", "PATH": root / "empty-bin"}
  for path in paths.values():
    private_directory(path)
  guard = root / "guard"
  private_file(guard / "sitecustomize.py", CHILD_GUARD.encode())
  environment = {key: str(path) for key, path in paths.items()}
  environment.update(PYTHONPATH=str(guard), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
  profiles = [f"bench-profile-{number:03}" for number in range(definition["public_profiles"])]
  for profile in profiles:
    private_file(checkout / "profiles" / (profile + ".toml"),
      f'schema_version=1\nid="{profile}"\nagent="dsh"\n'.encode())
  machines = [f"bench-machine-{number:03}" for number in range(definition["machines"])]
  for machine in machines:
    local = paths["XDG_CONFIG_HOME"] / "agentcfg/machines" / (machine + ".toml")
    private_file(local, f'schema_version=1\n[machine]\nid="{machine}"\ndefault_profile="{profiles[0]}"\n'.encode())
  if definition["runs"]:
    profile, machine = profiles[0], machines[0]
    local = paths["XDG_CONFIG_HOME"] / "agentcfg/machines" / (machine + ".toml")
    instance = paths["XDG_DATA_HOME"] / "agentcfg/instances/dsh" / profile
    state_root = paths["XDG_STATE_HOME"] / "agentcfg/dsh" / profile
    binding = {"machine": machine, "local": str(local), "profile": profile}
    anchor = {"schema_version": 1, "state_root": str(state_root), "binding": binding}
    private_file(instance / ".agentcfg-instance.json", (json.dumps(anchor, sort_keys=True,
      ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    digest = hashlib.sha256((json.dumps(binding, sort_keys=True, ensure_ascii=False,
      separators=(",", ":")) + "\n").encode()).hexdigest()
    for number in range(definition["runs"]):
      run_id = f"{number + 1:032x}"
      state = "unknown" if number % 2 else "idle_confirmed"
      manager = {"pid": 10000000 + number, "birth_id": "synthetic-benchmark-birth"}
      observation = {"kind": "manager_scope_ended" if state == "unknown" else "complete_release",
        "coverage": "unknown" if state == "unknown" else "complete",
        "source": "manager-scope-end" if state == "unknown" else "kernel-release",
        "observed_at_ns": 1, "manager_identity": manager, "host_identity": None}
      record = {"schema_version": 2, "binding_digest": digest, "run_id": run_id,
        "manager_identity": manager, "host_identity": None, "agent": "dsh", "backend": "managed",
        "profile": profile, "machine_ref": {"machine": machine, "local": str(local)},
        "start_cwd": {"path": str(root / "synthetic-project"), "source": "launch-spec",
          "confirmation": "confirmed", "observed_at_ns": 1}, "session_cwd": None,
        "native_home_ref": {"kind": "dsh-home", "path": str(instance / "dsh-home"),
          "source": "deployed-contract", "confirmation": "confirmed"},
        "deployed_identity": {"deployment": "b" * 64, "runtime": "c" * 64},
        "lifecycle_state": state, "affected_resources": ["instance", "runtime", "native-home"],
        "process_observation": observation, "session_observation": None, "terminal_ref": None,
        "protocol": {"registration": 2, "control": None}, "coordination_domain": None}
      private_file(state_root / "run-owners" / (run_id + ".json"), encode(record))
  return {"root": root, "checkout": checkout, "environment": environment,
    "machines": machines, "profiles": profiles, "source_manifest": manifest}


def snapshot(root):
  result = {}
  for directory, directories, files in os.walk(root, followlinks=False):
    for name in directories + files:
      path = Path(directory) / name
      info = path.lstat()
      value = os.readlink(path) if stat.S_ISLNK(info.st_mode) else (
        hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(info.st_mode) else None)
      result[str(path.relative_to(root))] = [info.st_mode, info.st_ino, info.st_mtime_ns, value]
  return result


def valid_output(scenario, workload, content):
  if scenario["output"] == "help":
    return b"usage: rotom" in content
  if scenario["output"] in ("machines", "profiles"):
    values = content.split(b"\0")
    if values and values[-1] == b"":
      values.pop()
    expected = workload[scenario["output"]]
    return sorted(values) == sorted(value.encode() for value in expected)
  try:
    report = json.loads(content)
    rows = report["instances"]
    return (len(rows) == 1000 and not report["incomplete"]
      and {row["run_id"] for row in rows} == {f"{number + 1:032x}" for number in range(1000)}
      and all(row["process"]["ownership_state"] in ("unknown", "idle_confirmed") for row in rows))
  except (ValueError, KeyError, TypeError):
    return False


def measure(scenario, workload, python, iterations, output):
  argv = [str(python), "-B", "-c", BOOTSTRAP, str(workload["checkout"] / "rotom"), *scenario["arguments"]]
  before = snapshot(workload["root"])
  samples = []
  for index in range(iterations):
    start = time.perf_counter_ns()
    child = subprocess.run(argv, cwd=workload["root"], env=workload["environment"],
      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    duration = (time.perf_counter_ns() - start) / 1000000000
    correct = child.returncode == scenario["expected_exit"] and valid_output(scenario, workload, child.stdout)
    samples.append({"iteration": index + 1, "seconds": duration, "exit_code": child.returncode,
      "output_valid": correct, "stdout_bytes": len(child.stdout), "stderr_bytes": len(child.stderr),
      "stdout_sha256": hashlib.sha256(child.stdout).hexdigest(),
      "stderr_sha256": hashlib.sha256(child.stderr).hexdigest()})
    if not correct:
      private_file(output / (scenario["id"] + f"-{index + 1:02}.stdout"), child.stdout)
      private_file(output / (scenario["id"] + f"-{index + 1:02}.stderr"), child.stderr)
  unchanged = snapshot(workload["root"]) == before
  durations = sorted(sample["seconds"] for sample in samples)
  p50, p95 = (durations[math.ceil(percentile * iterations) - 1] for percentile in (0.5, 0.95))
  result = {**scenario, "actual_argv": argv, "actual_environment": workload["environment"],
    "iterations": iterations, "samples": samples, "p50_seconds": p50, "p95_seconds": p95,
    "max_seconds": durations[-1], "readonly_unchanged": unchanged,
    "passed": unchanged and all(sample["output_valid"] for sample in samples) and p95 <= scenario["budget_seconds"]}
  private_file(output / (scenario["id"] + ".json"), encode(result))
  return result


def build_parser(convention):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--output", required=True, type=Path, help="new private directory; must not exist")
  selection = parser.add_mutually_exclusive_group()
  selection.add_argument("--phase", choices=("help", "completion", "list"), action="append")
  selection.add_argument("--scenario", choices=tuple(item["id"] for item in convention["scenarios"]), action="append")
  return parser


def main(argv=None):
  convention = json.loads(CONVENTION.read_bytes())
  parser = build_parser(convention)
  args = parser.parse_args(argv)
  phases = args.phase or ["help", "completion"]
  try:
    validate_output(args.output, REPOSITORY)
  except ValueError:
    parser.error("output must be a new absolute directory outside repositories")
  os.umask(0o077)
  args.output.mkdir(mode=0o700)
  scenarios = [item for item in convention["scenarios"] if
    item["id"] in args.scenario] if args.scenario else [
      item for item in convention["scenarios"] if item["phase"] in phases]
  venv = (REPOSITORY / ".venv").resolve(strict=True)
  python = REPOSITORY / ".venv/bin/python"
  workloads = {name: build_workload(REPOSITORY, args.output / name, convention["workloads"][name], venv)
    for name in dict.fromkeys(item["workload"] for item in scenarios)}
  results = [measure(item, workloads[item["workload"]], python, convention["iterations"], args.output)
    for item in scenarios]
  report = {"schema_version": 1, "workload_version": convention["workload_version"],
    "measurement_convention_sha256": hashlib.sha256(CONVENTION.read_bytes()).hexdigest(),
    "prepared_venv": str(venv), "python_version": __import__("sys").version,
    "source_manifests": {name: work["source_manifest"] for name, work in workloads.items()},
    "results": results}
  private_file(args.output / "report.json", encode(report))
  for result in results:
    print(f"{result['id']}: n={result['iterations']} p50={result['p50_seconds']:.6f}s "
      f"p95={result['p95_seconds']:.6f}s max={result['max_seconds']:.6f}s passed={result['passed']}")
  return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
  raise SystemExit(main())
