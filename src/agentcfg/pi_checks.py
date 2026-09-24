"""可信前台检查的封闭 argv；不启动沙箱或检查进程。"""

import os
import hashlib
from pathlib import Path

from .activity import digest
from .paths import configured_path
from .schema import ConfigError
from .storage import Conflict


FIELDS = {"executable", "args", "project_root", "timeout_seconds", "foreground"}


def compile_check(binding, *, candidate, executable, read_roots=()):
  if (set(binding) - FIELDS - {"kind", "parser", "minimum_tests", "inputs", "read_roots"} or FIELDS - set(binding) or binding["foreground"] is not True
      or type(binding["timeout_seconds"]) is not int or binding["timeout_seconds"] < 1
      or not isinstance(binding["args"], list) or any(not isinstance(arg, str) or "\0" in arg for arg in binding["args"])):
    raise ConfigError("pi-check-binding")
  candidate = Path(candidate).resolve(strict=True)
  executable = configured_path(str(executable))
  if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
    raise ConfigError("pi-check-executable")
  info = executable.stat()
  if info.st_mode & 0o6022:
    raise ConfigError("pi-check-executable-permissions")
  if not candidate.is_dir():
    raise ConfigError("pi-check-project")
  result = {"schema_version": 1, "argv": [str(executable), *binding["args"]], "cwd": str(candidate),
    "timeout_seconds": binding["timeout_seconds"], "foreground": True, "network": "none",
    "read_roots": [str(Path(root).resolve(strict=True)) for root in read_roots],
    "executable_identity": {"device": info.st_dev, "inode": info.st_ino, "size": info.st_size,
      "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}}
  result["result_contract"] = {key: binding[key] for key in ("kind", "parser", "minimum_tests", "inputs") if key in binding}
  result["binding_digest"] = digest(result)
  return result


def verify_check(check):
  if check.get("network") != "none" or check.get("foreground") is not True:
    raise ConfigError("pi-check-sandbox-contract")
  if check["binding_digest"] != digest({key: value for key, value in check.items() if key != "binding_digest"}):
    raise Conflict("项目检查绑定已经变化")
  if "web_cli_port" in check:
    if (type(check["web_cli_port"]) is not int or not 1024 <= check["web_cli_port"] <= 65535
        or len(check.get("socket_paths", [])) != 1):
      raise ConfigError("pi-web-cli-network-binding")
  executable = Path(check["argv"][0])
  info = executable.lstat()
  expected = check["executable_identity"]
  if (executable.is_symlink() or info.st_dev != expected["device"] or info.st_ino != expected["inode"]
      or info.st_size != expected["size"] or hashlib.sha256(executable.read_bytes()).hexdigest() != expected["sha256"]):
    raise Conflict("项目检查的可执行程序在准入后发生变化")


def linux_verifier_argv(check, *, temporary, system_roots=("/usr", "/bin", "/lib", "/lib64"), denied_paths=(), denied_fds=None):
  verify_check(check)
  candidate = Path(check["cwd"])
  temp = configured_path(str(temporary))
  if temp.is_relative_to(candidate) or candidate.is_relative_to(temp):
    raise ConfigError("pi-check-temporary-overlap")
  # 从空根构造：不把真实 HOME、整个 /etc 或原 checkout 默认为可读。
  argv = ["/usr/bin/bwrap", "--unshare-all", "--cap-drop", "ALL", "--die-with-parent", "--proc", "/proc", "--dev", "/dev", "--bind", str(temp), "/tmp"]
  for root in [*system_roots, *check["read_roots"]]:
    root = Path(root)
    if root.exists():
      if root == Path("/") or root == Path.home():
        raise ConfigError("pi-check-overbroad-read-root")
      argv.extend(("--ro-bind", str(root), str(root)))
  writes = [configured_path(path) for path in check.get("write_roots", [str(candidate)])]
  argv.extend(("--bind" if any(candidate.is_relative_to(path) for path in writes) else "--ro-bind", str(candidate), str(candidate)))
  for path in sorted(writes, key=lambda path: len(path.parts)):
    if path != candidate: argv.extend(("--bind", str(path), str(path)))
  git = candidate / ".git"
  if git.exists() or git.is_symlink():
    if git.is_symlink():
      raise Conflict("候选Git标记不能是符号链接")
    argv.extend(("--ro-bind", str(git), str(git)))
  denied_fds = denied_fds or {}
  visible = [candidate, *writes, *[Path(root) for root in system_roots], *[Path(root) for root in check["read_roots"]]]
  for value in denied_paths:
    path = configured_path(str(value))
    if not any(path == root or path.is_relative_to(root) for root in visible):
      continue  # 空根命名空间已经拒绝未挂载路径。
    if path.is_symlink() or not path.exists():
      # 不为了挂载而在业务目录偷偷创建占位文件。
      raise ConfigError("pi-check-denial-not-representable")
    if path.is_dir():
      argv.extend(("--perms", "000", "--tmpfs", str(path), "--remount-ro", str(path)))
    elif path.is_file():
      fd = denied_fds.get(str(path))
      if type(fd) is not int or fd < 3:
        raise ConfigError("pi-check-denial-fd")
      argv.extend(("--perms", "000", "--ro-bind-data", str(fd), str(path)))
    else:
      raise ConfigError("pi-check-denial-not-representable")
  argv.extend(("--chdir", str(candidate), "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp", "--", *check["argv"]))
  return tuple(argv)


def macos_verifier_policy(check, *, temporary, denied_paths=(), terminal_device=None):
  verify_check(check)
  import json
  from .storage import Tree
  root = Path(__file__).resolve().parents[2]
  with Tree(root, private=False) as tree:
    raw = tree.read("agents/pi/runtime/sandbox-macos.sb")
  if raw is None:
    raise ConfigError("pi-macos-sandbox-template")
  quote = lambda path: json.dumps(str(path), ensure_ascii=False)
  candidate = configured_path(check["cwd"])
  temp = configured_path(str(temporary))
  if temp.is_relative_to(candidate) or candidate.is_relative_to(temp):
    raise ConfigError("pi-check-temporary-overlap")
  template = raw[0].decode()
  if check.get("socket_paths"): template = template.replace("(deny network*)", "")
  lines = [template, "(allow file-read* (subpath " + quote(candidate) + "))",
    "(allow file-read* file-write* (subpath " + quote(temp) + "))",
    "(deny file-write* (literal " + quote(candidate / ".git") + ") (subpath " + quote(candidate / ".git") + "))"]
  lines.extend("(allow file-write* (subpath " + quote(configured_path(path)) + "))" for path in check.get("write_roots", [str(candidate)]))
  lines.extend("(allow file-read* (subpath " + quote(configured_path(path)) + "))" for path in check["read_roots"])
  for path in denied_paths:
    path = configured_path(str(path))
    if path == temp or path.is_relative_to(temp):
      raise ConfigError("pi-check-temporary-denied")
    if temp.is_relative_to(path):
      # 单次执行的私人 scratch 已显式授权；其父 state 目录及其他任务仍拒绝。
      lines.append("(deny file-read* file-write* (literal " + quote(path) + ") (require-all (subpath " + quote(path) + ") (require-not (literal " + quote(temp) + ")) (require-not (subpath " + quote(temp) + "))))")
    else:
      lines.append("(deny file-read* file-write* (literal " + quote(path) + ") (subpath " + quote(path) + "))")
  for path in check.get("socket_paths", []):
    lines.append("(allow network-outbound (remote unix-socket (literal " + quote(configured_path(path)) + ")))" )
  if "web_cli_port" in check:
    endpoint = "127.0.0.1:" + str(check["web_cli_port"])
    lines.append('(allow network-bind network-inbound (local ip "' + endpoint + '"))')
    lines.append('(allow network-outbound (remote ip "' + endpoint + '"))')
  if check.get("terminal_size") is not None:
    import re
    if not isinstance(terminal_device, str) or not re.fullmatch(r"/dev/ttys[0-9]+", terminal_device):
      raise ConfigError("pi-terminal-device")
    if any(Path(terminal_device).is_relative_to(configured_path(str(path))) for path in denied_paths):
      raise Conflict("TERMINAL_DENIED")
    lines.append("(allow file-write* file-ioctl (literal " + quote(terminal_device) + ") (literal \"/dev/tty\"))")
  return "\n".join(lines) + "\n"


def check_environment(check, temporary):
  result = {"PATH": str(Path(check["argv"][0]).parent) + os.pathsep + "/usr/bin:/bin", "HOME": str(temporary), "TMPDIR": str(temporary), "LANG": "C.UTF-8"}
  result.update(check.get("service_environment", {}))
  if check.get("terminal_size") is not None:
    result["TERM"] = os.environ.get("TERM", "xterm-256color")
  if check.get("git_status"):
    result.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_SYSTEM="/dev/null", GIT_CONFIG_GLOBAL="/dev/null",
      GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1", GIT_NO_REPLACE_OBJECTS="1")
  return result
