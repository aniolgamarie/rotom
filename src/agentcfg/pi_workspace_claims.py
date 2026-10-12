"""账户短锁内的Git/登记根物理覆盖索引；不提供执行队列或终止oracle。"""
from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import re

from jsonschema import Draft202012Validator
from .activity import allocation_digest as journal_digest, digest
from .deployment import json_bytes
from .paths import _absolute_directory
from .pi_catalog import validate
from .pi_registered_roots import RegisteredRoots, closed, pairs
from .schema import ConfigError
from .storage import Conflict, Tree


CONTEXT_KEYS = ("instance_id", "lease_id", "allocation_id", "owner_nonce", "supervisor_activation_id",
  "manager_activation_id", "supervisor_process_identity", "task_id", "attempt_id", "planned_workspaces",
  "lock_identity", "slice_identity", "policy_digest", "candidate_digest", "execution_id", "parent_execution_id",
  "kind", "allocation_journal_digest")
JOURNAL_KEYS = ("instance_id", "supervisor_activation_id", "manager_activation_id", "owner_nonce",
  "supervisor_process_identity", "allocation_id", "planned_workspaces", "execution_id", "attempt_id")
PROPERTIES = json.loads((Path(__file__).resolve().parents[2] / "agents/pi/schemas/execution-lease.schema.json").read_bytes())["properties"]


def strict_integers(value):
  if isinstance(value, dict):
    for key, child in value.items():
      if key in ("device", "inode", "uid", "pid", "ppid", "pgid", "schema_version", "grant_generation") and type(child) is not int:
        raise Conflict("账户占用整数身份无效")
      strict_integers(child)
  elif isinstance(value, list):
    for child in value: strict_integers(child)


def context(lease):
  projected = {key: deepcopy(lease.get(key)) for key in CONTEXT_KEYS}
  validate_context(projected)
  return projected


def validate_context(value):
  closed(value, CONTEXT_KEYS)
  strict_integers(value)
  try:
    for key, item in value.items():
      if item is not None: Draft202012Validator(PROPERTIES[key]).validate(item)
    for key in ("instance_id", "lease_id", "allocation_id", "owner_nonce", "supervisor_activation_id", "attempt_id", "planned_workspaces"):
      if value[key] is None: raise ValueError()
    if value["allocation_id"] != value["lease_id"]: raise ValueError()
    if value["allocation_journal_digest"] is not None and all(value[key] is not None for key in JOURNAL_KEYS):
      if journal_digest(value) != value["allocation_journal_digest"]: raise ValueError()
  except Exception as error:
    if isinstance(error, Conflict): raise
    raise Conflict("账户占用分配上下文无效") from None


def workspace_fields(record):
  keys = ("workspace_key", "host_boot_id", "uid", "worktree_path", "git_dir_path", "canonical_worktree_identity", "git_dir_identity")
  if "workspace_kind" in record: keys += ("workspace_kind", "registered_root_id")
  return {key: record[key] for key in keys}


def identity_fields(record):
  keys = ("host_boot_id", "uid", "canonical_worktree_identity", "git_dir_identity")
  if "workspace_kind" in record: keys += ("workspace_kind", "registered_root_id")
  return {key: record[key] for key in keys}


def stable_key(record):
  fields = identity_fields(record)
  return digest({key: value for key, value in fields.items() if key not in ("host_boot_id", "uid")})


def checked_evidence(evidence, record, allocation_context):
  try:
    strict_integers(evidence)
    validate("termination-evidence", evidence)
    if (evidence["verified"] is not True or evidence["execution_lease_id"] != record["execution_lease_id"]
        or evidence["grant_generation"] != record["grant_generation"]
        or evidence["allocation_journal_digest"] != allocation_context["allocation_journal_digest"]
        or evidence["evidence_digest"] != digest({key: value for key, value in evidence.items() if key != "evidence_digest"})):
      raise ValueError()
  except (ConfigError, ValueError, KeyError, TypeError): raise Conflict("账户占用释放证据无效") from None


