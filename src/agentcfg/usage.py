"""OMP usage 透明封装；无选择时不得加载管理工作区。"""

import os
from pathlib import Path
import shutil
import subprocess

from .process import DependencyError
from .schema import ConfigError


def native_tail(arguments):
  """只移除管理入口的一层可选分隔符，不改写原生参数。"""
  arguments = tuple(arguments)
  return arguments[1:] if arguments[:1] == ("--",) else arguments


def run_native(arguments=()):
  executable = shutil.which("omp")
  if executable is None:
    raise DependencyError("PATH中未找到OMP；请先显式准备原生程序")
  try:
    child = subprocess.run([executable, "usage", *native_tail(arguments)], cwd=Path.cwd(), env=dict(os.environ))
  except OSError:
    raise DependencyError("原生OMP usage无法启动；请检查PATH中的程序") from None
  return child.returncode if child.returncode >= 0 else 128 - child.returncode


def run_managed(workspace, arguments=()):
  from .adapter import SecretRef
  from . import runtime
  from .omp_identity import native_identity
  if workspace.resolved.data["profile"]["agent"] != "omp":
    raise ConfigError("usage-requires-omp-profile")
  tail = native_tail(arguments)
  validate_managed_tail(tail)
  identity = native_identity(workspace.profile, workspace.instance)
  return runtime.run(workspace, cwd=identity.home, arguments=("usage", *tail),
    select_environment=lambda binding: not isinstance(binding.value, SecretRef))


def validate_managed_tail(arguments):
  # usage 的 -p/-r 分别是provider/redact，不能套用会话参数含义。
  forbidden = {"--profile", "--alias", "--config", "--cwd", "-C", "--agent-dir", "--session-dir",
    "--extension", "--trusted-extension", "-e", "--hook", "--plugin-dir", "--add-dir",
    "--api-key", "--token", "--secret", "--auth-broker", "--auth-broker-url", "--auth-broker-token",
    "--broker", "--gateway", "--auth-gateway", "--home"}
  index = 0
  arguments = tuple(arguments)
  if any(not isinstance(token, str) or "\0" in token for token in arguments):
    raise ConfigError("omp-usage-argv-invalid")
  while index < len(arguments):
    token = arguments[index]
    if token == "--":
      break
    name, equal, _ = token.partition("=")
    if name in forbidden:
      raise ConfigError("omp-usage-managed-boundary")
    # 仅识别固定版usage自身的value参数，未知语法留给原生报告。
    if name in {"--provider", "-p", "--days", "-d"} and not equal:
      index += 1
    index += 1
