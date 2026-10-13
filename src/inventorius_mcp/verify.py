"""Read-only deployed protocol check using the official MCP client.

python -m inventorius_mcp.verify https://inventory.computemachines.com/mcp workshop SHA
"""
import asyncio
import json
import sys
from mcp import Client


async def verify(url, environment, revision):
    async with Client(url, mode="legacy", read_timeout_seconds=40) as client:
        tools = (await client.list_tools()).tools
        assert {t.name for t in tools} == {"search_inventory", "get_inventory_item"}
        assert all(t.annotations.read_only_hint and not t.annotations.destructive_hint for t in tools)
        found = await client.call_tool("search_inventory", {"query": "!SKUS", "limit": 1})
        assert not found.is_error
        data = found.structured_content
        assert data["source"]["environment"] == environment
        assert data["source"]["api_revision"] == revision
        assert data["items"], "Need one recorded SKU for the read-only lookup check"
        identity = data["items"][0]["id"]
        detail = await client.call_tool("get_inventory_item", {"item_id": identity, "limit": 1})
        assert not detail.is_error and detail.structured_content["item"]["id"] == identity
        assert detail.structured_content["source"]["environment"] == environment
        empty = await client.call_tool("search_inventory", {"query": "MCPVerificationAbsent_727a6fd9"})
        assert not empty.is_error and empty.structured_content["total"] == 0
        invalid = await client.call_tool("get_inventory_item", {"item_id": "../../auth"})
        assert invalid.is_error
        print(json.dumps({"endpoint": url, "environment": environment, "api_revision": revision,
                          "initialization": "passed", "tools": [t.name for t in tools],
                          "lookup_id": identity, "empty_search": "passed", "invalid_input": "rejected",
                          "chatgpt_account_connection": "not tested"}))


if __name__ == "__main__":
    asyncio.run(verify(*sys.argv[1:]))
