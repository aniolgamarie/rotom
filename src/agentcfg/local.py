"""创建空秘密的框架本地文件；结构初始化不等于 profile/adapter 解析成功。"""

import json
import os
import tomllib
from pathlib import Path

from .paths import (InitializationError, PathError, configured_path,
                    create_initial_local, safe_id)


def available_profiles() -> list[tuple[str, str]]:
  """只读取仓库登记的公开 profile 元数据。"""
  repository = Path(__file__).resolve().parents[2]
  profiles = []
  for path in sorted((repository / "profiles").glob("*.toml")):
    try:
      document = tomllib.loads(path.read_text(encoding="utf-8"))
      profile_id, agent = document["id"], document["agent"]
      safe_id(profile_id)
      if not isinstance(agent, str) or profile_id != path.stem or agent not in ("dsh", "pi", "omp"):
        raise ValueError
      profiles.append((profile_id, agent))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, KeyError, ValueError, PathError):
      raise InitializationError(2) from None
  if not profiles:
    raise InitializationError(2)
  return profiles


def initialize_local(machine_id: str, *, config_home: str | Path, profile_id: str = "dsh-default") -> None:
  """不读取任何既有配置或凭据；失败可能留下本次新建的私人对象。"""
  try:
    machine_id = safe_id(machine_id)
    profile_id = safe_id(profile_id)
    if profile_id == "dsh-default":
      # 兼容原有空密钥初始化：只检查固定内置配方存在，不读取登记内容。
      if not (Path(__file__).resolve().parents[2] / "profiles/dsh-default.toml").is_file():
        raise InitializationError(2)
    elif profile_id not in {item[0] for item in available_profiles()}:
      raise InitializationError(2)
    root = configured_path(os.fspath(config_home))
    # 与从 / 开始的句柄遍历一致，统一 // 前缀但保留所有符号链接段。
    root = Path("/", *root.parts[1:])
    os.fsencode(root)
    # safe_id 已排除控制字符和反斜线；JSON 的引号转义在此子集也是合法 TOML。
    literal = json.dumps(machine_id, ensure_ascii=False)
    profile_literal = json.dumps(profile_id, ensure_ascii=False)
    data = (f"schema_version = 1\n\n[machine]\nid = {literal}\n"
            f"default_profile = {profile_literal}\n\n[secrets]\n"
            "deepseek_key = \"\"\nkimi_key = \"\"\nglm_key = \"\"\n").encode("utf-8")
  except (PathError, TypeError, ValueError, UnicodeError):
    raise InitializationError(2) from None

  repository = Path(__file__).resolve().parents[2]
  # 不 resolve 用户目标；否则符号链接会在 no-follow 校验前被抹去。
  if (root / "agentcfg" / "machines" / f"{machine_id}.toml").is_relative_to(repository):
    raise InitializationError(4)
  create_initial_local(root, machine_id, data)
