# dewy — 植物自动化监控与浇水系统

> Maintenance notes for contributors and coding agents, written in Chinese.
> Machine translation reads fine — the content is architectural, not idiomatic.

基于树莓派（Raspberry Pi Zero 2 WH）+ Cloudflare Workers 边缘代理的植物监控系统。
约 5400 行代码，四层架构：ESP32 固件 → 树莓派后端 → 边缘代理 → 浏览器前端。

---

## 一、架构总览

```
┌─────────────┐   MQTT    ┌──────────────────┐  HTTPS   ┌────────────────┐  HTTPS  ┌─────────┐
│ ESP32 节点  │ ────────▶ │  树莓派 (main.py) │ ◀─────── │ Cloudflare     │ ◀────── │ 浏览器  │
│ firmware/   │           │  FastAPI + SQLite │          │ Worker (BFF)   │         │ 单页应用│
└─────────────┘           └──────────────────┘          └────────────────┘         └─────────┘
                            ▲ I2C / GPIO                   worker.js                app.js
                            │                              纯代理 + 鉴权            index.html
                       传感器 / 水泵 / 摄像头                                        style.css
```

- **树莓派**是唯一持有数据和硬件的一端，对外只暴露内网 `127.0.0.1:8000`，经隧道由 Worker 访问。
- **Worker 不含业务逻辑**（仅 91 行），只做鉴权 + 转发 + 下发静态资源。改功能基本不需要动它。
- **前端**由 Worker 下发，通过 Worker 反代调用树莓派 API。

---

## 二、目录结构

```
main.py                  仅做装配：配置日志 → 建 FastAPI → 起后台线程 → 连 MQTT（49 行）
core/
  paths.py               所有路径由 __file__ 推导，零依赖、无副作用
  logging_setup.py       日志配置，必须在其它 core 模块导入前调用
  state.py               全局状态、硬件锁、密钥加载
  config.py              用户配置（config.json）的读写与默认值合并
  database.py            数据访问层（DAL）——全项目唯一允许出现 sqlite3 的地方
  mqtt_handler.py        MQTT 连接与消息回调
  logic/                 业务逻辑，按职责拆分
    system.py            网络探测、CPU/内存/磁盘查询
    power.py             UPS 放电监测与省电模式进出
    light.py             补光灯定时、日出日落推算、手动覆盖
    watering.py          浇水触发、间隔判定、土壤离群值过滤
    photo.py             每日拍照、磁盘不足时的对数稀疏化清理
    scheduler.py         后台主循环
api/routers.py           全部 HTTP 接口（10 个端点）
hardware/
  manager.py             硬件抽象层：读配置 → 动态加载驱动 → 统一读写接口
  drivers/               13 个驱动，每个实现 read() 或 trigger()
worker.js                Cloudflare Worker：鉴权 + 反代 + 下发前端
index.html / style.css   单页应用的骨架与样式
app.js                   前端入口：挂载 window 全局、绑定 onload
js/                      前端 ES 模块
  api.js                 所有 API 调用的唯一出口，鉴权头在此注入
  i18n.js                中英文案与 t()
  state.js               跨模块共享状态（可变对象）与 localStorage 键
  ui.js                  showToast
  navigation.js          设备/标签页/历史子页切换与 URL 同步
  dashboard.js           环境视图：指标卡片、浇水、切灯
  history.js             Chart.js 曲线与浇水日志
  camera.js              实时预览与高清抓拍
  timeline.js            照片时间轴与 GIF 导出
  settings.js            配置读写
  refresh.js             fetchAllData（单独成模块以打断循环引用）
firmware/plant_node/     ESP32 固件（PlatformIO / Arduino）
scripts/migrate_db.py    历史库迁移（env_log → node_data）
test/                    手动硬件调试脚本，不是自动化测试
```

---

## 三、树莓派端

### 分层约定（改代码前必读）

| 层 | 可以做什么 | 禁止 |
|---|---|---|
| `api/routers.py` | 鉴权、参数校验、调用 logic/DAL、组装响应 | 直接 `import sqlite3` |
| `core/logic/*` | 业务判断与硬件编排 | 直接 `import sqlite3`、写死路径 |
| `core/database.py` | 所有 SQL | 业务判断 |
| `hardware/*` | 与器件对话 | 依赖 `core.state` / `config` / `database` / `logic` |

