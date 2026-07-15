import sqlite3
import os
import sys

def migrate_database(db_path):
    if not os.path.exists(db_path):
        print(f"Error: Database file '{db_path}' not found.")
        sys.exit(1)

    print(f"Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create new unified node_data table
    print("Creating new table 'node_data'...")
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
    
    # Check if node_id exists in watering_log, if not, add it
    cursor.execute("PRAGMA table_info(watering_log)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'node_id' not in columns:
        print("Adding 'node_id' column to 'watering_log'...")
        cursor.execute("ALTER TABLE watering_log ADD COLUMN node_id TEXT DEFAULT 'main'")

    # Migrate env_log to node_data as node 'main'
    print("Migrating 'env_log' -> 'node_data' (node_id = 'main')...")
    try:
        cursor.execute('''
            INSERT INTO node_data (timestamp, node_id, temperature, humidity, soil_moisture, voltage, current, is_anomaly)
            SELECT timestamp, 'main', temperature, humidity, soil_moisture, voltage, current, is_anomaly FROM env_log
        ''')
        main_count = cursor.rowcount
        print(f"  Inserted {main_count} rows for node 'main'.")
    except sqlite3.OperationalError as e:
        print(f"  Skipping env_log migration: {e}")

    # Migrate esp32_env_log to node_data as node 'sub1'
    print("Migrating 'esp32_env_log' -> 'node_data' (node_id = 'sub1')...")
    try:
        cursor.execute('''
            INSERT INTO node_data (timestamp, node_id, temperature, humidity, pressure)
            SELECT timestamp, 'sub1', temperature, humidity, pressure FROM esp32_env_log
        ''')
        sub1_count = cursor.rowcount
        print(f"  Inserted {sub1_count} rows for node 'sub1'.")
    except sqlite3.OperationalError as e:
        print(f"  Skipping esp32_env_log migration: {e}")

    # Optional: Rename old tables to backup
    try:
        print("Renaming old tables to backup (_backup suffix)...")
        cursor.execute("ALTER TABLE env_log RENAME TO env_log_backup")
        cursor.execute("ALTER TABLE esp32_env_log RENAME TO esp32_env_log_backup")
    except sqlite3.OperationalError as e:
        print(f"  Note: {e}")

    conn.commit()
    conn.close()
    print("\n✅ Migration completed successfully!")
    print("The historical data is now ready for the new node-based architecture.")

if __name__ == "__main__":
    default_db = "/home/hkra/dewy/data/plant_history.db"
    
    db_file = sys.argv[1] if len(sys.argv) > 1 else default_db
    print(f"Using DB file: {db_file}")
    print("You can pass a custom DB path as an argument: python scripts/migrate_db.py <path_to_db>")
    print("-" * 50)
    
    migrate_database(db_file)
