"""OMP 18.8.6 的执行环境绑定；只检查路径元数据，不读取原生正文。"""

import os
from pathlib import Path
import sys

from .storage import Conflict


XDG_KEYS = (
  "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME",
  "XDG_RUNTIME_DIR",
)
_MESSAGE = "OMP执行环境绑定无效或原生路径发生冲突"


def _conflict():
  raise Conflict(_MESSAGE)


def _absolute(value):
  if not isinstance(value, str) or not value or "\0" in value or not os.path.isabs(value):
    _conflict()
  return os.path.normpath(value)


def _relative(value):
  if (not isinstance(value, str) or not value or "\0" in value
      or os.path.isabs(value) or os.path.normpath(value) != value):
    _conflict()
  return value


def _environment(caller_env):
  # 明确读取六个公开路径变量，不枚举环境或消费调用者 PI_CONFIG_DIR。
  raw_home = caller_env.get("HOME")
  home = _absolute(raw_home)
  raw_paths = [raw_home]
  xdg = {}
  for key in XDG_KEYS:
    value = caller_env.get(key)
    xdg[key] = None if value is None else _absolute(value)
    raw_paths.append(value)
  # 先检查原输入，避免 ../ 词法归一化抹去路径中的链接。
  _no_symlinks(raw_paths)
  return home, xdg


def _xdg(xdg):
  if type(xdg) is not dict or set(xdg) != set(XDG_KEYS):
    _conflict()
  return {key: None if xdg[key] is None else _absolute(xdg[key]) for key in XDG_KEYS}


def _present(path):
  path = Path(path)
  try:
    return path.exists() or path.is_symlink()
  except OSError:
    _conflict()


def _no_symlinks(paths):
  # 不 resolve 身份，也不打开文件；包括缺失末端的现存祖先链接。
  for value in paths:
    if value is None:
      continue
    path = Path(value)
    try:
      if any(part.is_symlink() for part in (path, *path.parents)):
        _conflict()
    except OSError:
      _conflict()


def predict_native_paths(identity, home, config_dir, xdg, *, platform=None, exists=None):
  """复现官方 DirResolver 的路径选择，不执行其迁移/复制副作用。

  POSIX 外置 state root 可通过 ../ 相对 PI_CONFIG_DIR 保持原布局；只支持
  Linux/Darwin 路径语义，不将此相对路径视为扩大目录访问权限的授权。
  """
  home = _absolute(home)
  config_dir = _relative(config_dir)
  xdg = _xdg(xdg)
  platform = sys.platform if platform is None else platform
  if platform not in ("linux", "darwin"):
    _conflict()
  exists = _present if exists is None else exists
  base = os.path.normpath(os.path.join(home, config_dir))
  config = os.path.join(base, "profiles", identity.native_name)
  agent = os.path.join(config, "agent")
  paths = {"schema_version": 1, "base_config_root": base,
    "config_root": config, "agent_dir": agent}
  for category in ("data", "state", "cache"):
    value = xdg["XDG_" + category.upper() + "_HOME"]
    app = os.path.join(value, "omp") if value is not None else None
    profile = os.path.join(app, "profiles", identity.native_name) if app else None
    selected = profile if profile and exists(Path(profile)) else None
    paths["root_" + category] = selected or config
    paths["agent_" + category] = selected or agent
    paths["base_" + category] = app if app and exists(Path(app)) else base
  suffixes = {
    "auth_db": ("agent_data", "agent.db"),
    "history_db": ("agent_data", "history.db"),
    "models_db": ("agent_data", "models.db"),
    "sessions": ("agent_data", "sessions"),
    "blobs": ("agent_data", "blobs"),
    "secret_placeholder_key": ("agent_state", "secret-placeholder.key"),
    "session_owners": ("base_state", "run/session-owners"),
    "global_daemon_root": ("base_state", "run/daemons/global"),
    "daemon_root": ("root_state", "run/daemons"),
    "provider_inflight_root": ("root_state", "run/provider-inflight"),
    "plugins_root": ("root_data", "plugins"),
    "marketplaces_registry": ("root_data", "marketplaces.json"),
  }
  for key, (root, suffix) in suffixes.items():
    paths[key] = os.path.join(paths[root], suffix)
  return paths


def _expected(identity, home, config_dir, *, platform=None):
  base = _absolute(os.fspath(identity.home / ".omp"))
  if os.path.normpath(os.path.join(home, config_dir)) != base:
    _conflict()
  expected = predict_native_paths(identity, home, config_dir,
    {key: None for key in XDG_KEYS}, platform=platform, exists=lambda path: False)
  if expected["agent_dir"] != _absolute(os.fspath(identity.agent_dir)):
    _conflict()
  return expected


def capture_execution_environment(identity, caller_env, *, platform=None):
  home, xdg = _environment(caller_env)
  config_dir = os.path.relpath(_absolute(os.fspath(identity.home / ".omp")), home)
  native_paths = predict_native_paths(identity, home, config_dir, xdg, platform=platform)
  _no_symlinks([os.fspath(identity.home), os.fspath(identity.agent_dir),
    home, *xdg.values(), *[value for value in native_paths.values()
    if isinstance(value, str)]])
  if native_paths != _expected(identity, home, config_dir, platform=platform):
    _conflict()
  return {"schema_version": 1, "home": home, "xdg": xdg,
    "config_dir": config_dir, "native_paths": native_paths}


def validate_execution_environment(identity, binding, caller_env):
  if (type(binding) is not dict or set(binding) != {
      "schema_version", "home", "xdg", "config_dir", "native_paths"}
      or type(binding["schema_version"]) is not int or binding["schema_version"] != 1):
    _conflict()
  home, xdg = _environment(caller_env)
  if _xdg(binding["xdg"]) != binding["xdg"]:
    _conflict()
  if binding["home"] != home or binding["xdg"] != xdg:
    _conflict()
  config_dir = _relative(binding["config_dir"])
  if config_dir != os.path.relpath(_absolute(os.fspath(identity.home / ".omp")), home):
    _conflict()
  expected = _expected(identity, home, config_dir)
  saved = binding["native_paths"]
  if (type(saved) is not dict or set(saved) != set(expected)
      or type(saved["schema_version"]) is not int or saved != expected):
    _conflict()
  current = capture_execution_environment(identity, caller_env)
  if current != binding:
    _conflict()
  return current
