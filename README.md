# m365-copilot-chat-gateway

> 一个轻量级网关：把 **Microsoft 365 Copilot Chat API（Microsoft Graph /beta）** 转换为 **OpenAI Chat Completions 兼容接口**，从而可被 AstrBot、MaiBot 等“OpenAI 兼容客户端”直接接入。

✅ 支持：
- OpenAI 兼容端点：`POST /v1/chat/completions`
- 流式：`stream=true` 时返回 SSE（`text/event-stream`），输出 OpenAI 风格 chunk（`data: {...}` / `data: [DONE]`）
- 关闭 Web Search Grounding：每次请求携带 `contextualResources.webContext.isWebEnabled=false`
- 多会话：conversation 复用 + TTL；遇到 5xx/内部错误可自动重建会话重试一次

⚠️ 注意：Copilot Chat API 使用 Graph `/beta`，文档提示可能变更且不建议用于生产环境。

---

## 目录
- [工作原理](#工作原理)
- [Entra 应用注册与权限配置（必看）](#entra-应用注册与权限配置必看)
- [安装与运行（Linux）](#安装与运行linux)
- [systemd 托管（推荐）](#systemd-托管推荐)
- [AstrBot / MaiBot 接入](#astrbot--maibot-接入)
- [关闭 Web Search Grounding](#关闭-web-search-grounding)
- [流式（Streaming）测试](#流式streaming测试)
- [已知限制](#已知限制)
- [常见问题排查](#常见问题排查)

---

## 工作原理

Copilot Chat API 的标准调用流程：

1. 创建对话：`POST https://graph.microsoft.com/beta/copilot/conversations`（body 为 `{}`）
2. 继续对话（同步）：`POST https://graph.microsoft.com/beta/copilot/conversations/{conversationId}/chat`
3. 继续对话（流式）：`POST https://graph.microsoft.com/beta/copilot/conversations/{conversationId}/chatOverStream`（返回 SSE `text/event-stream`）

网关将上述能力封装为 OpenAI 兼容的 `/v1/chat/completions`。

---

## Entra 应用注册与权限配置（必看）

> 本项目使用 **MSAL 设备码登录（Device Code Flow）** 获取 **Delegated（委派）** token。Device Code Flow 只适用于“公共客户端（Public client）”应用类型。

### 1）创建应用（App registration）

1. 登录 Microsoft Entra 管理中心 → **App registrations** → **New registration**。
2. Name：建议填 `m365-copilot-chat-gateway`。
3. Supported account types：一般选 **Accounts in this organizational directory only**（单租户）。
4. 创建后记录两项：
   - **Directory (tenant) ID** → 用于 `.env` 的 `TENANT_ID`
   - **Application (client) ID** → 用于 `.env` 的 `CLIENT_ID`

### 2）启用 Public client flows（设备码登录必需）

Device Code Flow 属于 Public client flow。你需要在应用的 **Authentication** 页面启用“Treat application as a public client / Allow public client flows”。

> 参考：MSAL 文档说明 Device Code Flow 仅适用于 public client，并且 authority 需要是 `https://login.microsoftonline.com/{tenant}/` 这种 tenanted 形式。

### 3）添加 Microsoft Graph Delegated 权限 + 管理员同意

Copilot Chat API **不支持 Application 权限**，需要 **Delegated 权限**。在应用 → **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions** 添加以下权限，并点击 **Grant admin consent**：

- `Sites.Read.All`
- `Mail.Read`
- `People.Read.All`
- `OnlineMeetingTranscript.Read.All`
- `Chat.Read`
- `ChannelMessage.Read.All`
- `ExternalItem.Read.All`

> 说明：Copilot Chat API 文档列出了需要的 Delegated 权限集合，并强调 `/beta` 可能变更。

### 4）首次登录（Device Code）

第一次运行网关并触发一次 `/v1/chat/completions` 请求时，控制台/日志会打印类似：

- 打开 `https://microsoft.com/devicelogin`
- 输入 code
- 使用你的工作/学校账号完成登录与授权

完成后 token 会缓存（见 `TOKEN_CACHE`），后续一般不需要反复登录。

---

## 安装与运行（Linux）

### 1）安装 Python

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip
```

### 2）创建虚拟环境并安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

> 如果代码启用了 `httpx.AsyncClient(http2=True)`，请安装 HTTP/2 依赖：

```bash
pip install -U "httpx[http2]"
```

### 3）配置 `.env`

```bash
cp .env.example .env
nano .env
```

至少填写：
- `TENANT_ID=...`
- `CLIENT_ID=...`
- `COPILOT_TIMEZONE=Asia/Singapore`

### 4）前台启动（推荐用于首次登录）

```bash
set -a; source .env; set +a
python -m uvicorn gateway:app --host 0.0.0.0 --port 9000 --log-level info
```

---

## systemd 托管（推荐）

```bash
sudo cp -f copilot-gateway.service /etc/systemd/system/copilot-gateway.service
sudo systemctl daemon-reload
sudo systemctl enable --now copilot-gateway
sudo systemctl status copilot-gateway --no-pager
```

查看日志：

```bash
sudo journalctl -u copilot-gateway -f
```

---

## AstrBot / MaiBot 接入

在 AstrBot / MaiBot 中新增 OpenAI 兼容提供商：

- API Base URL：`http://127.0.0.1:9000/v1`
- API Key：随便填（若网关不校验可忽略）

---

## 关闭 Web Search Grounding

在 Graph `chat` 请求体中使用 `contextualResources.webContext.isWebEnabled=false` 可在单轮关闭 web grounding。网关默认已在每次请求中携带此配置。

---

## 流式（Streaming）测试

### 非流式

```bash
curl -s http://127.0.0.1:9000/v1/chat/completions   -H "Content-Type: application/json"   -d '{"model":"copilot","messages":[{"role":"user","content":"ping"}],"user":"smoke-1"}'
```

### 流式（SSE）

```bash
curl -iN http://127.0.0.1:9000/v1/chat/completions   -H "Content-Type: application/json"   -d '{"model":"copilot","stream":true,"messages":[{"role":"user","content":"写一段200字说明，解释什么是流式输出"}],"user":"stream-1"}'
```

预期：响应头 `Content-Type: text/event-stream`，并持续输出 `data: {...}`，最终以 `data: [DONE]` 结束。

---

## 已知限制

Copilot Chat API 已知限制之一是：只返回文本响应，不支持图形/图像生成类工具。因此对“生图/画图”意图建议降级为 prompt/画面描述。

---

## 常见问题排查

- **创建仓库时提示“无法查到可用性”**：多为浏览器/网络导致前端校验失败，可尝试换浏览器、关闭翻译插件、或直接点击“创建仓库”。
- **9000 端口占用**：`[Errno 98] address already in use`，请先停止旧进程或换端口。
- **http2=True 报 h2 未安装**：执行 `pip install -U "httpx[http2]"`。
- **systemd 看不到设备码提示**：建议首次用前台启动完成登录，再切回 systemd。
