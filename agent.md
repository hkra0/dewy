# dewy — 植物自动化监控与浇水系统

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
index.html / app.js / style.css   单页应用（app.js 1194 行，待拆分）
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

- **`local_sensor_updater`**（`logic/power.py`）— 每 2 秒读一次本地传感器写入内存；同时监测 UPS 电流。
  连续放电超 120 秒且无网络 → 进省电模式（关 HDMI/LED、断 WiFi、下线 3 个 CPU 核）。
  恢复需连续 3 次确认，防电流抖动导致反复切换。省电模式下轮询降到 60 秒。
  **省电模式受看门狗保护，详见下方。**
- **`background_logger`**（`logic/scheduler.py`）— 主循环，每轮：灯控 → 采样归档 → 自动浇水 → 每日照片。
  正常 10 分钟一轮，省电模式 1 小时一轮，且**对齐到整点/整十分**（便于历史图表按固定间隔聚合）。

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
2. 在 `hardware/manager.py` 的 `driver_map` 里注册一行
3. 在 `hardware_config.toml` 里声明

**不需要改动 core 或 api 的任何代码。** 已注册：`SHT30`、`ADS1115_Soil`、`INA219_UPS`、`GPIO_Relay`、`MQTT_Relay`。
`drivers/` 下另有 8 个未注册的驱动（DHT、BME280、BH1750、AHT20、DS18B20、HTTP、Script、Dummy），
它们都是惰性 import，依赖未安装也不影响启动——要用时在 `driver_map` 注册即可。

### 多节点

`node_id` 贯穿数据库、API、前端。加一株植物只需在配置里加一个节点，前端会自动出现设备切换。

---

## 五、边缘代理与前端

`worker.js` 通过 `wrangler.toml` 的 `[[rules]]` 把 `index.html` / `style.css` / `app.js`
作为文本内联进 Worker，按路径分发。API 请求转发到 `PI_BASE_URL`，并注入 `X-BFF-To-Pi-Token`。

前端四个视图：`environment`（实时数据 + 摄像头）、`system`（供电/CPU/内存/磁盘）、
`history`（Chart.js 曲线 + 浇水日志）、`settings`（自动浇水/补光/拍照配置）。
另有照片时间轴播放器与 GIF 导出（gifshot 从 CDN 加载，有三个备用源）。中英双语，按 `navigator.language` 自动选择。

---

## 六、配置与环境变量

### 树莓派端

| 变量 | 默认 | 说明 |
|---|---|---|
| `PI_SECRET_TOKEN` | 自动生成 | BFF→Pi 共享密钥。未设时自动生成并写入 `data/secret_token`（权限 600），启动日志会打印，需同步到 Worker |
| `DEWY_DATA_DIR` | `<项目根>/data` | 数据目录（数据库、照片、配置、密钥） |
| `DEWY_POWER_SAVER` | `<项目根>/power_saver.sh` | 省电脚本路径 |
| `DEWY_LOG_LEVEL` | `INFO` | 日志级别 |
| `DEWY_LOG_FILE` | 未设 | 设置后额外落盘，按 5MB × 3 份轮转 |

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
3. **Worker → Pi**：请求头 `X-BFF-To-Pi-Token` 匹配 `PI_SECRET_TOKEN`，10 个端点逐一校验，无旁路。

前端首次通过魔法链接 `?key=` 把 viewer key 写入 localStorage；浇水密钥单独存 `robin_water_key`。

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
- **`can_water_now` 用 `datetime.utcnow()` 与库里的 UTC 时间戳比较**，二者时区一致。
  不要改成本地时间，会导致间隔判断错 8 小时。（注：`utcnow()` 在 Python 3.12+ 已废弃，
  未来迁移到 `datetime.now(timezone.utc)` 时两侧要一起改。）

### 已知待办

- `app.js` 1194 行单文件、约 20 个全局变量、无构建步骤，是当前最该拆分的部分。
- `test/` 目录名不副实，里面是手动硬件调试脚本而非自动化测试。
  `compute_next_boundary`、`_select_photos_to_delete`、土壤离群值过滤这三处是纯函数，最适合先补测试。