`hardware/*` 只允许依赖 core 里**零依赖的基础设施模块**（目前是 `core.logfold`，
纯标准库、无副作用）。禁止的是业务状态与数据层——那会让硬件层无法脱离本项目复用。
新增此类共享模块前先确认它不 import 任何其它 core 模块。

**数据库访问一律走 `core/database.py`。** 它提供上下文管理器：

```python
from core.database import get_conn

with get_conn() as conn:          # 自动持锁 → 正常退出 commit → 异常 rollback → 必定 close
    conn.execute("INSERT ...", params)
```

在此之上是 13 个语义化函数（`insert_node_data`、`query_24h_history`、`query_last_watering_time` …），
另有 `query()` / `execute()` 两个通用辅助。新增查询时**在 database.py 里加函数**，不要在业务代码里拼 SQL。

### 后台线程

`main.py` 启动两个 daemon 线程：

- **`local_sensor_updater`**（`logic/power.py`）— 读本地传感器写入内存，同时监测 UPS 电流。
  **采样分两档**：只有提供 `current` 的传感器按 10 秒读（`DEWY_UPS_SAMPLE_SEC` 可调），
  其余传感器 30 秒一轮。归档是 10 分钟、前端轮询 30 秒，温湿度按秒级读属于几百倍过采样，
  白占 CPU 与 I2C 总线，且 SHT30 高频读取会自热抬高温度读数。
  快档曾是 2 秒，放宽到 10 秒的依据：判据是"连续放电超 120 秒"，10 秒采样在窗口内仍有
  12 个样本；而且**任何一个高于阈值的样本都会把计时器清零**，所以采样越快越难进省电模式——
  放慢只会让判断更稳，同时把 I2C 事务量降到 1/5。
  哪些传感器进快档由 `hardware_manager.sensors_for_field("main", "current")` 在每次全量读取后
  重新探测（依据是驱动实际返回的字段，不是配置声明），坏掉又恢复的传感器会自动归队；
  节点上没有电流传感器时快档整个停掉，退化成 30 秒一轮。
  连续放电超 120 秒且无网络 → 进省电模式（关 HDMI/LED、断 WiFi、下线 3 个 CPU 核）。
  恢复需连续 3 次确认，防电流抖动导致反复切换。省电模式下不再分档，整体降到 60 秒。
  **省电模式受看门狗保护，详见下方。**
- **`background_logger`**（`logic/scheduler.py`）— 主循环，每轮：灯控 → 采样归档 → 自动浇水 → 每日照片 → 每日清理。
  正常 10 分钟一轮，省电模式 1 小时一轮，且**对齐到整点/整十分**（便于历史图表按固定间隔聚合）。
  清理放在每轮最后，且每天只跑一次（本地日期变化时触发），不该拖慢灯控与采样。

### 省电模式的看门狗（改这块前必读）

`power_saver.sh enable` 会 `rfkill block wifi bluetooth`。**Pi Zero 2 W 没有网口，
一旦断网就完全失联，只能物理断电恢复。** 为此脚本内置了看门狗：

- `enable` **先**挂一个 systemd 瞬态定时器（默认 30 分钟后自动执行 `disable`），**再**断网。
  顺序不可颠倒——万一定时器挂不上，此时网络还在，脚本会拒绝进入省电模式并返回非零。
- 想长期停留在省电模式，必须周期性调用 `power_saver.sh pet` 续期。
- `disable` 会同时撤销看门狗。由看门狗自身触发的 `disable` 通过 `DEWY_WATCHDOG_FIRED=1`
  识别，不会去停自己的定时器（防自锁）。

Python 侧的续期**只写在"确认仍需省电"的那个分支里**（`logic/power.py` 的 `else` 分支）。
这是刻意的：电流传感器读不到值、循环抛异常、线程卡死、服务崩溃——任何异常都会导致
无人续期，看门狗到点触发，网络自行恢复。**不要把 `pet` 挪到循环顶部或 `finally` 里，
那会让它在程序已经失灵时继续续期，看门狗就形同虚设。**

