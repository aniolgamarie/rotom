"""公开检查只处理仓库文本；凭据哨兵不可读取或输出。"""

import importlib.util
from pathlib import Path


spec = importlib.util.spec_from_file_location("public_docs", Path(__file__).resolve().parents[1] / "scripts/check-public-docs.py")
public_docs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public_docs)


def test_broken_link_and_machine_path_report_locations_only(tmp_path):
  path = tmp_path / "README.md"
  private_path = "/home/private-person/private-project"
  path.write_text("[missing](docs/absent.md)\n" + private_path + "\n")
  findings = public_docs.inspect(tmp_path, ["README.md"])
  assert {item["category"] for item in findings} == {"broken-local-link", "machine-specific-path"}
  assert private_path not in str(findings)
  assert all(set(item) == {"path", "line", "category"} for item in findings)


def test_generic_paths_fences_unknown_native_names_and_credential_files(tmp_path):
  (tmp_path / "docs").mkdir()
  (tmp_path / "docs/guide.md").write_text("# A heading\n\n## 中文 heading\n")
  (tmp_path / "README.md").write_text("[guide](docs/guide.md#a-heading)\n[中文](docs/guide.md#中文-heading)\n/home/user/project\n```sh\n[not a link](absent.md)\n```\n")
  (tmp_path / "secrets.toml").write_bytes(b"\xff\xfe")
  assert public_docs.inspect(tmp_path, ["README.md", "docs/guide.md", "secrets.toml"]) == []


def test_link_outside_repository_and_missing_fragment_fail(tmp_path):
  (tmp_path / "README.md").write_text("# Title\n[escape](../outside.md)\n[missing](#absent)\n")
  assert [item["category"] for item in public_docs.inspect(tmp_path, ["README.md"])] == ["broken-local-link", "missing-heading"]


def test_symlinked_document_directory_is_not_read(tmp_path):
  repository = tmp_path / "repository"
  repository.mkdir()
  outside = tmp_path / "private"
  outside.mkdir()
  (outside / "account.md").write_bytes(b"\xff\xfe")
  (repository / "docs").symlink_to(outside, target_is_directory=True)
  assert public_docs.inspect(repository, ["docs/account.md"]) == [
    {"path": "docs/account.md", "line": 0, "category": "unsafe-public-path"},
  ]
