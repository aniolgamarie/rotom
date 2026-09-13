"""纯层合并；来源位置为私有元数据，不属于生成输入。"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field

from .schema import ConfigError


class _Missing:
  def __repr__(self):
    return "MISSING"

  def __deepcopy__(self, memo):
    return self


MISSING = _Missing()


@dataclass(frozen=True)
class Provenance(Mapping):
  _sources: dict[tuple[str, ...], str] = field(repr=False)

  def __getitem__(self, key):
    return self._sources[key]

  def __iter__(self):
    return iter(self._sources)

  def __len__(self):
    return len(self._sources)


@dataclass(frozen=True)
class MergeResult:
  data: dict = field(repr=False)
  provenance: Provenance = field(repr=False)


def merge_layers(layers) -> MergeResult:
  """接受有序 (公开层名, mapping)；数组整体替换，MISSING 表示省略。"""
  sources = {}

  def discard(path):
    for key in list(sources):
      if key[:len(path)] == path:
        del sources[key]

  def merge(old, new, path, layer):
    if new is MISSING:
      return old
    if isinstance(new, Mapping):
      if not isinstance(old, Mapping):
        discard(path)
        old = {}
      result = dict(old)
      for key, value in new.items():
        if value is not MISSING:
          result[key] = merge(result.get(key, MISSING), value, path + (key,), layer)
      if result:
        sources.pop(path, None)
      elif path:
        sources[path] = layer
      return result
    discard(path)
    sources[path] = layer
    return deepcopy(new)

  data = {}
  for layer, values in layers:
    if layer not in ("registry", "defaults", "profile", "local", "request") or not isinstance(values, Mapping):
      raise ConfigError("merge")
    data = merge(data, values, (), layer)
  return MergeResult(data, Provenance(sources))
