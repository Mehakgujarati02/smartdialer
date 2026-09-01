import threading

from smartdialer.models import Call, CallStatus


# Single source of truth for legal call-state moves, pulled out to
# module level so PersistentCallManager (see persistent_store.py)
# can reuse the exact same table instead of a second hand-maintained
# copy that could drift from this one.
CALL_VALID_TRANSITIONS = {
    CallStatus.QUEUED: {
        CallStatus.RESERVED,
        CallStatus.CANCELLED
    },

    CallStatus.RESERVED: {
        CallStatus.INITIATED,
        CallStatus.CANCELLED,
        CallStatus.FAILED
    },

    CallStatus.INITIATED: {
        CallStatus.RINGING,
        CallStatus.FAILED,
        CallStatus.CANCELLED
    },

    CallStatus.RINGING: {
        CallStatus.ANSWERED,
        CallStatus.FAILED,
        CallStatus.CANCELLED
    },

    CallStatus.ANSWERED: {
        CallStatus.CONNECTED,
        CallStatus.COMPLETED,
        CallStatus.FAILED,
        CallStatus.ABANDONED
    },

    CallStatus.CONNECTED: {
        CallStatus.COMPLETED,
        CallStatus.FAILED
    },

    CallStatus.COMPLETED: set(),
    CallStatus.FAILED: set(),
    CallStatus.CANCELLED: set(),
    CallStatus.ABANDONED: set()
}


class CallManager:

    def __init__(self):
        self.calls = {}
        self.lock = threading.Lock()
        self.valid_transitions = CALL_VALID_TRANSITIONS

    def add_call(self, call: Call):
        with self.lock:
            self.calls[call.id] = call

    def get_call(self, call_id):
        with self.lock:
            return self.calls.get(call_id)

    def transition(self, call_id, new_status):

        with self.lock:

            call = self.calls.get(call_id)

            if call is None:
                return False

            current_status = call.status

            # Ignore duplicate event
            if current_status == new_status:
                return True

            allowed_states = self.valid_transitions.get(
                current_status,
                set()
            )

            if new_status not in allowed_states:
                return False

            call.status = new_status

            return True