def read_table(tree, coordinator):
  raw = tree.read("claims.json", max_bytes=1024 * 1024)
  if raw is None or raw[1] != 0o600: raise Conflict("账户占用记录缺失或权限无效")
  try:
    table = json.loads(raw[0], object_pairs_hook=pairs)
    closed(table, ("schema_version", "coordinator", "claims"))
    if type(table["schema_version"]) is not int or table["schema_version"] != 1 or table["coordinator"] != coordinator or not isinstance(table["claims"], list): raise ValueError()
    seen, roots = set(), set()
    for item in table["claims"]:
      closed(item, ("stable_root_key", "allocation_digest", "allocation_context", "record"))
      validate_context(item["allocation_context"])
      record = item["record"]
      strict_integers(record); validate("workspace-write-lease", record)
      if item["stable_root_key"] != stable_key(record) or item["allocation_digest"] != digest(item["allocation_context"]) or item["stable_root_key"] in seen: raise ValueError()
      planned = workspace_fields(record)
      if planned not in item["allocation_context"]["planned_workspaces"]: raise ValueError()
      if record["workspace_key"] != digest(identity_fields(record)): raise ValueError()
      if not owner_matches(record, item["allocation_context"]): raise ValueError()
      root_key = tuple(record["canonical_worktree_identity"][key] for key in ("device", "inode", "uid"))
      if root_key in roots: raise ValueError()
      roots.add(root_key)
      seen.add(item["stable_root_key"])
      if record["state"] == "released":
        if not record["termination_evidence_refs"]: raise ValueError()
        for reference in record["termination_evidence_refs"]:
          proof = tree.read("claim-evidence/" + reference + ".json", max_bytes=1024 * 1024)
          if not proof or proof[1] != 0o600: raise ValueError()
          evidence = json.loads(proof[0], object_pairs_hook=pairs)
          checked_evidence(evidence, record, item["allocation_context"])
          if evidence["evidence_digest"] != reference: raise ValueError()
    if "claim-evidence" in os.listdir(tree.fd):
      with Tree(tree.root / "claim-evidence") as evidence_tree:
        for name in os.listdir(evidence_tree.fd):
          if not re.fullmatch(r"[0-9a-f]{64}\.json", name): raise ValueError()
          proof = evidence_tree.read(name, max_bytes=1024 * 1024)
          if not proof or proof[1] != 0o600: raise ValueError()
          value = json.loads(proof[0], object_pairs_hook=pairs)
          strict_integers(value); validate("termination-evidence", value)
          if value["evidence_digest"] != name[:-5] or value["evidence_digest"] != digest({key: child for key, child in value.items() if key != "evidence_digest"}): raise ValueError()
    return table
  except (ValueError, TypeError, KeyError, ConfigError): raise Conflict("账户占用记录损坏；保护保持生效") from None


def owner_matches(record, lease):
  return all(record[key] == lease[source] for key, source in (("instance_id", "instance_id"),
    ("execution_lease_id", "lease_id"), ("allocation_id", "allocation_id"), ("holder_nonce", "owner_nonce"),
    ("supervisor_activation_id", "supervisor_activation_id"), ("task_id", "task_id"), ("attempt_id", "attempt_id")))


class WorkspaceClaims:
  def __init__(self, *, account_home=None):
    self.registry = RegisteredRoots(account_home=account_home)

  @contextmanager
  def locked(self, *, create=False):
    with self.registry._locked(write=True) as account_fd:
      with self.registry._state(account_fd, create=create) as (tree, registry, raw):
        if tree is None:
          yield None, None, None
          return
        if registry["schema_version"] == 1:
          if not create:
            yield tree, {"schema_version": 1, "coordinator": registry["coordinator"], "claims": []}, registry
            return
          if raw is None: tree.write_new("registry.json", json_bytes(registry))
          if tree.read("claims.json", max_bytes=1024 * 1024) is None:
            tree.write_new("claims.json", json_bytes({"schema_version": 1, "coordinator": registry["coordinator"], "claims": []}))
          registry.update(schema_version=2, claim_protocol=1)
          tree.write_state("registry.json", json_bytes(registry))
        yield tree, read_table(tree, registry["coordinator"]), registry

  def find(self, table, planned):
    return next((item for item in table["claims"] if item["stable_root_key"] == stable_key(planned)), None) if table else None

  def matches(self, item, lease, *, exact_generation=True):
    return item is not None and item["allocation_digest"] == digest(context(lease)) and owner_matches(item["record"], lease) and (not exact_generation or item["record"]["grant_generation"] == lease["grant_generation"])

  def check(self, table, planned, identify, *, lease=None):
    if not table: return
    candidate = Path(planned["worktree_path"])
    def inode_chain(path):
      result = set()
      for directory in (path, *path.parents):
        with _absolute_directory(directory) as fd:
          info = os.fstat(fd); result.add((info.st_dev, info.st_ino))
      return result
    candidate_chain = inode_chain(candidate)
    candidate_key = (planned["canonical_worktree_identity"]["device"], planned["canonical_worktree_identity"]["inode"])
    for item in table["claims"]:
      saved = item["record"]
      if saved["state"] == "released": continue
      try:
        actual = identify(saved["worktree_path"])
        keys = (set(workspace_fields(saved)) | set(actual)) - {"host_boot_id", "workspace_key"}
        if any(actual.get(key) != saved.get(key) for key in keys): raise ValueError()
        saved_key = (actual["canonical_worktree_identity"]["device"], actual["canonical_worktree_identity"]["inode"])
        overlapping = saved_key in candidate_chain or candidate_key in inode_chain(Path(actual["worktree_path"]))
      except Exception: raise Conflict("WORKSPACE_UNKNOWN：活动账户占用的物理根无法核验") from None
      if overlapping and not (lease is not None and self.matches(item, lease)):
        raise Conflict("WORKSPACE_BUSY：物理覆盖范围已有写入占用")

  def save(self, tree, table, planned, lease, record):
    item = {"stable_root_key": stable_key(planned), "allocation_context": context(lease),
            "allocation_digest": digest(context(lease)), "record": deepcopy(record)}
    old = self.find(table, planned)
    if old is None:
      old = next((saved for saved in table["claims"] if saved["record"]["state"] == "released"
        and saved["record"]["canonical_worktree_identity"] == planned["canonical_worktree_identity"]), None)
    if old: table["claims"][table["claims"].index(old)] = item
    else: table["claims"].append(item)
    tree.write_state("claims.json", json_bytes(table))
