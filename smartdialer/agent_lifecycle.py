from smartdialer.models import AgentStatus


# Single source of truth for legal agent-state moves, shared by the
# in-memory AgentManager and the cross-process PersistentAgentManager so
# the two never drift apart.
#
#   OFFLINE   -- agent not logged in / not working the campaign
#   AVAILABLE -- free, eligible to be reserved for a call
#   RESERVED  -- claimed for a specific call, not dialing yet
#   DIALING   -- provider is actively ringing the borrower for this
#                agent's call (progressive dialing binds the agent
#                before ringing starts, so this state applies there;
#                predictive/overdialed calls only bind an agent once
#                already ANSWERED, so they skip straight from RESERVED
#                to CONNECTED -- see RESERVED's allowed targets below)
#   CONNECTED -- agent is on a live call with the borrower
#   WRAP_UP   -- call just ended, agent finishing after-call work
#                before being eligible for the next call
#   PAUSED    -- agent-initiated break; only reachable from AVAILABLE
#                (an agent can't pause mid-call in this model)
#
# release_agent() (on both managers) is intentionally NOT gated by this
# table -- it always forces AVAILABLE unconditionally, regardless of
# current state, matching its existing (pre-lifecycle) behaviour so
# nothing that already calls it breaks. Everything else funnels through
# this table.
AGENT_VALID_TRANSITIONS = {
    AgentStatus.OFFLINE: {
        AgentStatus.AVAILABLE
    },
    AgentStatus.AVAILABLE: {
        AgentStatus.RESERVED,
        AgentStatus.PAUSED,
        AgentStatus.OFFLINE
    },
    AgentStatus.RESERVED: {
        AgentStatus.DIALING,
        AgentStatus.CONNECTED,   # predictive: agent bound at ANSWERED time
        AgentStatus.AVAILABLE,   # call failed/abandoned before dialing began
        AgentStatus.OFFLINE
    },
    AgentStatus.DIALING: {
        AgentStatus.CONNECTED,
        AgentStatus.WRAP_UP,     # call ended before ever connecting
        AgentStatus.AVAILABLE,
        AgentStatus.OFFLINE
    },
    AgentStatus.CONNECTED: {
        AgentStatus.WRAP_UP,
        AgentStatus.OFFLINE
    },
    AgentStatus.WRAP_UP: {
        AgentStatus.AVAILABLE,
        AgentStatus.OFFLINE
    },
    AgentStatus.PAUSED: {
        AgentStatus.AVAILABLE,
        AgentStatus.OFFLINE
    },
}
