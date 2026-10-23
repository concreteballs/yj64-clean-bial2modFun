# YJ-64 LOCAL SKILLS

Human-readable semantic summary. Structured events, state, and tasks live in `yj64_memory.sqlite3`.

## Operating rules
- Do not store API keys, passwords, or access tokens in summaries.
- Keep API context bounded; include only the recent messages needed.
- Run routine observer ticks locally without LLM calls.
- Record route, request-body byte count, history count, duration, and result.
- Never substitute one participant's answer for another participant.
- Keep the full diagnostic archive separate from short semantic summaries.
