# Cloudflare Email binding

为 NAccount 在 Cloudflare Workers 上使用原生 Email Service 添加 provider，
不向应用注入 Cloudflare 账户管理 API token。原有 SMTP/Resend 等 provider 不变。
`EMAIL_PROVIDER_NAME=cloudflare` 要求 `CLOUDFLARE_EMAIL` binding 和
`CLOUDFLARE_SENDER_ADDRESS`。发送失败或缺 messageId 均不报告成功，不重试，
原始 provider 错误不进入邮件日志。API 接受不等于邮件送达。

部署配置由 `.sba/cloudflare.py` 生成。官方接口依据：
<https://developers.cloudflare.com/email-service/api/send-emails/workers-api/>。
本轮在线接口说明使用结构化消息并返回 `{messageId}`。
