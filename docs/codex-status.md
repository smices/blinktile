# Codex 执行状态桥接

这个可选集成只使用 IconShow 现有的 JSON 显示协议，不修改固件，也不占用其他应用的接入口。Codex hook 只上报事件名称和会话／轮次／子代理 ID；不读取或发送提示词、工具参数、转录和账号数据。

## 启动

先安装 Python 依赖，再启动本机桥接。已通过 USB 连接的设备可直接使用串口，不需要切换 Wi-Fi：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/codex_status.py bridge --serial-port /dev/cu.usbmodemXXXX --listen-port 8766
```

`/dev/cu.usbmodemXXXX` 是占位符，先用 `arduino-cli board list` 核对实际串口。若设备已联网，也可使用 `--ws-url ws://设备IP:81/ws --token-env ICONSHOW_TOKEN`；把设备控制密钥放在 `ICONSHOW_TOKEN` 环境变量中，不要写入命令、仓库或日志。桥接仅在 `127.0.0.1:8766` 接收 hook。本工具不会发起配网或切换电脑网络。可用模拟器的 `ws://127.0.0.1:8765/ws` 做软件测试。终止桥接后，灯板上最后一条状态会在其有效期届满后回到桌宠。

在 Codex 用户级 `hooks.json` 中，为下列事件各配置一个命令 hook。将示例中的 `/ABS/PATH/TO/IconShow` 换成此项目的实际绝对路径；不要直接复制占位路径。用户级配置可覆盖不同项目中的 Codex 会话。不要替换已有 hooks，合并对应事件数组即可。

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "PreToolUse": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "PostToolUse": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "PermissionRequest": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "SubagentStart": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "SubagentStop": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "Stop": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "Interrupt": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}],
    "SessionEnd": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/tools/codex_status.py hook --port 8766","timeout":3}]}]
  }
}
```

Codex 需要用户用 `/hooks` 审阅并信任非托管 hook；未信任时不会运行。本项目不会自动改写用户级 Codex 配置。hook 在桥接未启动时静默失败，不影响 Codex 执行。

## 状态语义与边界

运行中显示 `loading`；等待授权显示 `question`；正常停止短暂显示 `success`，随后恢复桌宠；中断或会话结束停止续期本轮状态，最多再保留 15 秒。桥接按会话和轮次汇总子代理活动，不把 `SubagentStop` 误判为主轮次完成。它只续期自己持有、且图标仍匹配的显示 ID，从不主动发送无条件 `release`；别的应用占用灯板时不清除对方画面。设备协议本身仍是后发覆盖先发，没有跨应用优先级队列；查询和显示之间仍可能发生极短的竞争。若某个终止 hook 丢失，运行态在最后一次事件后 10 分钟停止续期。

hook 的 `PermissionRequest` 表示即将询问授权，但没有“用户刚批准”的独立 hook；等待态最迟在后续工具事件时更新。因此它是状态指示，不是精确的审批计时器。`Stop` 表示 Codex 本轮停止，不能证明所有工具或任务都成功。设备连接断开时，当前桥接进程会退出，需重新启动；灯板上的临时状态仍会按 TTL 过期。桌面端、CLI、IDE 的 hook 覆盖取决于当前 Codex 版本和用户的 hook 信任状态；本项目的模拟测试不能代替这些端上的实测。

参考：[Codex Hooks 官方文档](https://learn.chatgpt.com/docs/hooks)、[codex-status-bar](https://github.com/KiwiGaze/codex-status-bar)、[codex_status_light](https://github.com/kejixiaoliang/codex_status_light)。开源项目用来核对事件接法；这里未复制它们的固件或私有会话扫描方案。