同理，`_run_power_saver()` 会检查退出码，**`enable` 失败时绝不能把 `power_save_mode`
置为 `True`**，否则内存状态与实际硬件状态不符。

超时时间用 `DEWY_POWERSAVE_WATCHDOG_MIN` 调整；`WATCHDOG_PET_INTERVAL_SEC`（默认 300 秒）
必须显著小于它。

> 手动测试省电模式时**永远不要直接在 SSH 里跑 `enable`**——命令一执行你自己就断线了，
> 后面的 `disable` 再也没机会执行。现在有了看门狗会自动恢复，但仍建议先用
> `DEWY_POWERSAVE_WATCHDOG_MIN=2` 缩短超时再测。

### 关键业务规则

- **自动浇水**：每天 6:00 检查，距上次浇水 > 12 小时且土壤湿度 < 阈值（默认 50%）时启泵，默认 0.5 秒。
  手动浇水经 `/api/water`，时长被钳制在 0.1–1.0 秒。
- **补光灯**：`fixed` 固定时段，或按经纬度实时推算日出日落（支持偏移量，经纬度缺失时用 IP 定位）。
  手动切灯置 `manual_override`，到下一个开/关边界自动失效。
- **每日照片**：到点拍一张 2592×1944 HQ 图 + 320×240 缩略图。磁盘剩余空间低于阈值（默认 20GB）时，
  按 `min_gap(d) = max(1, floor(3·ln(d+1)))` 稀疏化历史照片——近期密集、远期稀疏，最近 7 天永不删除。

---

## 四、硬件抽象层（扩展性最好的部分）

`hardware_config.toml`（支持 TOML/YAML/JSON）描述节点、传感器、执行器，
`HardwareManager` 读配置后用 `importlib` 动态加载驱动类。

```toml
[nodes.main]
type = "local"                    # local: 直连 I2C/GPIO

[nodes.main.sensors.sht30]
driver = "SHT30"                  # 对应 driver_map 里的键
bus = 1
address = "0x44"

[nodes.main.actuators.pump]
driver = "GPIO_Relay"
pin = 4
active_low = true

[nodes.sub1]
type = "mqtt_node"                # mqtt_node: 通过 MQTT 收数据
topic = "sensor/esp32/env_data"
```

### 新增一个传感器

1. 在 `hardware/drivers/` 写一个类，实现 `read()` 返回 dict（执行器实现 `trigger(**kwargs)` 返回 bool）
   （`read()` 返回的键会被 manager 记下来，供 `sensors_for_field` 按字段挑传感器——见分档采样）
2. 在 `hardware/manager.py` 的 `driver_map` 里注册一行
3. 在 `hardware_config.toml` 里声明

**不需要改动 core 或 api 的任何代码。** 已注册：`SHT30`、`ADS1115_Soil`、`INA219_UPS`、`GPIO_Relay`、`MQTT_Relay`。
`drivers/` 下另有 8 个未注册的驱动（DHT、BME280、BH1750、AHT20、DS18B20、HTTP、Script、Dummy），
它们都是惰性 import，依赖未安装也不影响启动——要用时在 `driver_map` 注册即可。

### 多节点

`node_id` 贯穿数据库、API、前端。加一株植物只需在配置里加一个节点，前端会自动出现设备切换。

---

## 五、边缘代理与前端

`worker.js` 通过 `wrangler.toml` 的 `[[rules]]` 把 `index.html` / `style.css` / `app.js` / `js/*.js`
作为文本内联进 Worker，按路径分发。API 请求转发到 `PI_BASE_URL`，并注入 `X-BFF-To-Pi-Token`。

前端是**无构建步骤的原生 ES 模块**（`<script type="module">`），浏览器按 import 逐个请求。
改前端时需要注意的地方：

