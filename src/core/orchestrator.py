from src.agents.office_agent import OfficeAgent
from src.core.config import COMPANY_CONFIG, get_api_key_for_company
from src.tools.lexoffice import LexofficeTool, create_lexoffice_tools


class Orchestrator:
    """Routes tasks to the appropriate agent based on company context."""

    def __init__(self):
        self._agents: dict[str, OfficeAgent] = {}
        self._default_agent = OfficeAgent(tools=LexofficeTool.tools)

    def _get_agent(self, company_key: str | None) -> OfficeAgent:
        if not company_key:
            return self._default_agent
        if company_key not in self._agents:
            api_key = get_api_key_for_company(company_key)
            tools = create_lexoffice_tools(api_key)
            company_name = COMPANY_CONFIG[company_key]["name"]
            self._agents[company_key] = OfficeAgent(tools=tools, company_name=company_name)
        return self._agents[company_key]

    def run(self, message: str, company_key: str | None = None) -> str:
        """Process a user message and return the agent's response."""
        return self._get_agent(company_key).run(message)
