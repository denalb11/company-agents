import argparse

from dotenv import load_dotenv

load_dotenv()

from src.core.orchestrator import Orchestrator


def run_cli(orchestrator: Orchestrator) -> None:
    from src.core.config import get_company_for_prefix
    print("Company Agents - Multi-Agent System")
    print("Prefix: ms: / dp: / nao: / sv:  |  'exit' to quit.\n")

    history: list[tuple[str, str]] = []
    current_company: str | None = None

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        detected_company, message = get_company_for_prefix(user_input)
        if detected_company:
            current_company = detected_company  # switch company on new prefix

        text, pdf_paths = orchestrator.run(message, company_key=current_company, history=history)
        history.append((message, text))

        print(f"Agent: {text}")
        if pdf_paths:
            print(f"PDFs: {', '.join(pdf_paths)}")
        print()


def run_teams(orchestrator: Orchestrator) -> None:
    from src.interfaces.teams_bot import start_teams_server

    start_teams_server(orchestrator)


def main() -> None:
    parser = argparse.ArgumentParser(description="Company Agents - Multi-Agent System")
    parser.add_argument(
        "--teams",
        action="store_true",
        help="Start the Teams bot server on port 3978 instead of the CLI.",
    )
    args = parser.parse_args()

    orchestrator = Orchestrator()

    if args.teams:
        run_teams(orchestrator)
    else:
        run_cli(orchestrator)


if __name__ == "__main__":
    main()
