# -*- coding: utf-8 -*-
import json
import os
import re
import time
import uuid
from typing import Any, AsyncGenerator, Dict, Optional

import httpx
import msal
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

TENANT_ID = os.getenv("TENANT_ID", "").strip()
CLIENT_ID = os.getenv("CLIENT_ID", "").strip()
TIMEZONE = os.getenv("COPILOT_TIMEZONE", "Asia/Singapore").strip()
GRAPH = "https://graph.microsoft.com"

ALWAYS_NEW_CONVERSATION = os.getenv("COPILOT_ALWAYS_NEW_CONVERSATION", "0") == "1"
RETRY_ON_5XX = os.getenv("COPILOT_RETRY_ON_5XX", "1") == "1"
SESSION_TTL = int(os.getenv("COPILOT_SESSION_TTL", "900"))
DISABLE_WEB = os.getenv("COPILOT_DISABLE_WEB", "1") == "1"
CACHE_PATH = os.getenv("TOKEN_CACHE", "/root/tset/token_cache.bin").strip()

SCOPES = [
    "Sites.Read.All",
    "Mail.Read",
    "People.Read.All",
    "OnlineMeetingTranscript.Read.All",
    "Chat.Read",
    "ChannelMessage.Read.All",
    "ExternalItem.Read.All",
]

AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

app = FastAPI(title="Copilot Chat API → OpenAI Compatible Gateway")
GRAPH_CLIENT = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0), http2=True)

cache = msal.SerializableTokenCache()
if os.path.exists(CACHE_PATH):
    try:
        cache.deserialize(open(CACHE_PATH, "r", encoding="utf-8").read())
    except Exception:
        pass

pca = msal.PublicClientApplication(
    client_id=CLIENT_ID,
    authority=AUTHORITY,
    token_cache=cache,
)

def _save_cache() -> None:
    if cache.has_state_changed:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            f.write(cache.serialize())

def acquire_token() -> str:
    accounts = pca.get_accounts()
    result = None
    if accounts:
        result = pca.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        flow = pca.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Failed to create device flow: {flow}")
        print(flow["message"])  # follow device code login
        result = pca.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(f"Token acquire failed: {result}")

    _save_cache()
    return result["access_token"]


class OpenAIChatReq(BaseModel):
    model: Optional[str] = None
    messages: list
    stream: Optional[bool] = False
    user: Optional[str] = None


CONV: Dict[str, Dict[str, Any]] = {}

SYSTEM_REMINDER_RE = re.compile(r"<system_reminder>.*?</system_reminder>", re.DOTALL | re.IGNORECASE)


def flatten_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    parts.append(str(item["text"]))
                elif "text" in item:
                    parts.append(str(item["text"]))
                elif "content" in item:
                    parts.append(str(item["content"]))
            else:
                parts.append(str(item))
        return "\n".join([p for p in parts if p.strip()])
    return str(content)


def strip_system_reminder(text: str) -> str:
    return SYSTEM_REMINDER_RE.sub("", text).strip()


def extract_last_user_message(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "user":
            raw = flatten_content(m.get("content"))
            return strip_system_reminder(raw)
    return ""


def is_image_intent(text: str) -> bool:
    if not text:
        return False
    kws = ["生成一张", "画一张", "生成图片", "生成图像", "画图", "出图", "image", "picture"]
    t = text.lower()
    return any(k.lower() in t for k in kws)


def build_copilot_payload(user_text: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "message": {"text": user_text},
        "locationHint": {"timeZone": TIMEZONE},
    }
    if DISABLE_WEB:
        payload["contextualResources"] = {"webContext": {"isWebEnabled": False}}
    return payload


async def create_conversation(token: str) -> str:
    url = f"{GRAPH}/beta/copilot/conversations"
    r = await GRAPH_CLIENT.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={},
    )
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"Create conversation failed: {r.text}")
    cid = r.json().get("id")
    if not cid:
        raise HTTPException(status_code=502, detail=f"Create conversation no id: {r.text}")
    return cid


async def ensure_conversation(session_key: str, token: str) -> str:
    now = time.time()
    if not ALWAYS_NEW_CONVERSATION:
        cached = CONV.get(session_key)
        if cached and (now - cached["ts"] < SESSION_TTL):
            return cached["id"]
    cid = await create_conversation(token)
    CONV[session_key] = {"id": cid, "ts": now}
    return cid


