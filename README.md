# Company Agents

A company multi-agent system built with [LangGraph](https://github.com/langchain-ai/langgraph) and [Claude](https://www.anthropic.com/claude) (Anthropic).

## Overview

This system uses a multi-agent architecture to automate internal company workflows. An orchestrator routes tasks to specialized agents that interact with business tools such as Lexoffice.

## Project Structure

```
company-agents/
├── src/
│   ├── agents/         # Specialized agents
│   │   └── office_agent.py
│   ├── tools/          # Tool integrations (APIs, services)
│   │   └── lexoffice.py
│   └── core/           # Orchestration logic
│       └── orchestrator.py
├── main.py             # Entry point
├── requirements.txt
├── .env.example
└── README.md
```

## Setup

1. Clone the repository and create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and fill in your API keys:
   ```bash
   cp .env.example .env
   ```

4. Run the system:
   ```bash
   python main.py
   ```

## Agents

- **OfficeAgent** — Handles administrative and accounting tasks via Lexoffice.

## Tools

- **Lexoffice** — Fetches contacts and invoices from the Lexoffice API.
