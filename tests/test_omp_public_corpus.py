import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_rebuild", ROOT / "scripts/rebuild-omp-test-corpus.py")
public = importlib.util.module_from_spec(spec)
spec.loader.exec_module(public)


@pytest.mark.parametrize("command", [
  "echo PrivateIdentity42 /home/PrivateIdentity42/project", "curl https://private-company.example/path?key=PrivateCanary42",
  "echo TOKEN='PrivateCanary42'", "python -c 'print(\"PrivateCanary42\")'", "echo 'PrivateCanary42' # PrivateIdentity42",
  r"echo Private\Canary42", "echo 私有身份42", "echo %50%72%69%76%61%74%65",
])
def test_public_rebuild_removes_unknown_data_and_encoded_identity(command):
  output = public.rebuild(command)
  assert not any(x in output for x in ["PrivateIdentity42", "PrivateCanary42", "private-company", "私有身份", "%50", "/home/"])
  assert output.isascii()


@pytest.mark.parametrize("command,expected", [
  ('echo "\\$literal"', {"status": "complete", "commands": [{"connector": "start", "argv": ["echo", "$literal"]}]}),
  ("echo a \\\nb", {"status": "complete", "commands": [{"connector": "start", "argv": ["echo", "a", "b"]}]}),
  ("echo a # ; rm -rf /", {"status": "complete", "commands": [{"connector": "start", "argv": ["echo", "a"]}]}),
  ("echo foo#bar", {"status": "complete", "commands": [{"connector": "start", "argv": ["echo", "foo#bar"]}]}),
  ("ls *.jar 2>/dev/null", {"status": "complete", "commands": [{"connector": "start", "argv": ["ls", "*.jar"], "globs": [1], "redirections": [{"fd": 2, "operator": ">", "target": "/dev/null"}]}]}),
])
def test_oracle_has_literal_anchors_independent_of_production(command, expected):
  assert public.oracle.expected_parse(command) == expected


def test_public_rebuild_keeps_risk_and_quote_boundaries():
  for command in ["ls *.jar 2>/dev/null; rm -rf /", 'sh -c "rm -rf /"', "cat '/etc/shadow'", "echo '' 'a'b", "echo '$NAME'", "echo one \\\ntwo"]:
    rebuilt = public.rebuild(command)
    assert public.oracle.expected_parse(rebuilt)["status"] == public.oracle.expected_parse(command)["status"]
  assert "rm -rf /" in public.rebuild('sh -c "rm -rf /"')
  assert "/etc/shadow" in public.rebuild("cat '/etc/shadow'")
  assert "2>/dev/null" in public.rebuild("ls *.jar 2>/dev/null")
  assert '2>&"2"' in public.rebuild('echo x 2>&"2"')
  assert "--api-key=REDACTED" in public.rebuild("curl --api-key=REDACTED")
  assert "API_KEY=REDACTED" in public.rebuild("echo ORGANIZATION_ACCESS_TOKEN=REDACTED")


def test_tracked_corpus_is_synthetic_strict_and_reproducible():
  path = ROOT / "tests/fixtures/omp/command-scenarios/corpus.json.gz"
  raw = path.read_bytes()
  assert raw[3] & 8 == 0
  data = json.loads(gzip.decompress(raw))
  assert set(data) == {"schemaVersion", "publication", "oracleVersion", "records", "summary"}
  assert data["publication"] == "synthetic-public"
  allowed = public.WORDS | set(re.findall(r"[^\W]+", " ".join(public.FLAGS | public.SPECIAL_PATHS)))
  vocabulary = re.compile("(?:fixture_\\d+|x|[0-9]|" + "|".join(re.escape(w) for w in sorted(allowed, key=len, reverse=True)) + ")+")
  assert sum(r["representedScenarios"] for r in data["records"]) == data["summary"]["inputScenarios"] == 11504
  assert len(data["records"]) == data["summary"]["publicCases"]
  for record in data["records"]:
    assert set(record) == {"id", "command", "category", "features", "representedScenarios", "expected", "expectedGate"}
    assert record["id"] == hashlib.sha256(record["command"].encode()).hexdigest()
    assert record["expected"] == public.oracle.expected_parse(record["command"])
    assert record["expectedGate"] == public.oracle.expected_gate(record["command"])
    assert not re.search(r"/(?:home|Users|data|opt|private|workspace)/", record["command"])
    assert all(vocabulary.fullmatch(v) for v in re.findall(r"[^\W]+", record["command"]))
  assert raw[4:8] == b"\0\0\0\0"


def test_unknown_source_fields_fail_instead_of_being_copied():
  with pytest.raises(ValueError):
    public.public_corpus({"schemaVersion": 2, "publication": "private-review-required", "unknown": "canary"})


def test_public_destination_rejects_traversal_and_symlink(tmp_path, monkeypatch):
  monkeypatch.setattr(public, "ROOT", tmp_path)
  folder = tmp_path / "tests/fixtures/omp/command-scenarios"
  folder.mkdir(parents=True)
  assert public.public_destination(str(folder / "corpus.json.gz")) == folder / "corpus.json.gz"
  for path in [folder / "../escaped.gz", tmp_path / "elsewhere.gz", folder / "corpus.json"]:
    with pytest.raises(ValueError):
      public.public_destination(str(path))
  (folder / "linked").symlink_to(tmp_path, target_is_directory=True)
  with pytest.raises(ValueError):
    public.public_destination(str(folder / "linked/corpus.json.gz"))
