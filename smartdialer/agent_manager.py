import threading

from smartdialer.models import Agent, AgentStatus
from smartdialer.agent_lifecycle import AGENT_VALID_TRANSITIONS


class AgentManager:

    def __init__(self):
        self.agents = {}
        self.lock = threading.Lock()

    def add_agent(self, agent: Agent):
        with self.lock:
            self.agents[agent.id] = agent

    def get_available_agents(self):
        with self.lock:
            return [
                agent
                for agent in self.agents.values()
                if agent.status == AgentStatus.AVAILABLE
            ]

    def reserve_agent(self):
        with self.lock:
            for agent in self.agents.values():

                if agent.status == AgentStatus.AVAILABLE:
                    agent.status = AgentStatus.RESERVED
                    return agent

            return None

    def release_agent(self, agent_id):
        with self.lock:
            agent = self.agents.get(agent_id)

            if agent is None:
                return False

            agent.status = AgentStatus.AVAILABLE
            return True

    def _transition(self, agent_id, new_status):
        """
        Shared enforcement point for the fuller lifecycle states, using
        the table in agent_lifecycle.py. release_agent() above stays
        unconditional on purpose -- see that table's docstring.
        """

        with self.lock:
            agent = self.agents.get(agent_id)

            if agent is None:
                return False

            allowed = AGENT_VALID_TRANSITIONS.get(agent.status, set())

            if new_status not in allowed:
                return False

            agent.status = new_status
            return True

    def mark_dialing(self, agent_id):
        return self._transition(agent_id, AgentStatus.DIALING)

    def mark_connected(self, agent_id):
        return self._transition(agent_id, AgentStatus.CONNECTED)

    def mark_wrap_up(self, agent_id):
        return self._transition(agent_id, AgentStatus.WRAP_UP)

    def pause_agent(self, agent_id):
        return self._transition(agent_id, AgentStatus.PAUSED)

    def resume_agent(self, agent_id):
        return self._transition(agent_id, AgentStatus.AVAILABLE)

    def bring_online(self, agent_id):
        return self._transition(agent_id, AgentStatus.AVAILABLE)

    def set_offline(self, agent_id):
        """
        Returns (success, was_mid_call). was_mid_call is True if the
        agent was bound to an in-flight call (RESERVED/DIALING/
        CONNECTED) at the moment it went offline -- this is the direct
        answer to "what happens when the agent disappears during call
        setup": the manager reports it, and the caller (the dialer, or
        a reconciliation pass) is responsible for failing/reassigning
        that specific call. This manager only tracks agent state; it
        deliberately never reaches into call state itself.
        """

        with self.lock:
            agent = self.agents.get(agent_id)

            if agent is None:
                return False, False

            was_mid_call = agent.status in (
                AgentStatus.RESERVED,
                AgentStatus.DIALING,
                AgentStatus.CONNECTED
            )

            agent.status = AgentStatus.OFFLINE
            return True, was_mid_call