"""私人文件 inbox 候选；元数据不是批准、现场句柄或派发许可。

可信调用者选择每 run 私人根；生产来源、计划批准、host 和期限仍须另核验。
仅独立 Registry 短 NB 元数据锁，不读取 owner/Domain，不获取外部锁或控制宿主。
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import re
import uuid

from . import run_owners, stop_requests, storage, stop_locks
from .storage import Conflict


_ERROR = "停止 inbox 元数据或私人目录不能确认；保留现有文件"
_ENDPOINT_KEYS = {"schema_version", "kind", "binding_digest", "run_id", "manager_identity", "host_identity", "nonce", "physical"}
_ENVELOPE_KEYS = {"schema_version", "kind", "endpoint_digest", "request"}
_REQUEST_NAME = re.compile(r"request-([0-9a-f]{32})\.json")


@contextmanager
def _boundary():
  try:
    yield
  except Exception:
    raise Conflict(_ERROR) from None


def _identity(value):
  if type(value) is not dict or set(value) != {"pid", "birth_id"}:
    raise ValueError()
  return run_owners._manager(value)


def _same(a, b):
  return run_owners._encode(a) == run_owners._encode(b)


def _physical(tree):
  info = os.fstat(tree.fd)
  return {"device": info.st_dev, "inode": info.st_ino}


def _names(tree):
  names = set()
  with os.scandir(tree.fd) as entries:
    for entry in entries:
      name = entry.name
      if (name in names or len(names) >= 129
          or name != "endpoint.json" and _REQUEST_NAME.fullmatch(name) is None):
        raise ValueError()
      names.add(name)
  return names


def _read(tree, name, limit):
  raw = tree.read(name, max_bytes=limit)
  if raw is None or raw[1] != 0o600:
    raise ValueError()
  value = json.loads(raw[0].decode("utf-8"), object_pairs_hook=run_owners._pairs,
    parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
  run_owners._no_float(value)
  if type(value) is not dict:
    raise ValueError()
  return value, raw[0]


def _request(value, endpoint):
  value = stop_requests.decode_stop_request(stop_requests.encode_stop_request(value))
  if (value["run_id"] != endpoint["run_id"]
      or not _same(value["manager_identity"], endpoint["manager_identity"])
      or not _same(value["host_identity"], endpoint["host_identity"])):
    raise ValueError()
  return value


class StopInbox:
  def __init__(self, root, binding):
    with _boundary():
      self._registry = run_owners.Registry(root, binding)
      self.root = self._registry.root

  def _endpoint(self, value, tree):
    if (type(value) is not dict or set(value) != _ENDPOINT_KEYS
        or type(value["schema_version"]) is not int or value["schema_version"] != 1
        or type(value["kind"]) is not str or value["kind"] != "stop-inbox"
        or type(value["binding_digest"]) is not str or value["binding_digest"] != self._registry.binding_digest):
      raise ValueError()
    run_owners._run_id(value["run_id"])
    run_owners._run_id(value["nonce"])
    manager, host = _identity(value["manager_identity"]), _identity(value["host_identity"])
    physical = value["physical"]
    if (manager["pid"] == host["pid"] or type(physical) is not dict or set(physical) != {"device", "inode"}
        or any(type(physical[key]) is not int for key in physical)
        or physical != _physical(tree) or len(run_owners._encode(value)) > 16384):
      raise ValueError()
    return deepcopy(value)

  def _load(self, tree):
    if tree is None:
      return None, {}
    names = _names(tree)
    if not names:
      self._registry._verify_root(tree)
      return None, {}
    if "endpoint.json" not in names:
      raise ValueError()
    endpoint = self._endpoint(_read(tree, "endpoint.json", 16384)[0], tree)
    digest = hashlib.sha256(run_owners._encode(endpoint)).hexdigest()
    requests = {}
    for name in sorted(names - {"endpoint.json"}):
      value, _ = _read(tree, name, 20 * 1024)
      if (set(value) != _ENVELOPE_KEYS or type(value["schema_version"]) is not int
          or value["schema_version"] != 1 or type(value["kind"]) is not str
          or value["kind"] != "stop-inbox-request" or value["endpoint_digest"] != digest):
        raise ValueError()
      request = _request(value["request"], endpoint)
      if name != "request-" + request["request_id"] + ".json" or request["request_id"] in requests:
        raise ValueError()
      requests[request["request_id"]] = request
    if _names(tree) != names:
      raise ValueError()
    self._registry._verify_root(tree)
    return endpoint, requests

  @staticmethod
  def _expected(expected, endpoint):
    if type(expected) is not dict or endpoint is None or not _same(expected, endpoint):
      raise ValueError()

  def create(self, *, run_id, manager_identity, host_identity):
    with _boundary():
      run_owners._run_id(run_id)
      manager, host = _identity(manager_identity), _identity(host_identity)
      if (manager["pid"] == host["pid"]
          or not _same(manager, _identity(run_owners.current_process_identity()))):
        raise ValueError()
      with self._registry._locked(create=True, nonblocking=True) as tree:
        if _names(tree):
          raise ValueError()
        endpoint = self._endpoint({"schema_version": 1, "kind": "stop-inbox",
          "binding_digest": self._registry.binding_digest, "run_id": run_id,
          "manager_identity": manager, "host_identity": host, "nonce": uuid.uuid4().hex,
          "physical": _physical(tree)}, tree)
        encoded = run_owners._encode(endpoint)
        tree.write_new("endpoint.json", encoded)
        storage.sync_directory_ancestors(self.root.parent)
        if _read(tree, "endpoint.json", 16384)[1] != encoded:
          raise ValueError()
        current, _ = self._load(tree)
        self._expected(endpoint, current)
        return deepcopy(current)

  def describe(self, deadline_ns=None):
    guard = (self._registry._locked(nonblocking=True) if deadline_ns is None
      else stop_locks.locked(self._registry, deadline_ns))
    with _boundary(), guard as tree:
      endpoint, _ = self._load(tree)
      return deepcopy(endpoint)

  def submit(self, request, *, expected, wait_for_lock=False):
    with _boundary():
      if type(wait_for_lock) is not bool:
        raise ValueError()
      request = stop_requests.decode_stop_request(stop_requests.encode_stop_request(request))
      guard = (stop_locks.locked(self._registry, request["deadline_ns"]) if wait_for_lock
        else self._registry._locked(nonblocking=True))
      with guard as tree:
        endpoint, requests = self._load(tree)
        self._expected(expected, endpoint)
        request = _request(request, endpoint)
        if len(requests) >= 128:
          raise ValueError()
        encoded = run_owners._encode({"schema_version": 1, "kind": "stop-inbox-request",
          "endpoint_digest": hashlib.sha256(run_owners._encode(endpoint)).hexdigest(), "request": request})
        if len(encoded) > 20 * 1024:
          raise ValueError()
        name = "request-" + request["request_id"] + ".json"
        tree.write_new(name, encoded)
        storage.sync_directory_ancestors(self.root.parent)
        if _read(tree, name, 20 * 1024)[1] != encoded:
          raise ValueError()
        current, requests = self._load(tree)
        self._expected(endpoint, current)
        if not _same(requests[request["request_id"]], request):
          raise ValueError()

  def pending(self, *, expected, poll=False):
    with _boundary():
      if type(poll) is not bool:
        raise ValueError()
    guard = stop_locks.try_locked(self._registry) if poll else self._registry._locked(nonblocking=True)
    with _boundary(), guard as tree:
      if poll and tree is None:
        return []
      endpoint, requests = self._load(tree)
      self._expected(expected, endpoint)
      if not _same(_identity(run_owners.current_process_identity()), endpoint["manager_identity"]):
        raise ValueError()
      self._registry._verify_root(tree)
      return [deepcopy(requests[key]) for key in sorted(requests)]
