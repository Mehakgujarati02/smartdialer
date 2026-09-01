import threading


class SafetyController:

    def __init__(
            self,
            max_global_concurrency,
            max_campaign_concurrency
    ):
        self.max_global_concurrency = max_global_concurrency
        self.max_campaign_concurrency = max_campaign_concurrency

        self.active_global_calls = 0
        self.active_campaign_calls = 0

        # When True, the predictive pacing engine's requests are clamped
        # down to progressive (1 dial per available agent) behaviour,
        # regardless of what it asked for. This is the "fall back to
        # progressive behaviour" lever from the assignment. Only this
        # controller can set it -- the pacing engine has no reference to
        # this object and cannot flip it.
        self.degraded = False

        self.lock = threading.Lock()

    def can_start_call(self):

        with self.lock:

            if self.active_global_calls >= self.max_global_concurrency:
                return False

            if self.active_campaign_calls >= self.max_campaign_concurrency:
                return False

            return True

    def call_started(self):

        with self.lock:
            self.active_global_calls += 1
            self.active_campaign_calls += 1

    def call_finished(self):

        with self.lock:

            if self.active_global_calls > 0:
                self.active_global_calls -= 1

            if self.active_campaign_calls > 0:
                self.active_campaign_calls -= 1

    def authorize_capacity(self, requested_capacity, available_agents):
        """
        The single choke point between a pacing engine's *suggestion* and
        calls actually being allocated. The pacing engine only ever gets
        to ask; this method is what actually decides. It can:

          - approve the request in full,
          - reduce it (hard concurrency ceilings, or degraded mode),
          - reject it outright (return 0),
          - fall back to progressive-style 1:1 pacing (degraded mode).

        `available_agents` is passed in explicitly rather than fetched
        from an agent manager reference, so this stays a pure function of
        its own counters plus whatever the caller tells it -- easy to
        unit test, and it can't reach into other components to do
        anything beyond what its two concurrency ceilings allow.
        """

        with self.lock:

            if requested_capacity <= 0:
                return 0

            global_headroom = max(
                0, self.max_global_concurrency - self.active_global_calls
            )

            campaign_headroom = max(
                0, self.max_campaign_concurrency - self.active_campaign_calls
            )

            authorized = min(
                requested_capacity,
                global_headroom,
                campaign_headroom
            )

            if self.degraded:
                # Progressive fallback: never authorize more speculative
                # calls than there are agents free to actually take them.
                authorized = min(authorized, available_agents)

            return max(0, authorized)

    def trip_safety_fallback(self):
        """
        Force predictive pacing into progressive-only behaviour. Intended
        to be called by campaign monitoring when something looks wrong
        (e.g. answer rate collapses, provider starts erroring) -- not by
        the pacing engine itself.
        """

        with self.lock:
            self.degraded = True

    def clear_safety_fallback(self):

        with self.lock:
            self.degraded = False