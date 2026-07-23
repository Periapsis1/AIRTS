"""Minimal WebSocket smoke client for the GameHost WS transport.

Connects to a running ``python main.py --server`` instance, walks the full
handshake (lobby_info -> join -> server_config/lobby_status -> ping/pong ->
start_game -> game_start -> state frames) and prints what it observes. Exits 0
on success (a state frame arrived), 1 otherwise.

Usage: python test/ws_smoke_client.py [ws://127.0.0.1:7778]
"""
from __future__ import annotations

import asyncio
import json
import sys

import websockets


async def main(url: str) -> int:
    seen: set[str] = set()
    got_state = False
    sent_start = False
    player_id = None

    async with websockets.connect(url, max_size=10_000_000) as ws:
        # 1. lobby_info first
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=5.0))
        print("RECV", first.get("msg"), "->", {k: first[k] for k in first if k != "ai_choices"})
        assert first.get("msg") == "lobby_info", f"expected lobby_info, got {first.get('msg')}"
        player_id = first.get("client_player_id")
        assert player_id is not None, "no client_player_id"
        ac = first.get("ai_choices")
        assert ac and ac.get("choices"), "lobby_info missing ai_choices"
        print(f"  player_id={player_id}, ai_choices={len(ac['choices'])} bots")

        # 2. join
        await ws.send(json.dumps({"msg": "join", "player_name": "WSSmoke"}))
        print("SENT join")

        # 3. drive the rest of the handshake
        deadline = asyncio.get_event_loop().time() + 20.0
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            msg = json.loads(raw)
            mtype = msg.get("msg")
            if mtype not in seen:
                seen.add(mtype)
                if mtype == "server_config":
                    cfg = msg.get("config", {})
                    print("RECV server_config -> unit_types:", len(cfg.get("unit_types", {})),
                          "spawnable:", len(cfg.get("spawnable_types", [])))
                elif mtype == "state":
                    print("RECV state -> tick:", msg.get("tick"),
                          "entities:", len(msg.get("entities", [])),
                          "winner:", msg.get("winner"))
                else:
                    print("RECV", mtype)

            if mtype == "ping":
                await ws.send(json.dumps({"msg": "pong", "id": msg.get("id")}))

            # Once we've seen the lobby roster, request a vs-AI game.
            if mtype == "lobby_status" and not sent_start:
                sent_start = True
                opponent = 2 if player_id != 2 else 3
                config = {
                    "width": 800, "height": 600,
                    "obstacle_count": 0, "metal_spots": 0, "time_limit": 1,
                    "player_ai_ids": {str(opponent): "wander"},
                    "player_team": {str(player_id): 1, str(opponent): 2},
                    "enable_t2": False, "fog_of_war": False,
                }
                await ws.send(json.dumps({"msg": "start_game", "config": config}))
                print("SENT start_game", config["player_team"])

            if mtype == "state":
                got_state = True
                # grab a couple of frames then stop
                if msg.get("tick", 0) > 0:
                    break

    print("\nSEEN:", sorted(seen))
    print("RESULT:", "PASS" if got_state else "FAIL")
    return 0 if got_state else 1


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:7778"
    sys.exit(asyncio.run(main(url)))
