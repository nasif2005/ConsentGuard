
"""ConsentGuard Stage 4: MCP integration and security tests.

Run:
    python test_mcp_client.py

Requires:
    mcp_server.py
    security_gateway.py
    secure_retrieval.py
    consentguard_v2.py
    consentguard_v2.db
    chroma_storage/
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


ROOT = Path(__file__).resolve().parent
SERVER = ROOT / "mcp_server.py"


def parse_result(result):
    """Extract the gateway dictionary from an MCP tool response."""

    structured = getattr(result, "structuredContent", None)

    if isinstance(structured, dict):
        # Some MCP SDK versions wrap the return value.
        if isinstance(structured.get("result"), dict):
            return structured["result"]

        return structured

    for item in getattr(result, "content", []):
        if getattr(item, "type", None) == "text":
            try:
                parsed = json.loads(item.text)

                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass

    return {}


def report(name, passed, detail=None):
    status = "PASS" if passed else "FAIL"
    print(f"{status}: {name}")

    if detail is not None:
        print(f"  Detail: {detail}")

    return passed


async def main():
    if not SERVER.is_file():
        print("ERROR: mcp_server.py not found")
        return

    # Controlled test identity. This is not authentication.
    env = os.environ.copy()
    env["CONSENTGUARD_TEST_PRINCIPAL"] = "P01"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER)],
        cwd=str(ROOT),
        env=env,
    )

    results = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("MCP connection: established")

            tools_response = await session.list_tools()
            tool_names = [tool.name for tool in tools_response.tools]

            print("Available tools:", tool_names)

            results.append(report(
                "Both MCP tools available",
                {"search_records", "summarize"}.issubset(
                    set(tool_names)
                ),
            ))

            # -------------------------------------------------
            # Test 1: Authorized search
            # -------------------------------------------------

            search_result = await session.call_tool(
                "search_records",
                arguments={
                    "patient_id": "P01",
                    "query": "medication changes",
                    "top_k": 3,
                },
            )

            search_data = parse_result(search_result)

            print(
                "Authorized search status:",
                search_data.get("status")
            )
            print(
                "Authorized result count:",
                search_data.get("count")
            )

            records = search_data.get("results", [])
            record_ids = [
                item.get("record_id")
                for item in records
                if isinstance(item, dict)
            ]

            print("Record IDs:", record_ids)

            search_ok = (
                not search_result.isError
                and search_data.get("status") == "ok"
                and isinstance(records, list)
                and len(records) == 3
                and len(record_ids) == 3
            )

            results.append(report(
                "Authorized MCP retrieval",
                search_ok,
            ))

            retrieval_id = search_data.get("retrieval_id")

            # -------------------------------------------------
            # Test 2: Summarize authorized retrieval
            # -------------------------------------------------

            if search_ok and isinstance(retrieval_id, str):
                summary_result = await session.call_tool(
                    "summarize",
                    arguments={
                        "retrieval_id": retrieval_id
                    },
                )

                summary_data = parse_result(summary_result)

                print(
                    "Summarize status:",
                    summary_data.get("status")
                )
                print(
                    "Summarize count:",
                    summary_data.get("count")
                )

                excerpts = summary_data.get("excerpts", [])

                summary_record_ids = [
                    item.get("record_id")
                    for item in excerpts
                    if isinstance(item, dict)
                ]

                print(
                    "Summarized record IDs:",
                    summary_record_ids
                )

                summary_ok = (
                    not summary_result.isError
                    and summary_data.get("status") == "ok"
                    and summary_data.get("count") == 3
                    and len(excerpts) == 3
                    and set(summary_record_ids) == set(record_ids)
                )

                results.append(report(
                    "Authorized MCP summarization",
                    summary_ok,
                ))
            else:
                results.append(report(
                    "Authorized MCP summarization",
                    False,
                    "No valid retrieval_id from search",
                ))

            # -------------------------------------------------
            # Test 3: Search principal spoofing
            # -------------------------------------------------

            spoof_search = await session.call_tool(
                "search_records",
                arguments={
                    "patient_id": "P01",
                    "query": "medication",
                    "top_k": 3,
                    "principal_id": "HP0006",
                },
            )

            spoof_search_data = parse_result(spoof_search)

            results.append(report(
                "Search rejects unexpected principal_id",
                bool(spoof_search.isError)
                and spoof_search_data.get("status") == "denied",
            ))

            # -------------------------------------------------
            # Test 4: Summarize principal spoofing
            # -------------------------------------------------

            if isinstance(retrieval_id, str):
                spoof_summary = await session.call_tool(
                    "summarize",
                    arguments={
                        "retrieval_id": retrieval_id,
                        "principal_id": "HP0006",
                    },
                )

                spoof_summary_data = parse_result(spoof_summary)

                results.append(report(
                    "Summarize rejects unexpected principal_id",
                    bool(spoof_summary.isError)
                    and spoof_summary_data.get("status") == "denied",
                ))
            else:
                results.append(report(
                    "Summarize rejects unexpected principal_id",
                    False,
                    "No valid retrieval_id",
                ))

            # -------------------------------------------------
            # Test 5: Invalid retrieval reference
            # -------------------------------------------------

            invalid_summary = await session.call_tool(
                "summarize",
                arguments={
                    "retrieval_id": "invalid-retrieval-reference"
                },
            )

            invalid_data = parse_result(invalid_summary)

            results.append(report(
                "Invalid retrieval_id denied",
                invalid_data.get("status") == "denied"
                and not invalid_data.get("excerpts"),
            ))

            # -------------------------------------------------
            # Final result
            # -------------------------------------------------

            print()
            print("=" * 45)
            print(
                f"Stage 4 MCP tests: "
                f"{sum(results)}/{len(results)} passed"
            )
            print("=" * 45)

            if not all(results):
                sys.exit_code = 1


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(
            "MCP integration failed:",
            type(exc).__name__,
            str(exc),
        )
