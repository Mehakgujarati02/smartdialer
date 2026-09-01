class PacingEngine:

    def __init__(self, agent_manager, campaign_max_concurrency):
        self.agent_manager = agent_manager
        self.campaign_max_concurrency = campaign_max_concurrency

    def calculate_capacity(self, active_calls):

        available_agents = len(
            self.agent_manager.get_available_agents()
        )

        agent_capacity = available_agents

        remaining_campaign_capacity = (
                self.campaign_max_concurrency - active_calls
        )

        if remaining_campaign_capacity <= 0:
            return 0

        return min(
            agent_capacity,
            remaining_campaign_capacity
        )