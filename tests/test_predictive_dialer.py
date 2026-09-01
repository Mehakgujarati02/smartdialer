from smartdialer.agent_manager import AgentManager
from smartdialer.borrower_manager import BorrowerManager
from smartdialer.call_allocator import CallAllocator
from smartdialer.call_manager import CallManager
from smartdialer.predictive_pacing_engine import PredictivePacingEngine
from smartdialer.safety_controller import SafetyController
from smartdialer.predictive_dialer import PredictiveDialer
from smartdialer.event_processor import EventProcessor
from smartdialer.provider_a import ProviderA

from smartdialer.models import (
    Agent,
    AgentStatus,
    Borrower,
    BorrowerStatus,
    CallStatus
)


def setup_system(
        num_agents=3,
        num_borrowers=20,
        campaign_max_concurrency=10,
        max_global_concurrency=10,
        max_overdial_ratio=5.0,
        default_answer_rate=0.5
):

    agent_manager = AgentManager()

    for i in range(num_agents):
        agent_manager.add_agent(
            Agent(id=f"A{i}", name=f"Agent {i}", status=AgentStatus.AVAILABLE)
        )

    borrower_manager = BorrowerManager()

    for i in range(num_borrowers):
        borrower_manager.add_borrower(
            Borrower(id=f"B{i}", name=f"Borrower {i}", phone_number=f"9{i:09d}")
        )

    allocator = CallAllocator(agent_manager, borrower_manager)

    pacing = PredictivePacingEngine(
        campaign_max_concurrency=campaign_max_concurrency,
        max_overdial_ratio=max_overdial_ratio,
        default_answer_rate=default_answer_rate
    )

    safety = SafetyController(
        max_global_concurrency=max_global_concurrency,
        max_campaign_concurrency=campaign_max_concurrency
    )

    call_manager = CallManager()
    event_processor = EventProcessor(call_manager)
    provider = ProviderA()

    dialer = PredictiveDialer(
        pacing, safety, allocator, call_manager, event_processor, provider
    )

    return dialer, call_manager, safety, agent_manager, borrower_manager


def test_predictive_dialer_never_exceeds_safety_campaign_limit():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=5,
        num_borrowers=50,
        campaign_max_concurrency=6,
        max_overdial_ratio=10.0,
        default_answer_rate=0.1  # would love to overdial hugely
    )

    batch = dialer.launch_calls()

    assert len(batch) <= 6
    assert safety.active_campaign_calls <= 6


def test_predictive_dialer_never_exceeds_safety_global_limit():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=50,
        num_borrowers=100,
        campaign_max_concurrency=1000,
        max_global_concurrency=4,
        max_overdial_ratio=100.0,
        default_answer_rate=0.05
    )

    batch = dialer.launch_calls()

    assert len(batch) <= 4
    assert safety.active_global_calls <= 4


def test_degraded_mode_forces_1_to_1_pacing():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=3,
        num_borrowers=50,
        campaign_max_concurrency=1000,
        max_overdial_ratio=100.0,
        default_answer_rate=0.05  # would normally overdial massively
    )

    safety.trip_safety_fallback()

    batch = dialer.launch_calls()

    # Only 3 agents available -> degraded mode caps at 3 regardless of
    # how aggressive the pacing engine wanted to be.
    assert len(batch) == 3


def test_predictive_dialer_completes_calls_and_releases_resources():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=3, num_borrowers=10, campaign_max_concurrency=3
    )

    batch = dialer.launch_calls()

    for call in batch:
        dialer.process_call(call)
        assert call.status == CallStatus.COMPLETED
        dialer.complete_call(call.id)

    assert len(agent_manager.get_available_agents()) == 3
    assert safety.active_campaign_calls == 0
    assert safety.active_global_calls == 0


def test_predictive_dialer_feeds_outcomes_back_to_pacing_engine():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=2, num_borrowers=10, campaign_max_concurrency=2
    )

    assert len(dialer.pacing_engine._outcomes) == 0

    batch = dialer.launch_calls()

    for call in batch:
        dialer.process_call(call)

    # ProviderA always ends in COMPLETED -> both outcomes recorded as
    # answered=True
    assert len(dialer.pacing_engine._outcomes) == len(batch)
    assert all(dialer.pacing_engine._outcomes)


