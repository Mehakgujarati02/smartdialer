from smartdialer.models import (
    Agent,
    AgentStatus,
    Borrower,
    BorrowerStatus,
    Call,
    CallStatus,
)


def test_agent_starts_offline():
    agent = Agent(id="A1", name="Agent 1")

    assert agent.status == AgentStatus.OFFLINE


def test_borrower_starts_waiting():
    borrower = Borrower(
        id="B1",
        name="Borrower 1",
        phone_number="9999999999"
    )

    assert borrower.status == BorrowerStatus.WAITING


def test_call_starts_queued():
    call = Call(
        id="C1",
        agent_id="A1",
        borrower_id="B1"
    )

    assert call.status == CallStatus.QUEUED