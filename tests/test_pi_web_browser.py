"""浏览器源只用临时数据库；不读取真实 HOME、账号或 keychain。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.pi_supervisor import Principal
from agentcfg.pi_web_browser import BrowserSnapshots
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError


def fixture(tmp_path):
  browser = tmp_path / "browser"; (browser / "Default").mkdir(parents=True, mode=0o700)
  source = browser / "Default/Cookies"; source.write_bytes(b"fixture database, never real browser data")
  wal = browser / "Default/Cookies-wal"; wal.write_bytes(b"fixture WAL")
  state = tmp_path / "state"; state.mkdir(mode=0o700)
  manifest = {"plugins": ["pi-web"], "web_browser_profiles": {"fixture": {"root": str(browser), "profile": "Default",
    "browser": "chrome", "allowed_hosts": ["private.example.invalid"], "max_bytes": 1024}}}
  now = [datetime.now(timezone.utc)]
  host = SimpleNamespace(root=state, store=SimpleNamespace(owner={"instance_id": "fixture", "owner_nonce": "fixture-private"}), manifest=lambda: manifest)
  snapshots = BrowserSnapshots(host, now=lambda: now[0])
  args = {"operation_id": "fixture-operation", "profile_id": "fixture", "hosts": ["private.example.invalid"]}
  return snapshots, args, source, wal, manifest, now


def test_selected_profile_snapshot_is_private_idempotent_and_does_not_modify_browser(tmp_path):
  snapshots, args, source, wal, manifest, now = fixture(tmp_path)
  value = snapshots.prepare(Principal("manager"), args)
  directory = Path(value["directory"])
  assert (directory / "Default/Cookies").read_bytes() == source.read_bytes()
  assert (directory / "Default/Cookies-wal").read_bytes() == wal.read_bytes()
  assert (directory / "Default/Cookies").stat().st_mode & 0o777 == 0o600
  assert snapshots.prepare(Principal("manager"), args) == value
  assert snapshots.finish(Principal("manager"), {"snapshot_id": value["snapshot_id"]}) == {"released": True}
  assert not directory.exists() and source.exists() and wal.exists()
  assert snapshots.finish(Principal("manager"), {"snapshot_id": value["snapshot_id"]}) == {"released": True}


@pytest.mark.parametrize("kind", ["worker", "unselected", "host", "profile", "size", "symlink", "hardlink", "writable", "bootstrap"])
def test_browser_snapshot_rejects_unbound_or_unsafe_inputs(tmp_path, kind):
  snapshots, args, source, wal, manifest, now = fixture(tmp_path)
  principal = Principal("worker") if kind == "worker" else Principal("manager")
  if kind == "unselected": manifest["plugins"] = []
  if kind == "host": args["hosts"] = ["other.example.invalid"]
  if kind == "profile": args["profile_id"] = {"unexpected": True}
  if kind == "size": manifest["web_browser_profiles"]["fixture"]["max_bytes"] = 4
  if kind == "symlink": source.unlink(); source.symlink_to(wal)
  if kind == "hardlink": source.unlink(); source.hardlink_to(wal)
  if kind == "writable": source.chmod(0o666)
  if kind == "bootstrap": manifest["bootstrap"] = True
  with pytest.raises((Conflict, ConfigError)): snapshots.prepare(principal, args)
  assert snapshots.pending == {}
  assert not list(snapshots.root.glob("*/Default/Cookies"))


def test_snapshot_scope_changes_refuse_reuse_and_expiration_removes_only_the_private_copy(tmp_path):
  snapshots, args, source, wal, manifest, now = fixture(tmp_path)
  value = snapshots.prepare(Principal("manager"), args)
  manifest["web_browser_profiles"]["fixture"]["allowed_hosts"].append("another.example.invalid")
  with pytest.raises(Conflict, match="STALE"): snapshots.prepare(Principal("manager"), args)
  now[0] += timedelta(minutes=6); snapshots.tick()
  assert snapshots.pending == {} and not Path(value["directory"]).exists()
  assert source.exists() and wal.exists()


def test_source_checkpoint_during_wal_copy_refuses_a_mixed_database_snapshot(tmp_path, monkeypatch):
  from contextlib import contextmanager
  from agentcfg.storage import Tree
  snapshots, args, source, wal, manifest, now = fixture(tmp_path)
  original = Tree.open_read
  @contextmanager
  def changing(tree, name, **kwargs):
    with original(tree, name, **kwargs) as value:
      if str(name).endswith("-wal") and tree.root == source.parent.parent:
        source.write_bytes(b"changed checkpoint during snapshot")
      yield value
  monkeypatch.setattr(Tree, "open_read", changing)
  with pytest.raises(Conflict): snapshots.prepare(Principal("manager"), args)
  assert snapshots.pending == {} and not list(snapshots.root.glob("*/Default/Cookies"))


def test_expired_snapshot_cleanup_cannot_remove_a_new_generation(tmp_path):
  snapshots, args, source, wal, manifest, now = fixture(tmp_path)
  first = snapshots.prepare(Principal("manager"), args)
  now[0] += timedelta(minutes=6)
  second = snapshots.prepare(Principal("manager"), args)
  assert second["snapshot_id"] != first["snapshot_id"]
  snapshots.finish(Principal("manager"), {"snapshot_id": first["snapshot_id"]})
  assert Path(second["directory"]).exists() and snapshots.pending


def test_restart_cleans_expired_owned_auth_copies_without_touching_browser_data(tmp_path):
  snapshots, args, source, wal, manifest, now = fixture(tmp_path)
  value = snapshots.prepare(Principal("manager"), args)
  restarted = BrowserSnapshots(snapshots.host, now=lambda: now[0])
  restarted.tick(scan=True); assert Path(value["directory"]).exists()
  now[0] += timedelta(minutes=6); restarted.tick(scan=True)
  assert not Path(value["directory"]).exists() and source.exists() and wal.exists()
