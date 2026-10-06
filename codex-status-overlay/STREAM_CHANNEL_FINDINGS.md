# 桌面流式通道检查（2026-10-06）

检查已安装的 Windows Codex 桌面包 `26.930.7945.0`，只读核对代码并实际订阅当前对话。

## 实际验证

- Windows 命名管道 `\\.\pipe\codex-ipc` 存在且可连接。
- 连接采用四字节小端长度头，随后是 UTF-8 JSON；不是 app-server 的逐行 JSON-RPC。
- 使用 `initialize` 请求注册监听客户端，成功取得客户端 ID。
- 发送版本 1 的 `thread-stream-following-changed` 广播，参数为 `hostId: local`、当前 `conversationId`、`following: true`。
- 收到版本 11 的 `thread-stream-state-changed` 广播，包括 `snapshot` 和 `patches`。
- 在当前对话的中文进度消息生成期间，实际收到连续的 `items/.../text` 补丁及 `acceptedTextChanges`。这验证了实时文本旁路监听，而不只是历史快照读取。
- 同时观察到 `latestTokenUsageInfo` 补丁，但本次检查未证明其按每个生成 Token 实时更新。
- 检查结束发送 `following: false` 并关闭连接；没有发起或中断生成，没有修改安装包。

## 结论和实现约束

输出流接入可行。此前 `app-server proxy` 的 socket 错误只排除了该连接方式，不能据此判断桌面端没有外部监听通道。

实时文本补丁不直接等于准确的模型 Token 数。进一步测试中，33 次文本变化只伴随一次用量更新，不能用其计算逐段生成速度。

现已接入 `stream_speed.py` 后台监听器：用 D 盘本地 `o200k_base` 分词词表估算可见文本 Token 数，每 0.5 秒更新近 5 秒速度。面板明确显示 `≈ xx.x token/s`，不声称与当前模型服务端分词完全一致。实际中文输出测试收到采样中及 streaming 状态，数值包括 48.8、43.0 token/s；待机、切换与重连会重置采样。精确的服务端逐 Token 速度仍不可用。

该通道属于内部桌面 IPC，协议版本可能随应用升级变化。生产监听器应校验版本、检查当前对话 ID、处理重连与切换、在退出时取消订阅；消息正文只在内存处理，不应写入测速日志。

## 检查工具

`probe_stream_channel.py` 可进行 25 秒只读探测，只打印结构元数据，不打印消息正文。运行前按项目约定设置 `.codex\test-tmp` 环境变量。
