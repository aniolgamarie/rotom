"""OMP生成的环境引用名；契约生成与状态校验共用同一命名边界。"""

import hashlib
import re

from .schema import ConfigError


PATTERN = re.compile(r"(?:AGENTCFG_OMP_PROVIDER_[A-F0-9]{24}_KEY|AGENTCFG_OMP_MCP_[A-F0-9]{24}_(?:ENV|HEADER))")


def is_generated_name(value):
  return isinstance(value, str) and PATTERN.fullmatch(value) is not None


def generated_name(kind, full_id, purpose, *, claimed=None):
  """从完整身份生成环境名；claimed用于拒绝24位摘要截断碰撞。"""
  if not all(isinstance(value, str) and value for value in (kind, full_id, purpose)):
    raise ConfigError("omp-env-name-input")
  normalized_kind = kind.lower()
  normalized_purpose = purpose.lower()
  if normalized_kind == "provider" and normalized_purpose == "key":
    stem, suffix = "PROVIDER", "KEY"
  elif normalized_kind == "mcp" and normalized_purpose.startswith("env:") and normalized_purpose[4:]:
    stem, suffix = "MCP", "ENV"
  elif normalized_kind == "mcp" and normalized_purpose.startswith("header:") and normalized_purpose[7:]:
    stem, suffix = "MCP", "HEADER"
  else:
    raise ConfigError("omp-env-name-kind-purpose")
  identity = "\0".join((normalized_kind, full_id, normalized_purpose))
  digest = hashlib.sha256(identity.encode("utf-8")).hexdigest().upper()[:24]
  result = f"AGENTCFG_OMP_{stem}_{digest}_{suffix}"
  if claimed is not None:
    previous = claimed.setdefault(result, identity)
    if previous != identity:
      raise ConfigError("omp-env-name-digest-collision")
  return result