1. **新增一个 js 模块要改三处**：`worker.js` 的 `JS_MODULES`（Wrangler 的 Text 规则
   只能静态 import，无法遍历目录）、`index.html` 的 `modulepreload` 列表、以及 import 它的模块。
   漏掉 `JS_MODULES` 的话该路径会 404——已特意让未注册的 `/js/` 路径返回 404 而不是
   回落到 SPA 兜底，否则浏览器只报一个难以定位的 MIME 错误。

   `wrangler.toml` 里那条 Text 规则的 glob **必须写成 `**/js/*.js`**。写 `js/*.js`
   匹配不到任何文件，js 模块会被当成普通 ES 模块打包，报
   "No matching export for import default"，整个 Worker 构建失败。改完跑
   `npx wrangler deploy --dry-run` 验证。
2. **所有色值一律用 CSS 变量**，包括指标语义色（`--metric-temp` / `--metric-hum` /
   `--metric-soil` / `--metric-pres` / `--metric-water` / `--metric-light-on` /
   `--metric-power` / `--metric-cpu`）**和状态色**（`--danger` / `--text-muted` / `--accent`），
   定义在 `style.css` 的 `:root` 与暗色媒体查询里。不要再往 HTML 或 js 里写十六进制色值。
   Chart.js 只认真实色值，`history.js` 用 `getComputedStyle` 从 `:root` 读，色值来源仍是 CSS。

   两个容易踩的点：
   - **土壤湿度是 `--metric-soil`，不是 `--accent`。** 卡片曾用 `--accent`、曲线用
     `--metric-soil`，同一个指标在两个视图里是两种颜色。
   - **背景是 `--accent` 的控件，文字必须用 `--on-accent`**（按钮、`.sub-nav-btn.active`）。
     暗色下 `--accent` 是浅绿 `#81c995`，写死白字对比度只有 ~1.9:1。

   仅有的合法例外：`timeline.js` 里烧进导出 GIF 的水印色（画布没有 CSS 变量，
   而且导出结果不该随浏览器主题变），以及 `history.js` 里 `getComputedStyle` 取不到时的兜底值。

   圆角同理用 `--radius-sm|md|lg`，不要再写字面 px。

3. **带 `onclick` 的元素必须可聚焦**：优先用真正的 `<button>`；实在只能是 `div`/`img` 时
   加 `role="button" tabindex="0"`。Enter/Space 由 `js/ui.js` 的 `initKeyboardActivation()`
   委托到 `document` 统一处理（认 `role="button"`），所以 `dashboard.js` 每轮重新生成的
   灯卡片也自动覆盖，**不需要**在渲染处重复绑定键盘事件。

4. **模块作用域不是全局作用域**。`index.html` 和 `dashboard.js` 生成的 HTML 里用了
   `onclick="xxx()"`，这类内联处理器只认 `window` 上的函数。新增内联处理器时，
   必须在 `app.js` 顶部的 `Object.assign(window, {...})` 里同步登记，否则点击即报错。
5. **不要直接调 `fetch('/api/...')`**。一律走 `js/api.js`：只读端点用 `apiGet`，
   高危端点用 `apiWater` / `apiWaterPost`，鉴权头由它注入（`bust()` 用于加时间戳防缓存）。
   新增端点时把它归到哪把钥匙下想清楚——这是 Worker 侧鉴权分支的镜像。

前端四个视图：`environment`（实时数据 + 摄像头）、`system`（供电/CPU/内存/磁盘）、
`history`（Chart.js 曲线 + 浇水日志）、`settings`（自动浇水/补光/拍照配置）。
另有照片时间轴播放器与 GIF 导出。

中英双语：默认按 `navigator.language` 选择，覆盖走链接参数 `?lang=zh` / `#lang=zh`，
存进 localStorage 的 `dewy_lang` 后长期生效。

**刻意不做界面上的语言开关。** 页面只有四个 tab，任何常驻的语言控件都会跟主导航
抢视觉权重、显得比实际功能还重要；而设置页要浇水密钥才可见，访客够不着。
链接参数则是这个项目**已有**的习惯（魔法链接本来就在传 `key`/`water_key`），
零像素占用。曾经在页头加过一个 EN/中 的 pill 开关，因为喧宾夺主已移除——
要再加请先想清楚放哪里，而不是放回标题正下方。