def test_predictive_dialer_duplicate_complete_call_does_not_double_release():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=2, num_borrowers=10, campaign_max_concurrency=2
    )

    batch = dialer.launch_calls()
    call = batch[0]

    dialer.process_call(call)

    assert dialer.complete_call(call.id) is True
    active_after_first = safety.active_campaign_calls

    assert dialer.complete_call(call.id) is True
    assert safety.active_campaign_calls == active_after_first


def test_predictive_dialer_calls_launch_unbound():

    # The whole point of predictive overdialing: a call can exist before
    # any agent is committed to it.
    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=2, num_borrowers=10, campaign_max_concurrency=2
    )

    batch = dialer.launch_calls()

    for call in batch:
        assert call.agent_id is None

    assert len(agent_manager.get_available_agents()) == 2  # untouched


def test_predictive_dialer_pre_answer_failure_never_touches_an_agent():

    # A call that fails before ever being answered should never have
    # consumed an agent -- that's the point of not binding one until
    # ANSWERED.
    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=2, num_borrowers=10, campaign_max_concurrency=2
    )

    batch = dialer.launch_calls()
    call = batch[0]
    assert call.agent_id is None

    call_manager.transition(call.id, CallStatus.INITIATED)
    call_manager.transition(call.id, CallStatus.FAILED)

    assert dialer.fail_call(call.id) is True
    assert call.agent_id is None

    borrower = borrower_manager.borrowers[call.borrower_id]
    assert borrower.status == BorrowerStatus.WAITING

    assert len(agent_manager.get_available_agents()) == 2


def test_predictive_dialer_post_answer_failure_releases_its_bound_agent():

    # A call that DID get answered (and bound to an agent) but then
    # fails mid-conversation should release that specific agent, same
    # as any other completion path.
    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=2, num_borrowers=10, campaign_max_concurrency=2
    )

    batch = dialer.launch_calls()
    call = batch[0]

    call_manager.transition(call.id, CallStatus.INITIATED)
    call_manager.transition(call.id, CallStatus.RINGING)
    call_manager.transition(call.id, CallStatus.ANSWERED)

    bound = dialer.call_allocator.try_bind_agent(call)
    assert bound is True
    assert call.agent_id is not None

    call_manager.transition(call.id, CallStatus.FAILED)

    assert dialer.fail_call(call.id) is True

    agent = agent_manager.agents[call.agent_id]
    assert agent.status == AgentStatus.AVAILABLE


def test_predictive_dialer_abandons_call_when_no_agent_free_at_answer_time():

    # 1 agent, but the pacing engine (with a 0.5 assumed answer rate)
    # will suggest overdialing to 2 -- exactly the scenario the
    # assignment flags as a compliance risk.
    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=1,
        num_borrowers=2,
        campaign_max_concurrency=2,
        max_overdial_ratio=5.0,
        default_answer_rate=0.5
    )

    batch = dialer.launch_calls()
    assert len(batch) == 2  # overdialed past the single agent

    call1, call2 = batch
    assert call1.agent_id is None
    assert call2.agent_id is None

    # ProviderA always "answers". Process call1 first and deliberately
    # do NOT complete it yet, so its agent stays tied up.
    dialer.process_call(call1)
    assert call1.status == CallStatus.COMPLETED
    assert call1.agent_id is not None

    # Now call2 answers too, but the only agent is still held by call1.
    dialer.process_call(call2)
    assert call2.status == CallStatus.ABANDONED
    assert call2.agent_id is None


def test_abandon_call_marks_borrower_failed_and_frees_safety_capacity():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        num_agents=1,
        num_borrowers=2,
        campaign_max_concurrency=2,
        max_overdial_ratio=5.0,
        default_answer_rate=0.5
    )

    batch = dialer.launch_calls()
    call1, call2 = batch

    dialer.process_call(call1)  # binds the only agent
    dialer.process_call(call2)  # abandoned -- no agent free

    assert call2.status == CallStatus.ABANDONED

    before = safety.active_campaign_calls

    assert dialer.abandon_call(call2.id) is True
    assert borrower_manager.borrowers[call2.borrower_id].status == BorrowerStatus.FAILED
    assert safety.active_campaign_calls == before - 1

    # Idempotent, same guard as complete_call()/fail_call()
    assert dialer.abandon_call(call2.id) is True
    assert safety.active_campaign_calls == before - 1
