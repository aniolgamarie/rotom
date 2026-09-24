"""显式旧 Pi 来源的只读盘点；不读取认证、不执行生成器、不接管目标。"""

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tomllib

from .config import _credential_url
from .paths import _open_directory, relative_path
from .pi_catalog import validate, validate_catalog
from .schema import ConfigError, validate_document
from .storage import Conflict, Tree


ROOT = Path(__file__).resolve().parents[2]
CORE_FIELDS = ("id", "kind", "source_id", "entrypoints", "requires", "conflicts",
  "control_domain", "supported_engines", "evidence_cases")
DISPOSITIONS = {"keep", "adapt", "merge", "replace", "optional", "exclude"}
DETAIL_FIELDS = {"source_paths", "home_paths", "target_path", "disposition", "reason", "package_specs", "expected_version"}
CATEGORIES = ("skills", "agents", "prompts", "themes", "extensions", "packages")
PROTOCOLS = {"openai-completions": "openai-compatible", "openai-responses": "openai-responses"}


def _digest(value):
  return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_catalog(repository):
  failed = False
  try:
    value = tomllib.loads((repository / "agents/pi/migration/capabilities.toml").read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "sources", "capabilities"}:
      raise ValueError()
    for row in value["capabilities"]:
      if set(row) != set(CORE_FIELDS) | DETAIL_FIELDS or row["disposition"] not in DISPOSITIONS:
        raise ValueError()
      if (not isinstance(row["reason"], str) or not row["reason"]
          or not isinstance(row["target_path"], str) or not isinstance(row["expected_version"], str)
          or any(not isinstance(row[key], list) or any(not isinstance(path, str) for path in row[key])
                 for key in ("source_paths", "home_paths", "package_specs"))):
        raise ValueError()
      for path in row["source_paths"] + row["home_paths"]:
        relative_path(path)
      if row["target_path"]:
        relative_path(row["target_path"])
    validate_catalog({**value, "capabilities": [{key: row[key] for key in CORE_FIELDS} for row in value["capabilities"]]})
  except Exception:
    failed = True
  if failed:
    raise ConfigError("pi-migration-catalog")
  return value


def _json(tree, name):
  raw = tree.read(name)
  if raw is None:
    return {}
  failed = False
  value = None
  try:
    if len(raw[0]) > 4 * 1024 * 1024:
      raise ValueError()
    value = json.loads(raw[0])
    if not isinstance(value, dict):
      raise ValueError()
  except Exception:
    failed = True
  if failed:
    raise ConfigError("pi-native-source-format")
  return value


def _presence(tree, name):
  """只读取文件元数据；不能因发现auth/config目录就读取其中正文。"""
  try:
    with tree.parent(name) as (fd, leaf):
      info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
      if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        return "unsafe"
      return "present"
  except FileNotFoundError:
    return "missing"
  except (OSError, Conflict):
    return "unsafe"


def _entries(tree, category):
  if tree.fd is None:
    return []
  try:
    with tree.parent(category + "/entry") as (fd, _):
      return sorted(os.listdir(fd))
  except FileNotFoundError:
    return []
  except (OSError, Conflict):
    raise Conflict("无法安全列出原生资源目录") from None


def _safe_specs(settings):
  specs = settings.get("packages", [])
  if not isinstance(specs, list):
    raise ConfigError("pi-package-selection")
  result, filtered, invalid = [], 0, 0
  for value in specs:
    if isinstance(value, dict):
      if set(value) - {"source", "extensions", "skills", "prompts", "themes"}:
        invalid += 1
        continue
      filtered += 1
      value = value.get("source")
    if not isinstance(value, str) or not value or "\0" in value or _credential_url(value):
      invalid += 1
      continue
    result.append(value)
  return result, filtered, invalid


