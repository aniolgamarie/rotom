"""从源码与完整锁重建两个新目标；不复制现有实例或 node_modules。"""
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import sysconfig

from .activity import digest
from .pi_dependencies import PiBackend, platform_id
from .pi_vendor import source_files, installation_network, INSTALL_PROXY_NAMES
from .pi_cold_sandbox import isolated_runner
from .schema import ConfigError
from .process import DependencyError
from .storage import Conflict, Tree, ensure_private


SOURCE_DIRECTORIES = ("src", "agents", "shared", "profiles", "locks", "schemas", "scripts")
SOURCE_FILES = ("agentcfg", "pyproject.toml", "uv.lock")


def prepare_cold_configuration(checkout, base, home, profile, run):
  from .pi_scope import PROFILES
  from .pi_validation_fixture import prepare_configuration
  if profile not in PROFILES: raise ConfigError("pi-cold-profile")
  programs = {name: shutil.which(name) for name in (PROFILES[profile], "git")}
  if not all(programs.values()): raise DependencyError("冷重建需要显式解释器和 Git 前提")
  environment = checkout / ".venv"
  bindings = {"engine": str(Path(programs[PROFILES[profile]]).resolve(strict=True)), "git": str(Path(programs["git"]).resolve(strict=True)),
    "python": str(Path(sys._base_executable).resolve(strict=True)), "python_runtime": str(Path(sys.base_prefix).resolve(strict=True)),
    "python_packages": sysconfig.get_path("purelib", vars={"base": str(environment), "platbase": str(environment)})}
  def git(argv, **kwargs):
    # 移除 kwargs 中可能冲突的参数
    kwargs.pop('capture_output', None)
    kwargs.pop('timeout', None)
    result = run(argv, capture_output=True, timeout=60, **kwargs)
    if result.returncode: raise DependencyError("冷重建合成 Git 项目初始化失败")
    return result.stdout.decode().strip()
  prepared = prepare_configuration(home / "native-fixture", checkout, profile, "http://127.0.0.1:43217/v1", bindings, run=git)
  return prepared["workspace"].local_path


def collect_source(repository):
  repository = Path(repository)
  entries = []
  for name in SOURCE_DIRECTORIES:
    if (repository / name).exists():
      excluded = []
      for directory, names, _ in os.walk(repository / name, followlinks=False):
        for child in list(names):
          if child in ("node_modules", ".git", "__pycache__", ".venv"):
            excluded.append((Path(directory) / child).relative_to(repository / name).as_posix()); names.remove(child)
      entries += [(name + "/" + path, bool(mode & 0o111), raw) for path, raw, mode in source_files(repository, name, excluded)]
  with Tree(repository, private=False) as source:
    for name in SOURCE_FILES:
      raw = source.read(name)
      if raw is None: raise ConfigError("pi-cold-source-incomplete")
      entries.append((name, bool(raw[1] & 0o111), raw[0]))
  return entries


def snapshot_digest(entries):
  # 用布尔执行位而不是原始权限位，保证从冷拷贝重算与源仓库一致（拷贝会归一为0o600/0o700）。
  import hashlib
  return digest([{"path": name, "exec": executable, "sha256": hashlib.sha256(raw).hexdigest()} for name, executable, raw in entries])


def copy_source(repository, target):
  if target.exists() or target.is_symlink(): raise Conflict("COLD_TARGET_EXISTS")
  entries = collect_source(repository)
  with Tree(target, create=True) as tree:
    for name, executable, raw in entries: tree.replace(name, raw, mode=0o700 if executable else 0o600, expected=None)
  return snapshot_digest(entries)


