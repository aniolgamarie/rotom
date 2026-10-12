"""真实plan编译跨许可/Writer分配；只用临时目录和合成mountinfo，无helper。"""

from pathlib import Path

import pytest

from agentcfg.activity import digest, protected
from agentcfg.pi_shell_mounts import compile_mount_plan
from agentcfg.storage import Conflict
from test_pi_shell_launch import configured
from test_pi_admitted_shell import prepare, consume
from test_pi_shell_mounts import mount_row


def configured_plan(tmp_path):
  f = configured(tmp_path)
  def backend(public):
    return {"runtime_identity": f[2].runtime_root.name, "helper_identity": "1" * 64,
      "plan_digest": digest(compile_mount_plan(public, system_roots=(), mountinfo=mount_row(1, "/")))}
  f[0].backend_preflight = backend
  return f


def test_first_writer_metadata_creation_does_not_invalidate_hidden_git_plan(tmp_path):
  f = configured_plan(tmp_path)
  git = Path(f[4]["cwd"]) / ".git"
  assert not (git / "agentcfg").exists()
  prepared = prepare(f)
  old = git.stat()
  ticket = consume(f, prepared)
  assert (git / "agentcfg/write-lease.json").is_file()
  assert git.stat() != old
  lease = f[2].store.read(ticket["lease_id"])
  command = f[0].command(lease, {"operation_id": prepared["operation_id"]})
  assert command.process_scope == "linux-shell" and not command.launch.attempted
  assert protected(lease)


def test_replacing_masked_git_directory_still_rejects_after_admission(tmp_path):
  f = configured_plan(tmp_path)
  prepared = prepare(f); ticket = consume(f, prepared)
  git = Path(f[4]["cwd"]) / ".git"
  git.rename(git.with_name("saved-private-git"))
  git.mkdir(); (git / "HEAD").write_text("ref: refs/heads/fixture\n")
  lease = f[2].store.read(ticket["lease_id"])
  with pytest.raises(Conflict): f[0].command(lease, {"operation_id": prepared["operation_id"]})
  assert protected(f[2].store.read(lease["lease_id"]))
