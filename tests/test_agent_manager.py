import threading

from smartdialer.agent_manager import AgentManager
from smartdialer.models import Agent, AgentStatus


def test_agent_can_be_added():

    manager = AgentManager()

    agent = Agent(
        id="A1",
        name="Agent 1",
        status=AgentStatus.AVAILABLE
    )

    manager.add_agent(agent)

    assert len(manager.agents) == 1
    assert manager.agents["A1"].status == AgentStatus.AVAILABLE


def test_available_agent_can_be_reserved():

    manager = AgentManager()

    agent = Agent(
        id="A1",
        name="Agent 1",
        status=AgentStatus.AVAILABLE
    )

    manager.add_agent(agent)

    reserved_agent = manager.reserve_agent()

    assert reserved_agent is not None
    assert reserved_agent.id == "A1"
    assert reserved_agent.status == AgentStatus.RESERVED


def test_no_available_agent_returns_none():

    manager = AgentManager()

    agent = Agent(
        id="A1",
        name="Agent 1",
        status=AgentStatus.CONNECTED
    )

    manager.add_agent(agent)

    reserved_agent = manager.reserve_agent()

    assert reserved_agent is None

def test_only_one_worker_can_reserve_same_agent():

    manager = AgentManager()

    agent = Agent(
        id="A1",
        name="Agent 1",
        status=AgentStatus.AVAILABLE
    )

    manager.add_agent(agent)

    results = []

    def try_reserve():
        reserved_agent = manager.reserve_agent()
        results.append(reserved_agent)

    worker1 = threading.Thread(target=try_reserve)
    worker2 = threading.Thread(target=try_reserve)

    worker1.start()
    worker2.start()

    worker1.join()
    worker2.join()

    successful_reservations = [
        agent for agent in results
        if agent is not None
    ]

    assert len(successful_reservations) == 1
    assert agent.status == AgentStatus.RESERVED