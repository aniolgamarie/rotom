"""公开静态oracle验收；只读仓库fixture，不启动shell、宿主或模型。"""

import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/omp/command-scenarios"
STRICT = json.loads((FIXTURES / "strict-acceptance.json").read_text())
UNSUPPORTED = {"status": "unsupported", "reason": "unsupported-syntax"}

# 手工声明新增普通正例的v1边界，不用v2输出决定哪些例子应该失败。
NEW_ORDINARY_IDS = {
  "user-home-query-pipeline", "bare-home-and-multiple-home", "home-plus-glob-compound",
  "glob-indices-after-literal", "redirect-copy-before-write", "redirect-write-before-copy",
  "redirect-interleaved-with-argv", "quoted-redirection-home-literal", "comment-after-home",
  "quoted-and-midword-comment", "continuation-with-home-query", "operator-newline-comment",
  "quoted-dynamic-literal", "query-quoted-name-and-path",
}
EXISTING_ORDINARY_IDS = {
  "public-git-pipeline-anchor", "existing-git-compound-anchor", "quoted-escaped-home-and-glob",
}
ORDINARY = [row for row in STRICT["complete"] if row["gate"] == "model-eligible"]


@pytest.fixture(scope="module")
def oracle():
  spec = importlib.util.spec_from_file_location("strict_review_oracle", REPO / "scripts/omp-shell-review-oracle.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


@pytest.mark.parametrize("row", STRICT["complete"], ids=lambda row: row["id"])
def test_v2_matches_independent_handwritten_full_structure(oracle, row):
  # 深比较覆盖argv、connector、HOME/glob位置以及有顺序的fd重定向。
  assert oracle.expected_parse(row["command"]) == {"status": "complete", "commands": row["commands"]}


@pytest.mark.parametrize("row", STRICT["manual"], ids=lambda row: row["id"])
@pytest.mark.parametrize("context", ["plain", "after-and", "before-semicolon", "after-query-pipe"])
def test_v2_preserves_declared_manual_boundaries_in_compounds(oracle, row, context):
  command = {
    "plain": row["command"],
    "after-and": "pwd && " + row["command"],
    "before-semicolon": row["command"] + "; echo done",
    "after-query-pipe": "command -v ob | " + row["command"],
  }[context]
  assert oracle.expected_parse(command) == UNSUPPORTED


def test_home_suffix_is_literal_after_one_leading_home_marker(oracle):
  assert oracle.expected_parse("ls ~/backup~ ~/notes/~draft && command -v ob") == {
    "status": "complete", "commands": [
      {"connector": "start", "argv": ["ls", "~/backup~", "~/notes/~draft"], "homeExpansions": [1, 2]},
      {"connector": "&&", "argv": ["command", "-v", "ob"]},
    ],
  }


@pytest.mark.parametrize("command", ["MODE=fast ls ~/bin", "echo ok > ~/out.txt", "command ob"])
def test_v2_does_not_expand_assignment_write_target_or_execution_wrapper_contract(oracle, command):
  assert oracle.expected_parse(command) == UNSUPPORTED


def test_fixed_overlay_build_is_reproducible_and_complete(oracle):
  fixed = json.loads((FIXTURES / "grammar-parse-upgrade-20261009.json").read_text())
  first = oracle.build_overlay()
  assert first == fixed
  assert oracle.build_overlay() == first
  assert len(fixed["entries"]) == len({entry["id"] for entry in fixed["entries"]}) == 583
  assert fixed["counts"] == {"HOME": 501, "query": 74, "HOME+query": 8}
  assert all(entry["fullParse"]["status"] == "complete" for entry in fixed["entries"])


@pytest.mark.parametrize("path, digest", [
  (REPO / "scripts/omp-shell-test-oracle.py", "3900a2b3d5bed3e60ea2a5627056b8e008b595749037022a8d6c803532b2effa"),
  (FIXTURES / "corpus.json.gz", "d6e5dc5d68c685d44949a0487f7ff71bd60b28daad228c20ec8070d39a710699"),
  (FIXTURES / "grammar-upgrade-20261009.json", "92211b188ca473c31ebdf431bee5c7bae661d4d6306a5e7ebfdaa9b0ed18815b"),
], ids=["frozen-v1-oracle", "frozen-public-corpus", "frozen-gate-overlay"])
def test_historical_public_sources_keep_reviewed_byte_fingerprints(path, digest):
  assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_v1_matches_history_and_v2_changes_exactly_fixed_583_rows(oracle):
  corpus = json.loads(gzip.decompress((FIXTURES / "corpus.json.gz").read_bytes()))
  fixed = json.loads((FIXTURES / "grammar-parse-upgrade-20261009.json").read_text())
  deltas = {entry["id"]: entry for entry in fixed["entries"]}
  changed = set()
  assert len(corpus["records"]) == 11473
  for row in corpus["records"]:
    original = oracle.v1.expected_parse(row["command"])
    current = oracle.expected_parse(row["command"])
    assert original == row["expected"], row["id"]
    if original != current:
      changed.add(row["id"])
    if row["id"] in deltas:
      delta = deltas[row["id"]]
      assert hashlib.sha256(oracle.canonical(row)).hexdigest() == delta["sourceRowSha256"], row["id"]
      assert original == UNSUPPORTED, row["id"]
      assert current == delta["fullParse"], row["id"]
    else:
      assert current == original, row["id"]
  assert changed == set(deltas)
  assert len(changed) == 583


@pytest.mark.parametrize("row", ORDINARY, ids=lambda row: row["id"])
def test_frozen_v1_language_boundary_distinguishes_new_and_existing_ordinary_anchors(oracle, row):
  # 这里只证明冻结Python语言oracle的历史边界，不冒充历史TS parser运行证据。
  if row["id"] in NEW_ORDINARY_IDS:
    assert oracle.v1.expected_parse(row["command"]) == UNSUPPORTED
  else:
    assert row["id"] in EXISTING_ORDINARY_IDS
    assert oracle.v1.expected_parse(row["command"]) == {"status": "complete", "commands": row["commands"]}


def test_handwritten_scope_is_explicit_and_syntax_success_is_never_approval():
  assert STRICT["oracle"] == "independent-handwritten-static-contract"
  assert len(STRICT["complete"]) == 20
  assert len(STRICT["manual"]) == 42
  assert {row["id"] for row in ORDINARY} == NEW_ORDINARY_IDS | EXISTING_ORDINARY_IDS
  assert len(NEW_ORDINARY_IDS) == 14
  assert len(EXISTING_ORDINARY_IDS) == 3
  assert len([row for row in STRICT["complete"] if row["gate"] == "native-protection-required"]) == 3
