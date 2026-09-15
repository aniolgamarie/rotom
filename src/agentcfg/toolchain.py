"""工具链版本解析与兼容检查。"""

import re

from .process import DependencyError


NODE_VERSION = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
NPM_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
# DSH 发布入口使用 import.meta.main；Node 24.0/24.1 会空退出。
NODE_24_MINIMUM = (24, 2, 0)


def parse_toolchain_version(tool: str, version: str) -> tuple[int, int, int]:
  pattern = NODE_VERSION if tool == "Node" else NPM_VERSION if tool == "npm" else None
  match = pattern.fullmatch(version) if pattern and isinstance(version, str) else None
  if match is None:
    raise ValueError("invalid toolchain version")
  return tuple(int(part) for part in match.groups())


def canonical_toolchain_version(tool: str, version: str) -> str | None:
  try:
    major, minor, patch = parse_toolchain_version(tool, version)
  except ValueError:
    return None
  prefix = "v" if tool == "Node" else ""
  return f"{prefix}{major}.{minor}.{patch}"


def compatible_toolchain(tool: str, actual: str, locked: str) -> bool:
  try:
    version = parse_toolchain_version(tool, actual)
    expected = parse_toolchain_version(tool, locked)
    return (version[0] == expected[0]
            and not (tool == "Node" and version[0] == 24 and version < NODE_24_MINIMUM))
  except ValueError:
    return False


def _actual_description(tool: str, actual: str) -> str:
  canonical = canonical_toolchain_version(tool, actual)
  return canonical if canonical is not None else "版本输出无效（已隐藏）"


def ensure_compatible_toolchain(tool: str, locked: str, actual: str) -> None:
  if compatible_toolchain(tool, actual, locked):
    return
  requirement = "同 major 兼容；Node 24 至少 v24.2.0，以支持 import.meta.main" if tool == "Node" else "同 major 兼容"
  raise DependencyError(
    f"{tool} 版本不匹配当前锁：期望 {locked}（{requirement}），"
    f"实际 {_actual_description(tool, actual)}；agentcfg 不安装 Node/npm，"
    "请自行准备兼容版本或参见 docs/getting-started.md"
  )


def ensure_exact_toolchain(tool: str, locked: str, actual: str) -> None:
  canonical = canonical_toolchain_version(tool, actual)
  if canonical is not None and canonical == locked:
    return
  raise DependencyError(
    f"解析工具链与 lock-policy.json 不一致：期望 {tool} {locked}，"
    f"实际 {_actual_description(tool, actual)}；agentcfg 不安装 Node/npm，"
    "生成锁前请准备精确版本或参见 docs/getting-started.md"
  )
