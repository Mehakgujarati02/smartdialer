from smartdialer.models import CallStatus, BorrowerStatus
from smartdialer.provider import ProviderEvent


# If a call ends processing in any status outside this set, something
# went wrong without ever reporting a terminal outcome (e.g. a provider
# returned a truncated event script). Treated as FAILED rather than
# left stuck -- see process_call()'s safety net below.
TERMINAL_CALL_STATUSES = {
    CallStatus.COMPLETED,
    CallStatus.FAILED,
    CallStatus.CANCELLED,
    CallStatus.ABANDONED
}


class ProgressiveDialer:

    def __init__(
            self,
            pacing_engine,
            safety_controller,
            call_allocator,
            call_manager,
            event_processor,
            provider,
            provider_failure_threshold=3
    ):
        self.pacing_engine = pacing_engine
        self.safety_controller = safety_controller
        self.call_allocator = call_allocator
        self.call_manager = call_manager
        self.event_processor = event_processor
        self.provider = provider

        self.active_calls = 0

        # Tracks call ids that have already been finalized (agent/borrower
        # released, safety controller notified) so that duplicate provider
        # events or duplicate finalize calls never release capacity twice
        # for the same call.
        self._finalized_call_ids = set()

        # Simple circuit breaker: N consecutive provider failures (raised
        # exceptions or calls that never reach a terminal outcome) trips
        # the Safety Controller's fallback mode. For ProgressiveDialer
        # this has no further effect on its own pacing (it's already 1:1
        # by design -- there's nowhere further "down" to fall back to),
        # but it's still recorded/tripped for consistency, visibility,
        # and because a shared SafetyController may also be gating a
        # PredictiveDialer on the same campaign, which DOES change
        # behaviour when this trips.
        self.provider_failure_threshold = provider_failure_threshold
        self._consecutive_provider_failures = 0

    def launch_calls(self):

        # 1. Ask pacing engine how many calls we can launch
        capacity = self.pacing_engine.calculate_capacity(
            self.active_calls
        )

        calls = []

        # 2. Try to create calls up to that capacity
        for _ in range(capacity):

            # 3. Safety check
            if not self.safety_controller.can_start_call():
                break

            # 4. Allocate agent + borrower
            call = self.call_allocator.allocate_call()

            if call is None:
                break

            # 5. Register call with CallManager
            self.call_manager.add_call(call)

            # 6. Update active-call counters
            self.safety_controller.call_started()
            self.active_calls += 1

            calls.append(call)

        return calls

    def process_call(self, call):

        # Get the borrower associated with this call
        borrower = self.call_allocator.borrower_manager.borrowers[
            call.borrower_id
        ]

        # Ask telecom provider to initiate the call. A provider outage
        # (timeout, connection error, etc.) raises rather than returning
        # events -- don't let that leak the agent/borrower/safety slot:
        # fail the call explicitly and let the normal fail_call() release
        # path handle cleanup, same as any other FAILED outcome.
        try:
            events = self.provider.initiate_call(
                call.id,
                borrower.phone_number
            )
        except Exception:
            self.call_manager.transition(call.id, CallStatus.FAILED)
            self._record_provider_failure()
            return call

        # Process every provider event
        for event in events:

            self.event_processor.process_event(
                call.id,
                event
            )

            if event == ProviderEvent.INITIATED:
                self.call_allocator.agent_manager.mark_dialing(call.agent_id)
            elif event == ProviderEvent.CONNECTED:
                self.call_allocator.agent_manager.mark_connected(call.agent_id)

        # Safety net: a provider that returns a truncated event script
        # (rings, then goes silent -- never COMPLETED/FAILED) would
        # otherwise leave the call stuck in a non-terminal state
        # forever. Don't rely on the caller to notice; fail it here.
        if call.status not in TERMINAL_CALL_STATUSES:
            self.call_manager.transition(call.id, CallStatus.FAILED)
            self._record_provider_failure()
        else:
            self._record_provider_success()

        return call

    def _record_provider_failure(self):
        self._consecutive_provider_failures += 1
        if self._consecutive_provider_failures >= self.provider_failure_threshold:
            self.safety_controller.trip_safety_fallback()

    def _record_provider_success(self):
        self._consecutive_provider_failures = 0

    def _finalize_call(self, call, borrower_terminal_status):
        """
        Release the resources (agent + borrower + safety-controller
        capacity) held by a call that has reached a terminal state.

        Idempotent: a call id is only finalized once, no matter how many
        times complete_call()/fail_call() are invoked for it (this is what
        keeps duplicate provider events, e.g. Provider B's duplicate
        RINGING/ANSWERED events, or a repeated finalize call, from
        releasing capacity or agents more than once).
        """

        if call.id in self._finalized_call_ids:
            return True

        self._finalized_call_ids.add(call.id)

        # Free the agent so it can be reserved for another borrower.
        self.call_allocator.agent_manager.release_agent(call.agent_id)

        # Move the borrower to its terminal state (COMPLETED) or back to
        # WAITING so it can be retried later (on failure).
        if borrower_terminal_status == BorrowerStatus.COMPLETED:
            self.call_allocator.borrower_manager.complete_borrower(
                call.borrower_id
            )
        else:
            self.call_allocator.borrower_manager.release_borrower(
                call.borrower_id
            )

        # Release the concurrency slot exactly once for this call.
        self.safety_controller.call_finished()

        if self.active_calls > 0:
            self.active_calls -= 1

        return True

    def complete_call(self, call_id):

        call = self.call_manager.get_call(call_id)

        if call is None:
            return False

        if call.status != CallStatus.COMPLETED:
            return False

        return self._finalize_call(call, BorrowerStatus.COMPLETED)

    def fail_call(self, call_id):

        call = self.call_manager.get_call(call_id)

        if call is None:
            return False

        if call.status != CallStatus.FAILED:
            return False

        return self._finalize_call(call, BorrowerStatus.WAITING)
