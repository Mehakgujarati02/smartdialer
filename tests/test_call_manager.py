from smartdialer.call_manager import CallManager
from smartdialer.models import Call, CallStatus


def create_call():

    return Call(
        id="C1",
        agent_id="A1",
        borrower_id="B1",
        status=CallStatus.RESERVED
    )


def test_valid_call_transition():

    manager = CallManager()

    call = create_call()
    manager.add_call(call)

    result = manager.transition(
        "C1",
        CallStatus.INITIATED
    )

    assert result is True
    assert call.status == CallStatus.INITIATED


def test_invalid_call_transition_is_rejected():

    manager = CallManager()

    call = create_call()
    manager.add_call(call)

    # RESERVED → COMPLETED is not allowed
    result = manager.transition(
        "C1",
        CallStatus.COMPLETED
    )

    assert result is False
    assert call.status == CallStatus.RESERVED


def test_duplicate_event_is_safe():

    manager = CallManager()

    call = Call(
        id="C1",
        agent_id="A1",
        borrower_id="B1",
        status=CallStatus.ANSWERED
    )

    manager.add_call(call)

    result = manager.transition(
        "C1",
        CallStatus.ANSWERED
    )

    assert result is True
    assert call.status == CallStatus.ANSWERED


def test_out_of_order_event_is_rejected():

    manager = CallManager()

    call = Call(
        id="C1",
        agent_id="A1",
        borrower_id="B1",
        status=CallStatus.RINGING
    )

    manager.add_call(call)

    # RINGING → COMPLETED is invalid
    result = manager.transition(
        "C1",
        CallStatus.COMPLETED
    )

    assert result is False
    assert call.status == CallStatus.RINGING


def test_completed_call_is_terminal():

    manager = CallManager()

    call = Call(
        id="C1",
        agent_id="A1",
        borrower_id="B1",
        status=CallStatus.COMPLETED
    )

    manager.add_call(call)

    result = manager.transition(
        "C1",
        CallStatus.ANSWERED
    )

    assert result is False
    assert call.status == CallStatus.COMPLETED