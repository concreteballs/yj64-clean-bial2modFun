"""YJ-64 minimal base application with an embedded diagnostic agent."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from kivy.app import App
from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.core.window import Window
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.filechooser import FileChooserListView

Window.softinput_mode = "below_target"

SERVICE_CLASS = "org.blackmirror.blackmirror.ServiceInternal"
MONITOR_ACTIVITY_CLASS = "org.blackmirror.blackmirror.MonitorActivity"
SERVICE_LAUNCH_FLAG = "yj64.internal_agent_launch"
REPORT_RELATIVE_PATH = Path("yj64-reports") / "yj64-report.jsonl"
TEST_COMMAND_RELATIVE_PATH = Path("yj64-test-command.json")
TEST_RESULT_RELATIVE_PATH = Path("yj64-test-result.json")


class YJ64BaseApp(App):
    def build(self):
        from message_distributor import MessageDistributor
        from chat_workspace import ChatWorkspace
        self.message_distributor = MessageDistributor()
        self.workspace = ChatWorkspace(self.user_data_dir)
        chats = self.workspace.list_chats()
        self.current_chat_id = str(chats[0]["id"])
        self.common_history: list[dict[str, str]] = self.workspace.load_messages(self.current_chat_id)
        self.private_histories: dict[str, list[dict[str, str]]] = {}
        self.practical_mode = False
        self.critique_mode = False
        self.consensus_reached = False
        self.consensus_summary = ""
        self.report_path = Path(self.user_data_dir) / REPORT_RELATIVE_PATH
        self.pid_path = Path(self.user_data_dir) / "yj64-main-process.pid"
        self.status = Label(
            text="Starting embedded diagnostic agent...",
            halign="left",
            valign="top",
            size_hint_y=None,
            height=90,
        )
        self.status.bind(
            size=lambda instance, value: setattr(instance, "text_size", value)
        )

        root = BoxLayout(orientation="vertical", padding=24, spacing=16)
        root.add_widget(Label(
            text="YJ-64 Base Application",
            size_hint_y=None,
            height=80,
        ))
        root.add_widget(self.status)

        tools_button = Button(
            text="TOOLS / MONITOR / DIAGNOSTICS",
            size_hint_y=None,
            height=56,
        )
        tools_button.bind(on_release=self._open_tools_menu)
        root.add_widget(tools_button)

        root.add_widget(Label(
            text="LLM CHAT",
            size_hint_y=None,
            height=42,
        ))
        self.chat_output = TextInput(
            text=self._render_history(),
            readonly=True,
            multiline=True,
            size_hint_y=None,
            height=180,
        )
        root.add_widget(self.chat_output)

        chat_row = BoxLayout(
            spacing=12,
            size_hint_y=None,
            height=64,
        )
        self.chat_input = TextInput(
            hint_text="Write a message...",
            multiline=True,
            write_tab=False,
            input_type="text",
            keyboard_suggestions=True,
        )
        self.chat_input.bind(focus=self._chat_input_focus_changed)
        chat_row.add_widget(self.chat_input)
        chat_send = Button(
            text="SEND",
            size_hint_x=None,
            width=120,
        )
        chat_send.bind(on_release=self._send_llm_chat)
        chat_row.add_widget(chat_send)
        root.add_widget(chat_row)

        workspace_row = BoxLayout(
            spacing=8, size_hint_y=None, height=54,
        )
        chats_button = Button(text="CHATS", size_hint_x=1)
        chats_button.bind(on_release=self._show_chats)
        new_chat_button = Button(text="NEW CHAT", size_hint_x=1)
        new_chat_button.bind(on_release=self._new_chat)
        attach_button = Button(text="ATTACH FILE", size_hint_x=1)
        attach_button.bind(on_release=self._attach_file)
        media_button = Button(text="CAMERA / LIVE MEDIA")
        media_button.bind(on_release=self._open_live_media_placeholder)
        workspace_row.add_widget(chats_button)
        workspace_row.add_widget(new_chat_button)
        workspace_row.add_widget(attach_button)
        workspace_row.add_widget(media_button)
        root.add_widget(workspace_row)

        modes_row = BoxLayout(
            spacing=8, size_hint_y=None, height=54,
        )
        self.critique_mode_button = Button(
            text="CRITIQUE PROJECT: OFF",
            background_color=(0.15, 0.65, 0.25, 1),
        )
        self.critique_mode_button.bind(on_release=self._toggle_critique_mode)
        skills_button = Button(text="SKILLS FILE")
        skills_button.bind(on_release=self._open_skills_editor)
        remote_button = Button(text="REMOTE PARTICIPANT (STUB)")
        remote_button.bind(on_release=self._open_remote_participant)
        modes_row.add_widget(self.critique_mode_button)
        modes_row.add_widget(skills_button)
        modes_row.add_widget(remote_button)
        root.add_widget(modes_row)

        practical_row = BoxLayout(
            spacing=12,
            size_hint_y=None,
            height=58,
        )
        self.practical_mode_button = Button(
            text="ПЕРЕЙТИ К ПРАКТИЧЕСКИМ ДЕЙСТВИЯМ: OFF",
            size_hint_x=1,
        )
        self.practical_mode_button.bind(on_release=self._toggle_practical_mode)
        practical_row.add_widget(self.practical_mode_button)
        self.implementation_button = Button(
            text="НАЧАТЬ РЕАЛИЗАЦИЮ ЧЕРЕЗ ПОДКЛЮЧЁННЫХ АГЕНТОВ",
            size_hint_x=1,
            disabled=True,
        )
        self.implementation_button.bind(on_release=self._start_agent_implementation)
        practical_row.add_widget(self.implementation_button)
        root.add_widget(practical_row)

        participant_column = BoxLayout(
            orientation="vertical",
            spacing=8,
            size_hint_y=None,
            height=340,
        )
        participant_column.add_widget(Label(
            text="PARTICIPANTS",
            size_hint_y=None,
            height=36,
        ))
        self.participant_buttons = {}
        for participant_name in ("Participant 1", "Participant 2", "Participant 3"):
            button = Button(
                text=participant_name,
                size_hint_y=None,
                height=54,
            )
            button.bind(
                on_release=lambda _button, name=participant_name:
                self._open_participant_menu(name)
            )
            self.participant_buttons[participant_name] = button
            participant_column.add_widget(button)
        dialogue_button = Button(
            text="START GROUP DIALOGUE",
            size_hint_y=None,
            height=58,
        )
        dialogue_button.bind(on_release=self._open_group_dialogue)
        participant_column.add_widget(dialogue_button)
        self.mode_button = Button(
            text="REQUEST MODE: TEXT",
            size_hint_y=None,
            height=54,
        )
        self.mode_button.bind(on_release=self._toggle_request_mode)
        participant_column.add_widget(self.mode_button)
        root.add_widget(participant_column)
        self._refresh_participant_buttons()

        root.size_hint_y = None
        root.bind(minimum_height=root.setter("height"))
        scroll = ScrollView(do_scroll_x=False, bar_width=8)
        scroll.add_widget(root)

        self._write_main_pid()
        self._append_report(
            "base_ui_ready",
            pid=os.getpid(),
            process_name=self._process_name(),
        )

        Clock.schedule_once(self._ensure_service_started, 0.5)
        Clock.schedule_interval(self._refresh_status, 1.0)
        Clock.schedule_interval(self._refresh_participant_buttons, 1.0)
        Clock.schedule_interval(self._poll_test_command, 0.5)
        self._append_report(
            "workspace_opened",
            chat_id=self.current_chat_id,
            chat_count=len(self.workspace.list_chats()),
            skills_path=str(self.workspace.skills_path),
        )
        return scroll

    def _render_history(self) -> str:
        rendered = []
        for item in self.common_history:
            role = "Owner" if item.get("role") == "user" else "YJ-64"
            rendered.append(f"{role}:\n{item.get('content', '')}")
        return "\n\n".join(rendered) or "New chat. Write a message below."

    def _save_common_history(self) -> None:
        self.workspace.save_messages(self.current_chat_id, self.common_history)

    def _select_chat(self, chat_id: str, popup: Popup) -> None:
        popup.dismiss()
        self.current_chat_id = chat_id
        self.common_history = self.workspace.load_messages(chat_id)
        self.chat_output.text = self._render_history()
        self.consensus_reached = False
        self.implementation_button.disabled = True
        self._append_report("workspace_chat_selected", chat_id=chat_id)
        self.status.text = f"Opened chat {chat_id[:8]} with {len(self.common_history)} saved messages."

    def _show_chats(self, *_: Any) -> None:
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        listing = ScrollView(do_scroll_x=False)
        items = BoxLayout(orientation="vertical", spacing=6, size_hint_y=None)
        items.bind(minimum_height=items.setter("height"))
        popup = Popup(title="SAVED CHATS", content=content, size_hint=(0.94, 0.86))
        for item in self.workspace.list_chats():
            title = str(item.get("title") or "Untitled chat")
            button = Button(
                text=f"{title}\n{str(item['id'])[:8]}",
                size_hint_y=None, height=62,
            )
            button.bind(
                on_release=lambda _btn, chat_id=str(item["id"]):
                self._select_chat(chat_id, popup)
            )
            items.add_widget(button)
        listing.add_widget(items)
        content.add_widget(listing)
        branch_button = Button(
            text="CREATE BRANCH FROM CURRENT CHAT",
            size_hint_y=None, height=52,
        )
        def create_branch(*_args: Any) -> None:
            parent = self.current_chat_id
            new_id = self.workspace.create_chat("Ветка обсуждения", parent_id=parent)
            self.workspace.save_messages(new_id, list(self.common_history))
            self._select_chat(new_id, popup)
            self._append_report("workspace_branch_created", chat_id=new_id, parent_id=parent)
        branch_button.bind(on_release=create_branch)
        content.add_widget(branch_button)
        close = Button(text="CLOSE", size_hint_y=None, height=48)
        close.bind(on_release=lambda *_: popup.dismiss())
        content.add_widget(close)
        popup.open()

    def _new_chat(self, *_: Any) -> None:
        self._save_common_history()
        self.current_chat_id = self.workspace.create_chat("Новый чат")
        self.common_history = []
        self.chat_output.text = self._render_history()
        self.consensus_reached = False
        self.implementation_button.disabled = True
        self._append_report("workspace_chat_created", chat_id=self.current_chat_id)
        self.status.text = "New local chat created."

    def _toggle_critique_mode(self, *_: Any) -> None:
        self.critique_mode = not self.critique_mode
        self.critique_mode_button.text = (
            "CRITIQUE PROJECT: ON" if self.critique_mode else "CRITIQUE PROJECT: OFF"
        )
        self.critique_mode_button.background_color = (
            (0.85, 0.15, 0.15, 1) if self.critique_mode else (0.15, 0.65, 0.25, 1)
        )
        self._append_report("critique_mode_changed", enabled=self.critique_mode)
        self.status.text = (
            "Critique mode ON: models must identify flaws, risks, and counter-evidence."
            if self.critique_mode else "Critique mode OFF: normal instructions restored."
        )

    def _open_skills_editor(self, *_: Any) -> None:
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        editor = TextInput(text=self.workspace.read_skills(), multiline=True)
        content.add_widget(editor)
        status = Label(text=f"Stored locally: {self.workspace.skills_path}", size_hint_y=None, height=44)
        content.add_widget(status)
        buttons = BoxLayout(size_hint_y=None, height=52, spacing=8)
        save = Button(text="SAVE SKILLS")
        close = Button(text="CLOSE")
        buttons.add_widget(save)
        buttons.add_widget(close)
        content.add_widget(buttons)
        popup = Popup(title="LOCAL SKILLS FILE", content=content, size_hint=(0.96, 0.9))
        def save_skills(*_args: Any) -> None:
            self.workspace.write_skills(editor.text)
            self._append_report("skills_file_saved", character_count=len(editor.text))
            status.text = "Saved locally. Instructions are added to future chat prompts."
        save.bind(on_release=save_skills)
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def _attach_file(self, *_: Any) -> None:
        preferred = Path("/storage/emulated/0/Download")
        start_path = preferred if preferred.is_dir() else Path(self.user_data_dir)
        content = BoxLayout(orientation="vertical", spacing=8, padding=10)
        chooser = FileChooserListView(path=str(start_path), filters=["*"])
        content.add_widget(chooser)
        note = Label(
            text="Text files are embedded in the prompt (max 64 KB). Other files are recorded by name only; binary/multimedia transfer is not yet implemented.",
            size_hint_y=None, height=58,
        )
        content.add_widget(note)
        buttons = BoxLayout(size_hint_y=None, height=52, spacing=8)
        attach = Button(text="ATTACH SELECTED")
        close = Button(text="CLOSE")
        buttons.add_widget(attach)
        buttons.add_widget(close)
        content.add_widget(buttons)
        popup = Popup(title="ATTACH A FILE", content=content, size_hint=(0.97, 0.92))
        def attach_selected(*_args: Any) -> None:
            if not chooser.selection:
                note.text = "Select a file first."
                return
            path = Path(chooser.selection[0])
            if not path.is_file():
                note.text = "Select a file, not a folder."
                return
            suffix = path.suffix.lower()
            text_suffixes = {".txt", ".md", ".json", ".csv", ".py", ".yaml", ".yml", ".xml", ".log"}
            try:
                if suffix in text_suffixes:
                    with path.open("rb") as handle:
                        raw = handle.read(65537)
                    if len(raw) > 65536:
                        note.text = "Text file exceeds 64 KB; not attached. Use a smaller excerpt."
                        return
                    body = raw.decode("utf-8", errors="replace")
                    self.chat_input.text += f"\n\n[ATTACHED TEXT FILE: {path.name}]\n{body}\n[END ATTACHMENT]\n"
                    self._append_report("chat_text_file_attached", name=path.name, bytes=len(raw))
                    note.text = f"Text contents added to message: {path.name}"
                else:
                    self.chat_input.text += f"\n\n[ATTACHMENT METADATA: {path.name}; type={suffix or 'unknown'}; content not transmitted]\n"
                    self._append_report(
                        "chat_binary_attachment_selected",
                        name=path.name, suffix=suffix, transmitted=False,
                    )
                    note.text = "File name added only. This file's binary contents have NOT been sent to an LLM."
                attach.disabled = True
            except OSError as exc:
                note.text = f"Could not read file: {type(exc).__name__}: {exc}"
                self._append_report("chat_attachment_failed", path=str(path), error=str(exc))
        attach.bind(on_release=attach_selected)
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def _open_tools_menu(self, *_: Any) -> None:
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        popup = Popup(title="TOOLS / MONITOR / DIAGNOSTICS", content=content, size_hint=(0.92, 0.84))
        actions = [
            ("OPEN INTERNAL MONITOR", self._open_monitor),
            ("TEST LLM API + COPY REPORT", self._test_llm_api),
            ("TEST LLM GENERATION + COPY", self._test_llm_generation),
            ("CONFIGURE LLM API / KEY", self._open_llm_settings),
            ("COPY DIAGNOSTIC REPORT", self._copy_diagnostic_report),
            ("CHATGPT BRIDGE (STUB)", self._open_chatgpt_bridge),
        ]
        for label, callback in actions:
            button = Button(text=label, size_hint_y=None, height=54)
            def invoke(_button: Any, action: Any = callback) -> None:
                popup.dismiss()
                action()
            button.bind(on_release=invoke)
            content.add_widget(button)
        close = Button(text="CLOSE", size_hint_y=None, height=48)
        close.bind(on_release=lambda *_: popup.dismiss())
        content.add_widget(close)
        popup.open()
        self._append_report("tools_menu_opened", actions=[item[0] for item in actions])

    def _copy_diagnostic_report(self, *_: Any) -> None:
        report = self._read_report_text()
        self._copy_to_clipboard(report)
        self.status.text = f"Diagnostic report copied from {self.report_path}"
        self._append_report("diagnostic_report_copy_requested", path=str(self.report_path))

    def _open_chatgpt_bridge(self, *_: Any) -> None:
        from chatgpt_bridge import get_status
        state = get_status()
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(
            text="CHATGPT BRIDGE — PLACEHOLDER ONLY\n\n" + state.message
                 + "\n\nNo browser session is read, no credentials are captured, "
                   "and no content is sent to ChatGPT from this screen."
        ))
        close = Button(text="CLOSE", size_hint_y=None, height=52)
        content.add_widget(close)
        popup = Popup(title="CHATGPT BRIDGE", content=content, size_hint=(0.94, 0.62))
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()
        self._append_report("chatgpt_bridge_placeholder_opened", connected=False)

    def _open_live_media_placeholder(self, *_: Any) -> None:
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(
            text="CAMERA / LIVE MEDIA\n\n"
                 "This build can select files, but it does not yet capture or stream live "
                 "camera video, and binary image/audio/video contents are not uploaded to "
                 "the LLM. A real implementation needs Android capture permissions, a "
                 "supported real-time transport, and explicit user controls."
        ))
        close = Button(text="CLOSE", size_hint_y=None, height=52)
        content.add_widget(close)
        popup = Popup(title="CAMERA / LIVE MEDIA", content=content, size_hint=(0.94, 0.6))
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()
        self._append_report("live_media_placeholder_opened", capture_started=False, streaming_started=False)

    def _open_remote_participant(self, *_: Any) -> None:
        from remote_participant import get_status
        state = get_status()
        content = BoxLayout(orientation="vertical", spacing=10, padding=12)
        content.add_widget(Label(
            text="REMOTE PARTICIPANT — PLACEHOLDER ONLY\n\n"
                 + state.message
                 + "\n\nNo network connection or remote command is attempted. "
                   "We will design the administrator's computer module in the next step.",
        ))
        close = Button(text="CLOSE", size_hint_y=None, height=52)
        content.add_widget(close)
        popup = Popup(title="REMOTE PARTICIPANT", content=content, size_hint=(0.94, 0.58))
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()
        self._append_report("remote_participant_placeholder_opened", connected=False)

    def _toggle_practical_mode(self, *_: Any) -> None:
        self.practical_mode = not self.practical_mode
        self.consensus_reached = False
        self.consensus_summary = ""
        self.implementation_button.disabled = True
        self.practical_mode_button.text = (
            "ПРАКТИЧЕСКИЕ ДЕЙСТВИЯ: ON — ОЖИДАЕМ КОНСЕНСУС"
            if self.practical_mode
            else "ПЕРЕЙТИ К ПРАКТИЧЕСКИМ ДЕЙСТВИЯМ: OFF"
        )
        self.practical_mode_button.background_color = (
            (0.15, 0.65, 0.25, 1) if self.practical_mode else (1, 1, 1, 1)
        )
        self._append_report(
            "practical_mode_changed",
            enabled=self.practical_mode,
            consensus_reached=False,
        )
        if self.practical_mode:
            self.status.text = (
                "Practical mode enabled. Each connected model will receive "
                "action-oriented rules before the next question."
            )
        else:
            self.status.text = "Practical mode disabled; normal chat instructions restored."

    def _start_agent_implementation(self, *_: Any) -> None:
        if not self.practical_mode or not self.consensus_reached:
            self._append_report(
                "agent_implementation_rejected",
                practical_mode=self.practical_mode,
                consensus_reached=self.consensus_reached,
                reason="practical_mode_or_consensus_missing",
            )
            self.status.text = (
                "Implementation is locked until practical mode is enabled "
                "and connected models report consensus."
            )
            return
        request = (
            "IMPLEMENTATION PHASE. The discussion has reached the app's explicit "
            "consensus gate. Produce a concrete implementation proposal now: "
            "list the exact files to change, provide complete code patches, "
            "explain integration points, and include tests and rollback steps. "
            "Do not claim that you modified the repository or executed code. "
            "This app currently has LLM connections, not a verified repository-writing "
            "agent, so return reviewable patches and identify any missing action-agent "
            "capability. End with [IMPLEMENTATION DRAFT]."
        )
        self._append_report(
            "agent_implementation_requested",
            participants=self._chat_target_details()["connected_participants"],
            consensus_summary=self.consensus_summary,
            execution_capability="llm_draft_only_until_action_agent_is_installed",
        )
        self.chat_input.text = request
        self._send_llm_chat()

    def _practical_instructions(self, prompt: str, implementation: bool = False) -> str:
        sections: list[str] = []
        if self.critique_mode:
            sections.append(
                "YJ-64 CRITIQUE PROJECT MODE: critically inspect assumptions, identify "
                "failure modes and counter-evidence, separate facts from speculation, "
                "and suggest tests that could disprove the proposal. Be constructive."
            )
        if self.practical_mode:
            if implementation:
                sections.append(
                    "YJ-64 PRACTICAL ACTION PROTOCOL. Phase: IMPLEMENTATION DRAFT. "
                    "Provide exact files, complete patches, integration points, tests, "
                    "rollback steps, and unknowns. Do not claim repository edits or execution "
                    "without evidence. No verified repository-writing agent is installed. "
                    "End with [IMPLEMENTATION DRAFT]."
                )
            else:
                sections.append(
                    "YJ-64 PRACTICAL ACTION PROTOCOL. Give ordered actionable steps, files/tools, "
                    "dependencies, risks, and testable completion criteria. Separate verified "
                    "facts from assumptions. End with [CONSENSUS: APPROVE] only when you agree "
                    "with no unresolved blocker, otherwise [CONSENSUS: OBJECT]. Do not imitate "
                    "another participant's vote without independent assessment."
                )
        try:
            skills = self.workspace.read_skills().strip()
        except (OSError, AttributeError):
            skills = ""
        if skills:
            sections.append("YJ-64 LOCAL SKILLS (user-editable instructions):\n" + skills[:12000])
        if not sections:
            return prompt
        return "\n\n".join(sections) + "\n\nUSER TASK:\n" + prompt

    def _toggle_request_mode(self, *_: Any) -> None:
        mode = self.message_distributor.toggle_mode()
        self.mode_button.text = f"REQUEST MODE: {mode.upper()}"
        self._append_report(
            "message_mode_changed",
            mode=mode,
            note=(
                "Agent mode selected; each participant uses its own configured Agent ID."
                if mode == "agent" else "Text mode selected."
            ),
        )
        self.status.text = (
            "Text mode selected."
            if mode == "text"
            else "Agent mode selected; each participant uses its own configured Agent ID."
        )

    def _participant_config_status(self, participant_name: str) -> dict[str, str | bool]:
        from llm_api import load_config, route_config_exists

        route_id = self.message_distributor.route_for_participant(participant_name)
        configured = route_config_exists(self.user_data_dir, route_id)
        config = load_config(self.user_data_dir, route_id=route_id) if configured else {}
        mode = "agent" if str(config.get("agent_id") or "").strip() else "text"
        return {
            "configured": configured,
            "mode": mode,
            "route_id": route_id,
            "provider": str(config.get("provider") or ""),
            "model": str(config.get("model") or ""),
        }

    def _refresh_participant_buttons(self, *_: Any) -> None:
        for participant_name, button in self.participant_buttons.items():
            status = self._participant_config_status(participant_name)
            if status["configured"]:
                button.background_color = (0.2, 0.8, 0.2, 1)
                button.text = f"{participant_name}  [CONNECTED]"
            else:
                button.background_color = (1, 1, 1, 1)
                button.text = participant_name

    def _open_participant_menu(self, participant_name: str) -> None:
        status = self._participant_config_status(participant_name)
        self._append_report(
            "participant_menu_opened",
            participant=participant_name,
            configured=status["configured"],
            mode=status["mode"],
            provider=status["provider"],
            model=status["model"],
        )

        content = BoxLayout(
            orientation="vertical",
            spacing=8,
            padding=12,
        )
        title = Label(
            text=f"{participant_name}\n"
                 f"{status['provider'] or 'not configured'} / "
                 f"{status['model'] or 'no model'}",
            size_hint_y=None,
            height=70,
        )
        content.add_widget(title)

        write_button = Button(text="WRITE / GET ANSWER", size_hint_y=None, height=56)
        write_button.bind(
            on_release=lambda *_: (
                popup.dismiss(),
                self._open_participant_chat(participant_name),
            )
        )
        content.add_widget(write_button)

        settings_button = Button(text="SETTINGS", size_hint_y=None, height=56)
        settings_button.bind(
            on_release=lambda *_: (
                popup.dismiss(),
                self._open_participant_settings(participant_name),
            )
        )
        content.add_widget(settings_button)

        close_button = Button(text="CLOSE", size_hint_y=None, height=56)
        close_button.bind(on_release=lambda *_: popup.dismiss())
        content.add_widget(close_button)

        popup = Popup(
            title=participant_name,
            content=content,
            size_hint=(0.9, 0.55),
        )
        popup.open()

    def _open_participant_settings(self, participant_name: str) -> None:
        self._append_report(
            "participant_settings_opened",
            participant=participant_name,
        )
        from llm_settings import LLMSettingsPopup
        route_id = self.message_distributor.route_for_participant(participant_name)
        LLMSettingsPopup(
            self.user_data_dir,
            route_id=route_id,
            on_report=lambda event, **data: self._append_report(
                "router_" + event,
                **{"participant": participant_name, **data},
            ),
            on_copy=self._copy_to_clipboard,
        ).open()

    def _open_participant_chat(self, participant_name: str) -> None:
        status = self._participant_config_status(participant_name)
        route_id = status["route_id"]
        mode = status["mode"]
        self._append_report(
            "participant_chat_opened",
            participant=participant_name,
            configured=status["configured"],
            mode=mode,
            provider=status["provider"],
            model=status["model"],
        )

        history = self.private_histories.setdefault(
            participant_name, self.workspace.load_named_history(participant_name)
        )
        output_lines = [
            f"{'You' if item.get('role') == 'user' else participant_name}:\n{item.get('content', '')}"
            for item in history
        ]
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        output = TextInput(
            text="\n\n".join(output_lines) or f"{participant_name} private conversation.",
            readonly=True,
            multiline=True,
        )
        prompt = TextInput(
            hint_text=f"Private message to {participant_name}...",
            multiline=True,
            size_hint_y=None,
            height=110,
            write_tab=False,
        )
        send = Button(text="SEND PRIVATELY", size_hint_y=None, height=54)
        publish = Button(
            text="PUBLISH LAST EXCHANGE TO COMMON CHAT",
            size_hint_y=None,
            height=48,
        )
        close = Button(text="CLOSE", size_hint_y=None, height=54)
        content.add_widget(output)
        content.add_widget(prompt)
        content.add_widget(send)
        content.add_widget(publish)
        content.add_widget(close)
        popup = Popup(
            title=f"{participant_name} PRIVATE CHAT",
            content=content,
            size_hint=(0.94, 0.78),
        )
        last_exchange: dict[str, Any] = {}

        def publish_last_exchange(*_args: Any) -> None:
            exchange = last_exchange.get("messages")
            if not exchange:
                output.text += "\n\nNo completed private exchange to publish."
                return
            if last_exchange.get("published"):
                output.text += "\n\nThis exchange was already published."
                return
            self.common_history.extend(exchange)
            rendered = "\n\n".join(
                f"{'Owner' if item['role'] == 'user' else participant_name}:\n{item['content']}"
                for item in exchange
            )
            self.chat_output.text += f"\n\n[PUBLISHED FROM {participant_name} PRIVATE CHAT]\n{rendered}"
            last_exchange["published"] = True
            self._append_report(
                "participant_private_exchange_published",
                participant=participant_name,
                route_id=route_id,
                message_count=len(exchange),
            )
            self.status.text = f"Last private exchange from {participant_name} published to common chat."

        def send_message(*_args: Any) -> None:
            message = prompt.text.strip()
            if not message:
                return
            if not self.message_distributor.dialogue_enabled:
                self._append_report(
                    "participant_request_rejected",
                    participant=participant_name,
                    reason="dialogue_stopped",
                )
                output.text = "Dialogue is stopped. Resume it before sending new LLM requests."
                return
            prompt.text = ""
            send.disabled = True
            output.text += f"\n\nYou: {message}\n\nSending privately..."
            common_context = list(self.common_history)
            private_context = list(self.private_histories.get(participant_name, []))
            request_message = self._practical_instructions(message)
            request_history = common_context + private_context + [
                {"role": "user", "content": request_message}
            ]
            self._append_report(
                "participant_request_started",
                participant=participant_name,
                route_id=route_id,
                mode=mode,
                prompt=message,
                provider=status["provider"],
                model=status["model"],
                common_history_count=len(common_context),
                private_history_count=len(private_context),
            )

            def run_chat() -> None:
                try:
                    self._append_report(
                        "participant_api_request_sent",
                        participant=participant_name,
                        route_id=route_id,
                        mode=mode,
                        provider=status["provider"],
                        model=status["model"],
                        history_count=len(request_history),
                    )
                    result = self.message_distributor.dispatch_message(
                        self.user_data_dir,
                        participant_name,
                        request_message,
                        mode=mode,
                        history=request_history,
                        report=lambda event, **data: self._append_report(
                            "participant_" + event,
                            **{"participant": participant_name, **data},
                        ),
                    )
                    response = result["response"]
                    event = (
                        "participant_api_response_received",
                        {
                            "participant": participant_name,
                            "route_id": route_id,
                            "mode": mode,
                            "provider": result["provider"],
                            "model": result["model"],
                            "response": response,
                        },
                    )
                    text_value = response
                except Exception as exc:
                    event = (
                        "participant_request_failed",
                        {
                            "participant": participant_name,
                            "route_id": route_id,
                            "mode": mode,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        },
                    )
                    text_value = f"FAILED: {type(exc).__name__}: {exc}"

                def finish(*_finish_args: Any) -> None:
                    self._append_report(event[0], **event[1])
                    if event[0] == "participant_api_response_received":
                        exchange = [
                            {"role": "user", "content": message},
                            {"role": "assistant", "content": text_value},
                        ]
                        self.private_histories.setdefault(participant_name, []).extend(exchange)
                        self.workspace.save_named_history(
                            participant_name, self.private_histories[participant_name]
                        )
                        last_exchange["messages"] = exchange
                        last_exchange["published"] = False
                        history_text = "\n\n".join(
                            f"{'You' if item['role'] == 'user' else participant_name}:\n{item['content']}"
                            for item in self.private_histories[participant_name]
                        )
                        output.text = history_text
                    else:
                        output.text += f"\n\n{text_value}"
                    send.disabled = False

                Clock.schedule_once(finish, 0)

            from threading import Thread
            Thread(
                target=run_chat,
                name=f"yj64-{participant_name.lower().replace(' ', '-')}-chat",
                daemon=True,
            ).start()

        send.bind(on_release=send_message)
        publish.bind(on_release=publish_last_exchange)
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def _open_group_dialogue(self, *_: Any) -> None:
        self.message_distributor.set_private_participant(None)
        participants = [
            name
            for name in ("Participant 1", "Participant 2", "Participant 3")
            if self._participant_config_status(name)["configured"]
        ]
        if len(participants) < 2:
            self._append_report(
                "group_dialogue_start_rejected",
                reason="at_least_two_participants_required",
                participants=participants,
            )
            self.status.text = "Configure at least two participants first."
            return

        self.message_distributor.reset_queue()
        self._append_report(
            "group_dialogue_opened",
            participants=participants,
            mode=self.message_distributor.mode,
            route_ids={
                name: self.message_distributor.route_for_participant(name)
                for name in participants
            },
        )
        content = BoxLayout(orientation="vertical", spacing=8, padding=12)
        output = TextInput(
            text="Group dialogue is ready.\n",
            readonly=True,
            multiline=True,
        )
        prompt = TextInput(
            hint_text="Your question to the participants...",
            multiline=True,
            size_hint_y=None,
            height=110,
            write_tab=False,
        )
        cycle_row = BoxLayout(spacing=8, size_hint_y=None, height=48)
        cycle_row.add_widget(Label(text="Rounds per participant:", size_hint_x=0.65))
        cycles_input = TextInput(
            text="3", multiline=False, input_filter="int", size_hint_x=0.35,
        )
        cycle_row.add_widget(cycles_input)
        controls = BoxLayout(
            spacing=8,
            size_hint_y=None,
            height=54,
        )
        toggle = Button(
            text="START GROUP DIALOGUE",
            size_hint_x=1,
            background_color=(0.85, 0.2, 0.2, 1),
        )
        controls.add_widget(toggle)
        close = Button(text="CLOSE", size_hint_y=None, height=54)
        content.add_widget(output)
        content.add_widget(prompt)
        content.add_widget(cycle_row)
        content.add_widget(controls)
        content.add_widget(close)

        popup = Popup(
            title="GROUP DIALOGUE",
            content=content,
            size_hint=(0.95, 0.86),
            auto_dismiss=False,
        )

        state = {
            "running": False,
            "stop_requested": False,
        }

        def append_chat(text_value: str) -> None:
            output.text = output.text.rstrip() + "\n" + text_value + "\n"

        def request_stop(*_args: Any) -> None:
            state["stop_requested"] = True
            self.message_distributor.set_dialogue_enabled(False)
            toggle.text = "START GROUP DIALOGUE"
            toggle.background_color = (0.85, 0.2, 0.2, 1)
            self._append_report("group_dialogue_stop_requested")
            append_chat("[STOP REQUESTED] Waiting for the current request to finish.")

        def run_dialogue(question: str, max_cycles: int) -> None:
            messages: list[dict[str, str]] = [
                {"speaker": "Owner", "text": question}
            ]
            seen_by = {name: 0 for name in participants}
            turn = 0
            self._append_report(
                "group_dialogue_started",
                participants=participants,
                question=question,
                max_cycles=max_cycles,
                max_turns=max_cycles * len(participants),
            )

            while (
                turn < max_cycles * len(participants)
                and not state["stop_requested"]
                and self.message_distributor.dialogue_enabled
            ):
                participant = self.message_distributor.next_participant(participants)
                status = self._participant_config_status(participant)
                history: list[dict[str, str]] = []
                for item in messages:
                    role = "assistant" if item["speaker"] == participant else "user"
                    history.append({
                        "role": role,
                        "content": f"{item['speaker']}: {item['text']}",
                    })
                request_text = self._practical_instructions(messages[-1]["text"])
                if history:
                    history[-1]["content"] = request_text
                new_count = len(messages) - seen_by[participant]
                self._append_report(
                    "group_dialogue_turn_started",
                    participant=participant,
                    turn=turn + 1,
                    new_messages=new_count,
                )
                Clock.schedule_once(
                    lambda _dt, p=participant: append_chat(f"\n[{p} is thinking...]"),
                    0,
                )
                try:
                    result = self.message_distributor.dispatch_message(
                        self.user_data_dir,
                        participant,
                        request_text,
                        history=history,
                        report=lambda event, **data: self._append_report(
                            "group_dialogue_" + event,
                            **{"participant": participant, **data},
                        ),
                    )
                    response = result["response"]
                    messages.append({"speaker": participant, "text": response})
                    seen_by[participant] = len(messages)
                    self._append_report(
                        "group_dialogue_turn_completed",
                        participant=participant,
                        turn=turn + 1,
                        response=response,
                        unseen_messages=new_count,
                    )
                    Clock.schedule_once(
                        lambda _dt, p=participant, r=response:
                        append_chat(f"{p}:\n{r}"),
                        0,
                    )
                except Exception as exc:
                    self._append_report(
                        "group_dialogue_turn_failed",
                        participant=participant,
                        turn=turn + 1,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    Clock.schedule_once(
                        lambda _dt, p=participant, e=exc:
                        append_chat(f"{p} FAILED: {type(e).__name__}: {e}"),
                        0,
                    )
                    break
                turn += 1
            state["running"] = False
            self.message_distributor.set_dialogue_enabled(False)
            def finish_dialogue_ui(_dt: float) -> None:
                toggle.text = "START GROUP DIALOGUE"
                toggle.background_color = (0.85, 0.2, 0.2, 1)
            Clock.schedule_once(finish_dialogue_ui, 0)
            self._append_report(
                "group_dialogue_stopped",
                participants=participants,
                turns=turn,
                stop_requested=state["stop_requested"],
            )

        def start_dialogue(*_args: Any) -> None:
            if state["running"]:
                request_stop()
                return
            question = prompt.text.strip()
            if not question:
                return
            try:
                max_cycles = int(cycles_input.text or "3")
            except ValueError:
                cycles_input.text = "3"
                self.status.text = "Dialogue rounds must be a number from 1 to 20."
                return
            if not 1 <= max_cycles <= 20:
                self.status.text = "Dialogue rounds must be between 1 and 20."
                return
            self.message_distributor.set_dialogue_enabled(True)
            state["running"] = True
            state["stop_requested"] = False
            prompt.text = ""
            toggle.text = "STOP GROUP DIALOGUE"
            toggle.background_color = (0.2, 0.7, 0.3, 1)
            output.text = "Group dialogue started.\n"
            from threading import Thread
            Thread(
                target=run_dialogue,
                args=(question, max_cycles),
                name="yj64-group-dialogue",
                daemon=True,
            ).start()

        toggle.bind(on_release=start_dialogue)
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.open()

    def _process_name(self) -> str:
        try:
            from jnius import autoclass
            return str(autoclass("android.os.Process").myProcessName())
        except Exception:
            return "unknown"

    def _write_main_pid(self) -> None:
        try:
            self.pid_path.parent.mkdir(parents=True, exist_ok=True)
            self.pid_path.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass

    def _append_report(self, event: str, **data: Any) -> None:
        try:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "schema": "yj64.diagnostic.v1",
                "agent": "yj64-base-application",
                "event": event,
                "timestamp_ms": int(time.time() * 1000),
                "monotonic_ns": time.monotonic_ns(),
                "message_id": f"APP-{uuid.uuid4().hex}",
                "data": data,
            }
            with self.report_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            pass

    def _open_monitor(self, *_: Any) -> None:
        self._append_report(
            "internal_monitor_window_requested",
            main_pid=os.getpid(),
            main_process_name=self._process_name(),
        )
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            monitor_activity = autoclass(MONITOR_ACTIVITY_CLASS)
            intent = autoclass("android.content.Intent")(activity, monitor_activity)
            # Keep the monitor in its own Android task.  The base app task
            # remains alive in the background and can be returned to from Recents.
            intent.addFlags(
                0x10000000  # FLAG_ACTIVITY_NEW_TASK
                | 0x00020000  # FLAG_ACTIVITY_REORDER_TO_FRONT
            )
            activity.startActivity(intent)
            self.status.text = "Internal Monitor window requested."
        except Exception as exc:
            self.status.text = (
                "Internal Monitor window failed: "
                f"{type(exc).__name__}: {exc}"
            )

    def _open_llm_settings(self, *_: Any) -> None:
        self._append_report("llm_settings_open_requested")
        try:
            self._append_report("llm_settings_import_started")
            from llm_settings import LLMSettingsPopup
            self._append_report("llm_settings_import_succeeded")
            popup = LLMSettingsPopup(
                self.user_data_dir,
                route_id="route_owner",
                on_report=lambda event, **data: self._append_report(
                    "router_settings_" + event, **data
                ),
                on_copy=self._copy_to_clipboard,
            )
            self._append_report("llm_settings_popup_created")
            popup.open()
            self._append_report("llm_settings_popup_opened")
        except Exception as exc:
            import traceback
            self._append_report(
                "llm_settings_open_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            self.status.text = (
                "LLM settings failed: "
                f"{type(exc).__name__}: {exc}"
            )

    def _test_llm_api(self, *_: Any) -> None:
        self._append_report("llm_api_test_started", scope="configured_participants")
        self.status.text = "Testing all configured participant connections..."

        def run_test() -> None:
            try:
                from llm_api import test_all_routes
                result = test_all_routes(
                    self.user_data_dir,
                    include_owner=False,
                    report=lambda event, **data: self._append_report(
                        "llm_api_" + event, **data
                    ),
                )
                report = result["report"]
                passed = sum(1 for item in result["results"] if item["status"] == "PASS")
                failed = len(result["results"]) - passed
                event = (
                    "llm_api_test_completed",
                    {
                        "scope": "configured_participants",
                        "tested_count": len(result["results"]),
                        "passed": passed,
                        "failed": failed,
                        "route_ids": [item["route_id"] for item in result["results"]],
                    },
                )
            except Exception as exc:
                report = (
                    "YJ-64 LLM API TEST — ALL PARTICIPANTS\n"
                    "Result: FAILED\n"
                    f"Error: {type(exc).__name__}: {exc}"
                )
                event = (
                    "llm_api_test_failed",
                    {
                        "scope": "configured_participants",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )

            def finish(*_args: Any) -> None:
                self._append_report(event[0], **event[1])
                self._copy_to_clipboard(report)
                self.status.text = report

            Clock.schedule_once(finish, 0)

        from threading import Thread
        Thread(target=run_test, name="yj64-llm-api-test-all-participants", daemon=True).start()

    def _test_llm_generation(self, *_: Any) -> None:
        prompt = "Reply with exactly: YJ64_OK"
        if not self.message_distributor.dialogue_enabled:
            self._append_report(
                "llm_generation_test_rejected",
                reason="dialogue_stopped",
                prompt=prompt,
            )
            self.status.text = "Dialogue is stopped. Resume it before sending new LLM requests."
            return

        target = self._chat_target_details()
        participant = target["participant"]
        route_id = target["route_id"]
        if not target["connected_participants"]:
            report_text = (
                "YJ-64 LLM GENERATION TEST — COMMON CHAT\n"
                "Result: FAILED\n"
                "Error: No configured participant connection is available."
            )
            self._append_report(
                "llm_generation_test_failed",
                scope="common_chat",
                route_id=route_id,
                error="No configured participant connection is available.",
            )
            self._copy_to_clipboard(report_text)
            self.chat_output.text += f"\n\n{report_text}"
            self.status.text = report_text
            return

        from llm_api import load_config
        config = load_config(self.user_data_dir, route_id=route_id)
        mode = "agent" if (config.get("agent_id") or "").strip() else "text"
        # Select mode for this route only; tests must not mutate the global chat mode.
        self._append_report(
            "llm_generation_test_chat_mode_selected",
            participant=participant,
            route_id=route_id,
            mode=mode,
            reason="match_configured_connection_test",
        )
        self._append_report(
            "llm_generation_test_started",
            scope="common_chat",
            prompt=prompt,
            participant=participant,
            route_id=route_id,
            mode=mode,
            connected_participants=target["connected_participants"],
            reason=target["reason"],
        )
        self.chat_output.text += (
            f"\n\nUser: {prompt}\nParticipant: {participant}\n"
            f"Route: {route_id} / {mode}\nTest request sent..."
        )
        self.status.text = f"Sending generation test through chat: {participant} / {route_id} / {mode}..."

        def run_test() -> None:
            try:
                result = self.message_distributor.dispatch_message(
                    self.user_data_dir,
                    participant,
                    prompt,
                    mode=mode,
                    report=lambda event, **data: self._append_report(
                        "llm_generation_chat_" + event, **data
                    ),
                )
                report_text = (
                    "YJ-64 LLM GENERATION TEST — COMMON CHAT\n"
                    f"Participant: {participant}\n"
                    f"Route: {route_id}\n"
                    f"Mode: {mode}\n"
                    f"Provider: {result['provider']}\n"
                    f"Model: {result['model']}\n"
                    f"Prompt: {prompt}\n"
                    "Result: SUCCESS\n"
                    f"Response: {result['response']}"
                )
                event = (
                    "llm_generation_test_completed",
                    {
                        "scope": "common_chat",
                        "participant": participant,
                        "route_id": route_id,
                        "mode": mode,
                        "provider": result["provider"],
                        "model": result["model"],
                        "prompt": prompt,
                        "response": result["response"],
                    },
                )
                chat_result = f"{participant}: {result['response']}"
            except Exception as exc:
                report_text = (
                    "YJ-64 LLM GENERATION TEST — COMMON CHAT\n"
                    f"Participant: {participant}\n"
                    f"Route: {route_id}\n"
                    f"Mode: {mode}\n"
                    f"Prompt: {prompt}\n"
                    "Result: FAILED\n"
                    f"Error: {type(exc).__name__}: {exc}"
                )
                event = (
                    "llm_generation_test_failed",
                    {
                        "scope": "common_chat",
                        "participant": participant,
                        "route_id": route_id,
                        "mode": mode,
                        "prompt": prompt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
                chat_result = f"{participant}: FAILED — {type(exc).__name__}: {exc}"

            def finish(*_args: Any) -> None:
                self._append_report(event[0], **event[1])
                self._copy_to_clipboard(report_text)
                self.chat_output.text += f"\n{chat_result}"
                self.status.text = report_text

            Clock.schedule_once(finish, 0)

        from threading import Thread
        Thread(
            target=run_test,
            name="yj64-llm-generation-test-common-chat",
            daemon=True,
        ).start()

    def _chat_input_focus_changed(self, _instance: Any, focused: bool) -> None:
        self._append_report("llm_chat_input_focus_changed", focused=focused)

    def _chat_target_details(self) -> dict[str, Any]:
        from llm_api import route_config_exists

        connected = [
            name for name in ("Participant 1", "Participant 2", "Participant 3")
            if self._participant_config_status(name)["configured"]
        ]
        owner_connected = route_config_exists(self.user_data_dir, "route_owner")
        preferred = self.message_distributor.active_participant
        if preferred and self._participant_config_status(preferred)["configured"]:
            participant = preferred
            reason = "preferred_configured_participant"
        elif connected:
            participant = connected[0]
            reason = "first_configured_participant"
        else:
            participant = "Owner"
            reason = "owner_fallback"
        return {
            "participant": participant,
            "route_id": self.message_distributor.route_for_participant(participant),
            "connected_participants": connected,
            "owner_connected": owner_connected,
            "preferred": preferred,
            "reason": reason,
        }

    def _test_llm_chat_route(self, *_: Any) -> None:
        prompt = "Reply with exactly: YJ64_OK"
        if not self.message_distributor.dialogue_enabled:
            self._append_report(
                "llm_chat_route_test_rejected",
                reason="dialogue_stopped",
                prompt=prompt,
            )
            self.status.text = "Dialogue is stopped. Resume it before sending new LLM requests."
            return

        target = self._chat_target_details()
        participant = target["participant"]
        route_id = target["route_id"]
        mode = self._participant_config_status(participant)["mode"]
        self._append_report(
            "llm_chat_route_test_started",
            prompt=prompt,
            participant=participant,
            route_id=route_id,
            mode=mode,
            connected_participants=target["connected_participants"],
            owner_connected=target["owner_connected"],
            preferred=target["preferred"],
            reason=target["reason"],
        )
        self.status.text = f"Testing common-chat route: {participant} / {route_id} / {mode}..."

        def run_test() -> None:
            try:
                result = self.message_distributor.dispatch_message(
                    self.user_data_dir,
                    participant,
                    prompt,
                    mode=mode,
                    report=lambda event, **data: self._append_report(
                        "llm_chat_route_test_" + event, **data
                    ),
                )
                report_text = (
                    "YJ-64 COMMON CHAT ROUTE TEST\n"
                    f"Participant: {participant}\n"
                    f"Route: {route_id}\n"
                    f"Mode: {mode}\n"
                    f"Provider: {result['provider']}\n"
                    f"Model: {result['model']}\n"
                    f"Prompt: {prompt}\n"
                    "Result: SUCCESS\n"
                    f"Response: {result['response']}"
                )
                event = (
                    "llm_chat_route_test_succeeded",
                    {
                        "participant": participant,
                        "route_id": route_id,
                        "mode": mode,
                        "provider": result["provider"],
                        "model": result["model"],
                        "prompt": prompt,
                        "response": result["response"],
                    },
                )
            except Exception as exc:
                report_text = (
                    "YJ-64 COMMON CHAT ROUTE TEST\n"
                    f"Participant: {participant}\n"
                    f"Route: {route_id}\n"
                    f"Mode: {mode}\n"
                    f"Prompt: {prompt}\n"
                    "Result: FAILED\n"
                    f"Error: {type(exc).__name__}: {exc}"
                )
                event = (
                    "llm_chat_route_test_failed",
                    {
                        "participant": participant,
                        "route_id": route_id,
                        "mode": mode,
                        "prompt": prompt,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )

            def finish(*_args: Any) -> None:
                self._append_report(event[0], **event[1])
                self._copy_to_clipboard(report_text)
                self.chat_output.text = report_text
                self.status.text = report_text

            Clock.schedule_once(finish, 0)

        from threading import Thread
        Thread(
            target=run_test,
            name="yj64-common-chat-route-test",
            daemon=True,
        ).start()

    def _send_llm_chat(self, *_: Any) -> None:
        prompt = self.chat_input.text.strip()
        if not prompt:
            return
        if not self.message_distributor.dialogue_enabled:
            self._append_report(
                "llm_chat_send_rejected",
                reason="dialogue_stopped",
                prompt=prompt,
            )
            self.status.text = "Dialogue is stopped. Resume it before sending new LLM requests."
            return

        target_details = self._chat_target_details()
        participants = list(target_details["connected_participants"])
        if not participants and target_details["owner_connected"]:
            participants = ["Owner"]
        if not participants:
            self._append_report(
                "llm_chat_send_rejected",
                reason="no_configured_connections",
                prompt=prompt,
            )
            self.chat_output.text += (
                f"\n\nUser: {prompt}\nNo configured participant connections are available."
            )
            self.status.text = "No configured participant connections are available."
            self.chat_input.text = ""
            return

        implementation_request = prompt.startswith("IMPLEMENTATION PHASE.")
        request_prompt = self._practical_instructions(
            prompt,
            implementation=implementation_request,
        )
        request_history = list(self.common_history) + [
            {"role": "user", "content": request_prompt}
        ]
        targets = []
        for name in participants:
            details = self._participant_config_status(name)
            targets.append({
                "participant": name,
                "route_id": str(details["route_id"]),
                "mode": str(details["mode"]),
                "provider": str(details["provider"]),
                "model": str(details["model"]),
            })
        self._append_report(
            "llm_chat_broadcast_started",
            prompt=prompt,
            participants=[item["participant"] for item in targets],
            route_ids={item["participant"]: item["route_id"] for item in targets},
            history_count=len(request_history),
        )
        for target in targets:
            self._append_report(
                "llm_chat_send_started",
                prompt=prompt,
                participant=target["participant"],
                route_id=target["route_id"],
                mode=target["mode"],
                history_count=len(request_history),
                broadcast=True,
            )
        self.status.text = (
            "Sending common-chat message to: "
            + ", ".join(item["participant"] for item in targets)
        )
        self.chat_input.text = ""
        self.chat_output.text += (
            f"\n\nOwner: {prompt}\n"
            + "\n".join(f"{item['participant']}: waiting for response..." for item in targets)
        )

        def run_participant(target: dict[str, str]) -> dict[str, Any]:
            participant_name = target["participant"]
            try:
                result = self.message_distributor.dispatch_message(
                    self.user_data_dir,
                    participant_name,
                    request_prompt,
                    mode=target["mode"],
                    history=request_history,
                    report=lambda event, _participant=participant_name, **data:
                    self._append_report(
                        "llm_chat_" + event,
                        **{"participant": _participant, "broadcast": True, **data},
                    ),
                )
                return {
                    "participant": participant_name,
                    "route_id": result.get("route_id", target["route_id"]),
                    "mode": target["mode"],
                    "provider": result["provider"],
                    "model": result["model"],
                    "response": result["response"],
                    "ok": True,
                }
            except Exception as exc:
                return {
                    "participant": participant_name,
                    "route_id": target["route_id"],
                    "mode": target["mode"],
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }

        def run_chat() -> None:
            from concurrent.futures import ThreadPoolExecutor

            outcomes: dict[str, dict[str, Any]] = {}
            with ThreadPoolExecutor(
                max_workers=len(targets),
                thread_name_prefix="yj64-common-chat",
            ) as executor:
                futures = {
                    target["participant"]: executor.submit(run_participant, target)
                    for target in targets
                }
                for target in targets:
                    outcomes[target["participant"]] = futures[target["participant"]].result()

            def finish(*_args: Any) -> None:
                lines = [f"Owner: {prompt}"]
                successful = 0
                history_additions: list[dict[str, str]] = [
                    {"role": "user", "content": prompt}
                ]
                for target in targets:
                    outcome = outcomes[target["participant"]]
                    participant_name = outcome["participant"]
                    if outcome["ok"]:
                        successful += 1
                        response = str(outcome["response"])
                        lines.append(
                            f"{participant_name} ({outcome['provider']} / {outcome['model']}):\n{response}"
                        )
                        self._append_report(
                            "llm_chat_send_succeeded",
                            participant=participant_name,
                            route_id=outcome["route_id"],
                            mode=outcome["mode"],
                            provider=outcome["provider"],
                            model=outcome["model"],
                            prompt=prompt,
                            response=response,
                            broadcast=True,
                        )
                        history_additions.append({
                            "role": "assistant",
                            "content": f"{participant_name}: {response}",
                        })
                    else:
                        error_text = (
                            f"{outcome['error_type']}: {outcome['error']}"
                        )
                        lines.append(f"{participant_name} FAILED:\n{error_text}")
                        self._append_report(
                            "llm_chat_send_failed",
                            participant=participant_name,
                            route_id=outcome["route_id"],
                            mode=outcome["mode"],
                            prompt=prompt,
                            error_type=outcome["error_type"],
                            error=outcome["error"],
                            broadcast=True,
                        )
                self.common_history.extend(history_additions)
                self._save_common_history()
                if self.practical_mode and not implementation_request:
                    votes = {
                        name: (
                            "APPROVE"
                            if "[CONSENSUS: APPROVE]" in str(outcomes[name].get("response", ""))
                            and "[CONSENSUS: OBJECT]" not in str(outcomes[name].get("response", ""))
                            else "OBJECT"
                            if "[CONSENSUS: OBJECT]" in str(outcomes[name].get("response", ""))
                            else "NO_VOTE"
                        )
                        for name in outcomes
                        if outcomes[name].get("ok")
                    }
                    all_connected_approved = (
                        len(targets) >= 2
                        and len(votes) == len(targets)
                        and all(vote == "APPROVE" for vote in votes.values())
                    )
                    self.consensus_reached = all_connected_approved
                    self.consensus_summary = (
                        ", ".join(f"{name}={vote}" for name, vote in votes.items())
                        if votes else "No successful model responses"
                    )
                    self.implementation_button.disabled = not self.consensus_reached
                    self.implementation_button.text = (
                        "НАЧАТЬ РЕАЛИЗАЦИЮ ЧЕРЕЗ ПОДКЛЮЧЁННЫХ АГЕНТОВ"
                        if self.consensus_reached
                        else "РЕАЛИЗАЦИЯ ЗАКРЫТА — НЕТ ПОЛНОГО КОНСЕНСУСА"
                    )
                    self._append_report(
                        "practical_consensus_evaluated",
                        reached=self.consensus_reached,
                        votes=votes,
                        summary=self.consensus_summary,
                        connected_participants=[item["participant"] for item in targets],
                        rule="every connected participant must return [CONSENSUS: APPROVE] in this response round",
                    )
                    self.status.text = (
                        "Consensus reached. Implementation draft can be requested."
                        if self.consensus_reached
                        else "Practical mode: consensus not reached. Review model votes and continue discussion."
                    )
                elif implementation_request:
                    self._append_report(
                        "agent_implementation_draft_completed",
                        participants=[item["participant"] for item in targets],
                        successful=sum(1 for item in outcomes.values() if item.get("ok")),
                        note="LLM-generated draft only; no repository write or code execution occurred.",
                    )
                self._append_report(
                    "llm_chat_broadcast_completed",
                    prompt=prompt,
                    participants=[item["participant"] for item in targets],
                    successful=successful,
                    failed=len(targets) - successful,
                )
                self.chat_output.text += "\n\n" + "\n\n".join(lines[1:])
                self._save_common_history()
                if self.practical_mode and not implementation_request:
                    self.status.text = (
                        "Consensus reached. Implementation draft is unlocked."
                        if self.consensus_reached
                        else "Practical mode: consensus not reached; review votes and continue discussion."
                    )
                elif implementation_request:
                    self.status.text = (
                        f"Implementation drafts returned by {successful}/{len(targets)} connected LLMs. "
                        "No repository files were changed by this action."
                    )
                else:
                    self.status.text = (
                        f"Common chat completed: {successful}/{len(targets)} participants answered."
                    )

            Clock.schedule_once(finish, 0)

        from threading import Thread
        Thread(target=run_chat, name="yj64-llm-chat-broadcast", daemon=True).start()

    def _copy_to_clipboard(self, text: str) -> None:
        try:
            from jnius import autoclass
            context = autoclass("org.kivy.android.PythonActivity").mActivity
            clipboard = context.getSystemService(
                autoclass("android.content.Context").CLIPBOARD_SERVICE
            )
            clip = autoclass("android.content.ClipData").newPlainText(
                "YJ-64 LLM API report", text
            )
            clipboard.setPrimaryClip(clip)
        except Exception as exc:
            self._append_report(
                "llm_api_clipboard_failed",
                error_type=type(exc).__name__,
                error=str(exc),
            )

    def _poll_test_command(self, *_: Any) -> None:
        command_path = Path(self.user_data_dir) / TEST_COMMAND_RELATIVE_PATH
        if not command_path.is_file():
            return
        try:
            command = json.loads(command_path.read_text(encoding="utf-8"))
            command_path.unlink()
        except (OSError, ValueError):
            return
        if command.get("action") != "full_test":
            return
        test_id = str(command.get("test_id") or uuid.uuid4().hex)
        self._run_full_function_test(test_id)

    def _run_full_function_test(self, test_id: str) -> None:
        from threading import Thread

        def step(name: str, action: Any) -> tuple[bool, str]:
            self._append_report("full_test_step_started", test_id=test_id, step=name)
            try:
                result = action()
                self._append_report(
                    "full_test_step_completed",
                    test_id=test_id,
                    step=name,
                    result=result,
                )
                return True, str(result)
            except Exception as exc:
                self._append_report(
                    "full_test_step_failed",
                    test_id=test_id,
                    step=name,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return False, f"{type(exc).__name__}: {exc}"

        def worker() -> None:
            self._append_report("full_test_started", test_id=test_id)
            results: list[str] = []

            ok, value = step("report_storage", lambda: f"report_exists={self.report_path.is_file()}")
            results.append(f"report_storage: {'PASS' if ok else 'FAIL'} ({value})")

            ok, value = step(
                "process_identity",
                lambda: f"pid={os.getpid()},process={self._process_name()}",
            )
            results.append(f"process_identity: {'PASS' if ok else 'FAIL'} ({value})")

            def config_check() -> str:
                from llm_api import load_config
                config = load_config(self.user_data_dir)
                if not config.get("api_key"):
                    raise RuntimeError("LLM API key is not configured")
                if not config.get("model"):
                    raise RuntimeError("LLM model is not configured")
                return f"provider={config.get('provider')},model={config.get('model')}"

            ok, value = step("llm_config", config_check)
            results.append(f"llm_config: {'PASS' if ok else 'FAIL'} ({value})")

            def api_check() -> str:
                from llm_api import test_llm_api
                return str(test_llm_api(
                    self.user_data_dir,
                    report=lambda event, **data: self._append_report(
                        "full_test_llm_api_" + event,
                        test_id=test_id,
                        **data,
                    ),
                )["result"])

            ok, value = step("llm_api", api_check)
            results.append(f"llm_api: {'PASS' if ok else 'FAIL'} ({value})")

            def generation_check() -> str:
                from llm_api import generate_test_response
                result = generate_test_response(
                    self.user_data_dir,
                    report=lambda event, **data: self._append_report(
                        "full_test_llm_generation_" + event,
                        test_id=test_id,
                        **data,
                    ),
                )
                return str(result["response"])

            ok, value = step("llm_generation", generation_check)
            results.append(f"llm_generation: {'PASS' if ok else 'FAIL'} ({value})")

            ok, value = step(
                "diagnostic_agent_status",
                lambda: (
                    "status_file_present"
                    if (Path(self.user_data_dir) / "diagnostic-agent-status.json").is_file()
                    else "status_file_missing"
                ),
            )
            results.append(f"diagnostic_agent_status: {'PASS' if ok else 'FAIL'} ({value})")

            summary = "YJ-64 FULL FUNCTION TEST\n" + "\n".join(results)
            self._append_report("full_test_completed", test_id=test_id, summary=summary)
            result_path = Path(self.user_data_dir) / TEST_RESULT_RELATIVE_PATH
            try:
                result_path.write_text(
                    json.dumps(
                        {
                            "test_id": test_id,
                            "completed": True,
                            "summary": summary,
                            "timestamp_ms": int(time.time() * 1000),
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                self._append_report(
                    "full_test_result_write_failed",
                    test_id=test_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )

            def finish(_dt: float) -> None:
                self._copy_to_clipboard(str(self.report_path))
                self.status.text = summary
            Clock.schedule_once(finish, 0)

        Thread(target=worker, name="yj64-full-function-test", daemon=True).start()

    def _read_report_text(self) -> str:
        try:
            return self.report_path.read_text(encoding="utf-8")
        except OSError as exc:
            return f"YJ-64 REPORT READ FAILED: {type(exc).__name__}: {exc}"

    def _launched_by_internal_agent(self) -> bool:
        try:
            from jnius import autoclass
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            return bool(activity.getIntent().getBooleanExtra(
                SERVICE_LAUNCH_FLAG, False
            ))
        except Exception:
            return False

    def _ensure_service_started(self, *_: Any) -> None:
        if self._launched_by_internal_agent():
            self.status.text = (
                "Base application started by the internal diagnostic agent."
            )
            return
        try:
            from jnius import autoclass
            service_class = autoclass(SERVICE_CLASS)
            activity = autoclass("org.kivy.android.PythonActivity").mActivity
            service_class.start(activity, "")
            self.status.text = (
                "Diagnostic agent starting first; waiting for self-diagnostic "
                "and bridge handshake..."
            )
        except Exception as exc:
            self.status.text = (
                "Diagnostic agent start failed: "
                f"{type(exc).__name__}: {exc}"
            )

    def _refresh_status(self, *_: Any) -> None:
        path = Path(self.user_data_dir) / "diagnostic-agent-status.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.status.text = (
            "Embedded diagnostic agent\n"
            f"Bridge: {data.get('bridge_status', 'unknown')}\n"
            f"Self-diagnostic: {data.get('self_diagnostic', 'unknown')}\n"
            f"Base app: {data.get('target_launch', 'unknown')}\n"
            f"Last event: {data.get('event', 'unknown')}"
        )

    def on_start(self) -> None:
        self._append_report(
            "base_activity_started",
            pid=os.getpid(),
            process_name=self._process_name(),
        )

    def on_resume(self) -> None:
        self._append_report("base_activity_resumed")

    def on_pause(self) -> bool:
        self._append_report("base_activity_paused")
        return True

    def on_stop(self) -> None:
        self._append_report("base_activity_stopped")


YJ64BaseApp().run()
