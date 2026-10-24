"""Authenticated WebSocket relay for YJ-64 remote chat participants.

This server relays chat text only. It does not execute commands or expose host access.
For remote use, configure TLS and connect with wss://; plain ws:// is limited to
loopback by default. Set YJ64_REMOTE_TOKEN to a random secret of at least 24 chars.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import ssl
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

try:
    from websockets.asyncio.server import serve
except ImportError:
    from websockets import serve

PROTOCOL = "yj64.remote-participant.v1"
MAX_MESSAGE_SIZE = 64 * 1024
MAX_CHAT_CHARS = 12_000
AUTH_TIMEOUT_SECONDS = 10
CLIENTS: dict[Any, dict[str, str]] = {}


def packet(kind: str, **fields: Any) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **fields,
    }


async def send_json(ws: Any, value: dict[str, Any]) -> None:
    await ws.send(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


async def close_with_error(ws: Any, code: str, message: str) -> None:
    try:
        await send_json(ws, packet("error", code=code, message=message))
    finally:
        await ws.close()


async def broadcast(value: dict[str, Any], exclude: Any = None) -> None:
    if not CLIENTS:
        return
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    peers = [ws for ws in CLIENTS if ws is not exclude]
    if not peers:
        return
    results = await asyncio.gather(*(ws.send(payload) for ws in peers), return_exceptions=True)
    for ws, result in zip(peers, results):
        if isinstance(result, Exception):
            try:
                await ws.close()
            except Exception:
                pass


async def handler(ws: Any) -> None:
    participant_id = None
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_SECONDS)
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_SIZE:
            await close_with_error(ws, "invalid_packet", "First packet must be a small JSON hello.")
            return
        try:
            hello = json.loads(raw)
        except json.JSONDecodeError:
            await close_with_error(ws, "invalid_json", "Hello packet is not valid JSON.")
            return

        expected_token = os.environ.get("YJ64_REMOTE_TOKEN", "")
        if len(expected_token) < 24:
            await close_with_error(ws, "server_not_configured",
                                   "Server token is not configured; administrator action required.")
            return
        if not isinstance(hello, dict) or hello.get("protocol") != PROTOCOL or hello.get("kind") != "hello":
            await close_with_error(ws, "invalid_hello", "Expected a compatible hello packet.")
            return
        supplied_token = hello.get("token")
        if not isinstance(supplied_token, str) or not secrets.compare_digest(supplied_token, expected_token):
            await close_with_error(ws, "authentication_failed", "Participant authentication failed.")
            return

        name = hello.get("name")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
            await close_with_error(ws, "invalid_name", "Participant name must be 1–80 characters.")
            return
        participant_id = uuid.uuid4().hex
        safe_name = name.strip()
        CLIENTS[ws] = {"id": participant_id, "name": safe_name}
        await send_json(ws, packet("welcome", participant_id=participant_id,
                                   name=safe_name, protocol=PROTOCOL))
        await broadcast(packet("participant_joined", participant_id=participant_id,
                               name=safe_name), exclude=ws)

        async for raw in ws:
            if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_MESSAGE_SIZE:
                await close_with_error(ws, "message_too_large", "Packet exceeds 64 KiB.")
                break
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await send_json(ws, packet("error", code="invalid_json", message="Packet is not valid JSON."))
                continue
            if not isinstance(message, dict) or message.get("protocol") != PROTOCOL:
                await send_json(ws, packet("error", code="protocol_mismatch", message="Unsupported protocol."))
                continue
            kind = message.get("kind")
            if kind == "chat_message":
                content = message.get("text")
                if not isinstance(content, str) or not content.strip() or len(content) > MAX_CHAT_CHARS:
                    await send_json(ws, packet("error", code="invalid_chat_text",
                                               message="Chat text must be 1–12000 characters."))
                    continue
                await broadcast(packet("chat_message", participant_id=participant_id,
                                       name=safe_name, text=content), exclude=ws)
            elif kind == "leave":
                break
            else:
                await send_json(ws, packet("error", code="unsupported_kind",
                                           message="Only chat_message and leave are accepted after hello."))
    except asyncio.TimeoutError:
        try:
            await close_with_error(ws, "hello_timeout", "Authentication hello timed out.")
        except Exception:
            pass
    except Exception as exc:
        try:
            await send_json(ws, packet("error", code="connection_error",
                                       message=f"Connection ended ({type(exc).__name__})."))
        except Exception:
            pass
    finally:
        participant = CLIENTS.pop(ws, None)
        if participant:
            await broadcast(packet("participant_left", participant_id=participant["id"],
                                   name=participant["name"]), exclude=ws)


def main() -> int:
    parser = argparse.ArgumentParser(description="YJ-64 authenticated remote chat relay")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: loopback only)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cert", help="TLS certificate PEM path; required for non-loopback binding")
    parser.add_argument("--key", help="TLS private key PEM path; required for non-loopback binding")
    args = parser.parse_args()

    token = os.environ.get("YJ64_REMOTE_TOKEN", "")
    if len(token) < 24:
        print("ERROR: set YJ64_REMOTE_TOKEN to a random secret of at least 24 characters.", file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        print("ERROR: --port must be between 1 and 65535.", file=sys.stderr)
        return 2

    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    tls_context = None
    if bool(args.cert) != bool(args.key):
        print("ERROR: --cert and --key must be supplied together.", file=sys.stderr)
        return 2
    if args.cert and args.key:
        tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        try:
            tls_context.load_cert_chain(args.cert, args.key)
        except (OSError, ssl.SSLError) as exc:
            print(f"ERROR: cannot load TLS certificate/key ({type(exc).__name__}).", file=sys.stderr)
            return 2
    if args.host not in loopback_hosts and tls_context is None:
        print("ERROR: non-loopback binding requires TLS; provide --cert and --key.", file=sys.stderr)
        return 2

    async def run() -> None:
        async with serve(handler, args.host, args.port, ssl=tls_context,
                         max_size=MAX_MESSAGE_SIZE, ping_interval=20, ping_timeout=20):
            scheme = "wss" if tls_context else "ws"
            print(f"YJ-64 remote participant relay listening on {scheme}://{args.host}:{args.port}")
            await asyncio.Future()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nYJ-64 relay stopped.")
    except OSError as exc:
        print(f"ERROR: server could not start ({type(exc).__name__}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
