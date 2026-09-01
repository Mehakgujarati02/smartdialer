from smartdialer.predictive_pacing_engine import PredictivePacingEngine


def test_cold_start_uses_default_answer_rate():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=100,
        default_answer_rate=0.5,
        default_provider_health=1.0,
        max_overdial_ratio=5.0
    )

    # No history yet -> falls back to default_answer_rate (0.5), so it
    # should suggest roughly 2x the available agents (1 / 0.5).
    suggested = engine.calculate_capacity(available_agents=2, active_calls=0)

    assert suggested == 4


def test_no_available_agents_suggests_zero():

    engine = PredictivePacingEngine(campaign_max_concurrency=100)

    suggested = engine.calculate_capacity(available_agents=0, active_calls=0)

    assert suggested == 0
    assert "no agents" in engine.last_decision.reason


def test_no_campaign_headroom_suggests_zero():

    engine = PredictivePacingEngine(campaign_max_concurrency=5)

    suggested = engine.calculate_capacity(available_agents=3, active_calls=5)

    assert suggested == 0
    assert "headroom" in engine.last_decision.reason


def test_low_answer_rate_increases_overdial_suggestion():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=1000,
        max_overdial_ratio=10.0
    )

    for _ in range(20):
        engine.record_call_outcome(answered=False)
    for _ in range(5):
        engine.record_call_outcome(answered=True)
    # answer_rate = 5/25 = 0.2

    suggested = engine.calculate_capacity(available_agents=2, active_calls=0)

    # 2 agents / 0.2 answer_rate = 10 dials needed
    assert suggested == 10


def test_high_answer_rate_suggests_close_to_1_to_1():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=1000,
        max_overdial_ratio=10.0
    )

    for _ in range(19):
        engine.record_call_outcome(answered=True)
    engine.record_call_outcome(answered=False)
    # answer_rate = 19/20 = 0.95

    suggested = engine.calculate_capacity(available_agents=10, active_calls=0)

    assert suggested == 10  # 10 / 0.95 = 10.5 -> int() truncates to 10


def test_poor_provider_health_reduces_effective_connect_rate():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=1000,
        max_overdial_ratio=10.0,
        default_answer_rate=0.5
    )

    for _ in range(10):
        engine.record_provider_event(success=False)
    # provider_health = 0.0 -> effective_connect_rate floors at
    # min_effective_connect_rate

    suggested = engine.calculate_capacity(available_agents=1, active_calls=0)

    assert suggested == engine.max_overdial_ratio * 1  # capped by overdial ratio


def test_overdial_ratio_caps_suggestion_regardless_of_answer_rate():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=1000,
        max_overdial_ratio=1.5,
        default_answer_rate=0.01  # would otherwise suggest 100x
    )

    suggested = engine.calculate_capacity(available_agents=4, active_calls=0)

    assert suggested == 6  # 4 * 1.5


def test_campaign_headroom_caps_suggestion():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=5,
        max_overdial_ratio=10.0,
        default_answer_rate=0.1  # would otherwise suggest ~50
    )

    suggested = engine.calculate_capacity(available_agents=5, active_calls=2)

    assert suggested == 3  # remaining campaign headroom = 5 - 2


def test_ringing_calls_are_not_double_counted():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=1000,
        max_overdial_ratio=10.0,
        default_answer_rate=0.5
    )

    with_no_ringing = engine.calculate_capacity(
        available_agents=4, active_calls=0, ringing_calls=0
    )
    with_ringing = engine.calculate_capacity(
        available_agents=4, active_calls=0, ringing_calls=3
    )

    assert with_no_ringing == 8       # 4 / 0.5
    assert with_ringing == 5          # 8 - 3 already in flight


def test_rolling_window_ages_out_old_outcomes():

    engine = PredictivePacingEngine(
        campaign_max_concurrency=1000,
        window_size=5,
        max_overdial_ratio=10.0
    )

    for _ in range(5):
        engine.record_call_outcome(answered=False)

    assert engine.answer_rate == 0.0

    for _ in range(5):
        engine.record_call_outcome(answered=True)

    # Window size 5 -> only the 5 most recent (all True) should remain
    assert engine.answer_rate == 1.0


def test_last_decision_is_recorded_for_explainability():

    engine = PredictivePacingEngine(campaign_max_concurrency=100)

    engine.calculate_capacity(available_agents=3, active_calls=0)

    assert engine.last_decision is not None
    assert engine.last_decision.suggested_calls >= 0
    assert isinstance(engine.last_decision.reason, str)
    assert len(engine.last_decision.reason) > 0
