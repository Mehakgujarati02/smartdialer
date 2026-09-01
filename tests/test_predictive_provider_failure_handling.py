from smartdialer.agent_manager import AgentManager
from smartdialer.borrower_manager import BorrowerManager
from smartdialer.call_allocator import CallAllocator
from smartdialer.call_manager import CallManager
from smartdialer.predictive_pacing_engine import PredictivePacingEngine
from smartdialer.safety_controller import SafetyController
from smartdialer.predictive_dialer import PredictiveDialer
from smartdialer.event_processor import EventProcessor
from smartdialer.provider import TelecomProvider, ProviderEvent
from smartdialer.models import Agent, AgentStatus, Borrower, CallStatus


class RaisingProvider(TelecomProvider):
    def initiate_call(self, call_id, phone_number):
        raise TimeoutError("simulated outage")


class TruncatedProvider(TelecomProvider):
    def initiate_call(self, call_id, phone_number):
        return [ProviderEvent.INITIATED, ProviderEvent.RINGING]


def setup_system(provider, num_agents=3, num_borrowers=10, campaign_max_concurrency=3):

    agent_manager = AgentManager()
    for i in range(num_agents):
        agent_manager.add_agent(Agent(id=f"A{i}", name=f"A{i}", status=AgentStatus.AVAILABLE))

    borrower_manager = BorrowerManager()
    for i in range(num_borrowers):
        borrower_manager.add_borrower(Borrower(id=f"B{i}", name=f"B{i}", phone_number="1"))

    allocator = CallAllocator(agent_manager, borrower_manager)
    pacing = PredictivePacingEngine(campaign_max_concurrency=campaign_max_concurrency, default_answer_rate=0.5)
    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=campaign_max_concurrency)
    call_manager = CallManager()
    event_processor = EventProcessor(call_manager)

    dialer = PredictiveDialer(pacing, safety, allocator, call_manager, event_processor, provider)

    return dialer, call_manager, safety, agent_manager, borrower_manager


def test_provider_exception_on_unbound_call_fails_cleanly():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(RaisingProvider())

    batch = dialer.launch_calls()
    call = batch[0]
    assert call.agent_id is None  # never bound, so nothing to leak

    dialer.process_call(call)

    assert call.status == CallStatus.FAILED
    assert dialer.fail_call(call.id) is True
    assert len(agent_manager.get_available_agents()) == len(agent_manager.agents)  # all still free


def test_truncated_provider_before_answer_is_treated_as_failure():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(TruncatedProvider())

    batch = dialer.launch_calls()
    call = batch[0]

    dialer.process_call(call)

    assert call.status == CallStatus.FAILED
    assert call.agent_id is None  # truncated before ANSWERED -- never bound


def test_circuit_breaker_trips_and_forces_progressive_fallback():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        RaisingProvider(), num_agents=5, num_borrowers=30, campaign_max_concurrency=30
    )
    dialer.provider_failure_threshold = 3

    for _ in range(3):
        batch = dialer.launch_calls()
        for call in batch:
            dialer.process_call(call)
            if call.status == CallStatus.FAILED:
                dialer.fail_call(call.id)

    assert safety.degraded is True

    # With degraded=True, authorize_capacity() now clamps overdialing to
    # available_agents even though the pacing engine would ask for more.
    next_batch = dialer.launch_calls()
    available = len(agent_manager.get_available_agents())
    assert len(next_batch) <= available
