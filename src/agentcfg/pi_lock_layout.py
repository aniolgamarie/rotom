"""固定Pi锁家族布局；不接受自定义路径，也不从另一家族补齐缺失正文。"""

from dataclasses import dataclass

from .paths import PathError, safe_id
from .schema import ConfigError


@dataclass(frozen=True)
class PiLockLayout:
  family: str
  lock_directory: str
  dependencies_path: str
  recipes_path: str
  schema_version: int


_LEGACY = PiLockLayout("legacy", "locks/pi", "agents/pi/dependencies.json", "agents/pi/build/recipes.json", 1)
_MODERN = PiLockLayout("modern", "locks/pi-modern", "agents/pi/dependencies-modern.json", "agents/pi/build/recipes-modern.json", 2)


def dependency_layout(*, profile=None, family=None):
  if profile is not None:
    if type(profile) is not str: raise ConfigError("pi-lock-layout")
    try: safe_id(profile)
    except PathError: raise ConfigError("pi-lock-layout") from None
  selected = "modern" if profile in ("pi-base", "pi-full") else "legacy"
  if family is not None:
    if type(family) is not str or family not in ("legacy", "modern"):
      raise ConfigError("pi-lock-layout")
    if profile is not None and family != selected:
      raise ConfigError("pi-lock-layout")
    selected = family
  return _MODERN if selected == "modern" else _LEGACY