def _model_proposal(tree, settings, blockers, locations, items):
  """只投影框架可表达的普通字段，原生apiKey永不复制或执行。"""
  native = _json(tree, "models.json")
  providers = native.get("providers", {})
  if not isinstance(providers, dict):
    raise ConfigError("pi-provider-source")
  proposal = {"providers": {}, "models": {}}
  bindings = {}
  seen_models = set()
  for key in ("defaultProvider", "defaultModel"):
    if settings.get(key) is not None and not isinstance(settings[key], str):
      raise ConfigError("pi-model-selection")
  for index, (name, provider) in enumerate(providers.items()):
    identity = "provider-" + str(index)
    items.append({"id": identity, "kind": "configuration", "source_id": "current", "source_state": "not-observed",
      "selected": False, "disk_state": "present", "load_evidence": "not-run", "execution_evidence": "not-run",
      "disposition": "adapt", "target_path": "local-overrides", "reason": "explicit-model-binding",
      "dependencies": [], "source_matches_baseline": None})
    locations.append({"id": identity, "origin": "current", "path": "models.json", "selector": ["providers", name]})
    if not isinstance(provider, dict) or set(provider) - {"api", "baseUrl", "apiKey", "models"}:
      blockers.append({"id": identity, "code": "provider-fields-require-mapping"})
      continue
    api, endpoint = provider.get("api"), provider.get("baseUrl")
    if api not in PROTOCOLS or not isinstance(endpoint, str) or not endpoint.startswith(("https://", "http://")) or _credential_url(endpoint):
      blockers.append({"id": identity, "code": "provider-route-requires-mapping"})
      continue
    models = provider.get("models", [])
    if not isinstance(models, list):
      raise ConfigError("pi-model-source")
    provider_id = "pi-provider-" + hashlib.sha256(name.encode()).hexdigest()[:12]
    proposal["providers"][provider_id] = {"protocol": PROTOCOLS[api], "base_url": endpoint,
      "auth_kind": "api-key", "credential_ref": "secret:" + provider_id + "-key"}
    blockers.append({"id": identity, "code": "credential-binding-required"})
    for model_index, model in enumerate(models):
      model_location = identity + "-model-" + str(model_index)
      locations.append({"id": model_location, "origin": "current", "path": "models.json", "selector": ["providers", name, "models", model_index]})
      if (not isinstance(model, dict) or set(model) - {"id", "input", "contextWindow", "maxTokens"}
          or not isinstance(model.get("id"), str) or not model["id"]):
        blockers.append({"id": model_location, "code": "model-fields-require-mapping"})
        continue
      model_id = "pi-model-" + _digest([name, model["id"]])[:12]
      if model_id in seen_models:
        proposal["models"].pop(model_id, None)
        bindings.pop((name, model["id"]), None)
        blockers.append({"id": model_location, "code": "duplicate-native-model"})
        continue
      seen_models.add(model_id)
      projected = {"provider": provider_id, "remote_id": model["id"], "input": model.get("input", ["text"])}
      for native_key, key in (("contextWindow", "context_window"), ("maxTokens", "max_output_tokens")):
        if native_key in model:
          projected[key] = model[native_key]
      proposal["models"][model_id] = projected
      bindings[(name, model["id"])] = model_id
  # 只验证可表达的框架部分；秘密引用仍需用户另行绑定，不编造可调用服务。
  validate_document("registry", {"schema_version": 1, **proposal})
  selected = bindings.get((settings.get("defaultProvider"), settings.get("defaultModel")))
  if selected:
    proposal["profiles"] = {"pi-default": {"providers": list(proposal["providers"]),
      "models": list(proposal["models"]), "roles": {"main": selected}}}
  elif settings.get("defaultProvider") is not None or settings.get("defaultModel") is not None:
    blockers.append({"id": "config-models", "code": "main-model-binding-required"})
  return {key: value for key, value in proposal.items() if value}


