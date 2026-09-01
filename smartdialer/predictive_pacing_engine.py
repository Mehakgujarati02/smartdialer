from collections import deque
from dataclasses import dataclass


@dataclass
class PacingDecision:
    """
    A transparent record of one capacity suggestion, kept so the system
    can answer "why did the pacing engine decide to ask for N calls right
    now?" without having to re-derive it after the fact.
    """
    suggested_calls: int
    answer_rate: float
    provider_health: float
    effective_connect_rate: float
    reason: str


class PredictivePacingEngine:
    """
    Suggests how many calls the dialer could start right now, based on
    recent connect performance for this campaign.
 
    Deliberately dependency-free: this class holds no reference to the
    SafetyController, CallAllocator, CallManager, or the telecom
    provider. It cannot place a call, cannot touch agent or borrower
    state, and has no method that could disable or bypass the Safety
    Controller -- it can only ever return a suggested integer. Every
    suggestion this engine makes still has to pass through
    SafetyController.authorize_capacity() before it turns into an actual
    call.
 
    The core idea is standard overdial math: if only `p` fraction of
    dials connect, filling N agent-slots needs roughly N / p dials. `p`
    here is estimated from a rolling window of this campaign's own
    recent outcomes (recent campaign behaviour), scaled down further by
    a rolling provider-health score so a flaky/timing-out provider makes
    the engine more conservative, not more aggressive.
 
    Known limitation: this is a synchronous/batch simulator, not a
    time-stepped one, so this engine has no wall-clock notion of "agents
    that will free up in the next N seconds" -- it only reasons about
    agents that are free *right now* plus calls already ringing. A fully
    time-stepped version would also fold in average call-setup time and
    average talk duration to estimate near-future agent availability;
    the hooks for those exist (see docstring on __init__) but are not
    used in the capacity formula for that reason.
    """

    def __init__(
            self,
            campaign_max_concurrency,
            max_overdial_ratio=2.0,
            window_size=50,
            default_answer_rate=0.4,
            default_provider_health=1.0,
            min_effective_connect_rate=0.05,
    ):
        """
        campaign_max_concurrency: soft ceiling this engine will not
            suggest past. (The Safety Controller enforces the real
            ceiling independently -- this is just the engine being a
            reasonable citizen, not the source of truth.)
        max_overdial_ratio: self-imposed cap of "never suggest more than
            this many dials per available agent", regardless of how bad
            the answer rate looks. A defense-in-depth limit inside the
            pacing engine itself, on top of the Safety Controller.
        window_size: how many recent call outcomes / provider events to
            keep for the rolling answer-rate / provider-health estimate.
            Bounds "recent campaign behaviour" so old data ages out
            instead of a lifetime average slowly going stale.
        default_answer_rate / default_provider_health: used before any
            real data has been observed (cold start).
        """
        self.campaign_max_concurrency = campaign_max_concurrency
        self.max_overdial_ratio = max_overdial_ratio
        self.window_size = window_size
        self.min_effective_connect_rate = min_effective_connect_rate

        self._outcomes = deque(maxlen=window_size)
        self._provider_events = deque(maxlen=window_size)

        self._default_answer_rate = default_answer_rate
        self._default_provider_health = default_provider_health

        self.last_decision = None

    def record_call_outcome(self, answered):
        """Feed back whether a completed call was actually answered."""
        self._outcomes.append(bool(answered))

    def record_provider_event(self, success):
        """Feed back whether the provider handled a call cleanly."""
        self._provider_events.append(bool(success))

    @property
    def answer_rate(self):
        if not self._outcomes:
            return self._default_answer_rate
        return sum(self._outcomes) / len(self._outcomes)

    @property
    def provider_health(self):
        if not self._provider_events:
            return self._default_provider_health
        return sum(self._provider_events) / len(self._provider_events)

    def calculate_capacity(self, available_agents, active_calls, ringing_calls=0):
        """
        available_agents: agents free right now.
        active_calls: calls already in flight for this campaign.
        ringing_calls: calls already dialed but not yet answered -- these
            are already "in the pipeline", so don't dial fresh numbers
            for the same eventual agent slot.
 
        Returns a suggested call count (int). Never negative, never
        larger than max_overdial_ratio * available_agents, never larger
        than remaining campaign headroom. This is only a suggestion --
        the Safety Controller has the final say.
        """

        remaining_campaign_capacity = max(
            0, self.campaign_max_concurrency - active_calls
        )

        if remaining_campaign_capacity <= 0 or available_agents <= 0:
            decision = PacingDecision(
                suggested_calls=0,
                answer_rate=self.answer_rate,
                provider_health=self.provider_health,
                effective_connect_rate=0.0,
                reason=(
                    "no campaign headroom left" if remaining_campaign_capacity <= 0
                    else "no agents currently available"
                )
            )
            self.last_decision = decision
            return 0

        effective_connect_rate = max(
            self.min_effective_connect_rate,
            self.answer_rate * self.provider_health
        )

        raw_dials_needed = available_agents / effective_connect_rate
        raw_suggestion = raw_dials_needed - ringing_calls

        overdial_cap = available_agents * self.max_overdial_ratio

        suggested = int(min(
            max(0.0, raw_suggestion),
            overdial_cap,
            remaining_campaign_capacity
        ))

        reason = (
            f"{available_agents} agent(s) free; recent answer_rate="
            f"{self.answer_rate:.0%}, provider_health={self.provider_health:.0%} "
            f"-> effective connect rate {effective_connect_rate:.0%}; "
            f"need ~{raw_dials_needed:.1f} dials to fill {available_agents} "
            f"agent(s), {ringing_calls} already ringing "
            f"(-> {max(0.0, raw_suggestion):.1f} more needed); "
            f"capped at {self.max_overdial_ratio}x agents "
            f"({overdial_cap:.0f}) and campaign headroom "
            f"({remaining_campaign_capacity}) -> suggesting {suggested}"
        )

        decision = PacingDecision(
            suggested_calls=suggested,
            answer_rate=self.answer_rate,
            provider_health=self.provider_health,
            effective_connect_rate=effective_connect_rate,
            reason=reason
        )
        self.last_decision = decision

        return suggested
 