因为没有运行时切换入口，语言在 `checkMagicLink()` 里就定下来了，**早于**
`applyTranslations()`（`app.js` 的调用顺序保证了这点），所以不需要任何重绘逻辑。
若将来真要加运行时切换，记住：光改 `currentLang` 不够，指标卡片、图表数据集标签、
日志表头都是渲染时经 `t()` 生成的，必须连带重绘。

**Chart.js 与 gifshot 都由 `js/cdn.js` 按需加载**（各有三个备用 CDN），不要再写回
`index.html` 的 `<head>`——那样每个只看环境页的访客都要白下载约 240KB。
`renderHistoryUI` 因此是 async 的，调用处需要 await。

### 预览图的条件请求（改这三处任一处前必读）

`/api/image` 只在带 `live=true` 时才真的跑 `rpicam-jpeg` 重写 `data/live.jpg`；
不带 `live` 只是把磁盘上那张发回去。而前端 30 秒轮询一次——**不带条件的话，
每轮都在重下同一张几十 KB 的图**，穿过 Cloudflare 与隧道白烧流量。

因此轮询路径带 `?since=<已持有图片的 mtime 秒>`，未变更时链路上三处配合返回 304：

- `api/routers.py` 的 `get_image`：`not live and since >= mtime` → `Response(304)`。
- `worker.js`：**304 的判断必须排在 `!piResponse.ok` 之前**，因为 `Response.ok` 只认 2xx，
  落到下面会被当成故障、回一个带 `"offline"` body 的 304——而 304 本就不允许带 body。
- `js/camera.js`：`currentCamEpoch` 记着当前这张的时间戳；收到 304 只重绘时间戳标签
  （是否 `⏳` 取决于当前时刻，不取决于响应），不碰 `img.src`。

不要"优化"成轮询时也 `live=true`：那等于让树莓派全天候每 30 秒唤醒一次 ISP。
也不要去掉 `since` 退回无条件 GET。

### 静态资源缓存

`worker.js` 给所有静态资源一个共用 `ETag`，响应带
`Cache-Control: public, max-age=0, must-revalidate`，命中 `If-None-Match` 返回 304。

**所有资源共用同一个 ETag 是有意的**：它们本来就同一次部署，共用 ETag 才能保证
`index.html` 与 `js/*.js` 不会各自缓存到不同版本。URL 里没有内容哈希，
所以也**不能**改成长 `max-age`——那样改完发上去，用户手里还是旧版本。

ETag 的值取自 `wrangler.toml` 的 `[version_metadata]` 绑定（`env.CF_VERSION_METADATA.id`），
每次部署自动变——"同一次部署"正是这个 id 的语义，且零计算。绑定缺失时（本地 dev、
旧版 wrangler）才退回逐字符的内容哈希，并且是懒计算，正常路径下那个循环根本不会跑。
**不要把它改回模块初始化时无条件哈希**：那是每个 isolate 冷启动都要付的十几万次循环。

### 安全响应头

所有响应带 `X-Content-Type-Options: nosniff` 与 `Referrer-Policy: no-referrer`
（后者也兜住旧格式魔法链接的密钥泄漏）。HTML 文档额外带一条 CSP。

CSP 的 `script-src` **保留了 `'unsafe-inline'`**，因为内联 `onclick` 是本项目的既定约定
（见上文第 4 条）。所以它挡不住注入的内联脚本，挡的是**主机**：外部脚本加载不了，
`connect-src 'self'` 让数据无法外发到任意域名。想拿掉 `'unsafe-inline'` 就得先把全部
内联处理器改成 `addEventListener`，那是另一件事。

**改 `js/cdn.js` 的 CDN 列表时必须同步 CSP 的 `script-src`**，否则库会被拦掉、
图表与 GIF 导出静默失效。`worker-src blob:` 是 gifshot 的 worker 需要的。

API 响应**不带 CORS 头**。前端与 API 同源，而鉴权走自定义头、跨源必须过预检，
这里又没有 OPTIONS 处理器——之前那行 `Access-Control-Allow-Origin: *` 是死代码，已移除。
不要因为"看着少了个头"再加回来。

### 浏览器历史

