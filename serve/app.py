"""FastAPI app exposing answer_question() as an OpenAI-compatible endpoint."""
import json
import logging
import time
import uuid

import openai
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from assistant.sql_assistant import answer_question
from serve import conversation
from serve.auth import require_auth
from serve.config import get_settings
from serve.schemas import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    Choice,
    ModelCard,
    ModelList,
)


def _format_content(result: dict) -> str:
    """Assistant message = the model's explanation, with the validation verdict appended
    when validate_sql flagged the draft (so the analyst sees it in the GUI)."""
    content = result.get("explanation") or ""
    v = result.get("validation") or {}
    if not v.get("ok", True) and v.get("errors"):
        bullets = "\n".join(f"> - {e}" for e in v["errors"])
        content += (
            "\n\n---\n> ⚠️ Automated validation flagged this draft — "
            "review before running:\n" + bullets
        )
    return content


def _operational_error_message(exc: Exception) -> str:
    """Turn a pipeline error into a GUI-friendly assistant message (not a red HTTP error)."""
    if isinstance(exc, openai.APIConnectionError):
        return ("⚠️ The model backend (Ollama) is unreachable. "
                "Make sure Ollama is running, then retry.")
    msg = str(exc)
    if "build_index" in msg:
        return ("⚠️ The schema index isn't built yet. Run "
                "`python ingest/build_index.py` on the host, then retry.")
    return f"⚠️ The assistant backend couldn't draft SQL: {msg}"


def _generate_content(question: str, history: list[dict]) -> str:
    """Run the pipeline (blocking) and format the assistant message. Operational errors
    become a friendly message rather than a 500."""
    try:
        result = answer_question(question, rag_enabled=True, history=history)
    except (RuntimeError, openai.OpenAIError) as exc:
        logging.getLogger(__name__).error("pipeline error: %s", exc)
        return _operational_error_message(exc)
    return _format_content(result)


def create_app() -> FastAPI:
    settings = get_settings()
    settings.require_token()  # fail-closed: refuse to start without a token
    app = FastAPI(title="CU SQL Assistant API")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/models", dependencies=[Depends(require_auth)])
    def list_models():
        return ModelList(data=[ModelCard(id=settings.model_id, created=int(time.time()))])

    def _json_response(content: str) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex}",
            created=int(time.time()),
            model=settings.model_id,
            choices=[Choice(message=ChatMessage(role="assistant", content=content))],
        )

    def _chunk(cid, created, delta, finish=None) -> str:
        payload = {
            "id": cid, "object": "chat.completion.chunk", "created": created,
            "model": settings.model_id,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    async def _sse(produce):
        # Emit the role chunk immediately to hold the connection, then run generation.
        cid, created = f"chatcmpl-{uuid.uuid4().hex}", int(time.time())
        yield _chunk(cid, created, {"role": "assistant"})
        content = await produce()
        yield _chunk(cid, created, {"content": content})
        yield _chunk(cid, created, {}, finish="stop")
        yield "data: [DONE]\n\n"

    @app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
    async def chat_completions(req: ChatCompletionRequest):
        if req.model and req.model != settings.model_id:
            raise HTTPException(status_code=404, detail=f"Unknown model '{req.model}'.")

        question, history = conversation.split_messages(req.messages)

        if conversation.is_task_prompt(req.messages):
            async def produce():
                return conversation.TASK_CANNED_RESPONSE
        elif not question.strip():
            raise HTTPException(status_code=400, detail="No user message found.")
        else:
            async def produce():
                return await run_in_threadpool(_generate_content, question, history)

        if req.stream:
            return StreamingResponse(_sse(produce), media_type="text/event-stream")
        return _json_response(await produce())

    return app
