"""严格schema缓存只能复用完整根已验证过的独立结构子树。"""
from copy import deepcopy

import pytest
from jsonschema.exceptions import ValidationError

from agentcfg import schema


def closed(properties):
  return {"type": "object", "properties": properties, "additionalProperties": False}


@pytest.fixture(autouse=True)
def clear_content_caches():
  schema._strict_schema_serialized.cache_clear()
  cache = getattr(schema, "_SCHEMA_SUBTREES", None)
  if cache is not None:
    cache.clear()
  yield
  schema._strict_schema_serialized.cache_clear()
  cache = getattr(schema, "_SCHEMA_SUBTREES", None)
  if cache is not None:
    cache.clear()


@pytest.fixture
def meta_calls(monkeypatch):
  calls = []
  original = schema.Draft202012Validator.validate
  def validate(self, instance, *args, **kwargs):
    calls.append(deepcopy(instance))
    return original(self, instance, *args, **kwargs)
  monkeypatch.setattr(schema.Draft202012Validator, "validate", validate)
  return calls


def test_verified_reference_free_nested_schema_reuses_meta_validation(meta_calls):
  child = closed({"nested": {"type": "integer", "minimum": 1}})
  schema._strict_schema(closed({"first": child, "second": deepcopy(child)}))
  count = len(meta_calls)
  assert count == 1
  schema._strict_schema(deepcopy(child))
  schema._strict_schema({"minimum": 1, "type": "integer"})
  assert len(meta_calls) == count


@pytest.mark.parametrize("nested", [False, True])
def test_parent_bound_ref_is_not_valid_independent_cached_schema(meta_calls, nested):
  reference = {"$ref": "#/$defs/target"}
  child = closed({"value": reference}) if nested else reference
  root = closed({"value": child})
  root["$defs"] = {"target": {"type": "string"}}
  schema._strict_schema(root)
  count = len(meta_calls)
  with pytest.raises((ValueError, KeyError, ValidationError)):
    schema._strict_schema(deepcopy(child))
  assert len(meta_calls) > count


@pytest.mark.parametrize("annotation", ["default", "examples"])
def test_annotation_values_do_not_enter_structural_cache(annotation):
  invalid = {"type": "invalid"}
  child = {"type": "string", annotation: invalid if annotation == "default" else [invalid]}
  schema._strict_schema(closed({"value": child}))
  with pytest.raises((ValueError, KeyError, ValidationError)):
    schema._strict_schema(invalid)


@pytest.mark.parametrize("change", [{"type": "invalid"}, {"minimum": "invalid"}, {"unknown_keyword": True}])
def test_changed_subtree_is_strictly_revalidated(change, meta_calls):
  child = {"type": "integer", "minimum": 1}
  schema._strict_schema(closed({"value": child}))
  count = len(meta_calls)
  child.update(change)
  with pytest.raises((ValueError, KeyError, ValidationError)):
    schema._strict_schema(child)
  assert len(meta_calls) > count


def test_failed_root_does_not_publish_previously_visited_good_child(meta_calls):
  child = {"type": "string", "minLength": 1}
  with pytest.raises((ValueError, KeyError, ValidationError)):
    schema._strict_schema(closed({"first": child, "second": {"type": "string", "unknown_keyword": True}}))
  count = len(meta_calls)
  schema._strict_schema(child)
  assert len(meta_calls) > count


def test_subtree_cache_remains_bounded_and_evicted_content_still_validates():
  for number in range(schema._SCHEMA_SUBTREE_LIMIT + 12):
    schema._strict_schema(closed({"value": {"type": "integer", "minimum": number}}))
  cache = getattr(schema, "_SCHEMA_SUBTREES", None)
  assert isinstance(cache, dict)
  assert schema._SCHEMA_SUBTREE_LIMIT == 512
  assert 0 < len(cache) <= schema._SCHEMA_SUBTREE_LIMIT
  schema._strict_schema({"type": "integer", "minimum": 0})
  with pytest.raises((ValueError, KeyError, ValidationError)):
    schema._strict_schema({"type": "integer", "minimum": "invalid"})


def test_new_root_does_not_repeat_meta_recursion_into_verified_subtree(monkeypatch):
  child = closed({"nested": {"type": "integer", "minimum": 37}})
  schema._strict_schema(child)
  repeated = []
  original = schema.Draft202012Validator.descend
  def descend(self, instance, *args, **kwargs):
    if instance == child:
      repeated.append(deepcopy(instance))
    yield from original(self, instance, *args, **kwargs)
  monkeypatch.setattr(schema.Draft202012Validator, "descend", descend)
  root = closed({"first": deepcopy(child), "second": deepcopy(child)})
  root["title"] = "new-root-with-verified-children"
  schema._strict_schema(root)
  assert repeated == []


@pytest.mark.parametrize("field,value", [("required", "invalid"), ("minProperties", "invalid"),
  ("properties", "invalid")])
def test_warm_subtree_cache_does_not_hide_parent_meta_errors(field, value):
  child = closed({"value": {"type": "string"}})
  schema._strict_schema(child)
  root = closed({"cached": deepcopy(child)})
  root[field] = value
  with pytest.raises(ValidationError):
    schema._strict_schema(root)


def test_warm_subtree_cache_still_checks_other_uncached_bad_child():
  child = closed({"value": {"type": "integer", "minimum": 41}})
  schema._strict_schema(child)
  root = closed({"cached": deepcopy(child), "uncached": {"type": "string", "minLength": "invalid"}})
  with pytest.raises(ValidationError):
    schema._strict_schema(root)


def test_verified_ref_syntax_reuses_meta_work_but_resolves_each_new_root(monkeypatch):
  reference = {"$ref": "#/$defs/target"}
  first = closed({"value": deepcopy(reference)})
  first["$defs"] = {"target": {"type": "string"}}
  schema._strict_schema(first)
  repeated = []
  original = schema.Draft202012Validator.descend
  def descend(self, instance, *args, **kwargs):
    if instance == reference:
      repeated.append(deepcopy(instance))
    yield from original(self, instance, *args, **kwargs)
  monkeypatch.setattr(schema.Draft202012Validator, "descend", descend)
  second = closed({"other": deepcopy(reference)})
  second["$defs"] = {"target": {"type": "integer", "minimum": 53}}
  schema._strict_schema(second)
  assert repeated == []
  # 语法已验证不能替代当前根的引用解析；缺失上下文与严格非法目标仍拒绝。
  with pytest.raises((ValueError, KeyError, ValidationError)):
    schema._strict_schema(reference)
  second["$defs"]["target"] = {"type": "string", "unknown_keyword": True}
  with pytest.raises(ValueError):
    schema._strict_schema(second)
