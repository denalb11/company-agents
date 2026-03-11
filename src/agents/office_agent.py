import re
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from src.tools.lexoffice import get_contacts, get_invoices, get_purchase_invoices, upload_document

SYSTEM_PROMPT = "You are a helpful office assistant. You have access to the following tools: get_contacts, get_invoices, get_purchase_invoices, and upload_document. Always use the upload_document tool when the user wants to upload a file."

DEFAULT_TOOLS = [get_contacts, get_invoices, get_purchase_invoices, upload_document]


class OfficeAgent:
    """Agent responsible for handling office and administrative tasks."""

    def __init__(self, tools: list = None, model_name: str = "claude-sonnet-4-6", company_name: str = None):
        self.llm = ChatAnthropic(model=model_name)
        self.tools = tools if tools is not None else DEFAULT_TOOLS
        prompt = SYSTEM_PROMPT
        if company_name:
            prompt += f" Du greifst auf das Lexoffice-Konto von '{company_name}' zu."
        self.agent = create_react_agent(
            self.llm,
            self.tools,
            prompt=SystemMessage(content=prompt),
        )

    def run(self, message: str) -> tuple[str, list[str]]:
        """Returns (agent_text_response, list_of_pdf_paths)."""
        result = self.agent.invoke({"messages": [("user", message)]})
        text = result["messages"][-1].content
        # Scan ToolMessages only (type=="tool") for PDF_READY markers, deduplicated
        seen = set()
        pdf_paths = []
        for msg in result["messages"]:
            if getattr(msg, "type", None) != "tool":
                continue
            content = msg.content if isinstance(msg.content, str) else ""
            for p in re.findall(r"PDF_READY:(\S+\.pdf)", content):
                if p not in seen:
                    seen.add(p)
                    pdf_paths.append(p)
        return text, pdf_paths
