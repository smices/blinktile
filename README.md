# IconShow

ESP32-C3 SuperMini + WS2812B 8×8 彩色状态灯。用 BLE 或局域网 WebSocket 显示图标、动画、数字和英文；没有临时状态时可作为会眨眼的桌宠。

## 先看效果

打开 [图鉴与控制器](web/index.html)。PNG 是真实 8×8 像素，GIF 是可下载的动画文件；不是示意插图。双击 HTML 可离线查看和预览。

连接设备时，在项目根目录启动本地服务：

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory web
```

在支持的桌面 Chrome/Edge 打开 `http://localhost:8000`。选图标或输入 `100%`，调整参数，再点击发送。WebSocket 地址为 `ws://设备IP:81/ws`。BLE 必须由用户点击并选择设备；浏览器不支持时使用 WebSocket。

完整资源包应一起保留，HTML 引用同目录脚本和 `assets/`，不依赖 CDN。GIF 展示默认效果，实时预览展示当前参数；显示器与灯珠的实际色彩和亮度仍有差异。

## 硬件

| 项目 | 值 |
| --- | --- |
| 板 | ESP32-C3 SuperMini，4MB Flash |
| 灯板 | 64 颗 WS2812B，GRB，800kHz |
| DIN | GPIO2，推荐串联约 330Ω 电阻 |
| 排列 | 逐行蛇形，奇数行反向 |
| 电源 | USB 5V/1A，共地，不用 3.3V 引脚供电 |
| 开机亮度 | 25%（64/255），默认熄灭 |
| 灯板估算电流预算 | 500mA，给控制板与无线通信留余量 |

GPIO2 是启动配置引脚，复位时不能被外围强制拉低。参考板接线可沿用；更换灯板后先做方向和颜色测试。长线或电平不稳定时使用适合 3.3V→5V 的电平转换器，电源入口建议加储能电容。

25% 不是固定功耗保证。输出会依据每帧内容进一步限亮：保守估算 `64mA + 20mA × 所有RGB通道值之和 / 255`，超过 500mA 等比例缩小输出。它不是电流传感器，USB 线损和整机电流仍需实测。

## 开发与构建

依赖 Node.js 22、Python 3，以及 Python 包 Pillow、websockets。固件版本固定为 Arduino-ESP32 3.3.11、Adafruit NeoPixel 1.15.5、ArduinoJson 7.4.3、WebSockets 2.7.2。已有版本时不需要重复安装。

```sh
arduino-cli core install esp32:esp32@3.3.11
arduino-cli lib install 'Adafruit NeoPixel@1.15.5' 'ArduinoJson@7.4.3' 'WebSockets@2.7.2'
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python tools/generate_assets.py
bash tools/build.sh
```

构建脚本只编译，不自动烧录。硬件接入后先运行 `arduino-cli board list` 核对串口，再按 [设备配置与验收](docs/hardware.md) 操作。

## 没有硬件也能验证控制链

```sh
.venv/bin/python tools/simulator.py
```

模拟器仅监听本机；终端提供临时测试密钥、HTML 地址和 `ws://localhost:8765/ws`。在控制器中输入该地址和测试密钥，完成认证后发送。模拟器共用网页渲染逻辑，不能代替固件或灯板验收。

```sh
.venv/bin/python tests/test_assets.py
node tests/test_engine.cjs
node tests/test_client.cjs
.venv/bin/python tests/test_transport.py
.venv/bin/python tests/test_firmware_render.py
.venv/bin/python tests/test_firmware_transport.py
.venv/bin/python tests/test_setup_page.py
```

固件渲染检查从当前 `.ino` 提取实际渲染函数，并与网页引擎逐帧比对；需要支持 C++17 的 `c++` 编译器和已安装的 ArduinoJson。配网页检查执行内嵌脚本并模拟 HTTP 响应。这些检查不验证 ESP32 无线、调度或电气行为。

完成构建及本地提交后，运行 `python3 tools/package.py` 生成 `dist/IconShow-release.zip`，内含源码、离线图鉴、固件二进制和 SHA-256 清单，不包含调试文件及构建缓存。

## 配网与再次配网

第一次通过 USB 串口设置 Wi-Fi，并读取设备独立的配置热点密码和控制密钥；精确命令见 [设备配置与验收](docs/hardware.md)。普通运行日志不显示凭据。密码保存在设备，不写入源码。

离开旧网络后，设备持续连接失败 30 秒会启动密码保护的配置热点。手机连接 `IconShow-…`，打开 `http://192.168.4.1`，选择新 Wi-Fi 并提交。先试连，取得 IP 才保存；失败保留旧配置和热点。成功页面显示新 IP，15 秒后关闭热点。只需局域网，不依赖互联网。USB 串口始终保留恢复入口。

在线时也可在控制器中主动打开配网热点。热点配置页是固件内置的精简页面，完整图鉴和控制器在电脑端。

## 集成

- [协议](docs/protocol.md)：JSON 指令、时序、鉴权和传输边界。
- [最小 HTML 示例](web/example.html)：实际客户端调用。
- [验收记录](docs/verification.md)：区分素材、模拟器、编译和真机验证。

Codex 等软件可以把处理中映射到 `loading`、等待输入映射到呼吸 `question`、完成映射到 `success`，把额度格式化成 `100%` 或 `25% LEFT`。此项目提供显示接口，不采集 Codex 私有会话、账号或额度数据。
