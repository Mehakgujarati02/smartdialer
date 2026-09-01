from smartdialer.agent_manager import AgentManager
from smartdialer.borrower_manager import BorrowerManager
from smartdialer.call_allocator import CallAllocator
from smartdialer.models import (
    Agent,
    AgentStatus,
    Borrower,
    CallStatus
)


def test_call_is_allocated_to_agent_and_borrower():

    agent_manager = AgentManager()
    borrower_manager = BorrowerManager()

    agent = Agent(
        id="A1",
        name="Agent 1",
        status=AgentStatus.AVAILABLE
    )

    borrower = Borrower(
        id="B1",
        name="Borrower 1",
        phone_number="9999999999"
    )

    agent_manager.add_agent(agent)
    borrower_manager.add_borrower(borrower)

    allocator = CallAllocator(
        agent_manager,
        borrower_manager
    )

    call = allocator.allocate_call()

    assert call is not None
    assert call.agent_id == "A1"
    assert call.borrower_id == "B1"
    assert call.status == CallStatus.RESERVED

    assert agent.status == AgentStatus.RESERVED
    assert borrower.status.value == "RESERVED"


def test_call_is_not_created_without_agent():

    agent_manager = AgentManager()
    borrower_manager = BorrowerManager()

    borrower = Borrower(
        id="B1",
        name="Borrower 1",
        phone_number="9999999999"
    )

    borrower_manager.add_borrower(borrower)

    allocator = CallAllocator(
        agent_manager,
        borrower_manager
    )

    call = allocator.allocate_call()

    assert call is None

    # Borrower should be available again
    assert borrower.status.value == "WAITING"