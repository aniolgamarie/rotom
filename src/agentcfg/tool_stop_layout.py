"""Pi/OMP 精确停止的部署布局；不证明共享资源可写或授予维护许可。"""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import os

from . import deployment, run_owners, runtime
from .omp_lifecycle import _same_file
from .paths import safe_id
from .resource_keys import resource_key
from .storage import Conflict, Tree


def inspect_deployment(workspace, record, *, instance_fd, state_fd):
  try:
    for fd in (instance_fd, state_fd):
      if type(fd) is not int or fd < 0:
        raise ValueError()
      os.fstat(fd)
    agent = workspace.agent
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    registry._validate_record(record["run_id"] + ".json", record)
    if (agent not in ("pi", "omp") or record["schema_version"] != 2
        or record["agent"] != agent or record["backend"] != "managed"
        or record["lifecycle_state"] != "active"
        or (record["coordination_domain"] is not None) != (agent == "omp")):
      raise ValueError()
    with ExitStack() as stack:
      target = stack.enter_context(Tree(workspace.instance))
      state = stack.enter_context(Tree(workspace.state_root))
      _same_file(state, "instance.lock", state_fd)
      if state.read("pending.json") is not None:
        raise ValueError()
      raw = state.read("deployment.json")
      saved = deployment.read_state(state)
      current = saved["current"]
      if (current is None or current["binding"] != workspace.binding
          or saved["owner"]["binding"] != workspace.binding
          or current["generation"] != record["deployed_identity"]["deployment"]):
        raise ValueError()
      contract = current["launch"]
      identity = safe_id(contract.get("runtime_identity", contract["lock_identity"]))
      digest = identity if len(identity) == 64 and all(c in "0123456789abcdef" for c in identity) else hashlib.sha256(identity.encode()).hexdigest()
      if digest != record["deployed_identity"]["runtime"]:
        raise ValueError()
      if agent == "pi":
        from .dsh_stop_scope import _marker
        from .pi import OFFICIAL_ENTRY
        marker = _marker(target, workspace)
        physical = workspace.instance
        root = workspace.instance / "runtimes" / identity
        native = workspace.instance / "pi-home"
        prefix = ["node", str(root / OFFICIAL_ENTRY), "--session-dir", str(native / "sessions")]
        if contract["argv"][:4] != prefix:
          raise ValueError()
        literals = {row["name"]: row.get("literal") for row in contract["environment"]}
        if (literals.get("PI_CODING_AGENT_DIR") != str(native)
            or literals.get("PI_CODING_AGENT_SESSION_DIR") != str(native / "sessions")):
          raise ValueError()
      else:
        from .omp_identity import native_identity, ownership, _validate_saved_owner
        native_id = native_identity(workspace.profile, workspace.instance)
        marker = target.read(".agentcfg-omp-owner.json")
        _validate_saved_owner(marker, ownership(workspace))
        physical = workspace.instance / ".agentcfg-omp.lock"
        _same_file(target, ".agentcfg-omp.lock", instance_fd)
        root = workspace.cache / "runtimes" / identity
        native = native_id.home
        if (contract["argv"] != [str(root / "bin/omp"), "--profile", native_id.native_name]
            or contract["adapter_binding"]["identity"]["home"] != str(native)):
          raise ValueError()
      if record["native_home_ref"]["path"] != str(native):
        raise ValueError()
      native_tree = stack.enter_context(Tree(native))
      package_tree = stack.enter_context(Tree(root))
      def keys():
        return {"instance": resource_key("instance", physical, lease_fd=instance_fd).as_dict(),
          "native_home": resource_key("native-home", native, lease_fd=native_tree.fd).as_dict(),
          "runtime": resource_key("runtime", root, lease_fd=package_tree.fd).as_dict()}
      before = keys()
      runtime.check_deployed_resources(current, target)
      marker_name = ".agentcfg-instance.json" if agent == "pi" else ".agentcfg-omp-owner.json"
      if (keys() != before or target.read(marker_name) != marker
          or state.read("deployment.json") != raw or state.read("pending.json") is not None):
        raise ValueError()
      _same_file(state, "instance.lock", state_fd)
      info = os.fstat(native_tree.fd)
      return {**before, "user_home": {"device": info.st_dev, "inode": info.st_ino},
        "deployed_identity": deepcopy(record["deployed_identity"])}
  except Exception:
    raise Conflict("当前工具部署与受管目录不能确认；保留已有保护") from None
