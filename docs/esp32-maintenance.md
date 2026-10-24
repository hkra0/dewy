# ESP32 远程维护

链路：网页或脚本 → Worker（water key）→ Pi → MQTT → ESP32。
无需 ESP32 的 IP 地址、端口转发、HTTP 固件下载服务或公网串口。
OTA 与日志查看都只允许管理员使用，viewer key 无权读取维护日志。

## 首次安装（每个节点一次）

1. 在 Pi 的私有 `hardware_config.toml` 对应 `[nodes.<id>]` 段加入
   `maintenance_key = "<独立随机密钥>"`，用 `python -c "import secrets; print(secrets.token_hex(32))"`
   生成。至少 32 个 ASCII 字符，不提交仓库、不通过 `/api/nodes` 下发。
   编译机器与 Pi 使用同一份该节点配置；所有远端节点分别配置，不共用密钥。
2. 为目标板选择 PlatformIO 环境。当前仓库提供 `esp32s3mini`，其他板需复制该环境并
   修改 `board` 和引脚。必须使用含 `otadata` 和两个应用槽的 OTA 分区表；不能使用
   `no_ota` / `huge_app`。本功能不通过 OTA 修改分区表或 bootloader。
   当前固定 PlatformIO Espressif32 7.0.1 / Arduino 2.0.17 的回滚版 SDK/bootloader；
   构建会检查真实 SDK 回滚选项与延迟验证 hook，不可用 `-D` 冒充 bootloader 配置。
3. Linux/macOS：`DEWY_NODE=aqua pio run -e esp32s3mini -t upload`。
   PowerShell：先 `$env:DEWY_NODE='aqua'`，再 `pio run -e esp32s3mini -t upload`。
   这是唯一必须连接 USB 的步骤，**必须完整上传 bootloader、分区表与应用**，不能只写应用。
   若装过上一版维护固件，也需要 USB 安装此次回滚基线；Pi 会拒绝无协议 v2 的基线/镜像。
   缺失维护密钥时固件仍可构建，但 OTA/日志发布被禁用。
   CI 可通过 `DEWY_MAINTENANCE_KEY` 环境变量覆盖构建密钥；必须与 Pi 的该节点密钥一致。
4. 更新并重启 Pi 服务，部署 Worker（`npx wrangler deploy`）。用含 water key 的已有
   管理链接进入网页，选择节点 → 设置 → 远程维护，应显示在线、板型和固件 build 标识。

Pi 重连时订阅所有已配置维护密钥的 MQTT 节点，每个节点使用
`<config_topic>/maintenance/set` 与 `<config_topic>/maintenance/state`，不使用 retained 消息。
固件每 5 秒发布心跳。节点超过 20 秒未回报显示离线。

## 网页升级

设置 `DEWY_NODE` 为目标节点，运行 `pio run -e esp32s3mini`，选择输出的
`.pio/build/esp32s3mini/firmware.bin`。点击更新并确认文件名/节点，等待“新固件已启动确认”。
选择的是应用镜像，不能选择 bootloader、partitions 或 merged 全闪存镜像。
每次构建嵌入唯一 build 标识和节点/板型标记；服务端拒绝错节点、错板型、超分区的文件。
请保留旧的可用应用镜像，需要退回时按相同流程重新刷入。

每个节点同一时刻只接受一个任务。刷新页面或关闭脚本不会中断 Pi 已接受的任务。
“传输 100%”仅代表数据已传完；随后依次显示“等待启动”“新固件试运行”“已确认”。
新 boot id、目标 build、已验证状态及匹配的持久化成功记录同时满足才算成功。
Pi 服务重启会丢弃内存中的任务、日志和固件；ESP32 在传输空闲 30 秒后中止未提交更新。
如果 Pi 在试运行阶段重启，不再为原任务发确认，候选固件会超时回滚；重连后仍可在
`device.update_result` 和网页失败横幅中看到 NVS 保留的最终结果。
超时后先查看节点当前 build 和日志，再决定是否重新上传。

## 启动失败自动回滚与失败反馈

1. `Update.end()` 选择备用槽之前，将 session、候选 build 和槽名作为一个 NVS 原子记录保存。
   若记录无法保存则拒绝提交。bootloader 把新槽标为 `PENDING_VERIFY`，只允许一次试启动。
2. 固件覆盖 Arduino 的 `verifyRollbackLater()`，取消其默认的提前确认。在 `setup()`
   **之前**启动独立的 120 秒定时器；初始化卡死、网络任务挂起也不能阻止该定时器到期重启。
   崩溃/看门狗/断电导致确认前重启时，bootloader 同样自动放弃候选槽，启动旧槽。
3. 新程序至少运行 30 秒、主循环完成 100 轮且最近 2 秒仍有心跳后才允许确认。
   Pi 通过节点维护密钥验证回报，并向**新 boot id**发签名 `confirm`；设备再次复查健康后
   才调用 `esp_ota_mark_app_valid_cancel_rollback()`，停止试运行定时器并保存成功结果。
   不以传感器是否插入为通过条件，缺少传感器本就是允许的正常配置。
4. 启动失败回到旧槽后，旧固件读 NVS 中未完成的事务，保存 `rolled_back` 结果。
   已知原因包括 `setup_incomplete`、`main_loop_stalled`、`confirmation_timeout`；如果
   候选固件在来得及写原因之前崩溃，则如实报告 `boot_failed_or_interrupted`。
   提交过程中断电但仍留在旧槽，也归此类，不假称获得了具体崩溃原因。

