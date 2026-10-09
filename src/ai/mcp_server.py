"""A local, read-only MCP server so an AI assistant (Claude Desktop) can
answer questions from Sift's data (docs/kb/features/ai-and-graph.md).

It offers the tools in src/ai/tools.py, acting for one person: the owner
by default, or `--user <email>`. Every call runs in its own database
session that is rolled back, so nothing is ever changed. It talks to the
assistant over stdin and stdout and opens no network port.

Needs the optional package in requirements-ai.txt:

    .venv\\Scripts\\pip install -r requirements-ai.txt

Claude Desktop, claude_desktop_config.json ("mcpServers"):

    "sift": {"command": "C:\\\\Users\\\\you\\\\Portfolio\\\\.venv\\\\Scripts\\\\python.exe",
             "args": ["-m", "src.ai.mcp_server"],
             "cwd": "C:\\\\Users\\\\you\\\\Portfolio"}
"""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import logging
import sys
from typing import Optional

from src import accounts
from src.ai import tools

INSTRUCTIONS = (
    "Sift is the user's ASX value-investing tool. Use these tools to answer from Sift's own data: company facts, "
    "why Sift suggests an action (explain_call), the user's portfolio and watchlists, who holds what, fund overlap, "
    "the screener and the track record. Quote figures as Sift gives them and say where they come from. Sift's "
    "suggested actions are rule-based research prompts, not financial advice; say so when discussing buying or selling."
)
_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list[str]}


def _wrapper(tool: tools.Tool, user_id):
    """A function with the tool's own parameters, as the MCP library reads them from the signature."""
    from mcp.server.mcpserver.exceptions import ToolError as McpToolError

    from src.config import get_session

    def run(**kwargs):
        with get_session() as session, accounts.acting_as(user_id):
            try:
                return tools.call(session, tool.name, kwargs)
            except tools.ToolError as exc:
                raise McpToolError(str(exc)) from None  # shown to the assistant as the answer's error
            finally:
                session.rollback()  # read-only, always

    params, notes = [], {}
    for name, spec in tool.params.items():
        kind = _TYPES[spec["type"]]
        if spec.get("required"):
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=kind))
            notes[name] = kind
        else:
            params.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=Optional[kind],
                                            default=spec.get("default")))
            notes[name] = Optional[kind]
    run.__name__ = tool.name
    run.__doc__ = tool.description
    run.__signature__ = inspect.Signature(params, return_annotation=dict)
    run.__annotations__ = notes | {"return": dict}
    return run


def build_server(user_id):
    """The MCP server with every Sift tool, acting for `user_id`."""
    from mcp.server.mcpserver import MCPServer
    from mcp_types import ToolAnnotations

    from src import version

    server = MCPServer(name="Sift", instructions=INSTRUCTIONS, version=version.VERSION)
    for tool in tools.TOOLS:
        server.add_tool(_wrapper(tool, user_id), name=tool.name, description=tool.description,
                        annotations=ToolAnnotations(title=tool.name.replace("_", " ").capitalize(), readOnlyHint=True,
                                                    destructiveHint=False, idempotentHint=True, openWorldHint=False))
    return server


def resolve_user(email: str | None):
    """The account the server acts for: the owner, or an active account by email."""
    from src.config import get_session

    with get_session() as session:
        user = accounts.find_user(session, email) if email else accounts.owner(session)
        session.commit()
    if user is None or not user.is_active:
        raise SystemExit(f"No active Sift account {email!r}")
    return user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sift's read-only MCP server for AI assistants (stdio).")
    parser.add_argument("--user", help="act for this account's email (default: the owner)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)  # stdout carries the protocol
    if importlib.util.find_spec("mcp") is None:
        print("The MCP package isn't installed: run  pip install -r requirements-ai.txt", file=sys.stderr)
        return 1
    user = resolve_user(args.user)
    print(f"Sift MCP server: acting for {user.display_name}; read-only.", file=sys.stderr)
    build_server(user.user_id).run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
