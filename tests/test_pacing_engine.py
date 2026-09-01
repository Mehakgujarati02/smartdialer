from smartdialer.agent_manager import AgentManager
from smartdialer.models import Agent, AgentStatus
from smartdialer.pacing_engine import PacingEngine


def create_manager(number_of_agents):

    manager = AgentManager()

    for i in range(number_of_agents):

        agent = Agent(
            id=f"A{i}",
            name=f"Agent {i}",
            status=AgentStatus.AVAILABLE
        )

        manager.add_agent(agent)

    return manager


def test_capacity_is_based_on_available_agents():

    manager = create_manager(5)

    engine = PacingEngine(
        manager,
        campaign_max_concurrency=10
    )

    capacity = engine.calculate_capacity(
        active_calls=2
    )

    assert capacity == 5


def test_campaign_limit_restricts_capacity():

    manager = create_manager(10)

    engine = PacingEngine(
        manager,
        campaign_max_concurrency=5
    )

    capacity = engine.calculate_capacity(
        active_calls=2
    )

    assert capacity == 3


def test_no_capacity_when_campaign_limit_reached():

    manager = create_manager(10)

    engine = PacingEngine(
        manager,
        campaign_max_concurrency=5
    )

    capacity = engine.calculate_capacity(
        active_calls=5
    )

    assert capacity == 0


def test_no_capacity_when_no_agents_available():

    manager = AgentManager()

    agent = Agent(
        id="A1",
        name="Agent 1",
        status=AgentStatus.CONNECTED
    )

    manager.add_agent(agent)

    engine = PacingEngine(
        manager,
        campaign_max_concurrency=5
    )

    capacity = engine.calculate_capacity(
        active_calls=0
    )

    assert capacity == 0