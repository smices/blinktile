# 设备配置与验收

## 连接与烧录边界

先核对 GPIO2→DIN、5V 和共地，确认 USB 电源至少 5V/1A。默认亮度 25%，仍保留每帧功耗估算限亮。首次测试从少量亮点开始，不用满白画面作为开机自检。

构建后使用 `arduino-cli board list` 识别实际板子的串口。不要把 Bluetooth-Incoming-Port 或 debug-console 当作 ESP32。烧录会替换板上原有程序，应只对指定的 BlinkTile 测试板执行。

```sh
arduino-cli upload \
  --port <ESP32串口> \
  --fqbn 'esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashSize=4M,PartitionScheme=huge_app,CPUFreq=160,FlashFreq=80,FlashMode=dio' \
  --input-dir dist
arduino-cli monitor --port <ESP32串口> --config baudrate=115200
```

先运行 `bash tools/build.sh` 生成 `dist/`。完整固件超过默认分区容量，因此编译和上传必须使用与脚本相同的 `PartitionScheme=huge_app`。不能只凭串口名推断板型。

## 配网预期流程

首次配置使用 115200 波特率 USB 串口，每条命令一行 JSON。串口本身无需认证；先读取设备生成的热点密码和控制密钥，再提交 2.4GHz Wi-Fi：

```json
{"id":1,"op":"secrets"}
{"id":2,"op":"wifi","ssid":"<WIFI_SSID>","password":"<WIFI_PASSWORD>"}
{"id":3,"op":"get"}
```

`secrets` 响应包含 `ap_name`、`setup_password`、`control_token` 和当前 `wifi_ssid`。这些值只在显式请求时输出，用户应自行保存，不复制到截图、提交记录或普通日志。`wifi` 最多尝试 30 秒；取得 IP 后才保存。用 `get` 响应中的 `state.wifi_connected` 和 `state.ip` 判断结果。

再次配网：设备离开已保存网络 30 秒后会开启密码保护热点；在线时也可通过已认证的 BLE/WebSocket 发送 `{"id":1,"op":"provision"}` 主动开启。用 `secrets` 返回的 `setup_password` 连接 `IconShow-…`，打开 `http://192.168.4.1`，选择 2.4GHz 网络；隐藏网络可以手动输入。网络名不作为 HTML 插入，密码字段不回显。

设备先尝试候选网络，只有取得 IP 后才保存；认证失败、找不到网络或 DHCP 超时都保留旧配置。成功后等待页面显示 IP；热点保留 15 秒再关闭，此后切回新 Wi-Fi。设备不检查外网连通性。

## BLE 连接

BLE 广播名是 `BlinkTile`，不需要先连接 Wi-Fi，也不需要在系统蓝牙设置中配对。新版固件刷入后，可在设备已运行时按住 BOOT 键约 2 秒，以物理操作授权当前 BLE 连接；松开后新连接需要再次授权。该流程不返回或存储长期控制密钥，WebSocket 仍必须使用密钥。若已有密钥，BLE 也可照旧使用；无需为 BLE 专门连接 USB 读取 `secrets`。不要在上电或复位时按住 BOOT，否则可能进入下载模式。

网页控制是可选入口：在仓库根目录运行 `python3 -m http.server 8000 --bind 127.0.0.1 --directory web`，用支持 Web Bluetooth 的桌面 Chrome/Edge 打开 `http://127.0.0.1:8000`。控制密钥可留空，点击“选择 BLE 设备”，在弹窗中选 `BlinkTile`，然后按住 BOOT 直至认证成功。网页会重试约 15 秒。只有使用这个浏览器页面才需要本地 HTTP 服务；若没有 Web Bluetooth 支持，可改用桥接或 WebSocket。

Codex 状态桥接：按 [sample 的 BLE 启动步骤](../codex-status/README.md) 安装可选 Bleak 依赖并启动 `--ble`，不需要浏览器、本地 HTTP 服务或控制密钥。同一个本机 hook 端口一次只运行一个桥接实例；从 USB 桥接切换前先停止旧实例。BLE 扫描、物理授权和实物显示尚未完成本机无线验收，不能把软件分包测试当作无线连接成功。

## 真机验收表

- [x] 上电进入桌宠；固件默认亮度查询为 64/255。最近一次烧录后另以指令设为 8/255（约 3%，重启后不保留）。
- [x] 红、绿、蓝颜色正确；四个方向和逐行线性映射正确。
- [ ] 眨眼自然，上传向上、下载向下、等待转圈。
- [ ] 七彩循环与空间彩虹不同，呼吸和明暗交替可独立调速。
- [ ] `100%` 和英文逐像素完整滚动；静态数字可辨。
- [ ] USB 5V/1A 下限亮有效，无掉电、复位、异常发热。
- [ ] BLE 20 字节分包、WebSocket、错误响应及断线恢复。
- [ ] 暂停期间仍能关闭，TTL 仍到期；续期不重启动画。
- [ ] 临时状态退出恢复桌宠；off 后不自动亮起。
- [ ] 首次配网、换网、错密码、隐藏 SSID、DHCP 失败。
- [ ] 候选网络测试期间断电不破坏原配置。
- [ ] 热点成功后关闭；配网页不从 STA 接口开放。
- [ ] BLE/Wi-Fi 同时工作时显示仍可响应关闭。

此表记录现场结果；未实际完成的条目不得打勾。
