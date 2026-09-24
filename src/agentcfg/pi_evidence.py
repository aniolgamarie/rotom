"""不可变能力证据；只读显式路径，不查宿主、账号或网络。"""
from datetime import datetime
import json
from pathlib import Path

from .activity import digest
from .deployment import json_bytes
from .paths import relative_path
from .pi_catalog import validate
from .schema import ConfigError
from .storage import Tree, Conflict


IDENTITY_FIELDS = ("lock_digest", "runtime_digest", "policy_digest", "resource_digest", "machine_contract_digest")


def timestamp(value):
  try:
    if not isinstance(value, str) or not value.endswith("Z"): raise ValueError()
    return datetime.fromisoformat(value[:-1] + "+00:00")
  except (ValueError, TypeError):
    raise ConfigError("pi-evidence-timestamp") from None


def validate_evidence(value):
  validate("evidence", value)
  if value["status"] == "not-run":
    if value["started_at"] is not None or value["finished_at"] is not None or not value["reason"]:
      raise ConfigError("pi-evidence-not-run")
  else:
    if timestamp(value["finished_at"]) < timestamp(value["started_at"]) or not value["command"]:
      raise ConfigError("pi-evidence-execution")
  return value


def evidence_path(value):
  if not isinstance(value, str) or any(char in value for char in "*?[]\\"):
    raise ConfigError("pi-evidence-path")
  try: return str(relative_path(value))
  except Exception: raise ConfigError("pi-evidence-path") from None


class EvidenceStore:
  def __init__(self, root):
    self.root = Path(root)

  def read(self, path):
    path = evidence_path(path)
    with Tree(self.root, private=False) as tree: raw = tree.read(path, max_bytes=1024 * 1024)
    if raw is None: return None
    if raw[1] & 0o022: raise Conflict("PI_EVIDENCE_WRITABLE_BY_OTHERS")
    try: value = json.loads(raw[0])
    except (ValueError, UnicodeError): raise ConfigError("pi-evidence-json") from None
    return validate_evidence(value)

  def write(self, path, value):
    path = evidence_path(path); validate_evidence(value)
    with Tree(self.root, create=True) as tree:
      if tree.read(path) is not None: raise Conflict("PI_EVIDENCE_EXISTS")
      tree.write_new(path, json_bytes(value))
    return digest(value)


def identity_for(*, lock, runtime, policy, resources, roles, machine_contract):
  # 仅接收非秘密的声明；角色、模型、路线变化进入相关身份。
  return {"lock_digest": lock, "runtime_digest": runtime, "policy_digest": digest(policy),
    "resource_digest": digest({"resources": resources, "roles": roles}), "machine_contract_digest": digest(machine_contract)}


def identity_changes(before, after):
  if set(before) != set(IDENTITY_FIELDS) or set(after) != set(IDENTITY_FIELDS): raise ConfigError("pi-evidence-identity")
  return [key for key in IDENTITY_FIELDS if before[key] != after[key]]
