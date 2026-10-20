"""离线门禁仅豁免已经固定并复核的本轮 cpuacct 描述符。"""
import importlib.util
from types import SimpleNamespace

import pytest

from test_herdr_benchmark import bench, fixture, filter_helper


def proof():
  return {"mode": "offline-sockets-seccomp", "no_new_privs": 1, "seccomp": 2,
    "inet_errno": 1, "inet6_errno": 1, "inet_pair_errno": 1, "inet6_pair_errno": 1,
    "unix_ipc": True, "io_uring_errno": 1, "root_owner_visible": True,
    "network_stdio_absent": True, "extra_fds_absent": True, "uid": 1234, "gid": 1234}


def loader(monkeypatch, prove):
  module = SimpleNamespace(prove_policy=prove)
  spec = SimpleNamespace(loader=SimpleNamespace(exec_module=lambda value: None))
  monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *args: spec)
  monkeypatch.setattr(importlib.util, "module_from_spec", lambda value: module)


def test_first_socket_proof_keeps_zero_argument_extra_fd_gate(monkeypatch):
  seen = []
  def prove(**kwargs):
    seen.append(kwargs)
    return proof()
  loader(monkeypatch, prove)
  assert bench.socket_filter_proof() == proof()
  assert seen == [{}]


def test_initial_helper_rejects_nonstdio_even_without_cpu_groups(monkeypatch):
  module = filter_helper()
  monkeypatch.setattr(module, "fd_numbers", lambda: [0, 1, 2, 99])
  monkeypatch.setattr(module.os, "fstat", lambda fd: SimpleNamespace(st_mode=0))
  with pytest.raises(OSError, match="inherited_nonstdio_fd_refused"):
    module.prove_policy(stdio_check=lambda: None)


def test_repeated_socket_proof_uses_exact_group_audit_and_maps_failure(monkeypatch):
  class Groups:
    failed = False
    def check_driver_descriptors(self):
      if self.failed:
        raise bench.CpuacctError("cpuacct_descriptors")
  groups = Groups()
  callbacks = []
  def prove(**kwargs):
    callback = kwargs["extra_fds_check"]
    assert callback.__self__ is groups
    callbacks.append(callback)
    callback()
    return proof()
  loader(monkeypatch, prove)
  assert bench.socket_filter_proof(groups) == proof()
  groups.failed = True
  with pytest.raises(bench.BenchError) as error:
    bench.socket_filter_proof(groups)
  assert error.value.code == 5 and error.value.reason == "offline_socket_capabilities_unverified"
  assert len(callbacks) == 2


def test_preflight_and_case_proof_reuse_same_group_audit(monkeypatch, tmp_path):
  manifest, policy = fixture("manifest"), fixture("policy")
  manifest["authorization_ref"] = "synthetic-approval"
  class Groups:
    checks = 0
    def check_driver_descriptors(self):
      self.checks += 1
  groups = Groups()
  seen = []
  def socket_proof(delegated=None):
    assert delegated is groups
    seen.append(delegated)
    delegated.check_driver_descriptors()
    return proof()
  monkeypatch.setattr(bench, "socket_filter_proof", socket_proof)
  monkeypatch.setattr(bench, "preflight", lambda *args: {"private": tmp_path})
  def measure(manifest, policy, subject, scope, directory, authorization, prepared, **kwargs):
    assert prepared["cpuacct_groups"] is groups
    report = bench.empty_report(manifest, policy, subject, scope)
    bench.record_socket_filter_proof(report, prepared, "output-1", "output", 1)
    return report
  monkeypatch.setattr(bench, "_native_measure", measure)
  bench._native_run(manifest, policy, "candidate", "first-baseline", tmp_path, "synthetic-approval", selected_case="output-1:output",
    offline_sockets=True, cpuacct_groups=groups)
  assert seen == [groups, groups] and groups.checks == 2
