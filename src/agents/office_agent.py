import re
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage
from langgraph.prebuilt import create_react_agent

from src.tools.lexoffice import LexofficeTool

SYSTEM_PROMPT = "You are a helpful office assistant with full access to Lexoffice. Use the available tools to answer questions and perform tasks. Always use the upload_document tool when the user wants to upload a file."

DEFAULT_TOOLS = LexofficeTool.get_tools()


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

    def run(self, message: str, history: list[tuple[str, str]] | None = None) -> tuple[str, list[str]]:
        """Returns (agent_text_response, list_of_pdf_paths).

        Args:
            message: The current user message.
            history: Optional list of (user_msg, assistant_msg) tuples from prior turns.
        """
        messages = []
        for user_msg, assistant_msg in (history or []):
            messages.append(("user", user_msg))
            messages.append(("assistant", assistant_msg))
        messages.append(("user", message))

        result = self.agent.invoke({"messages": messages})
        text = result["messages"][-1].content
        # Scan ToolMessages for PDF_READY markers, deduplicated
        seen = set()
        pdf_paths = []
        for msg in result["messages"]:
            msg_type = getattr(msg, "type", None)
            # Extract text content regardless of format
            raw = msg.content
            if isinstance(raw, str):
                content = raw
            elif isinstance(raw, list):
                content = " ".join(
                    b if isinstance(b, str) else b.get("text", "") if isinstance(b, dict) else ""
                    for b in raw
                )
            else:
                content = ""
            import logging as _log
            _log.getLogger(__name__).debug("msg type=%s content_preview=%s", msg_type, content[:120])
            if "PDF_READY:" in content:
                _log.getLogger(__name__).info("PDF_READY found in msg type=%s", msg_type)
                for p in re.findall(r"PDF_READY:(\S+\.pdf)", content):
                    if p not in seen:
                        seen.add(p)
                        pdf_paths.append(p)
        return text, pdf_paths
