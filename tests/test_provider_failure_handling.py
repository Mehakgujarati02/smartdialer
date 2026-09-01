from smartdialer.agent_manager import AgentManager
from smartdialer.borrower_manager import BorrowerManager
from smartdialer.call_allocator import CallAllocator
from smartdialer.call_manager import CallManager
from smartdialer.pacing_engine import PacingEngine
from smartdialer.safety_controller import SafetyController
from smartdialer.progressive_dialer import ProgressiveDialer
from smartdialer.event_processor import EventProcessor
from smartdialer.provider import TelecomProvider, ProviderEvent
from smartdialer.models import Agent, AgentStatus, Borrower, BorrowerStatus, CallStatus


class RaisingProvider(TelecomProvider):
    def initiate_call(self, call_id, phone_number):
        raise TimeoutError("simulated outage")


class TruncatedProvider(TelecomProvider):
    """Rings, then goes silent -- never reports a terminal outcome."""
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
    pacing = PacingEngine(agent_manager, campaign_max_concurrency=campaign_max_concurrency)
    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=campaign_max_concurrency)
    call_manager = CallManager()
    event_processor = EventProcessor(call_manager)

    dialer = ProgressiveDialer(pacing, safety, allocator, call_manager, event_processor, provider)

    return dialer, call_manager, safety, agent_manager, borrower_manager


def test_provider_exception_fails_call_without_leaking_resources():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(RaisingProvider())

    batch = dialer.launch_calls()
    call = batch[0]

    dialer.process_call(call)

    assert call.status == CallStatus.FAILED
    # The dialer itself doesn't auto-release here (that's fail_call()'s
    # job, same as any other FAILED call) -- confirm fail_call() cleans
    # it up the normal way.
    assert dialer.fail_call(call.id) is True
    assert agent_manager.agents[call.agent_id].status == AgentStatus.AVAILABLE
    assert borrower_manager.borrowers[call.borrower_id].status == BorrowerStatus.WAITING


def test_truncated_provider_script_is_treated_as_failure():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(TruncatedProvider())

    batch = dialer.launch_calls()
    call = batch[0]

    dialer.process_call(call)

    # Provider only ever sent INITIATED, RINGING -- never a terminal
    # status. The safety net should have forced FAILED rather than
    # leaving it stuck at RINGING.
    assert call.status == CallStatus.FAILED


def test_circuit_breaker_trips_safety_fallback_after_threshold():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        RaisingProvider(), num_agents=5, num_borrowers=20
    )
    dialer.provider_failure_threshold = 3

    assert safety.degraded is False

    for _ in range(3):
        batch = dialer.launch_calls()
        for call in batch:
            dialer.process_call(call)
            dialer.fail_call(call.id)

    assert safety.degraded is True


def test_circuit_breaker_resets_on_success():

    dialer, call_manager, safety, agent_manager, borrower_manager = setup_system(
        RaisingProvider(), num_agents=5, num_borrowers=20
    )
    dialer.provider_failure_threshold = 3

    batch = dialer.launch_calls()
    dialer.process_call(batch[0])
    dialer.fail_call(batch[0].id)
    assert dialer._consecutive_provider_failures == 1

    # A clean provider call resets the streak.
    dialer.provider = _CleanProvider()
    batch2 = dialer.launch_calls()
    dialer.process_call(batch2[0])
    assert dialer._consecutive_provider_failures == 0
    assert safety.degraded is False


class _CleanProvider(TelecomProvider):
    def initiate_call(self, call_id, phone_number):
        return [
            ProviderEvent.INITIATED,
            ProviderEvent.RINGING,
            ProviderEvent.ANSWERED,
            ProviderEvent.CONNECTED,
            ProviderEvent.COMPLETED
        ]
