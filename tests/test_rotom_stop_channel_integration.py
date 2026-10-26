"""私人文件投递到候选manager循环；只注入假内核、假child和假通道。"""

from agentcfg.managed_wait import wait_with_service
from agentcfg.stop_executor import StopRequestHandler
from agentcfg.stop_inbox import StopInbox
from agentcfg.storage import Tree
from agentcfg import spawned_host
from test_rotom_managed_wait import StrictChild, timeout
from test_rotom_stop_executor import controlled, fake, RUN


def inbox_for(case):
  inbox = StopInbox(case.journal.root.with_name("inbox"), case.journal.binding)
  endpoint = inbox.create(run_id=RUN, manager_identity=case.request["manager_identity"],
    host_identity=case.request["host_identity"])
  return inbox, endpoint


def service_for(case, inbox, endpoint):
  def verify(request):
    # 模拟可信工厂的来源复核；实际批准/资源核验仍待生产接线。
    assert request == case.request
    return inbox.describe() == endpoint
  handler = StopRequestHandler(RUN, case.host, case.journal, verify=verify, send=case.send, clock=lambda: case.now)
  def service():
    for request in inbox.pending(expected=endpoint):
      handler.handle(request)
  return service


def test_private_request_intent_and_fake_send_keep_original_child_and_result(controlled):
  case = controlled; inbox, endpoint = inbox_for(case)
  inbox.submit(case.request, expected=endpoint)
  child = StrictChild(timeout(), 23)
  assert wait_with_service(child, service=service_for(case, inbox, endpoint)) == 23
  assert child.calls == [{"timeout": 0.1}, {"timeout": 0.1}]
  assert case.signals == [case.host]
  assert case.journal.read(RUN)["dispatch"] == "signal_sent"
  assert inbox.pending(expected=endpoint) == [case.request]


def test_multiple_queued_requests_never_repeat_same_run_signal(controlled):
  case = controlled; inbox, endpoint = inbox_for(case)
  inbox.submit(case.request, expected=endpoint)
  inbox.submit({**case.request, "request_id": "e" * 32}, expected=endpoint)
  notices = []; child = StrictChild(timeout(), 17)
  assert wait_with_service(child, service=service_for(case, inbox, endpoint),
    unavailable=lambda: notices.append("unavailable")) == 17
  assert child.calls == [{"timeout": 0.1}, {}] and notices == ["unavailable"]
  assert case.signals == [case.host]
  assert case.journal.read(RUN)["request"] == case.request
  assert len(inbox.pending(expected=endpoint)) == 2


def test_request_expired_in_queue_preserves_inbox_and_does_not_dispatch(controlled):
  case = controlled; inbox, endpoint = inbox_for(case)
  inbox.submit(case.request, expected=endpoint)
  case.now = case.request["deadline_ns"]
  notices = []; child = StrictChild(timeout(), 0)
  assert wait_with_service(child, service=service_for(case, inbox, endpoint),
    unavailable=lambda: notices.append("unavailable")) == 0
  assert case.signals == [] and not case.journal.root.exists()
  assert inbox.pending(expected=endpoint) == [case.request]
  assert child.calls == [{"timeout": 0.1}, {}] and notices == ["unavailable"]


def test_inbox_replaced_after_intent_never_reaches_fake_send(controlled, monkeypatch):
  case = controlled; inbox, endpoint = inbox_for(case)
  inbox.submit(case.request, expected=endpoint)
  raw = (inbox.root / "endpoint.json").read_bytes()
  service = service_for(case, inbox, endpoint); write = Tree.write_new
  def changed(tree, name, *args, **kwargs):
    result = write(tree, name, *args, **kwargs)
    if name == RUN + ".json":
      inbox.root.rename(inbox.root.with_name("old-inbox"))
      inbox.root.mkdir(mode=0o700)
      with Tree(inbox.root) as new: write(new, "endpoint.json", raw)
    return result
  monkeypatch.setattr(Tree, "write_new", changed)
  child = StrictChild(timeout(), -15); notices = []
  assert wait_with_service(child, service=service,
    unavailable=lambda: notices.append("unavailable")) == -15
  assert child.calls == [{"timeout": 0.1}, {}] and notices == ["unavailable"]
  assert not case.signals and case.journal.read(RUN)["dispatch"] == "unknown"


def test_bound_pidfd_channel_is_called_after_durable_intent_and_only_once(controlled, monkeypatch):
  case = controlled; inbox, endpoint = inbox_for(case); calls = []
  inbox.submit(case.request, expected=endpoint)
  def native_api(*args):
    assert case.journal.read(RUN)["dispatch"] == "unknown"
    calls.append(args)
  monkeypatch.setattr(spawned_host.signal, "SIGTERM", 15, raising=False)
  monkeypatch.setattr(spawned_host.signal, "pidfd_send_signal", native_api, raising=False)
  case.send = lambda host: host.send_sigterm_once()
  child = StrictChild(timeout(), timeout(), 23); notices = []
  assert wait_with_service(child, service=service_for(case, inbox, endpoint),
    unavailable=lambda: notices.append("unavailable")) == 23
  assert calls == [(77, 15, None, 0)]
  assert case.journal.read(RUN)["dispatch"] == "signal_sent"
  assert child.calls == [{"timeout": 0.1}, {"timeout": 0.1}, {}]
  assert notices == ["unavailable"]


def test_bound_pidfd_response_failure_keeps_unknown_and_native_exit(controlled, monkeypatch):
  case = controlled; inbox, endpoint = inbox_for(case); calls = []
  inbox.submit(case.request, expected=endpoint)
  def native_api(*args):
    assert case.journal.read(RUN)["dispatch"] == "unknown"
    calls.append(args)
    raise InterruptedError("synthetic-private-canary")
  monkeypatch.setattr(spawned_host.signal, "SIGTERM", 15, raising=False)
  monkeypatch.setattr(spawned_host.signal, "pidfd_send_signal", native_api, raising=False)
  case.send = lambda host: host.send_sigterm_once()
  child = StrictChild(timeout(), -15); notices = []
  assert wait_with_service(child, service=service_for(case, inbox, endpoint),
    unavailable=lambda: notices.append("unavailable")) == -15
  assert calls == [(77, 15, None, 0)]
  assert case.journal.read(RUN)["dispatch"] == "unknown"
  assert child.calls == [{"timeout": 0.1}, {}] and notices == ["unavailable"]
