
"""ConsentGuard MCP Server — Stage 4.

Tools:
    search_records(patient_id, query, top_k)
    summarize(retrieval_id)

Security:
    - Strict validation of raw MCP arguments.
    - Trusted principal is never accepted from tool arguments.
    - All operations pass through the Security Gateway.
    - Summarization rechecks record-level consent.

Run:
    python mcp_server.py

Local controlled-identity prototype only.
Not production authentication.
"""

import json
import os

from mcp import types
from mcp.server.fastmcp import FastMCP

from security_gateway import SecurityGateway, TrustedSession


# ---------------------------------------------------------
# 1. Trusted session and Security Gateway
# ---------------------------------------------------------

def build_gateway() -> SecurityGateway:
    principal = os.environ.get(
        "CONSENTGUARD_TEST_PRINCIPAL",
        "P01"
    )

    return SecurityGateway(
        TrustedSession(principal_id=principal)
    )


gateway = build_gateway()

mcp = FastMCP("ConsentGuard")


# ---------------------------------------------------------
# 2. MCP Tool: Search
# ---------------------------------------------------------

@mcp.tool()
def search_records(
    patient_id: str,
    query: str,
    top_k: int = 5
) -> dict:
    """Search clinical records permitted by the consent policy."""

    return gateway.execute(
        "search_records",
        {
            "patient_id": patient_id,
            "query": query,
            "top_k": top_k,
        },
    )


# ---------------------------------------------------------
# 3. MCP Tool: Summarize
# ---------------------------------------------------------

@mcp.tool()
def summarize(retrieval_id: str) -> dict:
    """Summarize records from a previously authorized search.

    The retrieval_id is issued by the Security Gateway.
    Consent is revalidated before excerpts are returned.
    """

    return gateway.execute(
        "summarize",
        {
            "retrieval_id": retrieval_id,
        },
    )


# ---------------------------------------------------------
# 4. Strict MCP argument validation
# ---------------------------------------------------------

TOOL_SCHEMAS = {
    "search_records": {
        "allowed": frozenset({
            "patient_id",
            "query",
            "top_k",
        }),
        "required": frozenset({
            "patient_id",
            "query",
        }),
    },
    "summarize": {
        "allowed": frozenset({
            "retrieval_id",
        }),
        "required": frozenset({
            "retrieval_id",
        }),
    },
}


def install_strict_argument_validation() -> None:
    """Validate raw arguments before FastMCP binds parameters.

    Uses an internal MCP SDK 1.x request-handler interface.
    The server fails at startup if the expected handler is absent.
    """

    server = mcp._mcp_server

    original = server.request_handlers.get(
        types.CallToolRequest
    )

    if original is None:
        raise RuntimeError(
            "Cannot install MCP tool-call validation handler"
        )

    async def strict_call_tool(request):
        params = request.params
        name = params.name
        arguments = params.arguments

        schema = TOOL_SCHEMAS.get(name)

        valid = (
            schema is not None
            and isinstance(arguments, dict)
            and schema["required"].issubset(arguments)
            and not (set(arguments) - schema["allowed"])
        )

        if not valid:
            denied = {
                "status": "denied",
                "reason": "Invalid MCP tool name or arguments",
                "results": [],
            }

            return types.ServerResult(
                types.CallToolResult(
                    content=[
                        types.TextContent(
                            type="text",
                            text=json.dumps(denied),
                        )
                    ],
                    isError=True,
                )
            )

        return await original(request)

    server.request_handlers[
        types.CallToolRequest
    ] = strict_call_tool


install_strict_argument_validation()


# ---------------------------------------------------------
# 5. Start MCP server
# ---------------------------------------------------------

if __name__ == "__main__":
    # stdout is reserved for MCP protocol communication.
    mcp.run(transport="stdio")
