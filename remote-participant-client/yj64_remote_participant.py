#!/usr/bin/env python3
"""YJ-64 remote chat participant client.

Requires Python 3.10+ and the 'websockets' package.
This client relays chat text only; it does not execute remote commands.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from typing import Any
from urllib.parse import urlparse

PROTOCOL = "yj64.remote-participant.v1"
MAX_CHAT_CHARS = 12_000
MAX_PACKET_BYTES = 64 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect this computer to the YJ-64 remote participant chat."
    )
    parser.add_argument("--url", help="Relay URL, e.g. wss://your-host.example:8765")
    parser.add_argument("--name", help="Participant display name (1–80 characters)")
    parser.add_argument(
        "--token-env",
        default="YJ64_REMOTE_TOKEN",
        help="Environment variable containing the token (default: YJ64_REMOTE_TOKEN)",
    )
    return parser.parse_args()


def validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("wss", "ws") or not parsed.hostname:
        raise ValueError("URL must start with wss:// or ws:// and include a host.")
    if parsed.scheme == "ws" and parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("For remote connections use wss://; ws:// is allowed only on this computer.")
    if parsed.username or parsed.password:
        raise ValueError("Do not put credentials or the token inside the URL.")
    return url


def decode_packet(raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > MAX_PACKET_BYTES:
        raise ValueError("Server packet exceeds 64 KiB.")
    packet = json.loads(raw)
    if not isinstance(packet, dict):
        raise ValueError("Server sent a packet that is not a JSON object.")
    if packet.get("protocol") != PROTOCOL:
        raise ValueError("Server protocol mismatch.")
    return packet


def print_packet(packet: dict[str, Any]) -> None:
    kind = packet.get("kind")
    if kind == "chat_message":
        print(f"\n[{packet.get('name', 'participant')}] {packet.get('text', '')}", flush=True)
    elif kind == "participant_joined":
        print(f"\n[Система] Подключился участник: {packet.get('name', 'unknown')}", flush=True)
    elif kind == "participant_left":
        print(f"\n[Система] Отключился участник: {packet.get('name', 'unknown')}", flush=True)
    elif kind == "error":
        print(
            f"\n[Ошибка сервера] {packet.get('code', 'unknown')}: "
            f"{packet.get('message', 'no details')}",
            file=sys.stderr,
            flush=True,
        )
    elif kind == "welcome":
        print(
            f"Подключено к YJ-64 как {packet.get('name', 'participant')} "
            f"(ID: {packet.get('participant_id', 'unknown')}).",
            flush=True,
        )
    else:
        print(f"\n[Событие] {kind or 'unknown'}", flush=True)


async def run_client(url: str, name: str, token: str) -> int:
    try:
        from websockets.asyncio.client import connect
    except ImportError:
        try:
            from websockets import connect
        except ImportError:
            print(
                "Не установлена зависимость websockets. Выполните: "
                "python -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            return 2

    try:
        async with connect(
            url,
            max_size=MAX_PACKET_BYTES,
            open_timeout=15,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            hello = {
                "protocol": PROTOCOL,
                "kind": "hello",
                "name": name,
                "token": token,
            }
            await ws.send(json.dumps(hello, ensure_ascii=False))
            try:
                first = decode_packet(await asyncio.wait_for(ws.recv(), timeout=12))
            except asyncio.TimeoutError:
                print("Сервер не ответил на авторизацию за 12 секунд.", file=sys.stderr)
                return 1
            if first.get("kind") != "welcome":
                print_packet(first)
                print("Сервер не подтвердил подключение.", file=sys.stderr)
                return 1
            print_packet(first)
            print("Пишите сообщение и нажимайте Enter. Команда /quit завершает работу.")

            async def receive_one() -> dict[str, Any]:
                return decode_packet(await ws.recv())

            # Keep one pending console read. Cancelling asyncio.to_thread(input)
            # does not stop the underlying OS thread and can create competing readers.
            input_task = asyncio.create_task(asyncio.to_thread(input, "> "))
            while True:
                recv_task = asyncio.create_task(receive_one())
                done, _ = await asyncio.wait(
                    {recv_task, input_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if recv_task in done:
                    try:
                        incoming = recv_task.result()
                    except Exception as exc:
                        input_task.cancel()
                        print(
                            f"\nСоединение завершено: {type(exc).__name__}: {exc}",
                            file=sys.stderr,
                        )
                        return 1
                    print_packet(incoming)
                    if input_task.done():
                        # Process the already-entered line on the next pass.
                        pass
                    continue

                recv_task.cancel()
                try:
                    await recv_task
                except (asyncio.CancelledError, Exception):
                    pass
                try:
                    outgoing = input_task.result()
                except EOFError:
                    outgoing = "/quit"
                outgoing = outgoing.strip()
                if outgoing.lower() in ("/quit", "/exit"):
                    await ws.send(json.dumps({"protocol": PROTOCOL, "kind": "leave"}))
                    print("Отключение от YJ-64.")
                    return 0
                if not outgoing:
                    input_task = asyncio.create_task(asyncio.to_thread(input, "> "))
                    continue
                if len(outgoing) > MAX_CHAT_CHARS:
                    print(f"Сообщение слишком длинное: максимум {MAX_CHAT_CHARS} символов.")
                else:
                    await ws.send(json.dumps(
                        {"protocol": PROTOCOL, "kind": "chat_message", "text": outgoing},
                        ensure_ascii=False,
                    ))
                input_task = asyncio.create_task(asyncio.to_thread(input, "> "))
    except KeyboardInterrupt:
        print("\nОтключение по запросу пользователя.")
        return 130
    except Exception as exc:
        print(
            f"Не удалось подключиться или соединение потеряно ({type(exc).__name__}). "
            "Проверьте URL, сеть, TLS-сертификат и настройки сервера.",
            file=sys.stderr,
        )
        return 1
    return 0


def main() -> int:
    args = parse_args()
    try:
        url = validate_url(args.url or input("URL сервера YJ-64 (wss://…): "))
    except ValueError as exc:
        print(f"Ошибка URL: {exc}", file=sys.stderr)
        return 2

    name = (args.name or input("Имя участника: ")).strip()
    if not name or len(name) > 80:
        print("Имя участника должно содержать от 1 до 80 символов.", file=sys.stderr)
        return 2

    token = os.environ.get(args.token_env, "")
    if not token:
        token = getpass.getpass("Токен участника (ввод скрыт): ")
    if len(token) < 24:
        print("Токен должен содержать не менее 24 символов.", file=sys.stderr)
        return 2

    try:
        return asyncio.run(run_client(url, name, token))
    except KeyboardInterrupt:
        print("\nЗавершено.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
