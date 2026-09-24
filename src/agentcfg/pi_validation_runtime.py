"""原生验收只消费已密封的本机运行包；这里不启动解释器或宿主。"""
from dataclasses import dataclass
import json
from pathlib import Path

from .paths import PathError, relative_path
from .pi_dependencies import platform_id
from .pi_runtime_packages import status
from .pi_scope import PROFILES
from .schema import ConfigError
from .storage import Conflict, Tree


def worker_failure_observed(state_root, records, codes):
  """只采纳当前执行租约绑定的 worker 失败正文，不从笼统 BLOCKED 推断原因。"""
  with Tree(Path(state_root)) as tree:
    for lease in records:
      if lease["kind"] != "worker": continue
      raw = tree.read("activity/worker-homes/" + lease["lease_id"] + "/reports/result.json", max_bytes=1024 * 1024)
      if raw is None or raw[1] != 0o600: continue
      value = json.loads(raw[0])
      if (isinstance(value, dict) and value.get("attempt_id") == lease["attempt_id"] and value.get("state") == "execution_failed"
          and value.get("failure_code") in codes and "structured_result" in value and value["structured_result"] is None):
        return True
  return False


@dataclass(frozen=True)
class ValidationRuntime:
  root: Path
  profile: str
  engine: str
  platform: str
  identity: str
  lock_identity: str
  slice_identity: str
  entrypoint: str
  toolchains: dict

  def public_identity(self):
    return {"profile": self.profile, "engine": self.engine, "platform": self.platform, "runtime_identity": self.identity,
      "lock_identity": self.lock_identity, "slice_identity": self.slice_identity, "toolchains": dict(self.toolchains)}


def inspect_runtime(root, *, check=status, current_platform=platform_id):
  root = Path(root).absolute()
  if root.is_symlink() or not root.is_dir() or root.resolve(strict=True) != root: raise ConfigError("pi-validation-runtime-path")
  with Tree(root) as tree:
    profile_raw = tree.read("runtime/profile.json", max_bytes=8 * 1024 * 1024)
    receipt_raw = tree.read(".agentcfg-receipt.json", max_bytes=64 * 1024 * 1024)
  if profile_raw is None or receipt_raw is None: raise Conflict("PI_VALIDATION_RUNTIME_UNSEALED")
  try:
    installed, receipt = json.loads(profile_raw[0]), json.loads(receipt_raw[0])
    package = relative_path(receipt["slice"]["package_path"])
    entry = relative_path(installed["entrypoint"])
    if len(package.parts) != 2 or package.name != "package.json": raise ValueError()
    profile = package.parts[0]
    if (profile not in PROFILES or installed["schema_version"] != 1 or installed["engine"] != PROFILES[profile]
        or installed["platform"] != current_platform() or installed["platform"] != receipt["platform"]
        or installed["runtime_identity"] != receipt["identity"] or installed["lock_identity"] != receipt["lock_identity"]
        or installed["slice_identity"] != receipt["slice_identity"] or installed["toolchains"] != receipt["toolchains"]
        or str(entry) != profile + "/node_modules/@earendil-works/pi-coding-agent/dist/index.js" or installed["sdk_package"] != "@earendil-works/pi-coding-agent"
        or installed["sdk_version"] != "0.84.4" or installed["engine"] not in installed["toolchains"]): raise ValueError()
    if check(root, installed["runtime_identity"]) != "installed": raise Conflict("PI_VALIDATION_RUNTIME_DAMAGED")
    with Tree(root) as tree:
      if tree.read(str(entry)) is None or tree.read("runtime/launch.mjs") is None: raise Conflict("PI_VALIDATION_RUNTIME_ENTRYPOINT")
    return ValidationRuntime(root, profile, installed["engine"], installed["platform"], installed["runtime_identity"],
      installed["lock_identity"], installed["slice_identity"], str(entry), dict(installed["toolchains"]))
  except (ValueError, KeyError, TypeError, PathError): raise ConfigError("pi-validation-runtime-contract") from None