`updateURL()` 用 `pushState` 写地址栏，`initHistoryNav()`（`app.js` 启动时调用一次）
监听 `popstate` 把地址栏变化同步回视图。两者缺一不可：只 push 不监听，
前进/后退就只会改地址栏、界面不动。popstate 分支里所有 `switchTab`/`switchDevice`
都必须传 `pushState=false`，否则后退会再压一条历史记录。

---

## 六、配置与环境变量

### 树莓派端

| 变量 | 默认 | 说明 |
|---|---|---|
| `PI_SECRET_TOKEN` | 自动生成 | BFF→Pi 共享密钥。未设时自动生成并写入 `data/secret_token`（权限 600），启动日志会打印，需同步到 Worker |
| `DEWY_DATA_DIR` | `<项目根>/data` | 数据目录（数据库、照片、配置、密钥） |
| `DEWY_POWER_SAVER` | `<项目根>/power_saver.sh` | 省电脚本路径 |
| `DEWY_DATA_RETENTION_DAYS` | `365` | `node_data` 保留天数，超期行每天清理一次。设 0 关闭清理 |
| `DEWY_LOG_LEVEL` | `INFO` | 日志级别 |
| `DEWY_LOG_FILE` | 未设 | 设置后额外落盘，按 5MB × 3 份轮转 |
| `DEWY_UPS_SAMPLE_SEC` | `10` | UPS 电流的快档采样间隔（秒）。必须显著小于 `DISCHARGE_CONFIRM_SEC`(120) |

用户可调配置存于 `data/config.json`（`auto_water` / `auto_light` / `daily_photo`），
经 `/api/config` 读写，缺失字段会与 `DEFAULT_CONFIG` 自动合并。

### Worker 端

`PI_BASE_URL` 为变量；`PI_SECRET_TOKEN`、`VIEWER_MAGIC_KEY`、`WATER_MAGIC_KEY` 用
`wrangler secret put <NAME>` 设置。

---

## 七、鉴权

三道关卡，逐级收紧：

1. **Client → Worker（只读）**：`/api/monitor`、`/api/history`、`/api/nodes`、
   `/api/image`、`/api/photos*` 一律要求请求头 `X-Viewer-Key` 匹配 `VIEWER_MAGIC_KEY`，
   不匹配返回 404（不暴露端点存在）。**无任何旁路。**
2. **Client → Worker（高危操作）**：`/api/water`、`/api/light`、`/api/config` 要求
   请求头 `x-water-key` 匹配 `WATER_MAGIC_KEY`，不匹配返回 403。
   注意 viewer key 不能用于这三个端点，两把钥匙互相独立。
3. **Worker → Pi**：请求头 `X-BFF-To-Pi-Token` 匹配 `PI_SECRET_TOKEN`。校验挂在
   `APIRouter(dependencies=[Depends(verify_pi_token)])` 上，**对全部端点默认生效**——
   新增端点自动受保护，不会因为忘了粘贴校验代码而默默敞开。要放开某个端点必须显式声明。
   比较用 `hmac.compare_digest`，避免逐字节比较带来的时序差异。

前端首次通过魔法链接把 viewer key 写入 localStorage；浇水密钥单独存 `robin_water_key`。

**新链接一律用片段**：`https://…/#key=xxx&water_key=yyy`（可再带 `&lang=zh`）。
片段不随请求上行，密钥不会进 Cloudflare 的边缘访问日志，也不会出现在发往第三方
CDN/字体服务的 Referer 里。`?key=` 两处都会泄漏，而 `replaceState` 只擦得掉地址栏、
擦不掉已经写下的日志。`checkMagicLink` 仍然接受 `?key=`（否则已分享出去的旧链接全部失效），
但**不要再用它生成新链接**。

密钥挪进片段后多出一条路径需要照顾：**只改 hash 的导航不会重新加载文档**，
`window.onload` 不触发，`checkMagicLink` 也就不跑——用户已经开着页面时再点一条
`#key=` 链接会毫无反应。`initMagicLinkNav()` 监听 `hashchange` 补上这一段，
消费到参数后直接 `location.reload()`（此时参数已落盘、URL 已擦净，重载即走正常启动流程）。
`replaceState` 不触发 `hashchange`，所以不会自我循环。query 形式不受影响——
换 query 一定是整页导航。

