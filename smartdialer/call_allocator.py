from smartdialer.models import Call, CallStatus


class CallAllocator:

    def __init__(self, agent_manager, borrower_manager):
        self.agent_manager = agent_manager
        self.borrower_manager = borrower_manager
        self.call_counter = 0

    def allocate_call(self):

        borrower = self.borrower_manager.reserve_borrower()

        if borrower is None:
            return None

        agent = self.agent_manager.reserve_agent()

        if agent is None:
            # No agent available.
            # Release the borrower so it can be tried again later.
            self.borrower_manager.release_borrower(borrower.id)
            return None

        self.call_counter += 1

        call = Call(
            id=f"C{self.call_counter}",
            agent_id=agent.id,
            borrower_id=borrower.id,
            status=CallStatus.RESERVED
        )

        return call

    def allocate_unbound_call(self):
        """
        Predictive-dialing allocation: reserves a borrower and creates a
        Call with no agent bound yet. Used when the pacing engine wants
        to dial more numbers than there are agents free right now,
        betting that not all of them will be answered. An agent is only
        bound later, at the moment the call is actually answered -- see
        try_bind_agent(). This is what makes real overdialing possible;
        allocate_call() above always ties up an agent immediately, which
        caps launches at 1-per-agent no matter what the pacing engine
        asks for.
        """

        borrower = self.borrower_manager.reserve_borrower()

        if borrower is None:
            return None

        self.call_counter += 1

        return Call(
            id=f"C{self.call_counter}",
            agent_id=None,
            borrower_id=borrower.id,
            status=CallStatus.RESERVED
        )

    def try_bind_agent(self, call):
        """
        Attempt to bind a free agent to a call that's just been answered
        but has no agent yet (an overdialed predictive call). Returns
        True and sets call.agent_id if an agent was available; returns
        False if not -- the caller (the dialer) is responsible for
        deciding what an unbound answer means, e.g. marking the call
        ABANDONED. This method only ever tries to reserve an agent for a
        call that is already answered; it never places or influences the
        call itself.
        """

        agent = self.agent_manager.reserve_agent()

        if agent is None:
            return False

        call.agent_id = agent.id
        return True