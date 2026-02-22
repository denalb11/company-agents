from src.agents.office_agent import OfficeAgent
from src.tools.lexoffice import LexofficeTool


class Orchestrator:
    """Routes tasks to the appropriate agent."""

    def __init__(self):
        self.office_agent = OfficeAgent(tools=LexofficeTool.tools)

    def run(self, message: str) -> str:
        """Process a user message and return the agent's response."""
        return self.office_agent.run(message)
