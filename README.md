# Copilot Chat API Gateway（OpenAI 兼容）— 接入 AstrBot / MaiBot

> 一个轻量级网关：把 **Microsoft 365 Copilot Chat API（Microsoft Graph /beta）** 转换为 **OpenAI Chat Completions 兼容接口**，从而可被 AstrBot、MaiBot 等“OpenAI 兼容客户端”直接接入。

## 主要特性

- OpenAI 兼容端点：`POST /v1/chat/completions`
- 支持流式：当 `stream=true` 时返回 SSE（`text/event-stream`），并输出 OpenAI 风格 chunk（`data: {...}` / `data: [DONE]`）
- 可关闭 Web Search Grounding：每次请求携带 `contextualResources.webContext.isWebEnabled=false`
- 多会话：conversation 复用 + TTL；遇到 5xx/内部错误可自动重建会话重试一次
- 兼容 AstrBot 分段 content（parts 列表）与 `system_reminder`
- 对“生图/画图”意图做降级（Copilot Chat API 为文本聊天接口，建议转为 prompt/画面描述）

> 注意：Graph `/beta` API 可能变更，不建议直接用于生产环境。

---

## 工作原理

- 创建对话：`POST https://graph.microsoft.com/beta/copilot/conversations`
- 继续对话（同步）：`POST https://graph.microsoft.com/beta/copilot/conversations/{conversationId}/chat`
- 继续对话（流式）：`POST https://graph.microsoft.com/beta/copilot/conversations/{conversationId}/chatOverStream`

网关将这些能力封装为 OpenAI 兼容的 `/v1/chat/completions`。

---

## 前置条件

1. 需要工作/学校账号的 **Delegated** 权限（Copilot Chat API 不支持 Application 权限）。
2. 需要相应的 Microsoft Graph 权限并获得租户管理员同意（详见 Microsoft Learn 文档）。
3. 需要可用的 Microsoft 365 Copilot 许可（否则接口可能不可用）。

---

## 安装与运行（Linux）

### 1）准备 Python 环境

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

> 如果代码启用了 `httpx.AsyncClient(http2=True)`，请安装 HTTP/2 可选依赖：

```bash
pip install -U "httpx[http2]"
```

### 3）配置 `.env`

复制模板：

```bash
cp .env.example .env
```

编辑 `.env`，填写：

- `TENANT_ID=...`
- `CLIENT_ID=...`
- `COPILOT_TIMEZONE=Asia/Singapore`

### 4）临时前台运行（便于首次设备码登录）

```bash
set -a; source .env; set +a
python -m uvicorn gateway:app --host 0.0.0.0 --port 9000 --log-level info
```

首次调用时，控制台会提示你前往 `https://microsoft.com/devicelogin` 输入 code 完成登录。

---

## systemd 托管（推荐）

将 `copilot-gateway.service` 复制到 `/etc/systemd/system/`：

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

## 流式（Streaming）测试

### 非流式

```bash
curl -s http://127.0.0.1:9000/v1/chat/completions   -H "Content-Type: application/json"   -d '{"model":"copilot","messages":[{"role":"user","content":"ping"}],"user":"smoke-1"}'
```

### 流式（SSE）

```bash
curl -iN http://127.0.0.1:9000/v1/chat/completions   -H "Content-Type: application/json"   -d '{"model":"copilot","stream":true,"messages":[{"role":"user","content":"写一段200字说明，解释什么是流式输出"}],"user":"stream-1"}'
```

你应当看到响应头 `Content-Type: text/event-stream`，并持续输出 `data: {...}`，最终以 `data: [DONE]` 结束。

---

## 常见问题

- **9000 端口占用**：`[Errno 98] address already in use`，请先停止旧进程或换端口。
- **http2=True 报 h2 未安装**：执行 `pip install -U "httpx[http2]"`。
- **systemd 看不到设备码提示**：建议首次用前台启动完成登录，再切回 systemd。

---

## 目录结构

- `gateway.py`：网关主程序
- `requirements.txt`：依赖
- `.env.example`：环境变量模板
- `copilot-gateway.service`：systemd 服务文件
- `install.sh`：一键安装脚本（可选）

---

## License

MIT
