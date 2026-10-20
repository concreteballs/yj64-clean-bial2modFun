"""Persistent local workspace for YJ-64 chats, threads, and skills."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class ChatWorkspace:
    """Stores chat metadata and message histories in app-private storage."""

    def __init__(self, data_dir: str | Path) -> None:
        self.root = Path(data_dir) / "yj64-workspace"
        self.chats_dir = self.root / "chats"
        self.index_path = self.root / "chats-index.json"
        self.skills_path = self.root / "skills.md"
        self.chats_dir.mkdir(parents=True, exist_ok=True)
        if not self.skills_path.exists():
            self.skills_path.write_text(
                "# YJ-64 Skills\n\n"
                "Keep reusable skills as concise, reviewable Markdown instructions.\n"
                "Do not store API keys, passwords, access tokens, or private credentials here.\n",
                encoding="utf-8",
            )
        if not self.index_path.exists():
            self._write_index([])
        if not self.list_chats():
            self.create_chat("Первый чат")

    def _read_index(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            chats = data.get("chats", []) if isinstance(data, dict) else []
            return [item for item in chats if isinstance(item, dict) and item.get("id")]
        except (OSError, ValueError):
            return []

    def _write_index(self, chats: list[dict[str, Any]]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(
            json.dumps({"schema": "yj64.workspace.v1", "chats": chats},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_chats(self) -> list[dict[str, Any]]:
        return sorted(self._read_index(), key=lambda item: int(item.get("updated_ms", 0)),
                      reverse=True)

    def create_chat(self, title: str = "Новый чат", parent_id: str | None = None) -> str:
        now = int(time.time() * 1000)
        chat_id = uuid.uuid4().hex
        chats = self._read_index()
        chats.append({
            "id": chat_id, "title": (title.strip() or "Новый чат")[:100],
            "created_ms": now, "updated_ms": now, "parent_id": parent_id,
        })
        self._write_index(chats)
        self._write_messages(chat_id, [])
        return chat_id

    def load_messages(self, chat_id: str) -> list[dict[str, str]]:
        path = self.chats_dir / f"{chat_id}.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            messages = raw.get("messages", []) if isinstance(raw, dict) else []
            return [
                {"role": str(item.get("role", "user")),
                 "content": str(item.get("content", ""))}
                for item in messages if isinstance(item, dict)
            ]
        except (OSError, ValueError):
            return []

    def save_messages(self, chat_id: str, messages: list[dict[str, str]]) -> None:
        safe = [{"role": str(item.get("role", "user")),
                 "content": str(item.get("content", ""))}
                for item in messages]
        self._write_messages(chat_id, safe)
        chats = self._read_index()
        now = int(time.time() * 1000)
        for item in chats:
            if item.get("id") == chat_id:
                item["updated_ms"] = now
                first = next((m.get("content", "") for m in safe if m.get("role") == "user"), "")
                if first and item.get("title") in {"Новый чат", "Первый чат"}:
                    item["title"] = first[:80].replace("\n", " ")
                break
        self._write_index(chats)

    def _write_messages(self, chat_id: str, messages: list[dict[str, str]]) -> None:
        path = self.chats_dir / f"{chat_id}.json"
        path.write_text(
            json.dumps({"schema": "yj64.chat.v1", "chat_id": chat_id,
                        "messages": messages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_named_history(self, name: str) -> list[dict[str, str]]:
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_")
        path = self.root / f"private-{safe}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("messages", []) if isinstance(data, dict) else []
        except (OSError, ValueError):
            return []

    def save_named_history(self, name: str, messages: list[dict[str, str]]) -> None:
        safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_ ").strip().replace(" ", "_")
        (self.root / f"private-{safe}.json").write_text(
            json.dumps({"messages": messages}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_skills(self) -> str:
        return self.skills_path.read_text(encoding="utf-8")

    def write_skills(self, content: str) -> None:
        self.skills_path.write_text(content, encoding="utf-8")