def verify_installation(repository, local, profile, expected_lock):
  from .workspace import load_workspace
  workspace = load_workspace(local, profile, repository=repository)
  lock = workspace.backend.read_lock(repository)
  if lock.identity != expected_lock: raise Conflict("COLD_LOCK_CHANGED")
  identity = workspace.backend.runtime_identity(workspace, lock)
  if workspace.backend.status(workspace, identity) != "installed": raise Conflict("COLD_INSTALLATION_UNVERIFIED")
  return {"lock_identity": lock.identity, "runtime_identity": identity, "runtime_root": str(workspace.backend.root(workspace, identity)),
    "installation": "verified", "native_execution": "not-run"}


def native_cases(profile):
  return ("host-resources", "migration-conflicts", "taskkeeper-lifecycle" if profile == "pi-managed" else "model-delegate-replacement", "budget-permissions", "termination-recovery",
    *(("readseek-tools",) if profile in ("pi-default", "pi-codex", "pi-cursor") else ()),
    *(("optional-services",) if profile == "pi-default" else ()),
    *(("codex-receipts",) if profile == "pi-codex" else ()))


def verify_native_target(checkout, base, profile, installed, environment, run):
  from .pi_validation_native import scenarios
  records = []
  root = base / "native"; ensure_private(root)
  for case in native_cases(profile):
    output = root / (case + ".json")
    argv = [str(checkout / ".venv/bin/python"), "-B", str(checkout / "scripts/verify-pi.py"), "--tier", "native", "--allow-host", "--case", case,
      "--runtime", installed["runtime_root"], "--output", str(output)]
    try:
      completed = run(argv, cwd=checkout, env=environment, capture_output=True, timeout=7200)
      code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired:
      code, stdout, stderr = None, b"", b"native validation timed out\n"
    except OSError:
      code, stdout, stderr = None, b"", b"native validation unavailable\n"
    with Tree(root) as tree:
      tree.write_new(case + ".stdout", stdout); tree.write_new(case + ".stderr", stderr)
      raw = tree.read(output.name, max_bytes=8 * 1024 * 1024)
    value = None
    try: value = json.loads(raw[0]) if raw and raw[1] == 0o600 else None
    except (ValueError, UnicodeError): pass
    valid = (isinstance(value, dict) and type(value.get("schema_version")) is int and value.get("schema_version") == 1 and value.get("tier") == "native" and value.get("case") == case
      and isinstance(value.get("runtime"), dict) and value["runtime"].get("profile") == profile
      and value["runtime"].get("runtime_identity") == installed["runtime_identity"] and value["runtime"].get("lock_identity") == installed["lock_identity"]
      and value.get("source_digest") == installed["source_digest"] and isinstance(value.get("results"), list)
      and all(isinstance(row, dict) for row in value["results"])
      and [row.get("scenario_id") for row in value["results"]] == list(scenarios(case, profile)))
    state = value.get("status") if valid else "failed"
    if state not in ("passed", "failed", "not-run"): state = "failed"
    if state == "passed" and (code != 0 or any(row.get("status") != "passed" or not isinstance(row.get("execution"), dict)
        or row["execution"].get("termination_confirmed") is not True or row["execution"].get("exit_code") != 0 or row["execution"].get("timed_out") for row in value["results"])): state = "failed"
    records.append({"case": case, "status": state, "exit_code": code, "report": "native/" + output.name})
  status = "failed" if any(row["status"] == "failed" for row in records) else "not-run" if any(row["status"] == "not-run" for row in records) else "passed"
  return {"native_execution": status, "native_cases": records}


