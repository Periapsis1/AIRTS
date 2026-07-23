"""Prove a TCP (desktop) client and a WS (browser) client coexist on one server.

Connects one of each concurrently, sends join from both, and asserts that a
single lobby_status lists BOTH players — confirming the shared _clients dict
and cross-transport player_id allocation. Also confirms the TCP path still
speaks the unchanged length-prefixed protocol.

Usage: python test/coexist_smoke.py  (server must be running on 7777/7778)
"""
from __future__ import annotations

import asyncio
import json

import websockets

from networking.protocol import send_message, recv_message


async def tcp_client(names: dict, results: dict) -> None:
    reader, writer = await asyncio.open_connection("127.0.0.1", 7777)
    info = await recv_message(reader)
    assert info["msg"] == "lobby_info", info
    names["tcp"] = info["client_player_id"]
    await send_message(writer, {"msg": "join", "player_name": "TCPClient"})
    # read a few messages, capture the largest roster we see
    for _ in range(8):
        try:
            msg = await asyncio.wait_for(recv_message(reader), timeout=2.0)
        except asyncio.TimeoutError:
            break
        if msg and msg.get("msg") == "lobby_status":
            results["tcp_roster"] = msg["players"]
    writer.close()


async def ws_client(names: dict, results: dict) -> None:
    async with websockets.connect("ws://127.0.0.1:7778") as ws:
        info = json.loads(await ws.recv())
        assert info["msg"] == "lobby_info", info
        names["ws"] = info["client_player_id"]
        await ws.send(json.dumps({"msg": "join", "player_name": "WSClient"}))
        for _ in range(8):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            if msg.get("msg") == "ping":
                await ws.send(json.dumps({"msg": "pong", "id": msg.get("id")}))
            if msg.get("msg") == "lobby_status":
                results["ws_roster"] = msg["players"]


async def run() -> int:
    names: dict = {}
    results: dict = {}
    await asyncio.gather(tcp_client(names, results), ws_client(names, results))
    print("player_ids:", names)
    tcp_roster = results.get("tcp_roster", {})
    ws_roster = results.get("ws_roster", {})
    print("tcp saw roster:", tcp_roster)
    print("ws  saw roster:", ws_roster)
    # Success: at least one client saw BOTH players in the roster.
    both = max(len(tcp_roster), len(ws_roster))
    ok = both >= 2 and names.get("tcp") != names.get("ws")
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(run()))
