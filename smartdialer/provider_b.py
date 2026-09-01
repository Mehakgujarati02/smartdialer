import random

from smartdialer.provider import TelecomProvider, ProviderEvent


class ProviderB(TelecomProvider):
    """
    Slower, occasional timeouts, duplicate events -- as described in
    the assignment. Duplicate RINGING/ANSWERED events are unconditional
    (that's Provider B's baseline quirk, unchanged); timeouts are a
    configurable probability on top of that, defaulting to 0.0 for the
    same determinism reason as ProviderA (see its docstring) -- tests
    that instantiate ProviderB() with no arguments keep getting the
    exact deterministic duplicate-event script they always have. Pass
    timeout_rate explicitly (see app.py) for a realistic simulation run.
 
    A "timeout" here means the provider never responds at all -- it
    raises before returning any events, exercising the dialers'
    provider-outage handling (see ProgressiveDialer/PredictiveDialer
    process_call()'s try/except), rather than a mid-call failure.
    """

    def __init__(self, timeout_rate=0.0, seed=None):
        self.timeout_rate = timeout_rate
        self._random = random.Random(seed)

    def initiate_call(self, call_id, phone_number):

        if self._random.random() < self.timeout_rate:
            raise TimeoutError(
                f"Provider B timed out dialing {phone_number}"
            )

        return [
            ProviderEvent.INITIATED,
            ProviderEvent.RINGING,
            ProviderEvent.RINGING,
            ProviderEvent.ANSWERED,
            ProviderEvent.ANSWERED,
            ProviderEvent.CONNECTED,
            ProviderEvent.COMPLETED
        ]
 