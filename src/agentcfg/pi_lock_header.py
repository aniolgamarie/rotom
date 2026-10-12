"""固定自有schema资源与锁头校验；不提供来源或激活资格。"""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry

from .deployment import json_bytes


def validate_lock_header(manifest, *, schema_version):
  """读取固定schema，只核完整schema、版本与identity，不修改输入。"""
  failed = False
  try:
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/pi-lock.schema.json").read_text())
    if (type(schema_version) is not int or schema_version not in (1, 2)
        or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != schema_version
        or not Draft202012Validator(schema, registry=Registry()).is_valid(manifest)):
      raise ValueError()
    projection = {key: value for key, value in manifest.items() if key != "identity"}
    if hashlib.sha256(json_bytes(projection)).hexdigest() != manifest["identity"]:
      raise ValueError()
  except Exception:
    failed = True
  # 只清理新固定错误，包含调用方活跃异常的隐式上下文。
  if failed:
    try:
      raise ValueError("pi-lock-header")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise
