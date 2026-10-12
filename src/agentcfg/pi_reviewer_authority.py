"""账户授权工件的私有存储；不加载凭据、账本、SDK或产品factory。

写入只发生在显式create/update，失回执不重试。live身份绑定物理账户、
协调目录、文件stat与非秘密文档，不能用相同正文替换文件延续旧许可。
"""
from copy import deepcopy
import hashlib
import json
import os
import re

from .pi_registered_roots import RegisteredRoots, physical
from .pi_reviewer_authority_protocol import (validate_authority, decode_authority,
  encode_authority, authority_identity, validate_update, check_effective)
from .schema import ConfigError
from .storage import Conflict


FILE = "reviewer-authority.json"
MAX_BYTES = 16384


def _error(error):
  if isinstance(error, ConfigError) and error.code == "PI_RISK_REVIEW_AUTHORITY_INVALID":
    raise error from None
  if isinstance(error, Conflict):
    if str(error) == "WORKSPACE_BUSY：账户协调锁繁忙":
      raise Conflict("REVIEW_ACCOUNT_BUSY") from None
    if re.fullmatch("REVIEW_AUTHORITY_[A-Z_]+", str(error)):
      raise error from None
  raise Conflict("REVIEW_AUTHORITY_INVALID") from None


def _expected(value):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value):
    raise ConfigError("PI_RISK_REVIEW_AUTHORITY_INVALID")


def _snapshot(tree, account_identity):
  """已持有同一账户短锁的自有调用方复用；不再开锁或查询passwd。"""
  if tree is None:
    raise Conflict("REVIEW_AUTHORITY_MISSING")
  saved = tree.read(FILE, max_bytes=MAX_BYTES)
  if saved is None:
    raise Conflict("REVIEW_AUTHORITY_MISSING")
  if saved[1] != 0o600:
    raise Conflict("REVIEW_AUTHORITY_INVALID")
  document = decode_authority(saved[0])
  document_identity = authority_identity(document)
  binding = {"account": account_identity,
    "registry": physical(os.fstat(tree.fd)), "file": list(saved[2]),
    "document_identity": document_identity}
  identity = hashlib.sha256(json.dumps(binding, sort_keys=True,
    separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()
  return {"document": deepcopy(document), "document_identity": document_identity,
    "identity": identity}, saved


class ReviewerAuthorityStore:
  def __init__(self, *, account_home=None):
    try:
      self.__roots = RegisteredRoots(account_home=account_home)
    except Exception as error:
      _error(error)

  def __snapshot(self, tree):
    return _snapshot(tree, self.__roots.account_identity)

  def read(self):
    """只读观察，包括已过期工件；不创建协调目录或补授权。"""
    try:
      with self.__roots._locked() as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          return self.__snapshot(tree)[0]
    except Exception as error:
      _error(error)

  def active(self, *, now):
    snapshot = self.read()
    check_effective(snapshot["document"], now)
    return snapshot

  def verify_current(self, expected_identity, *, now):
    _expected(expected_identity)
    snapshot = self.active(now=now)
    if snapshot["identity"] != expected_identity:
      raise Conflict("REVIEW_AUTHORITY_STALE")
    return snapshot

  def __write(self, tree, document, *, expected):
    try:
      tree.replace(FILE, encode_authority(document), expected=expected)
      # 返回身份也必须来自已持久工件；失回执仅允许后续只读对账。
      snapshot, _ = self.__snapshot(tree)
      if snapshot["document"] != document:
        raise Conflict("REVIEW_AUTHORITY_WRITE_UNCONFIRMED")
      return snapshot
    except Exception:
      raise Conflict("REVIEW_AUTHORITY_WRITE_UNCONFIRMED") from None

  def create(self, document):
    document = validate_authority(document)
    if document["generation"] != 1:
      raise ConfigError("PI_RISK_REVIEW_AUTHORITY_INVALID")
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd, create=True) as (tree, registry, raw):
          if tree.read(FILE, max_bytes=MAX_BYTES) is not None:
            raise Conflict("REVIEW_AUTHORITY_EXISTS")
          if {"reviewer-budget", "reviewer-budget.json", "reviewer-scopes"} & set(os.listdir(tree.fd)):
            raise Conflict("REVIEW_AUTHORITY_RECOVERY_REQUIRED")
          if raw is None:
            try:
              tree.replace("registry.json", json.dumps(registry, sort_keys=True,
                separators=(",", ":")).encode("ascii"), expected=None)
            except Exception:
              raise Conflict("REVIEW_AUTHORITY_WRITE_UNCONFIRMED") from None
          return self.__write(tree, document, expected=None)
    except Exception as error:
      _error(error)

  def update(self, document, *, expected_identity):
    document = validate_authority(document)
    _expected(expected_identity)
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          before, saved = self.__snapshot(tree)
          if before["identity"] != expected_identity:
            raise Conflict("REVIEW_AUTHORITY_STALE")
          document = validate_update(before["document"], document)
          return self.__write(tree, document, expected=saved[2])
    except Exception as error:
      _error(error)
