from smartdialer.provider import ProviderEvent
from smartdialer.provider_a import ProviderA
from smartdialer.provider_b import ProviderB


def test_provider_a_returns_normal_call_events():

    provider = ProviderA()

    events = provider.initiate_call(
        "C1",
        "9999999999"
    )

    assert events == [
        ProviderEvent.INITIATED,
        ProviderEvent.RINGING,
        ProviderEvent.ANSWERED,
        ProviderEvent.CONNECTED,
        ProviderEvent.COMPLETED
    ]


def test_provider_b_returns_duplicate_events():

    provider = ProviderB()

    events = provider.initiate_call(
        "C1",
        "9999999999"
    )

    assert ProviderEvent.RINGING in events
    assert events.count(ProviderEvent.RINGING) == 2

    assert ProviderEvent.ANSWERED in events
    assert events.count(ProviderEvent.ANSWERED) == 2


def test_provider_a_default_is_fully_reliable():

    # No failure_rate given -> 0.0 -> always completes, same as before
    # this became configurable. Run several calls to be sure.
    provider = ProviderA()

    for i in range(50):
        events = provider.initiate_call(f"C{i}", "9999999999")
        assert events[-1] == ProviderEvent.COMPLETED


def test_provider_a_with_failure_rate_actually_fails_sometimes():

    # Seeded for reproducibility -- this isn't testing an exact count
    # (that's the pacing engine's job to estimate, not the provider's
    # job to guarantee), just that a nonzero failure_rate produces both
    # outcomes, not just one.
    provider = ProviderA(failure_rate=0.3, seed=7)

    outcomes = [
        provider.initiate_call(f"C{i}", "9999999999")[-1]
        for i in range(100)
    ]

    assert ProviderEvent.COMPLETED in outcomes
    assert ProviderEvent.FAILED in outcomes


def test_provider_a_failed_script_is_a_legal_call_state_sequence():

    provider = ProviderA(failure_rate=1.0, seed=1)

    events = provider.initiate_call("C1", "9999999999")

    assert events == [
        ProviderEvent.INITIATED,
        ProviderEvent.RINGING,
        ProviderEvent.FAILED
    ]


def test_provider_b_default_never_times_out():

    provider = ProviderB()

    for i in range(50):
        events = provider.initiate_call(f"C{i}", "9999999999")
        assert events[-1] == ProviderEvent.COMPLETED


def test_provider_b_with_timeout_rate_actually_times_out_sometimes():

    provider = ProviderB(timeout_rate=0.3, seed=7)

    timed_out = 0
    completed = 0

    for i in range(100):
        try:
            events = provider.initiate_call(f"C{i}", "9999999999")
            completed += 1
        except TimeoutError:
            timed_out += 1

    assert timed_out > 0
    assert completed > 0