# Entra 应用注册（App Registration）步骤

本项目通过 MSAL 设备码登录（Device Code Flow）获取 Delegated token，因此需要将应用注册为“公共客户端（Public client）”。

## 1. 创建应用
- Microsoft Entra 管理中心 → App registrations → New registration
- 记录 Tenant ID 与 Client ID

## 2. 启用 Public client flows
- App registrations → 选中应用 → Authentication
- 开启 “Treat application as a public client / Allow public client flows”

## 3. 添加 Graph Delegated 权限并管理员同意
API permissions → Add a permission → Microsoft Graph → Delegated permissions
添加并管理员同意：
- Sites.Read.All
- Mail.Read
- People.Read.All
- OnlineMeetingTranscript.Read.All
- Chat.Read
- ChannelMessage.Read.All
- ExternalItem.Read.All

## 4. 首次设备码登录
前台启动网关并触发一次 /v1/chat/completions 请求，按提示到 https://microsoft.com/devicelogin 输入 code 登录。

完成后 token 会写入 TOKEN_CACHE 指定的缓存文件。
