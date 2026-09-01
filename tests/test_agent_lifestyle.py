from smartdialer.agent_manager import AgentManager
from smartdialer.models import Agent, AgentStatus


def make_manager(status=AgentStatus.AVAILABLE):
    manager = AgentManager()
    manager.add_agent(Agent(id="A0", name="Agent 0", status=status))
    return manager


def test_full_progressive_lifecycle_sequence():

    manager = make_manager(AgentStatus.RESERVED)

    assert manager.mark_dialing("A0") is True
    assert manager.agents["A0"].status == AgentStatus.DIALING

    assert manager.mark_connected("A0") is True
    assert manager.agents["A0"].status == AgentStatus.CONNECTED

    assert manager.mark_wrap_up("A0") is True
    assert manager.agents["A0"].status == AgentStatus.WRAP_UP

    assert manager.release_agent("A0") is True
    assert manager.agents["A0"].status == AgentStatus.AVAILABLE


def test_predictive_bind_at_answer_skips_dialing():

    # Predictive calls only bind an agent once already ANSWERED, so the
    # agent goes straight from RESERVED to CONNECTED with no DIALING
    # phase -- confirm that's a legal transition.
    manager = make_manager(AgentStatus.RESERVED)

    assert manager.mark_connected("A0") is True
    assert manager.agents["A0"].status == AgentStatus.CONNECTED


def test_invalid_transition_is_rejected():

    manager = make_manager(AgentStatus.AVAILABLE)

    # Can't jump straight to CONNECTED from AVAILABLE.
    assert manager.mark_connected("A0") is False
    assert manager.agents["A0"].status == AgentStatus.AVAILABLE


def test_pause_only_allowed_from_available():

    manager = make_manager(AgentStatus.AVAILABLE)
    assert manager.pause_agent("A0") is True
    assert manager.agents["A0"].status == AgentStatus.PAUSED

    # Can't pause an agent that's mid-call.
    manager2 = make_manager(AgentStatus.CONNECTED)
    assert manager2.pause_agent("A0") is False
    assert manager2.agents["A0"].status == AgentStatus.CONNECTED


def test_resume_from_paused():

    manager = make_manager(AgentStatus.PAUSED)
    assert manager.resume_agent("A0") is True
    assert manager.agents["A0"].status == AgentStatus.AVAILABLE


def test_set_offline_reports_mid_call_correctly():

    mid_call_manager = make_manager(AgentStatus.CONNECTED)
    success, was_mid_call = mid_call_manager.set_offline("A0")
    assert success is True
    assert was_mid_call is True
    assert mid_call_manager.agents["A0"].status == AgentStatus.OFFLINE

    idle_manager = make_manager(AgentStatus.AVAILABLE)
    success, was_mid_call = idle_manager.set_offline("A0")
    assert success is True
    assert was_mid_call is False
    assert idle_manager.agents["A0"].status == AgentStatus.OFFLINE


def test_set_offline_unknown_agent_returns_false():

    manager = AgentManager()
    success, was_mid_call = manager.set_offline("does-not-exist")
    assert success is False
    assert was_mid_call is False


def test_offline_agent_cannot_be_reserved_until_brought_online():

    manager = make_manager(AgentStatus.OFFLINE)

    assert manager.reserve_agent() is None  # OFFLINE isn't AVAILABLE

    assert manager.bring_online("A0") is True
    assert manager.agents["A0"].status == AgentStatus.AVAILABLE
    assert manager.reserve_agent() is not None