def cold_rebuild(repository, profile, destination, *, allow_host=False, run=None, inspect=verify_installation, uv=None, configure=prepare_cold_configuration, native=verify_native_target, isolate=isolated_runner):
  if allow_host is not True: raise ConfigError("pi-cold-authorization-required")
  started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
  repository = Path(repository).absolute(); destination = Path(destination).absolute()
  lock = PiBackend().read_lock(repository)
  if profile not in lock.metadata["profile_slices"] or platform_id() not in lock.metadata["platforms"]:
    raise ConfigError("pi-cold-slice-platform")
  if destination.exists() or destination.is_symlink() or destination.is_relative_to(repository): raise Conflict("COLD_TARGET_EXISTS")
  uv = uv or shutil.which("uv")
  if not uv or not Path(uv).is_absolute(): raise ConfigError("pi-cold-uv-required")
  ensure_private(destination)
  # 长时间验证期间用户可能继续修改工作仓库；两目标必须消费同一份源输入。
  frozen = destination / "candidate-source"
  frozen_digest = None
  try:
    frozen_digest = copy_source(repository, frozen)
    if PiBackend().read_lock(frozen).identity != lock.identity: raise Conflict("COLD_LOCK_CHANGED")
  except (ConfigError, Conflict, DependencyError, OSError):
    frozen_digest = None
  if (frozen_digest is not None and run is None and inspect is verify_installation and configure is prepare_cold_configuration
      and native is verify_native_target and isolate is isolated_runner):
    # 控制代码和schema也从快照重新导入；只冻结数据不能防止调用者工作树的schema在长验证中变化。
    driver_home = destination / "driver-home"; ensure_private(driver_home)
    env = {"HOME": str(driver_home), "PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", **installation_network()}
    entry = ("import json,sys;from pathlib import Path;root=Path(sys.argv[1]);sys.path.insert(0,str(root/'src'));"
      "from agentcfg.pi_cold_rebuild import _run_targets,verify_installation,prepare_cold_configuration,verify_native_target,isolated_runner;"
      "from agentcfg.pi_dependencies import PiBackend;from agentcfg.storage import Tree;from agentcfg.deployment import json_bytes;import subprocess;"
      "destination=Path(sys.argv[3]);value=_run_targets(root,sys.argv[5],PiBackend().read_lock(root),sys.argv[2],destination,subprocess.run,verify_installation,sys.argv[4],prepare_cold_configuration,verify_native_target,isolated_runner);"
      "tree=Tree(destination);tree.__enter__();tree.write_new('frozen-result.json',json_bytes(value));tree.__exit__(None,None,None)")
    completed = subprocess.run([sys.executable, "-B", "-I", "-c", entry, str(frozen), profile, str(destination), str(uv), frozen_digest],
      cwd=frozen, env=env, capture_output=True, timeout=28800)
    with Tree(destination) as tree:
      tree.write_new("driver.stdout", completed.stdout); tree.write_new("driver.stderr", completed.stderr)
      raw = tree.read("frozen-result.json", max_bytes=8 * 1024 * 1024)
    if completed.returncode or raw is None: raise DependencyError("冻结源码的冷重建控制器未完成")
    value = json.loads(raw[0])
    if (not isinstance(value, dict) or set(value) != {"schema_version", "case", "profile", "platform", "lock_identity", "status", "reason", "targets"}
        or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["profile"] != profile or value["lock_identity"] != lock.identity
        or value["case"] != "cold-rebuild" or value["platform"] != platform_id() or not isinstance(value["targets"], list)
        or len(value["targets"]) != 2 or [row.get("target") for row in value["targets"] if isinstance(row, dict)] != ["first", "第二组 空格路径"]
        or any(row.get("installation") not in ("verified", "failed", "not-run") or row.get("native_execution") not in ("passed", "failed", "not-run")
          or row.get("source_digest") not in (None, frozen_digest) for row in value["targets"])): raise Conflict("COLD_DRIVER_IDENTITY")
    expected = "failed" if any(row["installation"] == "failed" or row["native_execution"] == "failed" for row in value["targets"]) else "passed" if all(row["installation"] == "verified" and row["native_execution"] == "passed" for row in value["targets"]) else "not-run"
    if value["status"] != expected: raise Conflict("COLD_DRIVER_STATUS")
    return _decorate(value, started)
  return _decorate(_run_targets(frozen, frozen_digest, lock, profile, destination, run or subprocess.run, inspect, uv, configure, native, isolate), started)


