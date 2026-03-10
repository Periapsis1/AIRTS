"""Wire protocol helpers for multiplayer networking.

Message format: [4-byte big-endian length][JSON payload]
Optionally zlib-compressed for large payloads.
"""
from __future__ import annotations

import asyncio
import json
import struct
import zlib

DEFAULT_PORT = 7777
COMPRESS_THRESHOLD = 1024  # bytes — compress payloads larger than this

_HEADER = struct.Struct("!I")  # 4 bytes, big-endian unsigned int


async def send_message(writer: asyncio.StreamWriter, data: dict) -> None:
    """Serialize *data* as JSON, optionally compress, and send with length prefix."""
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    if len(raw) > COMPRESS_THRESHOLD:
        compressed = zlib.compress(raw, level=1)
        # Only use compression if it actually shrinks the payload
        if len(compressed) < len(raw):
            raw = b"Z" + compressed  # 'Z' prefix signals zlib
    payload = _HEADER.pack(len(raw)) + raw
    writer.write(payload)
    await writer.drain()


async def recv_message(reader: asyncio.StreamReader) -> dict | None:
    """Read a length-prefixed message and return the decoded dict, or None on EOF."""
    header = await reader.readexactly(4)
    if not header:
        return None
    length = _HEADER.unpack(header)[0]
    if length > 10_000_000:  # sanity limit: 10 MB
        raise ValueError(f"Message too large: {length} bytes")
    raw = await reader.readexactly(length)
    if raw[:1] == b"Z":
        raw = zlib.decompress(raw[1:])
    return json.loads(raw.decode("utf-8"))
