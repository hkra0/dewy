import sqlite3
import core.state as state

def init_db():
    with state.db_lock:
        conn = sqlite3.connect(state.DB_FILE)
        conn.execute("PRAGMA journal_mode=WAL")
        cursor = conn.cursor()
        cursor.execute('''
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
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS watering_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                node_id TEXT DEFAULT 'main',
                duration REAL,
                soil_before REAL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_node_data_query ON node_data (node_id, is_anomaly, timestamp)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_watering_log_node ON watering_log (node_id, timestamp)')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photo_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                date TEXT NOT NULL UNIQUE,
                filename TEXT NOT NULL,
                file_size INTEGER,
                thumb_size INTEGER
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_photo_log_date ON photo_log (date)')
        conn.commit()
        conn.close()
