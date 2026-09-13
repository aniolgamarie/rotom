"""实现检查发现的 OAuth 与来源/部署路径边界回归。"""

import os
from pathlib import Path

import pytest

from agentcfg.paths import PathError, trusted_source_directory
from agentcfg.schema import ConfigError, validate_document


def test_oauth_registry_does_not_require_a_fictional_endpoint():
  document = {"schema_version": 1, "providers": {
    "subscription": {"protocol": "oauth-dynamic", "auth_kind": "oauth"}}}
  validate_document("registry", document)
  document["providers"]["subscription"]["auth_kind"] = "api-key"
  with pytest.raises(ConfigError):
    validate_document("registry", document)
  document["providers"]["subscription"]["base_url"] = "https://example.invalid/v1"
  validate_document("registry", document)


def test_trusted_read_source_can_be_under_shared_parent(tmp_path):
  shared = tmp_path / "shared"
  shared.mkdir()
  shared.chmod(0o777)
  source = shared / "repository"
  source.mkdir(mode=0o700)
  with trusted_source_directory(source) as fd:
    assert os.fstat(fd).st_ino == source.stat().st_ino
  source.chmod(0o777)
  with pytest.raises(PathError):
    with trusted_source_directory(source):
      pytest.fail("writable source accepted")


def test_trusted_source_still_rejects_ancestor_symlink(tmp_path):
  real = tmp_path / "real"
  real.mkdir()
  link = tmp_path / "link"
  link.symlink_to(real, target_is_directory=True)
  with pytest.raises(PathError):
    with trusted_source_directory(link):
      pytest.fail("source symlink followed")
