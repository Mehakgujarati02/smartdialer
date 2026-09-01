import random

from smartdialer.provider import TelecomProvider, ProviderEvent


class ProviderA(TelecomProvider):
    """
    Fast, reliable, low failure rate -- as described in the assignment.
 
    failure_rate defaults to 0.0, not because Provider A is actually
    100% reliable in the real world, but because a nonzero *default*
    would make every existing test that instantiates ProviderA() with
    no arguments intermittently flaky -- a call that's supposed to
    always complete would occasionally, randomly, fail depending on
    system entropy. Realism belongs in how the caller configures it,
    not in a hidden default nobody asked for. For an actual simulation
    run (see app.py), instantiate with a small nonzero failure_rate,
    e.g. ProviderA(failure_rate=0.05), to see Provider A's "low failure
    rate" character for real; pass seed=<int> for a reproducible run,
    or leave it as None for genuine randomness each time.
    """

    def __init__(self, failure_rate=0.0, seed=None):
        self.failure_rate = failure_rate
        self._random = random.Random(seed)

    def initiate_call(self, call_id, phone_number):

        if self._random.random() < self.failure_rate:
            return [
                ProviderEvent.INITIATED,
                ProviderEvent.RINGING,
                ProviderEvent.FAILED
            ]

        return [
            ProviderEvent.INITIATED,
            ProviderEvent.RINGING,
            ProviderEvent.ANSWERED,
            ProviderEvent.CONNECTED,
            ProviderEvent.COMPLETED
        ]
 