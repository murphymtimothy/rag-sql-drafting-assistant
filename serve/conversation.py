"""Translate an OpenAI messages array into (question, history) and detect Open WebUI's
housekeeping ('task') prompts that must NOT be run through the SQL pipeline."""

# Open WebUI fires these at the selected model for titles/tags/queries/autocomplete.
# Primary mitigation is configuring a separate Task Model in OWUI (see OPEN_WEBUI_SETUP.md);
# this detection is a best-effort backup so they don't burn GPU on the SQL pipeline.
_TASK_MARKERS = (
    "create a concise, 3-5 word title",
    "generate 1-3 broad tags",
    "### task:",
    "generate a concise",
    "autocomplete",
)

TASK_CANNED_RESPONSE = "Schema query"


def split_messages(messages) -> tuple[str, list[dict]]:
    """Return (question, history). question = the last user message; history = the prior
    user/assistant turns (system messages dropped — this service owns the system prompt)."""
    convo = [m for m in messages if m.role in ("user", "assistant")]
    last_user = next((i for i in range(len(convo) - 1, -1, -1) if convo[i].role == "user"), None)
    if last_user is None:
        return "", []
    question = convo[last_user].content
    history = [{"role": m.role, "content": m.content} for m in convo[:last_user]]
    return question, history


def is_task_prompt(messages) -> bool:
    """True if the request looks like an Open WebUI housekeeping task (title/tag/etc.)."""
    text = "\n".join(m.content for m in messages).lower()
    return any(marker in text for marker in _TASK_MARKERS)
