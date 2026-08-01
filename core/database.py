"""数据访问层（DAL）。

对外只暴露 get_conn() 与下面的 query_* / insert_* 函数，
业务代码（core/logic.py、api/routers.py）不应再直接 import sqlite3。

并发约定：所有连接都在 state.db_lock 保护下创建与关闭，
单个 with get_conn() 块即一个事务——正常退出自动 commit，
抛异常自动 rollback，任何路径下都保证 close（含提前 return）。
"""

import sqlite3
from contextlib import contextmanager

import core.state as state


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
    """返回 (逐日环境均值, 逐日浇水时长合计)。"""
    rows = query('''
        SELECT date(timestamp, 'localtime') as day, AVG(temperature), AVG(humidity), AVG(soil_moisture), AVG(pressure)
        FROM node_data
        WHERE node_id=? AND (is_anomaly = 0 OR is_anomaly IS NULL)
        GROUP BY day ORDER BY day DESC LIMIT ?
    ''', (node_id, limit))
    water_rows = query('''
        SELECT date(timestamp, 'localtime') as day, SUM(duration)
        FROM watering_log
        WHERE node_id=?
        GROUP BY day
    ''', (node_id,))
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
