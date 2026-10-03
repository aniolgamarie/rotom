"""权限运行包 manifest/receipt 的纯校验，不构建、下载或运行宿主。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .deployment import json_bytes
from .omp_permission_build_inputs import BUILD_SCRIPT_PATHS, BuildInputUnavailable, _ordinary_path, read_build_input_lock, verify_file
from .omp_permission_build import permission_plugin_digest
from .process import DependencyError
from .schema import ConfigError


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "locks/omp/permission-control/manifest.json"
RECEIPT_PATH = "locks/omp/permission-control/build-receipt.json"
INPUT_PATH = "agents/omp/patches/permission-control/build-inputs.lock.json"
ABI = "permission-control/v1"


def sha(value):
  return hashlib.sha256(value).hexdigest()


def _object(pairs):
  result = {}
  for key, value in pairs:
    if key in result: raise ConfigError("omp-permission-duplicate-key")
    result[key] = value
  return result


def read_json(path):
  try:
    raw = _ordinary_path(path).read_bytes()
    value = json.loads(raw, object_pairs_hook=_object,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
  except (OSError, BuildInputUnavailable):
    raise DependencyError("omp-permission-lock-unavailable") from None
  except (ValueError, UnicodeError):
    raise ConfigError("omp-permission-lock-json") from None
  return value, raw


def validate_manifest(value):
  schema = json.loads((ROOT / "schemas/omp-permission-runtime.schema.json").read_text())
  errors = list(Draft202012Validator(schema).iter_errors(value))
  if errors and all(list(error.absolute_path) == ["bridgeAbi"] and error.validator == "const" for error in errors):
    raise DependencyError("omp-permission-abi-incompatible")
  if errors:
    raise ConfigError("omp-permission-manifest-schema")
  without_identity = {key: item for key, item in value.items() if key != "identity"}
  if sha(json_bytes(without_identity)) != value["identity"]:
    raise ConfigError("omp-permission-manifest-identity")
  if len({item["path"] for item in value["patches"]}) != len(value["patches"]):
    raise ConfigError("omp-permission-patch-duplicate")
  if any(item["cacheKey"] != "sha256/" + item["sha256"] for item in value["assets"].values()):
    raise ConfigError("omp-permission-asset-key")
  return deepcopy(value)


def verify_runtime_asset(manifest, platform, artifact_cache):
  value = validate_manifest(manifest)
  asset = value["assets"].get(platform)
  if asset is None:
    raise DependencyError("omp-permission-platform-unavailable")
  path = Path(artifact_cache) / asset["cacheKey"]
  try:
    verify_file(path, asset["sha256"], size=asset["size"])
  except BuildInputUnavailable:
    raise DependencyError("omp-permission-asset-mismatch") from None
  return path


def combined_identity(official_identity, patched_identity, platform, plugin_digest):
  return sha(json_bytes({"official": official_identity, "patched": patched_identity,
    "platform": platform, "plugin": plugin_digest}))


def validate_receipt(value):
  """receipt 仅保存构建输入与真实输出；封闭每层字段，禁止机器路径和自由正文。"""
  runtime_schema = json.loads((ROOT / "schemas/omp-permission-runtime.schema.json").read_text())
  if not Draft202012Validator(runtime_schema["$defs"]["buildReceipt"]).is_valid(value):
    raise ConfigError("omp-permission-receipt-schema")
  for group, key in (("tools", "name"), ("dependencyArtifacts", "cacheKey"),
      ("patches", "path"), ("buildScripts", "path")):
    if len({item[key] for item in value[group]}) != len(value[group]):
      raise ConfigError("omp-permission-receipt-duplicate")
  if [item["path"] for item in value["buildScripts"]] != list(BUILD_SCRIPT_PATHS):
    raise ConfigError("omp-permission-build-script-closure")
  return deepcopy(value)


def read_permission_runtime(repository, *, platform, upstream_identity, plugin_digest, artifact_cache=None):
  """按真实文件身份核对整个交付链；artifact_cache 缺省时只验证静态锁。"""
  repository = Path(repository)
  manifest_raw, _ = read_json(repository / MANIFEST_PATH)
  manifest = validate_manifest(manifest_raw)
  receipt, receipt_bytes = read_json(repository / RECEIPT_PATH)
  receipt = validate_receipt(receipt)
  return _validate_delivery(repository, manifest, receipt, receipt_bytes, platform=platform,
    upstream_identity=upstream_identity, plugin_digest=plugin_digest, artifact_cache=artifact_cache)


def _validate_delivery(repository, manifest, receipt, receipt_bytes, *, platform,
    upstream_identity, plugin_digest, artifact_cache=None):
  if sha(receipt_bytes) != manifest["buildReceiptDigest"]:
    raise DependencyError("omp-permission-receipt-mismatch")
  if manifest["upstreamIdentity"] != upstream_identity or manifest["pluginDigest"] != plugin_digest:
    raise DependencyError("omp-permission-delivery-mismatch")
  try:
    if permission_plugin_digest(repository) != plugin_digest:
      raise DependencyError("omp-permission-plugin-mismatch")
  except BuildInputUnavailable:
    raise DependencyError("omp-permission-plugin-mismatch") from None
  if platform not in manifest["assets"]:
    raise DependencyError("omp-permission-platform-unavailable")
  expected = {"upstreamIdentity": upstream_identity, "pluginDigest": plugin_digest,
    "bridgeAbi": ABI, "platform": platform, "patches": manifest["patches"], "asset": manifest["assets"][platform]}
  if any(receipt[key] != value for key, value in expected.items()):
    raise DependencyError("omp-permission-receipt-binding")
  input_schema = json.loads((ROOT / "schemas/omp-permission-build-inputs.schema.json").read_text())
  try:
    inputs = read_build_input_lock(repository / INPUT_PATH, input_schema)
    verify_file(repository / INPUT_PATH, receipt["buildInputsDigest"])
    for key in ("upstreamSource", "dependencyLock", "tools", "dependencyArtifacts", "platform"):
      if receipt[key] != inputs[key]:
        raise DependencyError("omp-permission-input-binding")
    verify_file(repository / inputs["dependencyLock"]["path"], inputs["dependencyLock"]["sha256"])
    for item in [*receipt["patches"], *receipt["buildScripts"]]:
      verify_file(repository / item["path"], item["sha256"])
    series = _ordinary_path(repository / "agents/omp/patches/permission-control/series")
    expected_series = [(series.parent / name).relative_to(repository).as_posix() for name in series.read_text().splitlines()]
    if expected_series != [item["path"] for item in receipt["patches"]]:
      raise DependencyError("omp-permission-series-mismatch")
  except (BuildInputUnavailable, OSError, ValueError):
    raise DependencyError("omp-permission-source-mismatch") from None
  asset_path = None if artifact_cache is None else verify_runtime_asset(manifest, platform, artifact_cache)
  return {"manifest": manifest, "receipt": receipt, "asset_path": asset_path,
    "identity": combined_identity(upstream_identity, manifest["identity"], platform, plugin_digest)}


def lock_prepared_runtime(repository, artifact_cache, *, upstream_identity):
  """只核验和锁定现有产物；不构建、下载、运行或写入用户 OMP 配置。"""
  repository, artifact_cache = Path(repository), Path(artifact_cache)
  receipt, receipt_bytes = read_json(artifact_cache / "build-receipt.json")
  receipt = validate_receipt(receipt)
  value = {"schemaVersion": 1, "variant": "permission-control-v1",
    "upstreamIdentity": upstream_identity, "bridgeAbi": ABI, "patches": receipt["patches"],
    "buildReceiptDigest": sha(receipt_bytes), "pluginDigest": receipt["pluginDigest"],
    "assets": {receipt["platform"]: receipt["asset"]}}
  value["identity"] = sha(json_bytes(value))
  value = validate_manifest(value)
  result = _validate_delivery(repository, value, receipt, receipt_bytes, platform=receipt["platform"],
    upstream_identity=upstream_identity, plugin_digest=receipt["pluginDigest"], artifact_cache=artifact_cache)
  from .storage import Tree
  with Tree(repository, private=False) as tree:
    before_receipt, before_manifest = tree.read(RECEIPT_PATH), tree.read(MANIFEST_PATH)
    tree.replace(RECEIPT_PATH, receipt_bytes, expected=before_receipt[2] if before_receipt else None)
    installed_receipt = tree.read(RECEIPT_PATH)
    try:
      tree.replace(MANIFEST_PATH, json_bytes(value), expected=before_manifest[2] if before_manifest else None)
    except BaseException:
      tree.replace(RECEIPT_PATH, before_receipt[0] if before_receipt else None,
        before_receipt[1] if before_receipt else 0o600, expected=installed_receipt[2])
      raise
  return result
