# Codex 执行状态桥接

这个 sample 只使用 BlinkTile 现有的 JSON 显示协议，不修改固件，也不占用其他应用的接入口。Codex hook 只上报事件名称和会话／轮次／子代理 ID；不读取或发送提示词、工具参数、转录和账号数据。

## 启动

在仓库根目录先进入此 sample，安装它自己的 Python 依赖，再启动本机桥接。已通过 USB 连接的设备可直接使用串口，不需要切换 Wi-Fi：

```sh
cd codex-status
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python codex_status.py bridge --serial-port /dev/cu.usbmodemXXXX --listen-port 8766
```

`/dev/cu.usbmodemXXXX` 是占位符，先用 `arduino-cli board list` 核对实际串口。若设备已联网，也可使用 `--ws-url ws://设备IP:81/ws --token-env ICONSHOW_TOKEN`；把设备控制密钥放在 `ICONSHOW_TOKEN` 环境变量中，不要写入命令、仓库或日志。桥接仅在 `127.0.0.1:8766` 接收 hook。本工具不会发起配网或切换电脑网络。可用模拟器的 `ws://127.0.0.1:8765/ws` 做软件测试。终止桥接后，灯板上最后一条状态会在其有效期届满后回到桌宠。

也可直接通过 Bluetooth LE 连接，无需 USB、控制密钥、Wi-Fi 或浏览器。Bleak 是可选依赖，只在此模式安装；设备必须正在广播。

若 USB 桥接仍占用本机 `8766` 端口，先在运行它的终端按 `Ctrl+C` 停止；USB 与 BLE 桥接不要同时启动。macOS 首次使用时，还需允许运行 Python 的终端访问蓝牙。

```bash
.venv/bin/python -m pip install bleak
.venv/bin/python codex_status.py bridge --ble --listen-port 8766
```

先烧录支持 BOOT 物理授权的新固件。设备运行后按住板上的 BOOT 键（不要同时按 RESET）约 2 秒，直到桥接认证成功后松开。桥接在同一 BLE 连接上最多尝试 30 秒；该物理操作只授权本次连接，不读取、返回或保存长期控制密钥。若已有控制密钥，仍可通过 `ICONSHOW_TOKEN` 环境变量直接认证，不必按 BOOT；变量名是兼容旧配置保留的名称，不是设备广播名。
若设备仍运行改名前的固件，广播名仍是 `IconShow`，请临时改用 `--ble-name IconShow`；烧录新版固件后才会广播 `BlinkTile`。

默认扫描广播名为 `BlinkTile` 且提供本项目 BLE 服务的设备。若附近有多个匹配设备，程序会列出地址并停止；按提示重新运行并加上 `--ble-address <地址>`（macOS 上可能是系统 UUID）。也可用 `--ble-name` 选择自定义设备名。协议使用固件的服务 UUID `6d8f0000-6f52-4af0-9a2c-7b6143b8e100`、写特征 UUID `6d8f0001-6f52-4af0-9a2c-7b6143b8e100` 和通知特征 UUID `6d8f0002-6f52-4af0-9a2c-7b6143b8e100`；JSON 命令以换行结束，写入按 20 字节分块，响应通知会先拼成完整行再解析。

在 Codex 用户级 `hooks.json` 中，为下列事件各配置一个命令 hook。将示例中的 `/ABS/PATH/TO/IconShow` 换成此项目的实际绝对路径；不要直接复制占位路径。用户级配置可覆盖不同项目中的 Codex 会话。不要替换已有 hooks，合并对应事件数组即可。

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "PreToolUse": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "PostToolUse": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "PermissionRequest": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "SubagentStart": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "SubagentStop": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "Stop": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "Interrupt": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}],
    "SessionEnd": [{"hooks":[{"type":"command","command":"python3 /ABS/PATH/TO/IconShow/codex-status/codex_status.py hook --port 8766","timeout":3}]}]
  }
}
```

Codex 需要用户用 `/hooks` 审阅并信任非托管 hook；未信任时不会运行。本项目不会自动改写用户级 Codex 配置。hook 在桥接未启动时静默失败，不影响 Codex 执行。

可在此目录运行 `.venv/bin/python test_codex_status.py` 验证 sample；端到端模拟测试还需要仓库根目录的 `tools/simulator.py` 和 Node.js。

## 状态语义与边界

运行中显示 `loading`；等待授权显示 `question`；正常停止短暂显示 `success`，随后恢复桌宠；中断或会话结束停止续期本轮状态，最多再保留 15 秒。桥接按会话和轮次汇总子代理活动，不把 `SubagentStop` 误判为主轮次完成。它只续期自己持有、且图标仍匹配的显示 ID，从不主动发送无条件 `release`；别的应用占用灯板时不清除对方画面。设备协议本身仍是后发覆盖先发，没有跨应用优先级队列；查询和显示之间仍可能发生极短的竞争。若某个终止 hook 丢失，运行态在最后一次事件后 10 分钟停止续期。

hook 的 `PermissionRequest` 表示即将询问授权，但没有“用户刚批准”的独立 hook；等待态最迟在后续工具事件时更新。因此它是状态指示，不是精确的审批计时器。`Stop` 表示 Codex 本轮停止，不能证明所有工具或任务都成功。设备连接断开时，当前桥接进程会退出，需重新启动；灯板上的临时状态仍会按 TTL 过期。桌面端、CLI、IDE 的 hook 覆盖取决于当前 Codex 版本和用户的 hook 信任状态；本项目的模拟测试不能代替这些端上的实测。

参考：[Codex Hooks 官方文档](https://learn.chatgpt.com/docs/hooks)、[codex-status-bar](https://github.com/KiwiGaze/codex-status-bar)、[codex_status_light](https://github.com/kejixiaoliang/codex_status_light)。开源项目用来核对事件接法；这里未复制它们的固件或私有会话扫描方案。
