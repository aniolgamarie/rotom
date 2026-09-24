"""原生验收的宿主外层沙箱；只给合成模型端口及显式运行包/工具链访问。"""
import json
from pathlib import Path
import shutil
import sys

from .paths import configured_path
from .schema import ConfigError
from .storage import Tree, ensure_private, Conflict


def sandbox_argv(runtime, work_root, input_path, programs, provider_port, *, system=None, system_roots=None, python_prefix=None, local_runtime=False):
  system = system or sys.platform
  root = configured_path(str(work_root)); input_path = configured_path(str(input_path))
  runtime_root = configured_path(str(runtime.root))
  if (not input_path.is_relative_to(root) or runtime_root.is_relative_to(root) or root.is_relative_to(runtime_root)
      or type(provider_port) is not int or not 1024 <= provider_port <= 65535): raise ConfigError("pi-native-sandbox-scope")
  python_prefix = configured_path(str(python_prefix or sys.prefix))
  reads = {runtime_root, python_prefix, configured_path(programs["python_runtime"]), configured_path(programs["python_packages"])}
  # Git helper 与解释器共享发行目录；不授予其他 HOME 或整个 /etc。
  reads.update(configured_path(programs[name]).parent.parent for name in ("engine", "git"))
  # Bun 宿主下的 ReadSeek worker 需要独立 Node 绑定，其发行目录必须同样只读可见。
  if programs.get("node"): reads.add(configured_path(programs["node"]).parent.parent)
  if any(path == Path("/") or path == Path.home() or root.is_relative_to(path) for path in reads): raise ConfigError("pi-native-sandbox-overbroad")
  command = [sys.executable, "-B", "-I", str(runtime_root / "supervisor/scripts/pi-native-scenario.py"), "--input", str(input_path)]
  if system == "linux":
    system_roots = system_roots if system_roots is not None else [Path(path) for path in ("/usr", "/bin", "/lib", "/lib64") if Path(path).exists()]
    argv = ["/usr/bin/bwrap", "--unshare-all", "--cap-drop", "ALL", "--die-with-parent", "--new-session", "--proc", "/proc", "--dev", "/dev", "--dir", "/etc", "--tmpfs", "/tmp"]
    for path in sorted(set(map(Path, system_roots)) | reads, key=str): argv += ["--ro-bind", str(path), str(path)]
    argv += ["--bind", str(root), str(root), "--ro-bind", str(root / "source"), str(root / "source")]
    if local_runtime:
      slot = input_path.parent / "fixture/instances_root/pi" / runtime.profile / "runtimes" / runtime.identity
      if slot.exists() or slot.is_symlink(): raise Conflict("PI_NATIVE_RUNTIME_SLOT_EXISTS")
      ensure_private(slot)
      argv += ["--ro-bind", str(runtime_root), str(slot)]
    argv += ["--chdir", str(input_path.parent), "--", *command]
    return tuple(argv)
  if system != "darwin": raise ConfigError("pi-native-sandbox-platform")
  system_roots = system_roots if system_roots is not None else [Path(path) for path in ("/System", "/usr", "/bin", "/dev")]
  quote = lambda value: json.dumps(str(value), ensure_ascii=False)
  lines = ["(version 1)", "(deny default)", "(allow process-exec process-fork)", "(allow signal (target same-sandbox))",
    "(allow process-info* (target same-sandbox))", "(allow sysctl-read)", '(allow file-write-data (literal "/dev/null"))',
    "(allow file-read* file-write* (subpath " + quote(root) + "))", "(deny file-write* (subpath " + quote(root / "source") + "))"]
  lines.extend("(allow file-read* (subpath " + quote(path) + "))" for path in sorted(set(map(Path, system_roots)) | reads, key=str))
  endpoint = "127.0.0.1:" + str(provider_port)
  lines += ['(allow network-bind network-inbound (local ip "' + endpoint + '"))', '(allow network-outbound (remote ip "' + endpoint + '"))',
    "(allow network-bind network-inbound network-outbound (local unix-socket (subpath " + quote(root) + ")))",
    "(allow network-outbound (remote unix-socket (subpath " + quote(root) + ")))"]
  if local_runtime:
    # macOS sandbox-exec没有bind挂载；inspect_runtime拒绝符号链接，只能整包拷贝为真实目录。
    # 原始运行包仍在策略 reads 中只读，副本变更只影响本夹具实例。
    slot = input_path.parent / "fixture/instances_root/pi" / runtime.profile / "runtimes" / runtime.identity
    if slot.exists() or slot.is_symlink(): raise Conflict("PI_NATIVE_RUNTIME_SLOT_EXISTS")
    ensure_private(slot.parent)
    shutil.copytree(runtime_root, slot, symlinks=True)
  policy = input_path.parent / "native.sb"
  with Tree(policy.parent) as tree: tree.write_new(policy.name, ("\n".join(lines) + "\n").encode())
  return ("/usr/bin/sandbox-exec", "-f", str(policy), *command)
