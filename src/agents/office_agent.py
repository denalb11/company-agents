import re
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from src.tools.lexoffice import get_contacts, get_invoices, get_purchase_invoices, upload_document

SYSTEM_PROMPT = "You are a helpful office assistant. You have access to the following tools: get_contacts, get_invoices, get_purchase_invoices, and upload_document. Always use the upload_document tool when the user wants to upload a file."

DEFAULT_TOOLS = [get_contacts, get_invoices, get_purchase_invoices, upload_document]


class _PDFCapturingCallback(BaseCallbackHandler):
    """Captures PDF_READY markers emitted by tools before the LLM can rewrite them."""

    def __init__(self):
        self.pdf_paths: list[str] = []

    def on_tool_end(self, output, **kwargs):
        if isinstance(output, str):
            self.pdf_paths.extend(re.findall(r"PDF_READY:(\S+\.pdf)", output))


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
        callback = _PDFCapturingCallback()
        result = self.agent.invoke(
            {"messages": [("user", message)]},
            config={"callbacks": [callback]},
        )
        text = result["messages"][-1].content
        return text, callback.pdf_paths
