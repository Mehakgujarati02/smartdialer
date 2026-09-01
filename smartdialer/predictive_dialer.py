from smartdialer.models import CallStatus, BorrowerStatus
from smartdialer.provider import ProviderEvent


# Same terminal-state set as ProgressiveDialer (kept local rather than
# imported to avoid a cross-import between the two dialer modules --
# they're deliberately independent; see class docstrings).
TERMINAL_CALL_STATUSES = {
    CallStatus.COMPLETED,
    CallStatus.FAILED,
    CallStatus.CANCELLED,
    CallStatus.ABANDONED
}


class PredictiveDialer:
    """
    Same job as ProgressiveDialer -- launch calls, run provider events,
    release resources on completion/failure -- but sources its launch
    capacity from a PredictivePacingEngine instead of the simple
    1-agent-1-call PacingEngine.

    The key architectural rule: the predictive engine's suggestion is
    never used directly. It always goes through
    SafetyController.authorize_capacity(), which is the only component
    with authority to approve, reduce, reject, or force a fallback to
    progressive (1:1) behaviour. The pacing engine has no reference to
    the safety controller and no way to influence that decision beyond
    the number it suggests.
    """

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
        self.ringing_call_ids = set()

        # Same duplicate-finalize guard as ProgressiveDialer -- a call id
        # is only ever released (agent freed, borrower requeued/completed,
        # safety capacity returned) once.
        self._finalized_call_ids = set()

        # Circuit breaker: N consecutive provider failures trips
        # SafetyController.degraded, which -- unlike ProgressiveDialer --
        # directly changes this dialer's own behaviour: authorize_capacity()
        # starts clamping every request to available_agents (1:1), i.e. an
        # unhealthy provider automatically forces this dialer back into
        # progressive-equivalent pacing without any human intervention.
        self.provider_failure_threshold = provider_failure_threshold
        self._consecutive_provider_failures = 0

    def launch_calls(self):

        available_agents = len(
            self.call_allocator.agent_manager.get_available_agents()
        )

        requested = self.pacing_engine.calculate_capacity(
            available_agents=available_agents,
            active_calls=self.active_calls,
            ringing_calls=len(self.ringing_call_ids)
        )

        authorized = self.safety_controller.authorize_capacity(
            requested,
            available_agents
        )

        calls = []

        for _ in range(authorized):

            # Unbound allocation: only reserves a borrower, not an
            # agent. This is what actually lets the predictive engine
            # dial more numbers than there are agents free right now --
            # an agent only gets bound if and when the call is answered
            # (see process_call() / try_bind_agent()).
            call = self.call_allocator.allocate_unbound_call()

            if call is None:
                # No borrower left waiting -- nothing more to launch.
                break

            self.call_manager.add_call(call)

            self.safety_controller.call_started()
            self.active_calls += 1
            self.ringing_call_ids.add(call.id)

            calls.append(call)

        return calls

    def process_call(self, call):
        """
        Runs the provider's event script for this call.

        Two things differ from ProgressiveDialer:

          1. If the call was launched unbound (agent_id is None) and the
             provider is about to report ANSWERED, we first try to bind
             a free agent right at that moment -- not before. If none is
             free, the call is marked ABANDONED (see below).
          2. A provider outage (raised exception, or a truncated event
             script that never reaches a terminal status) is handled the
             same defensive way as ProgressiveDialer: fail the call
             explicitly rather than leak resources or leave it stuck.
        """

        borrower = self.call_allocator.borrower_manager.borrowers[
            call.borrower_id
        ]

        try:
            events = self.provider.initiate_call(
                call.id,
                borrower.phone_number
            )
        except Exception:
            self.ringing_call_ids.discard(call.id)
            self.call_manager.transition(call.id, CallStatus.FAILED)
            self._record_provider_failure()
            return call

        abandoned = False

        for event in events:

            self.event_processor.process_event(call.id, event)

            if event == ProviderEvent.ANSWERED and call.agent_id is None:
                # The state machine has just accepted the RINGING ->
                # ANSWERED transition (call.status is now ANSWERED), so
                # ANSWERED -> ABANDONED below is a legal move if no agent
                # is free.
                self.ringing_call_ids.discard(call.id)

                if not self.call_allocator.try_bind_agent(call):
                    self.call_manager.transition(call.id, CallStatus.ABANDONED)
                    abandoned = True
                    break

                # Bound at answer time -- no DIALING phase for this
                # agent (it was never assigned while the phone was
                # ringing), so it goes straight RESERVED -> CONNECTED.
                self.call_allocator.agent_manager.mark_connected(call.agent_id)

            elif event == ProviderEvent.CONNECTED and call.agent_id is not None:
                # Progressive-style bound call (agent_id was already set
                # at launch, e.g. if this dialer is ever handed a
                # pre-bound call) -- mark_connected is idempotent-safe to
                # call again here since it's a no-op once already
                # CONNECTED (not in AGENT_VALID_TRANSITIONS[CONNECTED]).
                self.call_allocator.agent_manager.mark_connected(call.agent_id)

        self.ringing_call_ids.discard(call.id)

        if not abandoned and call.status not in TERMINAL_CALL_STATUSES:
            # Truncated provider script -- never reached a terminal
            # outcome. Don't leave it stuck; fail it explicitly.
            self.call_manager.transition(call.id, CallStatus.FAILED)

        if not abandoned:
            # Feed the real outcome back into the pacing engine so the
            # next capacity suggestion reflects what's actually
            # happening on this campaign, not just the cold-start
            # defaults. Abandoned calls are deliberately excluded here --
            # they're a safety-net failure of the estimate, not a signal
            # about the borrower list's real answer rate.
            answered = call.status in (CallStatus.CONNECTED, CallStatus.COMPLETED)
            self.pacing_engine.record_call_outcome(answered)
            self.pacing_engine.record_provider_event(
                call.status != CallStatus.FAILED
            )

            if call.status == CallStatus.FAILED:
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

        if call.id in self._finalized_call_ids:
            return True

        self._finalized_call_ids.add(call.id)
        self.ringing_call_ids.discard(call.id)

        # A call that was never answered (or was abandoned before an
        # agent got bound) may legitimately have no agent to release --
        # that's the entire point of not reserving one until ANSWERED.
        if call.agent_id is not None:
            self.call_allocator.agent_manager.release_agent(call.agent_id)

        if borrower_terminal_status == BorrowerStatus.COMPLETED:
            self.call_allocator.borrower_manager.complete_borrower(
                call.borrower_id
            )
        elif borrower_terminal_status == BorrowerStatus.FAILED:
            # Terminal, not requeued -- see mark_borrower_failed()
            # docstring. Used for ABANDONED calls so an abandoned
            # borrower isn't immediately redialed.
            self.call_allocator.borrower_manager.mark_borrower_failed(
                call.borrower_id
            )
        else:
            self.call_allocator.borrower_manager.release_borrower(
                call.borrower_id
            )

        # A call still occupied a safety-controller slot for its entire
        # lifetime, whether or not it ever got an agent -- launching it
        # was still one dial attempt against the campaign/provider
        # concurrency ceiling.
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

    def abandon_call(self, call_id):
        """
        Releases resources for a call that reached ABANDONED (answered,
        but no agent was free -- see process_call()). Mirrors
        complete_call()/fail_call() exactly, including the idempotency
        guard in _finalize_call(); the only difference is the terminal
        borrower disposition (FAILED, not requeued to WAITING).
        """

        call = self.call_manager.get_call(call_id)

        if call is None:
            return False

        if call.status != CallStatus.ABANDONED:
            return False

        return self._finalize_call(call, BorrowerStatus.FAILED)

