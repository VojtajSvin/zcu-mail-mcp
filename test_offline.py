"""Offline test MCP serveru přes stdio: nástroje, anotace a potvrzování. Síť ani heslo nepotřebuje.

Spuštění: python test_offline.py (v prostředí, kde je nainstalovaný tento balíček).
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp_types import ElicitResult

SERVER = StdioServerParameters(command=str(Path(sys.executable).parent / "zcu-mail-mcp"),
                               env={"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]})  # bez ZCU_USER/PASSWORD
NO_CREDS = "Chybí ZCU_USER"


def text(result) -> str:
    return " ".join(c.text for c in result.content if c.type == "text")


def data(result) -> dict:
    return json.loads(text(result))


async def session(elicit=None, check=None):
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write, elicitation_callback=elicit) as s:
            await s.initialize()
            await check(s)


async def without_elicitation(s):
    tools = {t.name: t for t in (await s.list_tools()).tools}
    assert len(tools) == 11, sorted(tools)
    for t in tools.values():
        a = t.annotations
        print(f"  {t.name:16} read_only={a.read_only_hint!s:5} destructive={a.destructive_hint}")
    assert all(tools[n].annotations.read_only_hint for n in ("list_folders", "list_messages", "search_messages", "read_message"))
    assert all(tools[n].annotations.destructive_hint for n in ("send_message", "reply_message", "forward_message", "move_message"))

    r = await s.call_tool("list_folders", {})
    assert r.is_error and NO_CREDS in text(r), text(r)

    args = {"to": ["jan@zcu.cz"], "subject": "Ahoj", "body": "Příliš žluťoučký kůň"}
    r = await s.call_tool("send_message", args)
    preview = data(r)
    assert not r.is_error and preview["status"].startswith("NÁHLED") and "Komu: jan@zcu.cz" in preview["preview"], r
    token = preview["confirmation_token"]

    r = await s.call_tool("send_message", {**args, "confirmation_token": "0123456789"})
    assert data(r)["status"].startswith("NÁHLED") and "nepatří" in data(r)["next"], r
    r = await s.call_tool("send_message", {**args, "body": "jiný text", "confirmation_token": token})
    assert data(r)["status"].startswith("NÁHLED"), "token platí jen pro stejné parametry"
    r = await s.call_tool("send_message", {**args, "confirmation_token": token})
    assert r.is_error and NO_CREDS in text(r), "se správným tokenem má dojít až na přihlášení"
    print("  bez elicitace: náhled, token a odmítnutí cizího tokenu OK")


def answering(action, provest=None):
    async def elicit(context, params):
        assert "Komu: jan@zcu.cz" in params.message
        return ElicitResult(action=action, content=None if provest is None else {"provest": provest})
    return elicit


async def declined(s):
    r = await s.call_tool("send_message", {"to": ["jan@zcu.cz"], "subject": "Ahoj", "body": "x"})
    assert not r.is_error and "zrušeno" in data(r)["status"], r


async def accepted(s):
    r = await s.call_tool("send_message", {"to": ["jan@zcu.cz"], "subject": "Ahoj", "body": "x"})
    assert r.is_error and NO_CREDS in text(r), text(r)


async def main():
    await session(check=without_elicitation)
    await session(answering("decline"), declined)
    await session(answering("accept", False), declined)
    await session(answering("accept", True), accepted)
    print("  s elicitací: odmítnutí, ne a ano OK\nVše prošlo.")


asyncio.run(main())
