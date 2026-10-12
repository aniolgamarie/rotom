"""探针专用的父侧来源准备和UID投影；不签发产品执行许可。"""

from contextlib import contextmanager
import os
import shlex

from .activity import digest
from .pi_shell_identity import identity_projection, parse_uid_map, project_uid, _read
from .pi_shell_execution import prepare_shell_execution
from .pi_shell_mounts import compile_mount_plan
from .pi_shell_preparation import prepare_shell
from .schema import ConfigError


def _require(value):
  if not value: raise ConfigError("pi-shell-probe-binding")


def preparation(directory, plan, case):
  root = directory / "cases" / case / "work"
  command = "/usr/bin/python3.11 -I -B -S " + shlex.quote(str(root / "readonly/payload.py")) + " --payload " + plan["nonces"][case] + "\n"
  if case == "descendants":
    command = "/usr/bin/python3.11 -I -B -S " + shlex.quote(str(root / "readonly/heartbeat.py")) + " " + plan["nonces"][case] + " &\n" + command + "wait\n"
  return prepare_shell(command_ref="tool:shell-probe", binding={"executable": "/usr/bin/bash",
    "project_root": "project", "read_roots": ["project", "readonly"], "write_roots": ["project"], "timeout_seconds": 30},
    command=command, cwd=str(root / "project"), policy_generation=1,
    declared_roots={"project": {"path": str(root / "project"), "purpose": "project"},
      "readonly": {"path": str(root / "readonly"), "purpose": "read"}},
    permission_policy={"schema_version": 1, "default": "deny", "rules": [
      {"id": "probe-shell", "kind": "command", "effect": "allow", "command_ref": "tool:shell-probe", "tool_ids": ["bash"], "operations": ["execute"]},
      {"id": "probe-private", "kind": "file", "effect": "deny", "root_ref": "project", "relative_path": "private",
        "match": "subtree", "tool_ids": ["read", "write"], "operations": ["read", "write", "create"]}]},
    permissions={"readonly_roots": ["readonly"]},
    protected_roots=[str(directory / "inputs"), plan["system"]["dependencies"]["path"], str(root / "home"), str(root / "outside")])


@contextmanager
def prepare_execution(directory, plan, case):
  part = preparation(directory, plan, case)
  public = {key: part[key] for key in ("resolution", "physical")}
  plan_digest = digest(compile_mount_plan(public))
  with prepare_shell_execution(public, part["private_input"]["command"], helper_path=str(directory / "inputs/helper"),
      helper_identity=plan["helper_identity"], plan_digest=plan_digest) as execution:
    yield execution, plan_digest


def bind_worker(execution, *, processes, leader, bootstrap, nonce, helper_identity, plan_digest):
  mapping = identity_projection(execution, processes=processes, leader=leader)
  projection = {row["host_uid"]: row["visible_uid"] for row in mapping["uid_projection"]}
  _require(mapping["worker_user_namespace"] == bootstrap["user_namespace"]
    and bootstrap["uid"] == projection[leader["uid"]]
    and bootstrap["owners"]["root"] in (projection[0], projection[os.geteuid()])
    and bootstrap["owners"]["usr"] == projection[0] and bootstrap["owners"]["bash"] == projection[0])
  return {"purpose": "shell-probe", "nonce": nonce, "helper_identity": helper_identity,
    "plan_digest": plan_digest, "worker_identity": leader, "worker_user_namespace": mapping["worker_user_namespace"],
    "uid_projection": mapping["uid_projection"]}, mapping
