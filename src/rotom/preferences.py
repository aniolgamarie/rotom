"""非秘密入口偏好；严格读取，显式保存并检测外部编辑。"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import errno
import json
import math
import os
from pathlib import Path
import stat
import tomllib

from agentcfg.paths import (
  PathError, _absolute_directory, _check_private, read_private_file, safe_id, xdg_config_home,
)
from agentcfg.storage import Conflict, Tree, advisory_lock


KEYS = (
  "defaults.agent_machine", "defaults.term_machine", "defaults.work_machine",
  "run_profiles.dsh", "run_profiles.pi", "run_profiles.omp",
)


class PreferenceError(Exception):
  """只暴露固定原因，不保留私人文档或底层异常正文。"""

  def __init__(self, exit_code):
    self.exit_code = exit_code
    super().__init__({
      2: "入口偏好或引用无效；请检查允许字段、格式和所选目标",
      4: "入口偏好所有权、权限或文件身份冲突；请重新检查",
      6: "入口偏好文件操作失败；请检查访问权限与存储",
    }[exit_code])


@dataclass(frozen=True)
class Preferences:
  data: dict

  def get(self, key, default=None):
    group, _, name = key.partition(".")
    return self.data.get(group, {}).get(name, default)


def _operation(callback):
  failure = None
  try:
    return callback()
  except PreferenceError:
    raise
  except (Conflict, PathError):
    failure = 4
  except OSError:
    failure = 6
  # 不在 except 内抛出，避免底层错误中的路径进入异常 context。
  raise PreferenceError(failure)


def _path(path):
  invalid = False
  try:
    result = Path(path) if path is not None else xdg_config_home() / "rotom" / "config.toml"
    if not result.is_absolute() or ".." in result.parts or result == Path("/"):
      invalid = True
  except (TypeError, ValueError, PathError):
    invalid = True
  if invalid:
    raise PreferenceError(2)
  return result


def _finite(value):
  if isinstance(value, float):
    return math.isfinite(value)
  if isinstance(value, dict):
    return all(_finite(item) for item in value.values())
  if isinstance(value, list):
    return all(_finite(item) for item in value)
  return True


def _decode(raw):
  invalid = False
  data = None
  try:
    data = tomllib.loads(raw.decode("utf-8"))
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[2] /
      "schemas/rotom/preferences.schema.json").read_text(encoding="utf-8"))
    invalid = (not _finite(data) or type(data.get("schema_version")) is not int
      or not Draft202012Validator(schema).is_valid(data))
    if not invalid:
      for group in ("defaults", "run_profiles"):
        for value in data.get(group, {}).values():
          safe_id(value)
  except (UnicodeError, tomllib.TOMLDecodeError, ValueError, TypeError, PathError):
    invalid = True
  if invalid:
    raise PreferenceError(2)
  return data


def _snapshot(path):
  try:
    with _absolute_directory(path.parent) as parent:
      _check_private(parent)
  except FileNotFoundError:
    return None
  with Tree(path.parent) as tree:
    before = tree.read(path.name)
  if before is not None and before[1] != 0o600:
    raise PreferenceError(4)
  return before


def load_preferences(*, path=None):
  """只检查偏好自身；所选引用在调用时核验，不读取其它机器。"""
  def load():
    target = _path(path)
    before = _snapshot(target)
    return Preferences(_decode(before[0]) if before else {"schema_version": 1})
  return _operation(load)


def validate_reference(key, value):
  """按管理面核验显式引用，不解析秘密或执行目标。"""
  def validate():
    if key not in KEYS or not isinstance(value, str):
      raise PreferenceError(2)
    invalid = False
    try:
      safe_id(value)
    except PathError:
      invalid = True
    if invalid:
      raise PreferenceError(2)
    try:
      group, name = key.split(".")
      if group == "run_profiles":
        from agentcfg.local import available_profiles
        from agentcfg.paths import InitializationError
        try:
          profiles = dict(available_profiles())
        except InitializationError:
          invalid = True
          profiles = {}
        invalid = invalid or profiles.get(value) != name
      else:
        # work 使用 agentcfg 的机器文件，但拥有独立的入口默认值。
        namespace = "termcfg" if name == "term_machine" else "agentcfg"
        target = xdg_config_home() / namespace / "machines" / (value + ".toml")
        data = tomllib.loads(read_private_file(target).decode("utf-8"))
        if name == "term_machine":
          from termcfg.config import MACHINE_ID
          invalid = not MACHINE_ID.fullmatch(value) or data.get("machine_id") != value
        else:
          invalid = (type(data.get("schema_version")) is not int or data.get("schema_version") != 1
            or not isinstance(data.get("machine"), dict) or data["machine"].get("id") != value)
    except (FileNotFoundError, UnicodeError, tomllib.TOMLDecodeError, ValueError, TypeError):
      invalid = True
    if invalid:
      raise PreferenceError(2)
  return _operation(validate)


@contextmanager
def _preference_lock(tree):
  """锁不替换或删除；固定私人目录句柄，拒绝链接和不安全权限。"""
  with tree.parent("preferences.lock") as (parent, name):
    try:
      before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
      before = None
    if before is not None and (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
        or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600):
      raise PreferenceError(4)
    refused = False
    try:
      fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        0o600, dir_fd=parent)
    except OSError as error:
      if error.errno != errno.ELOOP:
        raise
      refused = True
    if refused:
      raise PreferenceError(4)
  try:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
        or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
        or before is not None and (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)):
      raise PreferenceError(4)
    with advisory_lock(fd, busy_message="入口偏好正由其它操作保护"):
      yield
  finally:
    os.close(fd)


def _encode(data):
  lines = ["schema_version = 1"]
  for group in ("defaults", "run_profiles"):
    fields = data.get(group, {})
    if fields:
      lines.extend(("", "[" + group + "]"))
      for key in KEYS:
        section, name = key.split(".")
        if section == group and name in fields:
          lines.append(name + " = " + json.dumps(fields[name], ensure_ascii=False))
  return ("\n".join(lines) + "\n").encode("utf-8")


def update_preference(key, value, *, path=None):
  """None 是显式清除；保存仅改变所选字段，不要求旧失效引用仍存在。"""
  def update():
    if key not in KEYS:
      raise PreferenceError(2)
    target = _path(path)
    before = _snapshot(target)
    data = _decode(before[0]) if before else {"schema_version": 1}
    if value is not None:
      validate_reference(key, value)
    group, name = key.split(".")
    changed = deepcopy(data)
    if value is None:
      changed.get(group, {}).pop(name, None)
    else:
      changed.setdefault(group, {})[name] = value
    if changed == data:
      return Preferences(changed)
    with Tree(target.parent, create=True) as tree:
      with _preference_lock(tree):
        current = tree.read(target.name)
        if current != before:
          raise PreferenceError(4)
        tree.replace(target.name, _encode(changed), expected=before[2] if before else None)
    return Preferences(changed)
  return _operation(update)
