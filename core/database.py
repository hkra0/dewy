"""数据访问层（DAL）。

对外只暴露 get_conn() 与下面的 query_* / insert_* 函数，
业务代码（core/logic.py、api/routers.py）不应再直接 import sqlite3。

并发约定：所有连接都在 state.db_lock 保护下创建与关闭，
单个 with get_conn() 块即一个事务——正常退出自动 commit，
抛异常自动 rollback，任何路径下都保证 close（含提前 return）。
"""

import logging
import os
import sqlite3
from contextlib import contextmanager

import core.state as state

logger = logging.getLogger(__name__)

# node_data 的保留窗口。采样每 10 分钟一轮、每节点每天约 144 行，
# 不清理的话表会无限增长，而全表扫描的日均查询会随之逐年变慢。
# 应用本身最远只读 30 天（/api/history 的 daily 视图），365 天是留给
# 将来做长期分析的余量。设为 0 表示不清理。
_RETENTION_DEFAULT_DAYS = 365
try:
    NODE_DATA_RETENTION_DAYS = int(os.environ.get("DEWY_DATA_RETENTION_DAYS", _RETENTION_DEFAULT_DAYS))
except ValueError:
    logger.error("DEWY_DATA_RETENTION_DAYS=%r 非法，退回默认 %d 天",
                 os.environ.get("DEWY_DATA_RETENTION_DAYS"), _RETENTION_DEFAULT_DAYS)
    NODE_DATA_RETENTION_DAYS = _RETENTION_DEFAULT_DAYS

PRUNE_BATCH_SIZE = 500  # 每批删除的行数，避免长时间独占 db_lock


@contextmanager
def get_conn():
    """获取一个受锁保护、自动提交/回滚/关闭的连接。

    用法：
        with get_conn() as conn:
            conn.execute("INSERT ...", params)
    """
    with state.db_lock:
        conn = sqlite3.connect(state.DB_FILE)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def query(sql, params=()):
    """只读查询，返回全部行。"""
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def execute(sql, params=()):
    """单条写入，返回受影响行数。"""
    with get_conn() as conn:
        return conn.execute(sql, params).rowcount


# ==================== 建表 ====================

def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute('''
            CREATE TABLE IF NOT EXISTS node_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                node_id TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                soil_moisture REAL,
                pressure REAL,
                voltage REAL,
                current REAL,
                is_anomaly INTEGER DEFAULT 0
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS watering_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                node_id TEXT DEFAULT 'main',
                duration REAL,
                soil_before REAL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_node_data_query ON node_data (node_id, is_anomaly, timestamp)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_watering_log_node ON watering_log (node_id, timestamp)')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS photo_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                date TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                file_size INTEGER,
                thumb_size INTEGER
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_photo_log_date ON photo_log (date)')


# ==================== node_data（传感器归档） ====================

def insert_node_data(records):
    """批量写入一轮采样。records 为 dict 列表，需含 node_id。"""
    if not records:
        return
    with get_conn() as conn:
        conn.executemany('''
            INSERT INTO node_data (node_id, temperature, humidity, soil_moisture, pressure, voltage, current)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', [
            (d.get("node_id"),
             d.get("temperature"), d.get("humidity"), d.get("soil_moisture"),
             d.get("pressure"), d.get("voltage"), d.get("current"))
            for d in records
        ])


def query_recent_soil(node_id, limit=5):
    """取最近 N 条土壤读数，用于离群值判定。返回 [(id, soil_moisture), ...] 倒序。"""
    return query(
        "SELECT id, soil_moisture FROM node_data WHERE node_id=? ORDER BY id DESC LIMIT ?",
        (node_id, limit),
    )


def prune_node_data(retention_days=None):
    """删除超出保留窗口的采样行，返回删除条数。

    只清 node_data——浇水与照片记录是稀疏的人类可读事件，全部保留。
    分批删除：单条 DELETE 删掉几十万行会长时间持有 db_lock，
    把 /api/monitor 一起卡住。

    不执行 VACUUM：SQLite 会复用释放的页，文件不缩小但也不再增长，
    而 VACUUM 需要重写整库，在 SD 卡上代价过高。
    """
    days = NODE_DATA_RETENTION_DAYS if retention_days is None else retention_days
    if days <= 0:
        return 0

    cutoff = f"-{int(days)} days"

    # 每批都带上 timestamp 条件，删除范围只由它决定。
    # ORDER BY id 是为了让 SQLite 顺着主键扫、凑够一批就停：正常情况下
    # 过期行都在 id 低位，扫几百行即可，不会每批全表扫。
    # 不要改成先取 MAX(id) 再按 id 区间删——那要求 id 与 timestamp 同向
    # 递增，而 scripts/migrate_db.py 会写入带历史时间戳的行，一旦顺序
    # 不成立就会连未过期的数据一起删掉。
    total = 0
    while True:
        deleted = execute('''
            DELETE FROM node_data WHERE id IN (
                SELECT id FROM node_data WHERE timestamp < datetime('now', ?)
                ORDER BY id LIMIT ?
            )
        ''', (cutoff, PRUNE_BATCH_SIZE))
        total += deleted
        if deleted < PRUNE_BATCH_SIZE:
            break
    return total


