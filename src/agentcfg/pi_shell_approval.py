"""Shell完整挂载声明的保守审批分类；不认证计划、不授权、不执行或取得FD。

调用者须先完成原硬权限和物理挂载准备。全file allow的等级均保留，
整树能力覆盖仅为降至非human的充分条件，不把声明根或遮罩变成权限。
"""

import json
from pathlib import PurePosixPath
import re
import unicodedata

from .paths import relative_path
from .pi_catalog import validate_policy
from .pi_operation_admission import encode_private_input
from .pi_policy_approval import aggregate_approval
from .pi_shell_argv import compile_argv
from .schema import ConfigError
from .storage import Conflict


IDENTIFIER = re.compile(r"[a-z][a-z0-9_-]{0,63}")
READ = frozenset({"read", "list", "search"})
WRITE = frozenset({"write", "create", "delete", "rename"})


def _invalid():
  raise ConfigError("pi-shell-approval-classification") from None


def _path(value):
  if (type(value) is not str or not value or len(value) > 4096 or "\\" in value
      or any(unicodedata.category(char) == "Cc" or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
    _invalid()
  path = PurePosixPath(value)
  if not path.is_absolute() or str(path) != value or value.startswith("//") or ".." in path.parts:
    _invalid()
  return path


def _validated(permission_policy, root_paths, command_ref, mount_plan):
  # 在读取任何用户属性前只接受有界原生JSON；副本不会运行自定义getter或类型转换。
  captured = json.loads(encode_private_input({"policy": permission_policy, "roots": root_paths,
    "command": command_ref, "plan": mount_plan}))
  policy, roots, command, plan = (captured[key] for key in ("policy", "roots", "command", "plan"))
  if type(roots) is not dict or len(roots) > 4096: _invalid()
  for key, value in roots.items():
    if not IDENTIFIER.fullmatch(key): _invalid()
    _path(value)
  if type(command) is not str or not re.fullmatch(r"tool:[a-z][a-z0-9_-]{0,63}", command): _invalid()
  if type(policy) is not dict or type(policy.get("rules")) is not list or len(policy["rules"]) > 4096:
    _invalid()
  validate_policy(policy)
  files = []
  for rule in policy["rules"]:
    if rule["kind"] != "file": continue
    if rule["root_ref"] not in roots: _invalid()
    relative = rule["relative_path"]
    if len(relative) > 4096: _invalid()
    base = _path(roots[rule["root_ref"]])
    target = base if relative == "." else base / relative_path(relative)
    # 拼接后的路径也须守住同一单路径边界；不resolve或读取文件系统。
    target = _path(str(target))
    if rule["effect"] == "allow": files.append((rule, target))
  if type(plan) is not dict: _invalid()
  for key in ("mounts", "masks", "symlinks"):
    if type(plan.get(key)) is not list or len(plan[key]) > 4096: _invalid()
    for row in plan[key]:
      _path(row["path"])
      if key == "symlinks": _path(row["target"])
  _path(plan["cwd"]["path"])
  # 合成描述符仅用于原编译器的声明校验；从不打开、继承或执行这些整数。
  source_fds = {row["path"]: index for index, row in enumerate(plan["mounts"], 3)}
  offset = 3 + len(plan["mounts"])
  mask_fds = {row["path"]: offset + index for index, row in enumerate(plan["masks"]) if row["kind"] == "file"}
  script_fd = offset + len(plan["masks"])
  compile_argv(plan, source_fds=source_fds, mask_fds=mask_fds, script_fd=script_fd, seccomp_fd=script_fd + 1)
  return policy, command, plan, files


def _classification(policy, command_ref, plan, files):
  commands = [rule for rule in policy["rules"] if rule["kind"] == "command"
    and rule["command_ref"] == command_ref and "bash" in rule["tool_ids"] and "execute" in rule["operations"]]
  if any(rule["effect"] == "deny" for rule in commands) or not commands:
    raise Conflict("PERMISSION_DENIED") from None
  command_grade = aggregate_approval([rule.get("approval", "human") for rule in commands])
  # 所有file allow均参与等级上限；不按tool/operation/选中根/遮罩做字面排除。
  file_grade = aggregate_approval([rule.get("approval", "human") for rule, _ in files]) if files else "human"
  for mount in plan["mounts"]:
    target = PurePosixPath(mount["path"])
    directory = mount["kind"] == "directory"
    required = READ | WRITE if directory and mount["writable"] else READ if directory else {"read"}
    covered = set()
    for rule, path in files:
      if ((rule["match"] == "subtree" and target.is_relative_to(path))
          or not directory and rule["match"] == "exact" and target == path):
        covered.update(rule["operations"])
    if required - covered: return "human"
  return aggregate_approval([command_grade, file_grade])


def classify_shell_approval(*, permission_policy, root_paths, command_ref, mount_plan):
  """仅返回human/reviewer/deterministic-policy；没有许可、Writer或模型副作用。"""
  try:
    validated = _validated(permission_policy, root_paths, command_ref, mount_plan)
  except Exception:
    # 含容量/闭合/路径/schema错误都用固定代码，不暴露原输入或底层异常。
    raise ConfigError("pi-shell-approval-classification") from None
  return _classification(*validated)
