"""固定入口绑定的生成、验证和非秘密归类。"""

import json
from pathlib import Path

from termcfg.errors import TermcfgError
from . import entry_locator


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_SOURCES = entry_locator.PROTOCOL_SOURCES


def _call(function, *args, **kwargs):
  try:
    return function(*args, **kwargs)
  except entry_locator.LocatorError as error:
    raise TermcfgError(error.code, error.reason) from error
  except OSError as error:
    raise TermcfgError(4, "unsafe_entry_source") from error


def create_binding(repository):
  root = Path(repository)
  return {"schema_version": 1, "launcher_protocol": 1, "repository": str(root),
    "entry_relative": "rotom", "python_relative": ".venv/bin/python",
    "repository_identity": _call(entry_locator.source_snapshot, root)}


def serialize_binding(binding):
  return (json.dumps(binding, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def parse_binding(data, *, check_source=True):
  return _call(entry_locator.parse_binding, data, check_source=check_source)


def resolve_installed_invocation(installed, args):
  return _call(entry_locator.resolve_installed_invocation, installed, args)


def known_binding(data):
  """只对严格固定协议作非秘密归类；恢复不要求旧来源还存在。"""
  parse_binding(data, check_source=False)
  return data
