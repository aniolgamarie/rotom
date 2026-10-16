#!/usr/bin/env python3
"""Run fixed offline pytest in an explicit, controlled Linux bwrap executor."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
BWRAP = Path("/usr/bin/bwrap")
GIT = "/usr/bin/git"
SYSTEM = ("/usr", "/bin", "/lib", "/lib64")
WORKSPACE = "/workspace/rotom"
SUITES = {"full": [], "filesystem": ["tests/test_paths.py", "tests/test_execution_environment.py"]}
PYTEST = ["-m", "pytest", "-q", "-rs", "--tb=short", "-p", "no:cacheprovider",
          "--basetemp=/tmp/pytest", "-o", "tmp_path_retention_policy=failed",
          "-o", "tmp_path_retention_count=1", "--junitxml=/evidence/pytest.xml"]
ENVIRONMENT = {"PATH": "/usr/bin:/bin", "HOME": "/tmp/home", "XDG_CONFIG_HOME": "/tmp/config",
               "XDG_DATA_HOME": "/tmp/data", "XDG_STATE_HOME": "/tmp/state",
               "XDG_CACHE_HOME": "/tmp/cache", "XDG_RUNTIME_DIR": "/tmp/runtime", "TMPDIR": "/tmp",
               "PYTHONPATH": WORKSPACE + "/src", "PYTHONDONTWRITEBYTECODE": "1",
               "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONUTF8": "1", "LC_ALL": "C.UTF-8"}
BASELINE = r'''
import errno,json,os,pathlib,socket,stat,sys
import pytest,yaml,jsonschema,jinja2
from agentcfg.storage import ensure_private,create_new_private_file
from agentcfg.paths import read_private_file,PathError
checks={"python_supported":sys.version_info >= (3,11),
        "selected_venv":pathlib.Path(sys.prefix).resolve()==pathlib.Path(sys.argv[1]).resolve(),
        "root_owner_trusted":os.stat("/").st_uid in (0,os.geteuid()),
        "synthetic_home":os.environ["HOME"]=="/tmp/home",
        "git_metadata_hidden":not pathlib.Path("/workspace/rotom/.git").exists(),
        "private_cache_hidden":not pathlib.Path("/workspace/rotom/.cache").exists()}
p=pathlib.Path("/tmp/private")
ensure_private(p)
f=p/"synthetic"
create_new_private_file(f,b"sentinel")
checks["private_baseline"]=(read_private_file(f)==b"sentinel" and
    stat.S_IMODE(p.stat().st_mode)==0o700 and stat.S_IMODE(f.stat().st_mode)==0o600)
os.symlink(f,p/"link")
try:
    read_private_file(p/"link");checks["symlink_rejected"]=False
except PathError:
    checks["symlink_rejected"]=True
os.link(f,p/"hard")
try:
    read_private_file(f);checks["hardlink_rejected"]=False
except PathError:
    checks["hardlink_rejected"]=True
for label,path in (("root_readonly","/readonly-probe"),("source_readonly","/workspace/rotom/readonly-probe")):
    try:
        pathlib.Path(path).write_text("probe");checks[label]=False
    except OSError as error:
        checks[label]=error.errno==errno.EROFS
checks["venv_readonly"]=bool(os.statvfs(sys.prefix).f_flag & os.ST_RDONLY)
checks["toolchain_readonly"]=bool(os.statvfs(pathlib.Path(sys._base_executable).resolve()).f_flag & os.ST_RDONLY)
try:
    with socket.create_connection(("192.0.2.1",9),timeout=0.2):
        checks["network_blocked"]=False
except OSError:
    checks["network_blocked"]=True
print(json.dumps(checks))
raise SystemExit(0 if all(checks.values()) else 1)
'''


class Blocked(Exception):
  """仅传递固定原因码，不传播宿主路径或底层异常正文。"""


def write_json(path, value):
  with path.open("x", encoding="utf-8") as stream:
    json.dump(value, stream, indent=2)
    stream.write("\n")


def snapshot(repository, destination):
  # Git 只列出跟踪文件；禁用用户配置和可执行 fsmonitor，不执行 clone/filter/hook。
  git_env = {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
  result = subprocess.run([GIT, "-c", "core.fsmonitor=false", "ls-files", "-z", "--cached"],
                          cwd=repository, env=git_env, capture_output=True, timeout=30, check=False)
  if result.returncode:
    raise Blocked("tracked_source_unavailable")
  names = result.stdout.decode("utf-8").split("\0")
  names = [name for name in names if name]
  if not names or len(names) != len(set(names)):
    raise Blocked("invalid_tracked_source")
  destination.mkdir(mode=0o700)
  manifest = {}
  for name in sorted(names):
    relative = Path(name)
    if relative.is_absolute() or any(part in {"..", ".git", ".cache", ".venv"} for part in relative.parts):
      raise Blocked("unsafe_tracked_source")
    if any(repository.joinpath(*relative.parts[:index]).is_symlink() for index in range(1, len(relative.parts) + 1)):
      raise Blocked("symlinked_tracked_source")
    source = repository / relative
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
      before = os.fstat(stream.fileno())
      if not stat.S_ISREG(before.st_mode):
        raise Blocked("nonregular_tracked_source")
      data = stream.read()
      after = os.fstat(stream.fileno())
    def identity(info):
      return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_mode
    if identity(before) != identity(after) or identity(source.lstat()) != identity(after):
      raise Blocked("tracked_source_changed")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_bytes(data)
    mode = stat.S_IMODE(before.st_mode) & 0o777
    target.chmod(mode)
    manifest[name] = {"sha256": hashlib.sha256(data).hexdigest(), "mode": oct(mode)}
  return manifest


def validate_binding(path):
  # 只读取本用户账户目录元数据；不读取账户目录正文，不信任调用者 HOME 替代账户元数据。
  homes = {os.environ.get("HOME", "")}
  try:
    homes.add(pwd.getpwuid(os.geteuid()).pw_dir)
  except (KeyError, OSError):
    pass
  protected = {Path(name).resolve() for name in homes if name and Path(name).is_absolute()}
  protected.update(Path(name) for name in ("/", "/home", "/root", "/Users", "/run", "/run/user", "/tmp", "/var/tmp"))
  repository = ROOT.resolve()
  if path in protected or (str(path) not in SYSTEM and (path == repository or path in repository.parents)):
    raise Blocked("unsafe_python_binding")


def prepared_python(venv):
  if not venv.is_absolute():
    raise Blocked("venv_must_be_absolute")
  venv = venv.resolve(strict=True)
  validate_binding(venv)
  config = venv / "pyvenv.cfg"
  python = venv / "bin/python"
  if config.is_symlink() or not config.is_file() or not python.is_file() or not os.access(python, os.X_OK):
    raise Blocked("prepared_venv_required")
  metadata = dict(line.split("=", 1) for line in config.read_text().splitlines() if "=" in line)
  metadata = {key.strip(): value.strip() for key, value in metadata.items()}
  version = metadata.get("version_info", metadata.get("version", ""))
  try:
    parts = tuple(int(part) for part in version.split(".")[:2])
    supported = len(parts) == 2 and parts >= (3, 11)
  except ValueError:
    supported = False
  if not supported:
    raise Blocked("python_311_or_newer_required")
  executable = python.resolve(strict=True)
  toolchain = executable.parent.parent
  validate_binding(toolchain)
  version = ".".join(str(part) for part in parts)
  if (executable.parent.name != "bin" or not re.fullmatch(r"python(?:[0-9]+(?:\.[0-9]+)*)?", executable.name)
      or not any((toolchain / lib / ("python" + version) / "os.py").is_file() for lib in ("lib", "lib64"))):
    raise Blocked("unsupported_python_distribution_layout")
  identity = {"pyvenv_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
              "python_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "metadata_version": version}
  return venv, toolchain, identity


def sandbox_argv(source, output, venv, toolchain):
  args = [str(BWRAP), "--unshare-user", "--unshare-pid", "--unshare-net", "--unshare-ipc",
          "--unshare-uts", "--new-session", "--die-with-parent", "--tmpfs", "/"]
  for name in SYSTEM:
    if Path(name).is_dir():
      args += ["--ro-bind", name, name]
  # 先创建临时文件系统，再挂载明确的工具链子目录，避免遮蔽 /tmp 下的已准备环境。
  args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
  if str(toolchain) not in SYSTEM:
    args += ["--ro-bind", str(toolchain), str(toolchain)]
  args += ["--ro-bind", str(venv), str(venv), "--ro-bind", str(source), WORKSPACE,
           "--bind", str(output), "/evidence"]
  for name in ("home", "config", "data", "state", "cache", "runtime"):
    args += ["--dir", "/tmp/" + name]
  return args + ["--remount-ro", "/proc", "--remount-ro", "/", "--cap-drop", "ALL", "--chdir", WORKSPACE]


def run_stage(name, argv, output, *, timeout):
  started = time.monotonic()
  write_json(output / (name + "-argv.json"),
             {"argv": argv, "environment_names": sorted(ENVIRONMENT), "environment_scope": "fixed_synthetic"})
  with (output / (name + ".log")).open("xb") as log:
    try:
      result = subprocess.run(argv, cwd=ROOT, env=dict(ENVIRONMENT), stdin=subprocess.DEVNULL,
                              stdout=log, stderr=subprocess.STDOUT, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
      write_json(output / (name + "-result.json"), {"status": "BLOCKED", "reason": "timeout", "exit_code": None})
      raise Blocked(name + "_timeout") from None
    except KeyboardInterrupt:
      write_json(output / (name + "-result.json"), {"status": "BLOCKED", "reason": "interrupted", "exit_code": None})
      raise
  write_json(output / (name + "-result.json"), {"exit_code": result.returncode})
  return {"name": name, "exit_code": result.returncode,
          "elapsed_seconds": round(time.monotonic() - started, 2), "argv": argv}


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-sandbox", action="store_true", help="Explicitly allow the fixed Linux bwrap test executor")
  parser.add_argument("--evidence", type=Path, required=True, help="New absolute private evidence directory")
  parser.add_argument("--venv", type=Path, required=True, help="Explicit prepared Python 3.11+ environment; no installation")
  parser.add_argument("--suite", choices=tuple(SUITES), default="full", help="Fixed offline suite; full by default")
  args = parser.parse_args(argv)
  if not args.allow_sandbox:
    parser.error("--allow-sandbox is required; default tests do not start bwrap")
  if not args.evidence.is_absolute():
    parser.error("evidence must be a new absolute private directory")
  previous = os.umask(0o077)
  try:
    try:
      args.evidence.mkdir(mode=0o700, exist_ok=False)
    except OSError:
      parser.error("cannot create a new private evidence directory")
    report = {"status": "BLOCKED", "reason": "executor_not_started", "suite": args.suite, "stages": [],
              "scope": "controlled Linux offline pytest; no account or agent-host acceptance"}
    try:
      if not BWRAP.is_file() or not os.access(BWRAP, os.X_OK):
        raise Blocked("bwrap_unavailable")
      report["bwrap_sha256"] = hashlib.sha256(BWRAP.read_bytes()).hexdigest()
      venv, toolchain, report["python_identity"] = prepared_python(args.venv)
      source, output = args.evidence / "source", args.evidence / "output"
      output.mkdir(mode=0o700)
      manifest = snapshot(ROOT, source)
      (source / ".venv").symlink_to(venv, target_is_directory=True)
      report["source_manifest"] = manifest
      report["source_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
      report["lock_identity"] = {name: item["sha256"] for name, item in manifest.items()
                                 if name == "uv.lock" or name.startswith("locks/")}
      prefix = sandbox_argv(source, output, venv, toolchain)
      python = str(venv / "bin/python")
      baseline = run_stage("baseline", prefix + [python, "-c", BASELINE, str(venv)], output, timeout=30)
      report["stages"].append(baseline)
      if baseline["exit_code"]:
        raise Blocked("baseline_failed_use_supported_outer_executor")
      result = run_stage("pytest", prefix + [python, *PYTEST, *SUITES[args.suite]], output, timeout=7200)
      report["stages"].append(result)
      report["status"] = "PASS" if result["exit_code"] == 0 else "FAIL"
      report["reason"] = "offline_pytest_complete" if result["exit_code"] == 0 else "offline_pytest_failed"
    except Blocked as error:
      report["reason"] = str(error)
    except KeyboardInterrupt:
      report["reason"] = "executor_interrupted"
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError):
      report["reason"] = "executor_preparation_failed"
    try:
      write_json(args.evidence / "result.json", report)
    except OSError:
      print(json.dumps({"status": "BLOCKED", "reason": "private_evidence_write_failed"}))
      return 1
    print(json.dumps({"status": report["status"], "reason": report["reason"],
                      "next_step": "use a supported outer userns executor; no automatic escalation or sandbox bypass" if report["status"] == "BLOCKED" else "review private pytest output and skipped cases"}))
    return 0 if report["status"] == "PASS" else 1
  finally:
    os.umask(previous)


if __name__ == "__main__":
  raise SystemExit(main())