def build_inventory(pi_home, starter=None, *, repository=None):
  repository = Path(repository or ROOT)
  catalog = load_catalog(repository)
  baseline = json.loads((repository / "agents/pi/migration/source-baseline.json").read_text())
  source_files = {item["path"]: item for item in baseline["files"]}
  with ExitStack() as stack:
    current = stack.enter_context(Tree(Path(pi_home).absolute(), private=False))
    if current.fd is None:
      raise ConfigError("pi-home-missing")
    source = stack.enter_context(Tree(Path(starter).absolute(), private=False)) if starter is not None else None
    if source is not None and source.fd is None:
      raise ConfigError("pi-source-missing")
    settings = _json(current, "settings.json")
    specs, filtered, invalid = _safe_specs(settings)
    items, blockers, locations = [], [], []
    # 旧标记只作为来源归属提示，不采纳其权限、文件清单或历史快照。
    marker = ".starter-sync-manifest.json"
    marker_state = _presence(current, marker)
    if marker_state != "missing":
      blockers.append({"id": "legacy-sync-owner", "code": "legacy-manager-marker-preserved"})
      locations.append({"id": "legacy-sync-owner", "origin": "current", "path": marker})
      items.append({"id": "legacy-sync-owner", "kind": "configuration", "source_id": "current", "source_state": "not-observed",
        "selected": False, "disk_state": marker_state, "load_evidence": "not-run", "execution_evidence": "not-run",
        "disposition": "exclude", "target_path": "", "reason": "legacy-manager-not-adopted", "dependencies": [], "source_matches_baseline": None})
    recognized = set()
    known_home = {path for row in catalog["capabilities"] for path in row["home_paths"]}
    for row in catalog["capabilities"]:
      selected = any(spec in row["package_specs"] for spec in specs) if row["package_specs"] else None
      recognized.update(spec for spec in specs if spec in row["package_specs"])
      if row["kind"] == "theme" and isinstance(settings.get("theme"), str):
        selected = any(Path(path).stem == settings["theme"] for path in row["home_paths"])
      # 本地包只比较显式来源路径；不把同名任意目录视为同一个来源。
      if source is not None:
        for spec in specs:
          if ":" in spec or spec.startswith("git:"):
            continue
          path = os.path.abspath(os.path.join(str(current.root), spec))
          expected = [os.path.abspath(str(source.root / path).removesuffix("/package.json")) for path in row["source_paths"] if path.endswith("/package.json")]
          if path in expected:
            selected = True
            recognized.add(spec)
      states = [_presence(current, path) for path in row["home_paths"]]
      disk_state = "unsafe" if "unsafe" in states else "present" if "present" in states else "missing" if states else "not-observed"
      source_states, matches = [], []
      if source is not None:
        for path in row["source_paths"]:
          status = _presence(source, path)
          source_states.append(status)
          if status == "present":
            raw = source.read(path)
            expected = source_files.get(path)
            oid = hashlib.sha1(b"blob " + str(len(raw[0])).encode() + b"\0" + raw[0]).hexdigest()
            matches.append(expected is not None and oid == expected["git_blob"])
          elif status != "missing":
            blockers.append({"id": row["id"], "code": "source-path-unsafe"})
      source_state = ("not-observed" if source is None or not source_states else
        "unsafe" if "unsafe" in source_states else "present" if "present" in source_states else "missing")
      item = {"id": row["id"], "kind": row["kind"], "source_id": row["source_id"], "source_state": source_state,
        "selected": selected, "disk_state": disk_state, "load_evidence": "not-run", "execution_evidence": "not-run",
        "disposition": row["disposition"], "target_path": row["target_path"], "reason": row["reason"],
        "dependencies": row["requires"], "source_matches_baseline": all(matches) if matches else None}
      items.append(item)
      for path in row["home_paths"]:
        locations.append({"id": row["id"], "origin": "current", "path": path})
      if matches and not all(matches):
        blockers.append({"id": row["id"], "code": "source-drift"})
      if disk_state == "unsafe":
        blockers.append({"id": row["id"], "code": "native-path-unsafe"})
      if selected and row["disposition"] in {"replace", "exclude", "merge"}:
        blockers.append({"id": row["id"], "code": "legacy-selection-needs-replacement"})
    for index in range(invalid + len([value for value in specs if value not in recognized])):
      blockers.append({"id": "current-package-" + str(index), "code": "package-reference-requires-mapping"})
    if filtered:
      blockers.append({"id": "config-settings", "code": "package-filters-require-mapping"})
    for category in CATEGORIES:
      for name in _entries(current, category):
        path = category + "/" + name
        if any(known == path or known.startswith(path + "/") for known in known_home):
          continue
        if name.endswith(".bak") or ".bak." in name or name.startswith("."):
          continue
        identity = "current-extra-" + str(len(locations))
        locations.append({"id": identity, "origin": "current", "path": path})
        items.append({"id": identity, "kind": "configuration", "source_id": "current", "source_state": "not-observed",
          "selected": False, "disk_state": "present", "load_evidence": "not-run", "execution_evidence": "not-run",
          "disposition": "exclude", "target_path": "", "reason": "unmanaged-preserved", "dependencies": [], "source_matches_baseline": None})
    overrides = _model_proposal(current, settings, blockers, locations, items)
    selected_themes = [item["id"].removeprefix("theme-") for item in items
                       if item["kind"] == "theme" and item["selected"] is True]
    if selected_themes:
      profile = overrides.setdefault("profiles", {}).setdefault("pi-default", {})
      profile["agent_options"] = {"ui": {"theme": selected_themes[0]}}
    elif "theme" in settings:
      blockers.append({"id": "config-settings", "code": "theme-requires-mapping"})
    snapshot = {"baseline_revision": baseline["revision"], "baseline_digest": baseline["tree_manifest_sha256"]}
    # 不对整个混合原生文件取摘要，快照只由已过滤的非秘密事实组成。
    snapshot["projection_digest"] = _digest({"items": items, "overrides": overrides, "blockers": blockers})
    report = {"schema_version": 1, "feature_identity": "pi-migration-v1", "source_snapshot": snapshot,
      "items": items, "proposed_overrides": overrides, "blockers": blockers, "private_locations": locations}
    validate("migration", report)
    return report
