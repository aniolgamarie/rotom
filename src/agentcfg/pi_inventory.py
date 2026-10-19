"""显式旧home的只读元数据计数；不读取模型、账号或会话正文，不自动接管。"""

import json
import os
from pathlib import Path
import stat

from .schema import ConfigError
from .storage import Conflict, Tree


PROFILES = ("pi-base", "pi-pro")
THEMES = frozenset("catppuccin-" + flavor for flavor in ("latte", "frappe", "macchiato", "mocha"))
CATEGORIES = ("skills", "agents", "prompts", "themes", "extensions", "packages", "sessions")
LOADING = ("packages", "skills", "extensions", "prompts", "promptTemplates", "themes")


def _pairs(items):
  value = {}
  for key, item in items:
    if key in value:
      raise ValueError()
    value[key] = item
  return value


def _settings(tree):
  raw = tree.read("settings.json")
  if raw is None:
    return {}
  try:
    if len(raw[0]) > 4 * 1024 * 1024:
      raise ValueError()
    value = json.loads(raw[0], object_pairs_hook=_pairs,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict:
      raise ValueError()
    return value
  except (ValueError, TypeError, RecursionError):
    raise ConfigError("pi-inventory-settings-invalid") from None


def _presence(tree, name):
  try:
    with tree.parent(name) as (fd, leaf):
      info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
      if (info.st_uid != os.geteuid() or stat.S_ISLNK(info.st_mode)
          or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
          or stat.S_ISREG(info.st_mode) and info.st_nlink != 1):
        return "unsafe"
      return "present"
  except FileNotFoundError:
    return "missing"
  except (OSError, Conflict):
    return "unsafe"


def _count(tree, category):
  try:
    with tree.parent(category + "/entry") as (fd, _):
      return len(os.listdir(fd))
  except FileNotFoundError:
    return 0
  except (OSError, Conflict):
    raise Conflict("无法安全盘点旧资源目录；原有内容保持不变") from None


def build_inventory(pi_home, starter=None, *, repository=None, profile="pi-base"):
  """repository仅为调用兼容保留；报告不包含来源名称、命令、URL或私有字段值。"""
  if profile not in PROFILES:
    raise ConfigError("pi-inventory-profile-unsupported")
  if starter is not None:
    raise ConfigError("pi-inventory-starter-unsupported")
  items = []
  blockers = [{"code": "manual-binding-and-source-review-required"}]
  with Tree(Path(pi_home).absolute(), private=False) as tree:
    if tree.fd is None:
      raise ConfigError("pi-home-missing")
    settings = _settings(tree)
    for category in CATEGORIES:
      items.append({"id": "resource-" + category, "kind": "resource-count", "count": _count(tree, category),
        "load_evidence": "not_run", "execution_evidence": "not_run"})
    for key in LOADING:
      selected = settings.get(key, [])
      if type(selected) is not list:
        blockers.append({"code": "loading-declaration-invalid", "field": key})
        count = None
      else:
        count = len(selected)
        if selected:
          blockers.append({"code": "loading-declaration-not-adopted", "field": key})
      items.append({"id": "loading-" + key, "kind": "declaration-count", "count": count})
    theme = settings.get("theme")
    if theme is not None:
      allowed = type(theme) is str and theme in THEMES
      items.append({"id": "theme-preference", "kind": "preference", "theme": theme if allowed else None})
      if not allowed:
        blockers.append({"code": "theme-preference-requires-review"})
    for identifier, name in (("authentication", "auth.json"), ("models", "models.json"), ("trust", "trust.json"),
        ("legacy-sync-owner", ".starter-sync-manifest.json"), ("legacy-activity", "activity")):
      state = _presence(tree, name)
      items.append({"id": identifier, "kind": "metadata-presence", "state": state})
      if state != "missing":
        blockers.append({"code": "legacy-manager-marker-preserved" if identifier.startswith("legacy-")
          else "native-state-preserved", "id": identifier})
  return {"schema_version": 2, "profile": profile, "proposed_overrides": {}, "ready_to_deploy": False,
    "items": items, "blockers": blockers}
