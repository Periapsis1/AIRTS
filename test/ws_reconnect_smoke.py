"""Smoke test for the WS mid-game reconnect path.

Connects to a running ``python main.py --server`` instance, joins, starts a
vs-AI game, waits for state frames, then abruptly drops the socket and
reconnects with the session token. Passes if the server rebinds the same
player_id and state frames resume on the new socket.

Usage: python test/ws_reconnect_smoke.py [ws://127.0.0.1:7778]
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets


async def recv_until(ws, want: str, timeout: float = 10.0, pong: bool = True) -> dict:
    """Receive until a message of type *want* arrives (answering pings)."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        msg = json.loads(raw)
        mtype = msg.get("msg")
        if pong and mtype == "ping":
            await ws.send(json.dumps({"msg": "pong", "id": msg.get("id")}))
        if mtype == want:
            return msg
    raise TimeoutError(f"never received {want}")


async def main(url: str) -> int:
    # -- phase 1: fresh connect, join, start a game, see state frames --------
    ws = await websockets.connect(url, max_size=10_000_000)
    info = await recv_until(ws, "lobby_info")
    player_id = info["client_player_id"]
    print(f"[1] lobby_info: player_id={player_id}")

    await ws.send(json.dumps({"msg": "join", "player_name": "ReconnectSmoke"}))
    session = await recv_until(ws, "session")
    token = session.get("token", "")
    assert token, "no reconnect token in session message"
    print(f"[1] session token: {token[:8]}…")

    await recv_until(ws, "lobby_status")
    opponent = 2 if player_id != 2 else 3
    config = {
        "width": 800, "height": 600,
        "obstacle_count": 0, "metal_spots": 0, "time_limit": 5,
        "player_ai_ids": {str(opponent): "wander"},
        "player_team": {str(player_id): 1, str(opponent): 2},
        "enable_t2": False, "fog_of_war": False,
    }
    await ws.send(json.dumps({"msg": "start_game", "config": config}))
    await recv_until(ws, "game_start")
    print("[1] game_start received")

    # Wait past the ~3s warp-in hold so ticks are actually advancing.
    tick_before = 0
    while tick_before <= 0:
        state = await recv_until(ws, "state")
        tick_before = state.get("tick", 0)
    print(f"[1] state frame: tick={tick_before}")

    # -- phase 2: abrupt drop (no clean close handshake needed; close() is
    # the only way websockets exposes teardown, and the server treats any
    # socket death identically) ----------------------------------------------
    await ws.close()
    print("[2] socket dropped mid-game")
    await asyncio.sleep(1.0)

    # -- phase 3: reconnect with the token ------------------------------------
    ws2 = await websockets.connect(url, max_size=10_000_000)
    info2 = await recv_until(ws2, "lobby_info")
    print(f"[3] lobby_info on reconnect: player_id={info2['client_player_id']}")
    await ws2.send(json.dumps({
        "msg": "join",
        "player_name": "ReconnectSmoke",
        "reconnect_token": token,
    }))

    # The server re-sends lobby_info with our real id after rebinding.
    rebind = await recv_until(ws2, "lobby_info")
    assert rebind["client_player_id"] == player_id, (
        f"rebound to wrong slot: {rebind['client_player_id']} != {player_id}"
    )
    print(f"[3] rebound to player_id={rebind['client_player_id']}")

    tick_after = 0
    while tick_after <= tick_before:
        state2 = await recv_until(ws2, "state", timeout=15.0)
        tick_after = state2.get("tick", 0)
    print(f"[3] state frame after reconnect: tick={tick_after}")
    assert tick_after > tick_before, "game did not advance across reconnect"

    await ws2.close()
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:7778"
    sys.exit(asyncio.run(main(url)))
