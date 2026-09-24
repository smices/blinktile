# BlinkTile protocol v1

设备把显示内容、颜色变化、明暗变化分别计算，再应用用户亮度与功耗限制。WebSocket、BLE 和本地 USB 命令使用同一显示语义。

## 连接

| 通道 | 地址／规则 |
| --- | --- |
| WebSocket | `ws://<device-ip>:81/ws`，每个文本消息一个 JSON |
| BLE service | `6d8f0000-6f52-4af0-9a2c-7b6143b8e100` |
| BLE write | `6d8f0001-6f52-4af0-9a2c-7b6143b8e100` |
| BLE notify | `6d8f0002-6f52-4af0-9a2c-7b6143b8e100` |
| USB 串口 | 115200，换行分隔 JSON；本机配置和恢复入口 |

无线连接先认证：WebSocket 使用 `{"id":1,"op":"auth","token":"<device-control-token>"}`；BLE 可同样使用密钥，或在设备运行中按住 BOOT 键至少 1 秒后发送 `{"id":1,"op":"auth"}`，仅授权当前 BLE 连接。无密钥 BLE 认证不返回长期密钥，离线重连需再次按键。密钥不放在 URL、不自动保存到浏览器持久存储、不进入普通日志。局域网明文 WebSocket 不提供 TLS 保密性，请勿映射到公网。

USB 串口无需 `auth`，并额外提供两个仅限串口的配置命令：

```json
{"id":1,"op":"secrets"}
{"id":2,"op":"wifi","ssid":"<WIFI_SSID>","password":"<WIFI_PASSWORD>"}
```

`secrets` 返回 `ap_name`、`setup_password`、`control_token`、`wifi_ssid`；`wifi` 接受 1～32 字节非空 SSID 和最多 63 字节密码，立即确认已开始尝试，不代表已经联网。随后发送 `{"id":3,"op":"get"}`，以 `state.wifi_connected` 和 `state.ip` 判断是否取得地址。候选网络最多尝试 30 秒，成功才保存，失败恢复旧配置。

每个请求的 `id` 为 `1～2147483647` 整数。最大 JSON 请求 512 个 UTF-8 字节；BLE 末尾追加换行，单次 GATT 写入时 JSON 最多 511 字节。当前已验收的 `codex-status` BLE 路径将整条请求单次写入；固件虽有分段组帧逻辑，真机分段认证曾出现解析超时，网页 BLE 的 20 字节分段写入尚未验收。BLE 响应同样换行分帧，可以跨多个通知；响应接收上限为 2048 字节。断线丢弃未完成帧，组包超时 2 秒。

成功响应包含 `id` 和 `ok:true`；失败包含 `id`、`ok:false`、`error`。`get` 返回当前状态。客户端 5 秒超时后不自动重发显示命令。超时表示未确认，不代表设备没有执行。

## 显示指令

```json
{"id":2,"op":"show","icon":"upload"}
```

```json
{"id":3,"op":"show","icon":"loading","animation":{"enabled":true,"period_ms":1000,"repeat":0},"color":{"mode":"rainbow_cycle","period_ms":5000},"effect":{"type":"breathe","period_ms":2000,"min":20,"max":255},"duration_ms":15000}
```

```json
{"id":4,"op":"text","text":"100%","scroll":{"mode":"auto","direction":"left","step_ms":180,"repeat":1},"color":{"mode":"solid","values":["green"]}}
```

| 参数 | 规则 |
| --- | --- |
| `icon` | 图鉴中的稳定 ID，未知 ID 拒绝 |
| `animation.enabled` | 动画图标默认 true；false 显示静态代表帧；静态图标不能强行开启动画 |
| `animation.period_ms` | 完整像素动画周期，默认取图标数据 |
| `animation.repeat` | 0 无限，正整数轮数；完成后保持末帧 |
| `text` | 1～64 个 ASCII 可打印字符，保留前导零；不接受换行、中文 |
| `scroll.mode` | auto 按宽度；always 强制；never 静态且超宽时报错 |
| `scroll.direction` | left 默认；right 可选 |
| `scroll.step_ms` | 每移动一像素的时间，默认 180（约 5.6 像素/秒） |
| `scroll.repeat` | 默认 1；0 无限；有限滚动完成后释放显示 |
| `color.mode` | solid、step、gradient、rainbow_cycle、rainbow_flow |
| `color.values` | solid 一个颜色；step/gradient 2～8 个颜色；彩虹使用预设七色 |
| `color.period_ms` | 完整颜色循环，默认 5000 |
| `color.scope` | primary 默认、all；首版图标采用主色和灰度，没有独立辅助色，二者结果相同 |
| `effect.type` | none 默认、breathe、alternate、blink |
| `effect.period_ms` | 明暗循环，默认 2000 |
| `effect.min/max` | 相对亮度 0～255，默认 0/255，min 不得高于 max；blink 的 min 必须为 0 |
| `brightness` | 可选，0～255，改变全局用户亮度；开机 64（25%） |
| `duration_ms` | 0 或省略不限时；正数为墙钟有效时间，最大一天 |

