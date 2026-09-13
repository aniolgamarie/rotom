"""子进程只继承允许的终端环境；模型密钥仅由启动契约选定。"""

import os
import subprocess

from .adapter import SecretRef
from .storage import StateError


BASE_ENV = frozenset({"PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "COLORTERM", "LANG",
  "TZ", "TMPDIR", "TMP", "TEMP", "EDITOR", "VISUAL", "SSH_TTY", "SSH_AUTH_SOCK", "TMUX", "TMUX_PANE",
  "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"})


class DependencyError(StateError):
  exit_code = 5


def environment(machine=None, *, home=None):
  names = BASE_ENV | {name for name in os.environ if name.startswith("LC_")}
  env = {name: os.environ[name] for name in names if name in os.environ}
  if machine:
    settings = machine.get("environment", {})
    for name in settings.get("inherit", []):
      if name in os.environ:
        env[name] = os.environ[name]
    env.update(settings.get("values", {}))
    if "editor" in machine:
      env["EDITOR"] = machine["editor"]
      env["VISUAL"] = machine["editor"]
  if home:
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
               XDG_STATE_HOME=str(home / ".local/state"), XDG_CACHE_HOME=str(home / ".cache"))
    env.pop("XDG_RUNTIME_DIR", None)
  return env


def launch_environment(spec, machine, store):
  home = next((binding.value for binding in spec.environment if binding.name == "HOME"), None)
  from pathlib import Path
  env = environment(machine, home=Path(home) if home else None)
  for binding in spec.environment:
    value = store.resolve(binding.value, required=binding.required) if isinstance(binding.value, SecretRef) else binding.value
    if value is not None:
      if "\0" in value:
        from .secrets import CredentialError
        raise CredentialError()
      env[binding.name] = value
  return env


def checked(argv, *, cwd, env):
  """安装/探测命令不回显原始 stdout/stderr，避免 npm/private URL 异常泄漏。"""
  try:
    result = subprocess.run(list(argv), cwd=cwd, env=env, capture_output=True, text=True)
  except OSError:
    raise DependencyError("依赖命令不可执行；请检查锁定的 Node/npm") from None
  if result.returncode:
    raise DependencyError("依赖命令失败，未激活运行包；请检查版本、网络及完整锁")
  return result.stdout.strip()
