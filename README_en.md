# Copilot Chat API Gateway (OpenAI-Compatible) — for AstrBot / MaiBot

A lightweight gateway that converts **Microsoft 365 Copilot Chat API (Microsoft Graph /beta)** to an **OpenAI Chat Completions-compatible** endpoint so clients like AstrBot/MaiBot can integrate easily.

## Features
- OpenAI-compatible endpoint: `POST /v1/chat/completions`
- Streaming support: `stream=true` returns SSE (`text/event-stream`) with OpenAI-style chunks
- Disable Web Search Grounding per-turn via `contextualResources.webContext.isWebEnabled=false`
- Multi-session: conversation reuse with TTL; retry-on-5xx by recreating conversations

## Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
cp .env.example .env
# edit .env
set -a; source .env; set +a
python -m uvicorn gateway:app --host 0.0.0.0 --port 9000
```

## Streaming test
```bash
curl -iN http://127.0.0.1:9000/v1/chat/completions   -H "Content-Type: application/json"   -d '{"model":"copilot","stream":true,"messages":[{"role":"user","content":"Explain streaming in 200 words"}],"user":"stream-1"}'
```

MIT License.
