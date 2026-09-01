import multiprocessing
import os
import tempfile

from smartdialer.persistent_store import (
    PersistentAgentManager,
    PersistentBorrowerManager,
    PersistentCallManager,
    recover_stale_calls
)
from smartdialer.models import Agent, AgentStatus, Borrower, BorrowerStatus, Call, CallStatus


def tmp_path(name):
    return os.path.join(tempfile.gettempdir(), f"smartdialer_pstore_{os.getpid()}_{name}.json")


def test_persistent_agent_manager_basic_reserve_release():

    manager = PersistentAgentManager(tmp_path("agents_basic"))
    manager.add_agent(Agent(id="A0", name="A0", status=AgentStatus.AVAILABLE))

    agent = manager.reserve_agent()
    assert agent.id == "A0" and agent.status == AgentStatus.RESERVED
    assert manager.reserve_agent() is None  # none left

    assert manager.release_agent("A0") is True
    assert len(manager.get_available_agents()) == 1


def test_persistent_agent_manager_lifecycle_and_invalid_transition():

    manager = PersistentAgentManager(tmp_path("agents_lifecycle"))
    manager.add_agent(Agent(id="A0", name="A0", status=AgentStatus.RESERVED))

    assert manager.mark_dialing("A0") is True
    assert manager.mark_connected("A0") is True
    assert manager.mark_wrap_up("A0") is True
    assert manager.release_agent("A0") is True
    assert manager.agents["A0"].status == AgentStatus.AVAILABLE

    # AVAILABLE -> CONNECTED is not a legal jump.
    assert manager.mark_connected("A0") is False
    assert manager.agents["A0"].status == AgentStatus.AVAILABLE


def test_persistent_borrower_manager_priority_and_release():

    manager = PersistentBorrowerManager(tmp_path("borrowers"))
    manager.add_borrower(Borrower(id="B0", name="B0", phone_number="1", priority=0))
    manager.add_borrower(Borrower(id="B1", name="B1", phone_number="2", priority=5))

    reserved = manager.reserve_borrower()
    assert reserved.id == "B1"  # higher priority first

    assert manager.release_borrower("B1") is True
    assert manager.borrowers["B1"].status == BorrowerStatus.WAITING


def test_persistent_call_manager_transitions_and_duplicate_events():

    manager = PersistentCallManager(tmp_path("calls"))
    manager.add_call(Call(id="C1", borrower_id="B0", agent_id="A0", status=CallStatus.RESERVED))

    assert manager.transition("C1", CallStatus.INITIATED) is True
    assert manager.transition("C1", CallStatus.CONNECTED) is False  # illegal jump
    assert manager.transition("C1", CallStatus.INITIATED) is True   # duplicate event, no-op
    assert manager.get_call("C1").status == CallStatus.INITIATED


def test_recover_stale_calls_reconciles_a_crashed_worker():

    agents = PersistentAgentManager(tmp_path("recover_agents"))
    borrowers = PersistentBorrowerManager(tmp_path("recover_borrowers"))
    calls = PersistentCallManager(tmp_path("recover_calls"))

    agents.add_agent(Agent(id="A0", name="A0", status=AgentStatus.CONNECTED))
    borrowers.add_borrower(Borrower(id="B0", name="B0", phone_number="1", status=BorrowerStatus.RESERVED))
    calls.add_call(Call(id="C1", borrower_id="B0", agent_id="A0", status=CallStatus.ANSWERED))

    recovered = recover_stale_calls(calls, agents, borrowers)

    assert recovered == ["C1"]
    assert calls.get_call("C1").status == CallStatus.FAILED
    assert agents.agents["A0"].status == AgentStatus.AVAILABLE
    assert borrowers.borrowers["B0"].status == BorrowerStatus.WAITING

    # Safe to run twice -- nothing left to recover the second time.
    assert recover_stale_calls(calls, agents, borrowers) == []


def test_recover_stale_calls_ignores_terminal_calls():

    agents = PersistentAgentManager(tmp_path("recover2_agents"))
    borrowers = PersistentBorrowerManager(tmp_path("recover2_borrowers"))
    calls = PersistentCallManager(tmp_path("recover2_calls"))

    calls.add_call(Call(id="C1", borrower_id="B0", agent_id="A0", status=CallStatus.COMPLETED))

    assert recover_stale_calls(calls, agents, borrowers) == []
    assert calls.get_call("C1").status == CallStatus.COMPLETED  # untouched


# --- the actual claim under test: real OS processes, not threads -----

def _worker_reserve(store_path, result_queue):
    manager = PersistentAgentManager(store_path)
    agent = manager.reserve_agent()
    result_queue.put(agent.id if agent else None)


def test_multiple_processes_cannot_double_book_agents():

    path = tmp_path("mp_race")
    manager = PersistentAgentManager(path)
    for i in range(5):
        manager.add_agent(Agent(id=f"A{i}", name=f"A{i}", status=AgentStatus.AVAILABLE))

    ctx = multiprocessing.get_context("spawn")
    result_queue = ctx.Queue()

    # 5 agents, 12 real OS processes racing for them.
    processes = [ctx.Process(target=_worker_reserve, args=(path, result_queue)) for _ in range(12)]
    for p in processes:
        p.start()
    for p in processes:
        p.join(timeout=10)

    results = [result_queue.get(timeout=5) for _ in processes]
    successes = [r for r in results if r is not None]

    assert len(successes) == 5           # exactly the number of agents
    assert len(set(successes)) == 5      # all distinct -- no double-booking