Pi 等待最终结果最多 210 秒（包含设备 120 秒试运行及旧固件重连预算），没有收到结果时
返回 `outcome_unknown`，**不能将网络离线等同于回滚成功**。晚到的匹配签名结果会更新任务。
网页保留红色失败横幅，不会被下一轮心跳刷新清除；上传校验错误也会保持显示直到再次上传。
脚本失败返回非零退出码，输出 `error_code` 和设备原因。回滚后当前 build 仍显示实际旧固件。

## 仓库脚本（仅 Python 标准库）

```sh
# 管理密钥可交互输入（隐藏输入），或放入 DEWY_WATER_KEY 环境变量。
python scripts/esp32_maintenance.py --url https://dewy.example.com --node aqua
python scripts/esp32_maintenance.py --url https://dewy.example.com --node aqua --follow
python scripts/esp32_maintenance.py --url https://dewy.example.com --node aqua --firmware .pio/build/esp32s3mini/firmware.bin
```

脚本拒绝重定向以防转发密钥，不把密钥放命令行参数或 URL 中。默认只允许 HTTPS。
脚本直接访问 Worker，使用的是 water key，不是节点的 maintenance_key。

## 保障与边界

- 每条维护命令和状态回报均采用独立节点密钥 HMAC-SHA256 签名；命令绑定随机 boot id、
  session、数据偏移。固件分块传输、逐块确认、重传幂等，并以 MD5 做整镜像传输校验。
  镜像的 SHA-256 显示在任务/脚本中供核对。密钥编译在固件内，不替代 Secure Boot。
- 固件写入备用 OTA 槽，写入失败/中断时不切换启动槽。最终完整性校验通过才提交并重启。
  启动试运行失败自动回滚依赖首次 USB 安装的回滚 bootloader 与可用旧槽。
  保护只覆盖启动验证窗口，验证成功后出现的业务缺陷不会自动撤销已确认固件。
  回滚恢复应用槽，不撤销 NVS 配置/喂食记录；跨版本持久化格式必须保持兼容。
  两个应用槽损坏、硬件故障或 bootloader 被覆盖仍可能需要 USB 恢复。
- 使用现有 MQTT Broker 和信任边界。HMAC 防篡改，不加密串口输出；Broker 应仅在可信内网
  开放，并按节点限制 topic ACL，敏感信息不要输出到日志。维护密钥变更要同步 Pi 和固件，
  密钥不一致会无法远程维护，不要先单独改 Pi。
- 应用中的串口输出经 `RemoteSerial` 同时输出到 USB 串口和有界队列。当前已有的
  sensors/LED/network 输出均已接入。新增应用日志使用 `RemoteSerial.print/println/printf`。
  ROM、SDK 自身输出、panic 回溯不在此镜像范围；没有远程执行串口命令的入口。
- ESP32 缓冲 24 行，每行至多 192 字节，每秒最多发布 10 行；队列满时丢弃新行，状态含
  `dropped_logs`。Pi/网页各保留最近 300 行，服务重启后清空，不持久化到 SD 卡。
  换行/定长分段的 UTF-8 字符若在字节边界截断，可能显示替代字符。

API（均经 Worker 的 water key 和 Pi 的 BFF token 校验）：

- `GET /api/maintenance/<node>?after=<cursor>`：心跳、任务状态和增量日志。
- `POST /api/maintenance/<node>/firmware`：`application/octet-stream` 原始应用镜像，
  最多 4 MiB；返回 202 和任务标识。HTTP 接受上传不等于设备升级成功。

OTA 槽与提交机制参考 [Espressif OTA 文档](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/ota.html)。
Arduino 提前确认与延迟验证 hook 见
[Arduino 2.0.17 初始化源码](https://github.com/espressif/arduino-esp32/blob/2.0.17/cores/esp32/esp32-hal-misc.c)。

## 验证

自动化：`python -m unittest discover -s tests -t .`、`node tests/maintenance_frontend.mjs`、
`node tests/aqua_frontend.mjs`、`pio test -e native`、`pio run -e esp32s3mini` 与
`npx wrangler deploy --dry-run`。native 测试运行固件实际使用的 `boot_health.h`，
覆盖稳定窗口、主循环停滞、初始化未完成、确认超时与单调时间回绕；MQTT 模拟覆盖双向确认、
仅启动不算成功、同 build 重刷回滚、错误会话拒绝、超时后晚到回滚结果及失败横幅。

这些检查不能替代实机闪存/断电验收。首次 USB 安装后，先在可实体恢复的测试节点验证：

1. 正常候选镜像应依次进入试运行和确认成功，重启后仍运行新 build。
2. 用临时测试镜像在 setup 入口调用 `abort()`，应回到旧 build 并报告启动失败/中断。
3. 用临时测试镜像在 setup 卡住但允许 RTOS 调度，120 秒后应由试运行定时器重启并回滚。
4. 临时测试镜像停止主循环或使用不可连接的 WiFi 配置，不能获得 Pi 确认，应自动回滚。
5. 在试运行期间重启 Pi 服务，设备应回滚；Pi 恢复后网页仍显示持久化的失败结果。

测试镜像修改只用于验收，不提交/分发为正常固件；测试结束保留一份已确认可用的基线镜像。
