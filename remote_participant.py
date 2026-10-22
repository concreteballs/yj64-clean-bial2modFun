"""Authenticated WebSocket client used by the YJ-64 Android remote-participant dialog.

The module only relays text chat. It does not execute remote commands or expose files.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable
from urllib.parse import urlparse

PROTOCOL = "yj64.remote-participant.v1"
MAX_PACKET_BYTES = 64 * 1024
MAX_CHAT_CHARS = 12_000


def validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("wss", "ws") or not parsed.hostname:
        raise ValueError("Адрес должен начинаться с wss:// или ws:// и содержать имя сервера.")
    if parsed.scheme == "ws" and parsed.hostname not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("Для подключения через интернет используйте wss:// с TLS.")
    if parsed.username or parsed.password:
        raise ValueError("Не помещайте логин или токен в адрес сервера.")
    return url


class RemoteParticipantClient:
    def __init__(self, on_event: Callable[[str, dict[str, Any]], None]):
        self.on_event = on_event
        self.connected = False
        self._loop = None
        self._ws = None
        self._thread = None
        self._send_queue = None
        self._stop = threading.Event()

    def _emit(self, event: str, **data: Any) -> None:
        try:
            self.on_event(event, data)
        except Exception:
            pass

    def connect(self, url: str, name: str, token: str) -> None:
        if self.connected or (self._thread and self._thread.is_alive()):
            self._emit("error", message="Соединение уже выполняется или активно.")
            return
        try:
            url = validate_url(url)
        except ValueError as exc:
            self._emit("error", message=str(exc))
            return
        if not name.strip() or len(name.strip()) > 80:
            self._emit("error", message="Имя должно содержать от 1 до 80 символов.")
            return
        if not token or len(token) < 24:
            self._emit("error", message="Токен должен содержать не менее 24 символов.")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._thread_main, args=(url, name.strip(), token),
            name="yj64-remote-participant", daemon=True
        )
        self._thread.start()

    def _thread_main(self, url: str, name: str, token: str) -> None:
        try:
            asyncio.run(self._run(url, name, token))
        except Exception as exc:
            self.connected = False
            self._emit("error", message=f"{type(exc).__name__}: {exc}")
        finally:
            self.connected = False

    async def _run(self, url: str, name: str, token: str) -> None:
        try:
            from websockets.asyncio.client import connect
        except ImportError:
            try:
                from websockets import connect
            except ImportError as exc:
                raise RuntimeError("В этой сборке нет библиотеки websockets; нужна новая APK-сборка.") from exc

        try:
            async with connect(url, max_size=MAX_PACKET_BYTES, open_timeout=15,
                               ping_interval=20, ping_timeout=20) as ws:
                self._ws = ws
                self._loop = asyncio.get_running_loop()
                await ws.send(json.dumps({
                    "protocol": PROTOCOL, "kind": "hello", "name": name, "token": token
                }, ensure_ascii=False))
                try:
                    first_raw = await asyncio.wait_for(ws.recv(), timeout=12)
                except asyncio.TimeoutError as exc:
                    raise RuntimeError("Сервер не ответил на авторизацию за 12 секунд.") from exc
                first = self._decode(first_raw)
                if first.get("kind") != "welcome":
                    raise RuntimeError(str(first.get("message", first.get("code", "Сервер не подтвердил подключение."))))
                self.connected = True
                self._emit("connected", name=first.get("name", name),
                           participant_id=first.get("participant_id", ""))
                while not self._stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                    except asyncio.TimeoutError:
                        continue
                    packet = self._decode(raw)
                    kind = packet.get("kind")
                    if kind == "chat_message":
                        self._emit("message", name=packet.get("name", "участник"),
                                   text=str(packet.get("text", ""))[:MAX_CHAT_CHARS])
                    elif kind == "participant_joined":
                        self._emit("message", name="Система",
                                   text="Подключился участник: " + str(packet.get("name", "unknown")))
                    elif kind == "participant_left":
                        self._emit("message", name="Система",
                                   text="Отключился участник: " + str(packet.get("name", "unknown")))
                    elif kind == "error":
                        self._emit("error", message=f"{packet.get('code')}: {packet.get('message')}")
        finally:
            self.connected = False
            self._ws = None
            self._loop = None
            self._emit("disconnected", message="Соединение закрыто.")

    @staticmethod
    def _decode(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_PACKET_BYTES:
            raise RuntimeError("Сервер прислал недопустимый пакет.")
        packet = json.loads(raw)
        if not isinstance(packet, dict) or packet.get("protocol") != PROTOCOL:
            raise RuntimeError("Несовместимый протокол сервера.")
        return packet

    def send_message(self, message: str) -> bool:
        if not self.connected or self._loop is None or self._ws is None:
            return False
        message = message.strip()
        if not message or len(message) > MAX_CHAT_CHARS:
            self._emit("error", message="Сообщение должно содержать от 1 до 12000 символов.")
            return False
        async def send() -> None:
            await self._ws.send(json.dumps({
                "protocol": PROTOCOL, "kind": "chat_message", "text": message
            }, ensure_ascii=False))
        try:
            asyncio.run_coroutine_threadsafe(send(), self._loop)
            return True
        except Exception as exc:
            self._emit("error", message=f"Не удалось отправить сообщение: {type(exc).__name__}")
            return False

    def disconnect(self) -> None:
        self._stop.set()
        if self._loop and self._ws:
            async def close() -> None:
                try:
                    await self._ws.send(json.dumps({"protocol": PROTOCOL, "kind": "leave"}))
                    await self._ws.close()
                except Exception:
                    pass
            try:
                asyncio.run_coroutine_threadsafe(close(), self._loop)
            except Exception:
                pass
        else:
            self._emit("disconnected", message="Соединение не было запущено.")