async def copilot_chat(token: str, cid: str, user_text: str) -> str:
    url = f"{GRAPH}/beta/copilot/conversations/{cid}/chat"
    payload = build_copilot_payload(user_text)
    r = await GRAPH_CLIENT.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
    )
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Copilot chat failed: {r.text}")
    data = r.json()
    msgs = data.get("messages", [])
    if not msgs:
        return ""
    return msgs[-1].get("text", "") or ""


async def copilot_chat_stream(token: str, cid: str, user_text: str) -> AsyncGenerator[str, None]:
    url = f"{GRAPH}/beta/copilot/conversations/{cid}/chatOverStream"
    payload = build_copilot_payload(user_text)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    stream_id = f"chatcmpl-copilot-{uuid.uuid4().hex}"
    created = int(time.time())
    model_name = "copilot"
    previous_text = ""

    async with GRAPH_CLIENT.stream("POST", url, headers=headers, json=payload) as resp:
        if resp.status_code != 200:
            raw = await resp.aread()
            raise HTTPException(status_code=502, detail=f"Copilot chatOverStream failed: {raw.decode('utf-8', errors='ignore')}")

        buf = []
        async for line in resp.aiter_lines():
            if line == "":
                if not buf:
                    continue
                raw_event = "\n".join(buf).strip()
                buf = []

                if raw_event.startswith("data:"):
                    raw_event = raw_event[len("data:"):].strip()
                if raw_event == "[DONE]":
                    break

                try:
                    obj = json.loads(raw_event)
                except Exception:
                    continue

                msgs = obj.get("messages", [])
                if not msgs:
                    continue

                full_text = msgs[-1].get("text", "") or ""
                if full_text.startswith(previous_text):
                    delta = full_text[len(previous_text):]
                else:
                    delta = full_text

                if delta:
                    previous_text = full_text
                    chunk = {
                        "id": stream_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model_name,
                        "choices": [{
                            "index": 0,
                            "delta": {"content": delta},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                continue

            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                buf.append(line)

    final_chunk = {
        "id": stream_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model_name,
        "choices": [{
            "index": 0,
            "delta": {},
            "finish_reason": "stop"
        }]
    }
    yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/health")
async def health():
    return {"ok": True, "time": int(time.time())}


@app.post("/v1/chat/completions")
async def chat_completions(req: OpenAIChatReq, request: Request, x_session_id: Optional[str] = Header(None)):
    user_text = extract_last_user_message(req.messages)
    if not user_text:
        raise HTTPException(status_code=400, detail="No user message found in messages")

    # Text-only API: degrade image intent to prompt assistance
    if is_image_intent(user_text):
        return JSONResponse({
            "id": "chatcmpl-text-only",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model or "copilot",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "当前接入的 Copilot Chat API 仅支持文本回复，不支持直接生成图片。我可以帮你写一段高质量绘图提示词（prompt）或画面描述；请告诉我想要的风格（写实/动漫/摄影）、服装与场景。"
                },
                "finish_reason": "stop"
            }]
        })

    token = acquire_token()

    client_ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "no-ua")
    session_key = req.user or x_session_id or f"{client_ip}:{ua}"

    async def non_stream(force_new: bool) -> str:
        if force_new or ALWAYS_NEW_CONVERSATION:
            cid = await create_conversation(token)
        else:
            cid = await ensure_conversation(session_key, token)
        return await copilot_chat(token, cid, user_text)

    async def stream_gen(force_new: bool) -> AsyncGenerator[str, None]:
        if force_new or ALWAYS_NEW_CONVERSATION:
            cid = await create_conversation(token)
        else:
            cid = await ensure_conversation(session_key, token)
        async for chunk in copilot_chat_stream(token, cid, user_text):
            yield chunk

    if req.stream:
        async def generator():
            try:
                async for chunk in stream_gen(force_new=False):
                    yield chunk
            except HTTPException as e:
                if RETRY_ON_5XX and ("internalServerError" in str(e.detail) or "5" in str(e.status_code)):
                    async for chunk in stream_gen(force_new=True):
                        yield chunk
                else:
                    raise
        return StreamingResponse(generator(), media_type="text/event-stream")

    try:
        answer = await non_stream(force_new=False)
    except HTTPException as e:
        if RETRY_ON_5XX and ("internalServerError" in str(e.detail) or "5" in str(e.status_code)):
            answer = await non_stream(force_new=True)
        else:
            raise

    return JSONResponse({
        "id": f"chatcmpl-copilot-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or "copilot",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": answer},
            "finish_reason": "stop"
        }]
    })


@app.on_event("shutdown")
async def shutdown():
    await GRAPH_CLIENT.aclose()
