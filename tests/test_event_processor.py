from smartdialer.call_manager import CallManager
from smartdialer.event_processor import EventProcessor
from smartdialer.models import Call, CallStatus
from smartdialer.provider import ProviderEvent


def create_call(status):

    return Call(
        id="C1",
        agent_id="A1",
        borrower_id="B1",
        status=status
    )


def test_provider_event_updates_call_state():

    manager = CallManager()

    call = create_call(CallStatus.RESERVED)
    manager.add_call(call)

    processor = EventProcessor(manager)

    processor.process_event(
        "C1",
        ProviderEvent.INITIATED
    )

    assert call.status == CallStatus.INITIATED


def test_duplicate_provider_event_is_safe():

    manager = CallManager()

    call = create_call(CallStatus.RINGING)
    manager.add_call(call)

    processor = EventProcessor(manager)

    processor.process_event(
        "C1",
        ProviderEvent.RINGING
    )

    processor.process_event(
        "C1",
        ProviderEvent.RINGING
    )

    assert call.status == CallStatus.RINGING


def test_out_of_order_provider_event_is_rejected():

    manager = CallManager()

    call = create_call(CallStatus.RINGING)
    manager.add_call(call)

    processor = EventProcessor(manager)

    result = processor.process_event(
        "C1",
        ProviderEvent.COMPLETED
    )

    assert result is False
    assert call.status == CallStatus.RINGING

def test_provider_b_duplicate_events_do_not_break_call():

    from smartdialer.provider_b import ProviderB

    manager = CallManager()

    call = create_call(CallStatus.RESERVED)
    manager.add_call(call)

    processor = EventProcessor(manager)
    provider = ProviderB()

    events = provider.initiate_call(
        "C1",
        "9999999999"
    )

    for event in events:
        processor.process_event("C1", event)

    assert call.status == CallStatus.COMPLETED