"""冷重建命令只见新目标、显式工具链和系统依赖；安装允许联网，宿主另进原生沙箱。"""
import json
import os
import platform
from pathlib import Path
import shutil
import ssl
import sys

from .pi_scope import PROFILES
from .process import DependencyError, checked
from .schema import ConfigError
from .storage import Tree, ensure_private


def isolated_runner(base, profile, uv, run, *, system=None, programs=None, system_roots=None, trust_paths=None, architecture=None, developer_root=None):
  base = Path(base).resolve(strict=True)
  system = system or sys.platform
  if profile not in PROFILES or system not in ("linux", "darwin"): raise ConfigError("pi-cold-sandbox-platform")
  architecture = architecture or platform.machine()
  names = {"node", "npm", "git", "uv", *({"bun"} if PROFILES[profile] == "bun" else set())}
  if system == "darwin" and architecture == "x86_64": names.update(("zig", "make", "python3", "patch"))
  programs = programs if programs is not None else {name: uv if name == "uv" else shutil.which(name) for name in names}
  if set(programs) != names or not all(programs.values()): raise DependencyError("冷重建缺少完整工具链")
  bound = {name: Path(value).resolve(strict=True) for name, value in programs.items()}
  # agentcfg 的 env python3 入口不能依赖隔离视图外的 /etc/alternatives。
  bound.setdefault("python3", Path(sys._base_executable).resolve(strict=True))
  if any(not path.is_file() or not os.access(path, os.X_OK) for path in bound.values()): raise DependencyError("冷重建工具不可执行")
  roots = set()
  for name in names - {"uv"}:
    path = bound[name].parent.parent
    if path == Path("/"): path = bound[name].parent
    if path == Path.home().resolve() or base.is_relative_to(path): raise ConfigError("pi-cold-toolchain-root-too-broad")
    roots.add(path)
  roots.add(Path(sys.base_prefix).resolve(strict=True))
  systems = system_roots if system_roots is not None else ([Path(path) for path in ("/usr", "/bin", "/lib", "/lib64") if Path(path).exists()]
    if system == "linux" else [Path(path) for path in ("/System", "/usr", "/bin", "/dev")])
  if system == "darwin":
    if developer_root is None:
      developer_root = checked(["/usr/bin/xcode-select", "-p"], cwd=base,
        env={"HOME": str(base), "PATH": os.defpath, "LANG": "C.UTF-8"})
    developer = Path(developer_root).resolve(strict=True)
    if not developer.is_dir() or developer in (Path("/"), Path.home().resolve()) or base.is_relative_to(developer):
      raise ConfigError("pi-cold-sdk-root-too-broad")
    roots.add(developer)
  files = {bound["uv"]}
  if trust_paths is None:
    trust = ssl.get_default_verify_paths()
    # 使用系统默认信任位置，不把调用者 SSL_CERT_FILE/DIR 指向的私人文件带入新机器。
    trust_paths = [Path(path) for path in (trust.openssl_cafile, trust.openssl_capath, "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf") if path and Path(path).exists()]
  for path in trust_paths:
    original = Path(path).absolute()
    path = original.resolve(strict=True)
    selected = roots if path.is_dir() else files
    selected.add(path)
    # OpenSSL按编译时的入口路径查证书；只绑定符号链接终点会丢掉这个入口。
    selected.add(original)
  if Path("/") in roots or Path.home().resolve() in roots: raise ConfigError("pi-cold-toolchain-root-too-broad")
  binary = base / "tool-bin"; ensure_private(binary)
  for name, target in bound.items(): (binary / name).symlink_to(target)
  if system == "linux":
    prefix = ["/usr/bin/bwrap", "--unshare-all", "--share-net", "--new-session", "--cap-drop", "ALL", "--die-with-parent",
      "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp"]
    for path in sorted(set(map(Path, systems)) | roots | files, key=lambda path: (len(path.parts), str(path))): prefix += ["--ro-bind", str(path), str(path)]
    prefix += ["--bind", str(base), str(base)]
  else:
    quote = lambda path: json.dumps(str(path), ensure_ascii=False)
    policy = base / "cold-install.sb"
    lines = ["(version 1)", "(deny default)", "(allow process-exec process-fork)", "(allow signal (target same-sandbox))",
      "(allow process-info* (target same-sandbox))", "(allow sysctl-read)", "(allow network*)",
      '(allow file-write-data (literal "/dev/null"))', "(allow file-read* file-write* (subpath " + quote(base) + "))"]
    lines += ["(allow file-read* (subpath " + quote(path) + "))" for path in sorted(set(map(Path, systems)) | roots, key=str)]
    lines += ["(allow file-read* (literal " + quote(path) + "))" for path in sorted(files, key=str)]
    with Tree(base) as tree: tree.write_new(policy.name, ("\n".join(lines) + "\n").encode())
    prefix = ["/usr/bin/sandbox-exec", "-f", str(policy)]
  def execute(argv, *, cwd, env, **kwargs):
    if not Path(cwd).resolve(strict=True).is_relative_to(base) or not Path(env["HOME"]).resolve(strict=True).is_relative_to(base): raise ConfigError("pi-cold-command-scope")
    command = [str(binary / "uv") if str(argv[0]) == str(uv) else str(argv[0]), *argv[1:]]
    environment = {**env, "PATH": str(binary) + os.pathsep + os.defpath}
    wrapped = [*prefix, "--chdir", str(cwd), "--", *command] if system == "linux" else [*prefix, *command]
    return run(wrapped, cwd=cwd, env=environment, **kwargs)
  return execute
