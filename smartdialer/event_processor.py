from smartdialer.call_manager import CallManager
from smartdialer.models import CallStatus
from smartdialer.provider import ProviderEvent


class EventProcessor:

    def __init__(self, call_manager: CallManager):
        self.call_manager = call_manager

    def process_event(self, call_id, event: ProviderEvent):

        new_status = CallStatus(event.value)

        return self.call_manager.transition(
            call_id,
            new_status
        )