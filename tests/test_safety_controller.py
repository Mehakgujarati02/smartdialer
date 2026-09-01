from smartdialer.safety_controller import SafetyController


def test_authorize_capacity_approves_within_headroom():

    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=10)

    authorized = safety.authorize_capacity(requested_capacity=5, available_agents=5)

    assert authorized == 5


def test_authorize_capacity_reduces_to_campaign_headroom():

    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=3)

    authorized = safety.authorize_capacity(requested_capacity=8, available_agents=8)

    assert authorized == 3


def test_authorize_capacity_reduces_to_global_headroom():

    safety = SafetyController(max_global_concurrency=2, max_campaign_concurrency=10)

    authorized = safety.authorize_capacity(requested_capacity=8, available_agents=8)

    assert authorized == 2


def test_authorize_capacity_rejects_when_no_headroom():

    safety = SafetyController(max_global_concurrency=1, max_campaign_concurrency=1)
    safety.call_started()

    authorized = safety.authorize_capacity(requested_capacity=5, available_agents=5)

    assert authorized == 0


def test_authorize_capacity_rejects_non_positive_request():

    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=10)

    assert safety.authorize_capacity(requested_capacity=0, available_agents=5) == 0
    assert safety.authorize_capacity(requested_capacity=-3, available_agents=5) == 0


def test_authorize_capacity_falls_back_to_progressive_when_degraded():

    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=10)
    safety.trip_safety_fallback()

    # Pacing engine wants an aggressive overdial (10), but only 3 agents
    # are actually free -- degraded mode must clamp to available_agents.
    authorized = safety.authorize_capacity(requested_capacity=10, available_agents=3)

    assert authorized == 3


def test_clear_safety_fallback_restores_normal_authorization():

    safety = SafetyController(max_global_concurrency=10, max_campaign_concurrency=10)
    safety.trip_safety_fallback()
    safety.clear_safety_fallback()

    authorized = safety.authorize_capacity(requested_capacity=10, available_agents=3)

    assert authorized == 10


def test_authorize_capacity_never_exceeds_request_even_with_huge_headroom():

    safety = SafetyController(max_global_concurrency=1000, max_campaign_concurrency=1000)

    authorized = safety.authorize_capacity(requested_capacity=4, available_agents=100)

    assert authorized == 4

def test_call_is_allowed_under_limits():

    safety = SafetyController(
        max_global_concurrency=10,
        max_campaign_concurrency=5
    )

    assert safety.can_start_call() is True


def test_global_limit_blocks_call():

    safety = SafetyController(
        max_global_concurrency=2,
        max_campaign_concurrency=5
    )

    safety.call_started()
    safety.call_started()

    assert safety.can_start_call() is False


def test_campaign_limit_blocks_call():

    safety = SafetyController(
        max_global_concurrency=10,
        max_campaign_concurrency=2
    )

    safety.call_started()
    safety.call_started()

    assert safety.can_start_call() is False


def test_finished_call_frees_capacity():

    safety = SafetyController(
        max_global_concurrency=2,
        max_campaign_concurrency=2
    )

    safety.call_started()
    safety.call_started()

    assert safety.can_start_call() is False

    safety.call_finished()

    assert safety.can_start_call() is True