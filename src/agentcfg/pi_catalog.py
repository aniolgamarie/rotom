"""Pi 声明校验；没有文件部署、秘密解析或宿主执行。"""

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry

from .schema import ConfigError


SCHEMAS = Path(__file__).resolve().parents[2] / "agents/pi/schemas"
KINDS = frozenset({"catalog", "agent", "resources", "options", "permission-policy", "managed-descriptor", "operation-grant",
  "evidence", "validation-run", "acceptance-item", "acceptance-scope", "migration", "migration-proposal", "runtime-receipt", "execution-lease", "workspace-write-lease", "stop-recovery-plan", "stop-recovery", "process-identity", "termination-evidence"})


@lru_cache(maxsize=128)
def _compiled_schema(text):
  # 内容作缓存键；修改/删除 schema 不会继续采用旧版本。
  document = json.loads(text)
  Draft202012Validator.check_schema(document)
  return Draft202012Validator(document, registry=Registry())


def _validator(kind):
  if kind not in KINDS:
    raise ConfigError("pi-schema-kind")
  failed = False
  try:
    validator = _compiled_schema((SCHEMAS / (kind + ".schema.json")).read_text(encoding="utf-8"))
  except Exception:
    failed = True
  if failed:
    raise ConfigError("pi-schema-resource")
  return validator


def read_schema(kind):
  # 调用方可构造投影 schema，但不能修改共享的已编译规则。
  return deepcopy(_validator(kind).schema)


def validate(kind, value):
  failed = False
  try:
    failed = not _validator(kind).is_valid(value)
  except Exception:
    failed = True
  if failed:
    raise ConfigError("pi-schema", (kind,))


def validate_catalog(value):
  validate("catalog", value)
  items = {item["id"]: item for item in value["capabilities"]}
  if len(items) != len(value["capabilities"]):
    raise ConfigError("pi-duplicate-capability")
  for item in items.values():
    if item["source_id"] not in value["sources"]:
      raise ConfigError("pi-source-reference")
    if (set(item["requires"]) | set(item["conflicts"])) - items.keys():
      raise ConfigError("pi-capability-reference")
  complete, visiting = set(), set()

  def visit(identity):
    if identity in visiting:
      raise ConfigError("pi-capability-cycle")
    if identity in complete:
      return
    visiting.add(identity)
    for required in items[identity]["requires"]:
      visit(required)
    visiting.remove(identity)
    complete.add(identity)

  for identity in items:
    visit(identity)
  return items


def select_capabilities(catalog, selected, engine):
  items = validate_catalog(catalog)
  if len(set(selected)) != len(selected) or set(selected) - items.keys():
    raise ConfigError("pi-capability-selection")
  chosen = set(selected)
  for identity in selected:
    item = items[identity]
    if (set(item["requires"]) - chosen or set(item["conflicts"]) & chosen
        or engine not in item["supported_engines"]):
      raise ConfigError("pi-capability-combination")
  return tuple(items[identity] for identity in selected)


def validate_policy(policy):
  validate("permission-policy", policy)
  ids = [rule["id"] for rule in policy["rules"]]
  if len(ids) != len(set(ids)):
    raise ConfigError("pi-duplicate-rule")


def validate_resources(resources):
  validate("resources", resources)
  role_fields = {"model_role", "tools", "read_roots", "write_roots", "nested"}
  for resource in resources.values():
    if resource["kind"] == "role":
      if role_fields - resource.keys():
        raise ConfigError("pi-role-incomplete")
    elif resource.keys() & role_fields:
      raise ConfigError("pi-resource-fields")
