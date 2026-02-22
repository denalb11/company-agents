from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from src.tools.lexoffice import get_contacts, get_invoices, upload_document

SYSTEM_PROMPT = "You are a helpful office assistant. You have access to the following tools: get_contacts, get_invoices, and upload_document. Always use the upload_document tool when the user wants to upload a file."

DEFAULT_TOOLS = [get_contacts, get_invoices, upload_document]


class OfficeAgent:
    """Agent responsible for handling office and administrative tasks."""

    def __init__(self, tools: list = None, model_name: str = "claude-sonnet-4-6"):
        self.llm = ChatAnthropic(model=model_name)
        self.tools = tools if tools is not None else DEFAULT_TOOLS
        self.agent = create_react_agent(
            self.llm,
            self.tools,
            prompt=SystemMessage(content=SYSTEM_PROMPT),
        )

    def run(self, message: str) -> str:
        result = self.agent.invoke({"messages": [("user", message)]})
        return result["messages"][-1].content