def mark_anomalies(row_ids):
    """把指定行标记为离群值，后续统计与图表会跳过。"""
    if not row_ids:
        return
    placeholders = ','.join('?' * len(row_ids))
    execute(f"UPDATE node_data SET is_anomaly = 1 WHERE id IN ({placeholders})", tuple(row_ids))


# ==================== watering_log（浇水） ====================

def query_last_watering_time(node_id):
    """最近一次浇水的 UTC 时间字符串；从未浇过返回 None。"""
    rows = query(
        "SELECT timestamp FROM watering_log WHERE node_id=? ORDER BY id DESC LIMIT 1",
        (node_id,),
    )
    return rows[0][0] if rows else None


def insert_watering(node_id, duration, soil_before):
    execute(
        "INSERT INTO watering_log (node_id, duration, soil_before) VALUES (?, ?, ?)",
        (node_id, duration, soil_before),
    )


# ==================== photo_log（每日照片） ====================

def photo_exists(date_str):
    return bool(query("SELECT id FROM photo_log WHERE date = ?", (date_str,)))


def insert_photo(date_str, filename, file_size, thumb_size):
    """写入照片记录。并发重复插入时静默忽略（date 有 UNIQUE 约束）。"""
    try:
        execute(
            "INSERT INTO photo_log (date, filename, file_size, thumb_size) VALUES (?, ?, ?, ?)",
            (date_str, filename, file_size, thumb_size),
        )
    except sqlite3.IntegrityError:
        pass


def query_photos_desc():
    """照片列表，供 /api/photos 使用。"""
    return query("SELECT date, file_size, thumb_size, timestamp FROM photo_log ORDER BY date DESC")


def query_photos_asc():
    """按日期正序的 (date, filename)，供稀疏化清理遍历。"""
    return query("SELECT date, filename FROM photo_log ORDER BY date ASC")


def delete_photos(date_strs):
    """批量删除照片记录（文件本身由调用方删除）。"""
    if not date_strs:
        return
    placeholders = ','.join('?' * len(date_strs))
    execute(f"DELETE FROM photo_log WHERE date IN ({placeholders})", tuple(date_strs))


# ==================== 历史数据（/api/history） ====================

def query_watering_history(node_id, limit=30):
    return query('''
        SELECT datetime(timestamp, 'localtime'), duration, soil_before
        FROM watering_log
        WHERE node_id=?
        ORDER BY timestamp DESC LIMIT ?
    ''', (node_id, limit))


def query_daily_history(node_id, limit=30):
    """返回 (逐日环境均值, 逐日浇水时长合计)。

    两条查询都先按 timestamp 收窄再分组。分组键是 date(timestamp,'localtime')
    这个表达式，索引帮不上分组的忙——没有 WHERE 上的时间条件时，
    LIMIT 只作用于分组之后，等于每次都全表扫描，且随数据积累逐年变慢。

    窗口比 limit 多取一天：最旧的那天多半只有半天数据，
    ORDER BY ... DESC LIMIT 会把它挡在结果之外。
    """
    window = f"-{int(limit) + 1} days"
    rows = query('''
        SELECT date(timestamp, 'localtime') as day, AVG(temperature), AVG(humidity), AVG(soil_moisture), AVG(pressure)
        FROM node_data
        WHERE node_id=? AND (is_anomaly = 0 OR is_anomaly IS NULL)
          AND timestamp >= datetime('now', ?)
        GROUP BY day ORDER BY day DESC LIMIT ?
    ''', (node_id, window, limit))
    water_rows = query('''
        SELECT date(timestamp, 'localtime') as day, SUM(duration)
        FROM watering_log
        WHERE node_id=? AND timestamp >= datetime('now', ?)
        GROUP BY day
    ''', (node_id, window))
    return rows, water_rows


def query_24h_history(node_id):
    """返回 (24 小时内环境采样, 24 小时内浇水记录)。"""
    sensor_rows = query('''
        SELECT strftime('%H:%M', timestamp, 'localtime'), temperature, humidity, soil_moisture, pressure, strftime('%s', timestamp)
        FROM node_data
        WHERE node_id=? AND (is_anomaly = 0 OR is_anomaly IS NULL)
          AND timestamp >= datetime('now', '-24 hours')
        ORDER BY timestamp ASC
    ''', (node_id,))
    water_rows = query('''
        SELECT strftime('%H:%M', timestamp, 'localtime'), duration, soil_before, strftime('%s', timestamp)
        FROM watering_log
        WHERE node_id=? AND timestamp >= datetime('now', '-24 hours')
        ORDER BY timestamp ASC
    ''', (node_id,))
    return sensor_rows, water_rows
