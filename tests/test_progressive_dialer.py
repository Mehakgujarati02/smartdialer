from smartdialer.agent_manager import AgentManager
from smartdialer.borrower_manager import BorrowerManager
from smartdialer.call_allocator import CallAllocator
from smartdialer.call_manager import CallManager
from smartdialer.pacing_engine import PacingEngine
from smartdialer.safety_controller import SafetyController
from smartdialer.progressive_dialer import ProgressiveDialer
from smartdialer.event_processor import EventProcessor
from smartdialer.provider_a import ProviderA

from smartdialer.models import (
    Agent,
    AgentStatus,
    Borrower,
    BorrowerStatus,
    CallStatus
)


def setup_system():

    # Agent manager
    agent_manager = AgentManager()

    for i in range(3):

        agent = Agent(
            id=f"A{i}",
            name=f"Agent {i}",
            status=AgentStatus.AVAILABLE
        )

        agent_manager.add_agent(agent)

    # Borrower manager
    borrower_manager = BorrowerManager()

    for i in range(5):

        borrower = Borrower(
            id=f"B{i}",
            name=f"Borrower {i}",
            phone_number=f"999999999{i}",
            priority=i
        )

        borrower_manager.add_borrower(borrower)

    # Allocator
    allocator = CallAllocator(
        agent_manager,
        borrower_manager
    )

    # Pacing
    pacing = PacingEngine(
        agent_manager,
        campaign_max_concurrency=3
    )

    # Safety
    safety = SafetyController(
        max_global_concurrency=10,
        max_campaign_concurrency=3
    )

    # Call manager
    call_manager = CallManager()

    # Dialer
    event_processor = EventProcessor(call_manager)

    provider = ProviderA()

    dialer = ProgressiveDialer(
        pacing,
        safety,
        allocator,
        call_manager,
        event_processor,
        provider
    )

    return dialer, call_manager


def test_progressive_dialer_creates_calls():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()

    assert len(calls) == 3
    assert len(call_manager.calls) == 3


def test_calls_are_reserved():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()

    for call in calls:
        assert call.status.value == "RESERVED"


def test_dialer_respects_campaign_limit():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()

    assert len(calls) <= 3


def test_dialer_stops_when_agents_are_unavailable():

    dialer, call_manager = setup_system()

    first_batch = dialer.launch_calls()

    assert len(first_batch) == 3

    second_batch = dialer.launch_calls()

    assert len(second_batch) == 0

def test_call_completes_through_provider_lifecycle():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()

    assert len(calls) == 3

    for call in calls:
        dialer.process_call(call)

    for call in calls:
        assert call.status.value == "COMPLETED"


def test_completed_call_releases_agent_back_to_available():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()

    for call in calls:
        dialer.process_call(call)
        dialer.complete_call(call.id)

    agent_manager = dialer.call_allocator.agent_manager

    assert len(agent_manager.get_available_agents()) == 3
    for agent in agent_manager.agents.values():
        assert agent.status == AgentStatus.AVAILABLE


def test_completed_call_marks_borrower_completed_not_stuck_reserved():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()

    for call in calls:
        dialer.process_call(call)
        dialer.complete_call(call.id)

    borrower_manager = dialer.call_allocator.borrower_manager

    completed_borrower_ids = {call.borrower_id for call in calls}

    for borrower_id in completed_borrower_ids:
        borrower = borrower_manager.borrowers[borrower_id]
        assert borrower.status == BorrowerStatus.COMPLETED


def test_agents_freed_by_completion_can_be_reused_for_new_calls():

    dialer, call_manager = setup_system()

    first_batch = dialer.launch_calls()
    assert len(first_batch) == 3

    for call in first_batch:
        dialer.process_call(call)
        dialer.complete_call(call.id)

    # 2 borrowers remain waiting (5 total - 3 already called), and all
    # 3 agents should now be free again, so a second batch should launch.
    second_batch = dialer.launch_calls()

    assert len(second_batch) == 2


def test_duplicate_complete_call_does_not_double_release_capacity():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()
    call = calls[0]

    dialer.process_call(call)

    assert dialer.complete_call(call.id) is True
    active_after_first = dialer.safety_controller.active_campaign_calls

    # Calling complete_call again for the same, already-finalized call
    # must not release safety-controller capacity a second time.
    assert dialer.complete_call(call.id) is True
    assert dialer.safety_controller.active_campaign_calls == active_after_first


def test_failed_call_releases_agent_and_requeues_borrower():

    dialer, call_manager = setup_system()

    calls = dialer.launch_calls()
    call = calls[0]

    call_manager.transition(call.id, CallStatus.INITIATED)
    call_manager.transition(call.id, CallStatus.FAILED)

    assert dialer.fail_call(call.id) is True

    agent_manager = dialer.call_allocator.agent_manager
    borrower_manager = dialer.call_allocator.borrower_manager

    agent = agent_manager.agents[call.agent_id]
    borrower = borrower_manager.borrowers[call.borrower_id]

    assert agent.status == AgentStatus.AVAILABLE
    assert borrower.status == BorrowerStatus.WAITING