`setLang()` **即使新值与当前生效值相同也要落盘**。用户点 `?lang=zh` 是显式选择，
不该因为"碰巧和 `navigator.language` 一致"就不被记住，否则哪天浏览器语言变了这个选择会静默失效。
落盘与"是否需要重绘"是两件事，返回值只表示后者。

### 无密钥＝访客路径，必须保持静默

没有 viewer key 时前端**不发任何 API 请求**，也不显示任何提示或残留的加载态——
这是有意设计的：链接可以直接分享出去，拿不到密钥的人看到的就是一个普通空页面，
不该暴露"这里有个需要授权的系统"。

因此**不要给无密钥状态加"请获取密钥"之类的引导**。同理，Worker 对密钥不匹配一律回
404 而不是 403，前端收到 404 也必须静默返回。

只有**网络异常与 5xx**（Pi 掉线、边缘错误）才在状态栏提示 `conn_lost`——
那是持有有效密钥的用户，需要能分辨"数据没变"和"已经断了"。
新增前端请求时照此区分：`404 → 静默`，`其余失败 → 提示`。

> 历史注记：`/api/monitor`、`/api/history`、`/api/nodes` 曾接受
> `X-Requested-By: Robin-Web` 作为 `X-Viewer-Key` 的替代凭证。该头是写死在前端的
> 非机密字符串，等同于无鉴权，已于 2026-08 移除。新增只读端点时**不要**再引入类似的
> "标识头即凭证"设计。

---

## 八、数据库

SQLite（WAL 模式），三张表：

- **`node_data`** — 环境采样。`is_anomaly=1` 的行会被所有统计与图表排除。
- **`watering_log`** — 浇水记录（时长、浇水前土壤湿度）。
- **`photo_log`** — 每日照片索引，`date` 唯一。

时间戳统一用 SQLite 的 `CURRENT_TIMESTAMP`（**UTC**），查询时用 `datetime(timestamp, 'localtime')` 转本地时区。

### 保留策略

`node_data` 每天清理一次超过 `DEWY_DATA_RETENTION_DAYS`（默认 365 天）的行；
`watering_log` 与 `photo_log` 是稀疏的人类可读事件，**全部保留**（照片文件本身另有对数稀疏化清理）。

历史查询**必须带 timestamp 条件**。`daily` 视图按 `date(timestamp,'localtime')` 分组，
这是表达式分组、索引帮不上忙，`LIMIT` 又只作用于分组之后——没有 WHERE 上的时间窗口，
每次查询都是全表扫描，且随数据积累逐年变慢。新增聚合查询时照此办理。

`prune_node_data()` 分批删除（每批 500 行）以免长时间独占 `db_lock`，
且**每批都带 timestamp 条件**。不要"优化"成先取 `MAX(id)` 再按 id 区间删——
那要求 id 与 timestamp 同向递增，而 `scripts/migrate_db.py` 会写入带历史时间戳的行，
顺序一旦不成立就会把未过期的数据一起删掉。不执行 VACUUM：SQLite 会复用释放的页，
文件不缩小但也不再增长，而 VACUUM 要重写整库，在 SD 卡上代价过高。

---

## 九、AI 代理维护注意事项

### 必须遵守

- **不要在 `core/logic/*` 或 `api/routers.py` 里 `import sqlite3`**——所有 SQL 归 `core/database.py`。
  历史上这里出过连接泄漏（持锁时提前 `return`），DAL 的上下文管理器就是为杜绝此类问题而存在。
- **不要写死路径**。一律从 `core/paths.py` 取，它由 `__file__` 推导，换用户名/换部署目录都不受影响。
- **`main.py` 里 `setup_logging()` 必须在任何 `core.*` 导入之前执行**（故意不放在 import 块顶部，
  已加 `# noqa: E402`）。否则 `core.state` 的密钥告警和 `hardware.manager` 的配置日志会丢失。