固定字形为 5×7，字符间隔一列，宽度为 `6×字符数−1`。静态内容居中；滚动从屏幕外开始，完全离开后有三列空白再开始下一轮。短文本 auto 模式静态显示，不因 repeat 自动结束，可使用 duration_ms。

颜色表：red `#FF0000`、orange `#FF8000`、yellow `#FFFF00`、green `#00FF00`、cyan `#00FFFF`、blue `#0040FF`、purple `#A000FF`、pink `#FF4080`、white `#FFFFFF`、off `#000000`。也接受严格六位 `#RRGGBB`。

渐变按 RGB 在线性时间内插值，并从最后一色回到第一色；七彩采用上述前七种颜色。空间彩虹按横向像素位置增加 `x/8` 相位。呼吸由最大值平滑降到最小值再回升；明暗交替各占半周期。背景不着色。

## 时序与桌宠

| 命令 | 行为 |
| --- | --- |
| `brightness` + `value` | 设置 0～255 用户亮度，不重启动画；0 保留逻辑状态 |
| `speed` + `value` | 全局绝对倍率 0.25～4，默认 1；保持相位，实际周期除以倍率 |
| `pause` / `resume` | 冻结／继续当前画面的所有动画相位，有效时长继续消耗 |
| `idle` + `mode` | pet 或 off，只修改空闲方式，不覆盖临时内容 |
| `clock` + `epoch` + `utc_offset_min` | 校准 Unix 秒和 UTC 分钟偏移；浏览器连接时自动发送 |
| `time` | 立即以 24 小时制滚动显示当前 `HH:MM`，结束后返回空闲模式 |
| `release` | 释放临时内容，桌宠从竖线雨重新开始 |
| `keepalive` + `target_id` | 仅匹配当前显示 ID 才续原有效时长，不重启动画 |
| `off` | 清除显示、计时和桌宠；不会被 resume 重新点亮 |
| `get` | 查询内容、有效参数、亮度、倍速、暂停、剩余时间及限流状态 |
| `provision` | 已认证连接发送 `{"id":1,"op":"provision"}`，主动开启密码保护的配置热点 |

新 show/text 替换旧内容，从头播放；颜色和特效省略时恢复新内容的默认值，不继承旧内容。用户亮度、速度则保留至本次开机结束。协议没有显示队列、优先级或自动恢复旧覆盖层。

像素动画的有限轮数结束后，颜色及明暗变化继续；文字完成或有效期到期会释放，二者以先发生者为准。暂停不暂停 TTL。断线不把任务判定为完成，原 TTL 继续生效。

桌宠上电先显示仅绿色通道的下坠竖线：长短、深浅和密度随机变化，每 200 毫秒下落一格，持续随机 36～48 秒；随后显示暖黄色微笑 4 秒，再随机播放一次眨眼或心形动作约 2.2 秒，然后返回竖线雨。独立图鉴仍保留开心、惊讶和困倦图标，但桌宠不自动使用它们。自动报时首次在开机后随机 2～7 分钟触发，之后每隔随机 2～7 分钟滚动一次 24 小时制 `HH:MM`，不显示时区和秒；主动发送 `time` 可随时显示，手动从 off 切换到 pet 时优先报时。软件状态临时覆盖，到期或释放后恢复竖线雨。网页 GIF 是代表性节奏示意，真机的竖线、动作和间隔仍有随机性。

## 边界

参数先完整校验，再替换状态；无效命令不能部分修改亮度或其他设置。

- 基础周期范围 100～60000ms，重复次数 0～65535。
- 乘入全局速度后，每个像素动画帧及滚动步进至少 20ms。
- 有效颜色周期至少 500ms，闪烁和明暗周期至少 500ms，呼吸至少 600ms。
- 调速使当前画面违反上述限制时拒绝整条调速命令；后续新内容也按当前倍速校验。
- 用户亮度之后应用 500mA 灯板估算电流限制。功耗字段为估计值，不是测量值。
- 收到未知图标、非法颜色、参数类型错误、长度超限或非法组合均拒绝，保留当前画面。

## 软件状态例子

处理中：`loading`；等待用户：橙色呼吸 `question`；成功：绿色 `success` 显示 3000ms；失败：红色 `error` 明暗交替；额度：滚动 `100%` 或 `25% LEFT`。

长任务显示设置 15000ms TTL，每 5000ms 发一次匹配 target_id 的 keepalive。应用退出时发送 release。使用者负责从目标软件可靠地取得状态和单位，本项目不推测 Codex 额度含义。