def _decorate(value, started):
  # 登记器要求真实来源：时间与调用命令由实际执行 cold_rebuild 的进程产生，不事后拼装。
  return {**value, "started_at": started,
    "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "command": [sys.executable, *sys.argv]}


def _run_targets(frozen, frozen_digest, lock, profile, destination, run, inspect, uv, configure, native, isolate):
  results = []
  for label in ("first", "第二组 空格路径"):
    base = destination / label; ensure_private(base)
    home = base / "home"; ensure_private(home)
    temporary = home / "tmp"; ensure_private(temporary)
    checkout = base / "checkout"
    outcome = {"target": label, "source_digest": None, "steps": [], "installation": "not-run", "native_execution": "not-run"}
    results.append(outcome)
    try:
      if frozen_digest is None: raise Conflict("COLD_SOURCE_UNAVAILABLE")
      outcome["source_digest"] = copy_source(frozen, checkout)
      if outcome["source_digest"] != frozen_digest: raise Conflict("COLD_SOURCE_CHANGED")
      copied = PiBackend().read_lock(checkout)
      if copied.identity != lock.identity: raise Conflict("COLD_LOCK_CHANGED")
      target_run = isolate(base, profile, uv, run)
      local = configure(checkout, base, home, profile, target_run)
    except (ConfigError, Conflict, DependencyError, OSError, subprocess.TimeoutExpired):
      outcome.update(installation="failed", reason="target-preparation-failed")
      continue
    env = {"HOME": str(home), "TMPDIR": str(temporary), "PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
      "UV_NO_CONFIG": "1", "UV_CACHE_DIR": str(home / "uv-cache"), "UV_PYTHON": str(Path(sys._base_executable).resolve()),
      "NPM_CONFIG_CACHE": str(home / "npm-cache"), "NPM_CONFIG_USERCONFIG": str(home / "npmrc"), "NPM_CONFIG_GLOBALCONFIG": str(home / "global-npmrc"),
      **{name: str(home / name.lower()) for name in ("PI_CODING_AGENT_DIR", "CODEX_HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")}}
    env.update(installation_network())
    commands = [[uv, "sync", "--locked", "--project", str(checkout)],
      *[[str(checkout / "agentcfg"), "--local", str(local), "--profile", profile, command] for command in ("sync", "apply")]]
    for index, argv in enumerate(commands):
      try:
        completed = target_run(argv, cwd=checkout, env=env, capture_output=True, timeout=1800)
        code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
      except (OSError, subprocess.TimeoutExpired):
        code, stdout, stderr = None, b"", b"cold rebuild step unavailable or timed out\n"
      with Tree(base) as tree:
        tree.write_new(str(index) + ".stdout", stdout)
        tree.write_new(str(index) + ".stderr", stderr)
      outcome["steps"].append({"step": ("python-environment", "sync", "apply")[index], "exit_code": code})
      if code != 0:
        outcome["installation"] = "failed"; break
    if outcome["installation"] != "failed":
      try:
        outcome.update(inspect(checkout, local, profile, lock.identity))
      except (ConfigError, Conflict, DependencyError, OSError, ValueError):
        outcome.update(installation="failed", reason="target-installation-unverified")
        continue
      try:
        outcome.update(native(checkout, base, profile, outcome, {key: value for key, value in env.items() if key not in INSTALL_PROXY_NAMES}, target_run))
      except (ConfigError, Conflict, DependencyError, OSError, ValueError, subprocess.TimeoutExpired):
        outcome.update(native_execution="failed", reason="target-native-unverified")
  state = "failed" if any(row["installation"] == "failed" or row["native_execution"] == "failed" for row in results) else "passed" if all(row["installation"] == "verified" and row["native_execution"] == "passed" for row in results) else "not-run"
  return {"schema_version": 1, "case": "cold-rebuild", "profile": profile, "platform": platform_id(), "lock_identity": lock.identity,
    "status": state, "reason": "two-fresh-targets-verified" if state == "passed" else "cold-targets-incomplete", "targets": results}