- **用 logging 不用 print**。服务代码全部已改造完毕；`scripts/` 和 `test/` 下的独立脚本除外。
- **高频路径上的失败日志必须用 `core/logfold.py` 折叠**。判断标准：这行日志所在的代码
  是否可能被每秒/每几秒调用一次（传感器轮询、MQTT 回调、API 处理）。
  直接 `logger.warning` 会在硬件故障时产生每天十几万条日志，既刷屏又损耗 SD 卡。
  用法：`log_failure(logger, key, msg, *args)` + 成功时 `log_recovery(logger, key, ...)`，
  key 需能区分不同故障源（如 `f"sensor:{node_id}:{s_id}"`）。
- **不要写裸 `except:`**——它会连 `KeyboardInterrupt` 一起吞掉，导致 Ctrl-C 停不掉服务。

### 并发与硬件锁

三把锁，用途不同，**不要混用或嵌套错顺序**：

- `state.db_lock`（**RLock**，可重入）— 由 `database.get_conn()` 自动持有，业务代码不要手动获取。
- `state.camera_lock` — `rpicam-jpeg` 同一时刻只能有一个实例。
- `HardwareManager.sensor_lock` — I2C 总线互斥，并发访问会导致总线挂死。

### 容易被"误修"的既有行为

- **ADS1115 的截尾均值滤波 + 基准电压比例补偿**（`drivers/ads1115.py`）是为抵消供电波动而设计的：
  多次采样后排序、截去两端极值再取平均，然后按 `VCC_BASE / vcc_raw` 做比例校正。
  改动前务必理解整套算法，不要简化。SHT30 同样对多次采样排序取中位。
- **`apply_light_schedule` 每轮都重发 MQTT 指令**，而非仅在状态变化时发。这是有意的——
  ESP32 掉电重启后靠下一轮指令自动恢复。
- **手动覆盖到期的那一轮会连发两次灯控指令**（先清除 override 发一次，紧接着定时分支再发一次）。
  指令幂等、无实际影响，属已知行为。
- **`cleanup_old_photos` 里的 `MIN_PHOTOS_TO_CLEAN = 30` 是触发门槛，不是删除下限**。
  一旦触发会沿曲线一直删到磁盘够用，实测 120 张可删到 18 张。
- **切灯的乐观状态必须会过期**（`dashboard.js` 的 `optimisticLightStatus` /
  `optimisticLightUntil`）。它只用来填补"MQTT 指令已发、服务端 `light_status` 还没回报"
  的那一个轮询周期。两个交还时机缺一不可：服务端追上时提前交还、超过 TTL(35s) 兜底交还。
  历史上它一经设置就永不清空，结果是定时灯控到点关灯、或 `manual_override` 到期之后，
  界面仍显示用户当初点的那个值。**失败分支也不要把点击前的状态写回成新的乐观值**——
  那同样是一个永不过期的遮蔽。
- **`fetchAllData` 在启动路径上只应被调用一次**。`parseURLAndNavigate()` 里的
  `switchDevice`/`switchTab` 都传 `skipFetch=true`，取数由 `app.js` 统一发起。
  给 `switchDevice` 补 `fetchAllData` 会让每次打开页面都多打一轮请求、多跑一次 rpicam。
  popstate 分支相反，那里需要 `switchDevice` 自己取数。
- **GIF 导出的帧数上限与并发不是保险，是必需**（`timeline.js` 的 `GIF_MAX_FRAMES=120`、
  `GIF_FETCH_CONCURRENCY=5`）。照片按对数稀疏化策略只增不减，而每帧是一次
  浏览器→Cloudflare→隧道→Pi 的往返；去掉上限后几百个 data URL 同时驻留内存喂给
  gifshot，手机上等于标签页崩溃。`selectGifFrames` 均匀抽样并保证首尾入选。
- **`can_water_now` 用 `datetime.utcnow()` 与库里的 UTC 时间戳比较**，二者时区一致。
  不要改成本地时间，会导致间隔判断错 8 小时。（注：`utcnow()` 在 Python 3.12+ 已废弃，
  未来迁移到 `datetime.now(timezone.utc)` 时两侧要一起改。）

### 已知待办

- `test/` 目录名不副实，里面是手动硬件调试脚本而非自动化测试。
  `compute_next_boundary`、`_select_photos_to_delete`、土壤离群值过滤这三处是纯函数，最适合先补测试。
