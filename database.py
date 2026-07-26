import os
import sqlite3
from pymongo import MongoClient
from datetime import datetime, timezone, timedelta

DB_FILE = os.path.join(os.path.dirname(__file__), "carelink_cgm.db")
DATABASE_URL = os.environ.get("DATABASE_URL")
MONGO_URI = os.environ.get("MONGO_URI") or os.environ.get("MONGO_CONNECTION")

IS_MONGO = bool(MONGO_URI)
IS_POSTGRES = bool(DATABASE_URL and not IS_MONGO)

mongo_client = None
mongo_db = None

def get_mongo_db():
    global mongo_client, mongo_db
    if mongo_db is None and MONGO_URI:
        mongo_client = MongoClient(MONGO_URI)
        try:
            mongo_db = mongo_client.get_default_database()
        except Exception:
            mongo_db = mongo_client["nightscout"]
        if mongo_db is None:
            mongo_db = mongo_client["nightscout"]
    return mongo_db

def init_db():
    if IS_MONGO:
        try:
            db = get_mongo_db()
            db.entries.create_index([("dateString", -1)])
            db.entries.create_index([("date", -1)])
            db.treatments.create_index([("created_at", -1)])
            print("[Database] MongoDB initialized (indexes created).")
        except Exception as e:
            print(f"[MongoDB Init Error] {e}")
    else:
        conn = get_sql_connection()
        cursor = get_sql_cursor(conn)
        if IS_POSTGRES:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS entries (
                    id SERIAL PRIMARY KEY,
                    sgv INTEGER NOT NULL,
                    direction VARCHAR(50) NOT NULL,
                    dateString VARCHAR(100) NOT NULL,
                    timestamp BIGINT NOT NULL,
                    device VARCHAR(100) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp ON entries (timestamp DESC);
            ''')
        else:
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sgv INTEGER NOT NULL,
                    direction TEXT NOT NULL,
                    dateString TEXT NOT NULL,
                    timestamp INTEGER NOT NULL,
                    device TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_timestamp ON entries (timestamp DESC);
            ''')
        conn.commit()
        conn.close()
        print(f"[Database] SQL initialized (PostgreSQL: {IS_POSTGRES}).")

def get_sql_connection():
    if IS_POSTGRES:
        import psycopg2
        return psycopg2.connect(DATABASE_URL)
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn

def get_sql_cursor(conn):
    return conn.cursor()

def save_entry(sgv, direction, date_string, timestamp, device="Medtronic CareLink"):
    if IS_MONGO:
        try:
            db = get_mongo_db()
            if db.entries.find_one({"date": timestamp}):
                return False
            doc = {
                "sgv": sgv,
                "direction": direction,
                "dateString": date_string,
                "date": timestamp,
                "device": device,
                "type": "sgv"
            }
            db.entries.insert_one(doc)
            print(f"[MongoDB Saved] BG: {sgv} mg/dL ({direction})")
            return True
        except Exception as e:
            print(f"[MongoDB Save Error] {e}")
            return False
    else:
        conn = get_sql_connection()
        cursor = get_sql_cursor(conn)
        placeholder = "%s" if IS_POSTGRES else "?"
        try:
            cursor.execute(f'SELECT id FROM entries WHERE timestamp = {placeholder}', (timestamp,))
            if cursor.fetchone():
                return False
            
            if IS_POSTGRES:
                cursor.execute('''
                    INSERT INTO entries (sgv, direction, dateString, timestamp, device)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (sgv, direction, date_string, timestamp, device))
            else:
                cursor.execute('''
                    INSERT INTO entries (sgv, direction, dateString, timestamp, device)
                    VALUES (?, ?, ?, ?, ?)
                ''', (sgv, direction, date_string, timestamp, device))
            
            conn.commit()
            print(f"[SQL Saved] BG: {sgv} mg/dL ({direction})")
            return True
        except Exception as e:
            print(f"[SQL Save Error] {e}")
            return False
        finally:
            conn.close()

def get_latest_entry():
    if IS_MONGO:
        try:
            db = get_mongo_db()
            doc = db.entries.find_one(sort=[("date", -1)])
            if doc:
                return {
                    "sgv": doc.get("sgv"),
                    "direction": doc.get("direction"),
                    "dateString": doc.get("dateString"),
                    "timestamp": doc.get("date"),
                    "device": doc.get("device")
                }
            return None
        except Exception as e:
            print(f"[MongoDB Get Latest Error] {e}")
            return None
    else:
        conn = get_sql_connection()
        cursor = get_sql_cursor(conn)
        try:
            cursor.execute('''
                SELECT sgv, direction, dateString, timestamp, device
                FROM entries
                ORDER BY timestamp DESC
                LIMIT 1
            ''')
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            print(f"[SQL Get Latest Error] {e}")
            return None
        finally:
            conn.close()

def get_nightscout_entries(limit=10):
    if IS_MONGO:
        try:
            db = get_mongo_db()
            cursor = db.entries.find().sort("date", -1).limit(limit)
            rows = list(cursor)
            results = []
            for r in rows:
                results.append({
                    "_id": str(r.get("date", "")),
                    "sgv": r.get("sgv"),
                    "date": r.get("date"),
                    "dateString": r.get("dateString"),
                    "direction": r.get("direction"),
                    "device": r.get("device"),
                    "type": "sgv"
                })
            return results
        except Exception as e:
            print(f"[MongoDB Get Nightscout Error] {e}")
            return []
    else:
        conn = get_sql_connection()
        cursor = get_sql_cursor(conn)
        placeholder = "%s" if IS_POSTGRES else "?"
        try:
            cursor.execute(f'''
                SELECT id, sgv, direction, dateString, timestamp, device
                FROM entries
                ORDER BY timestamp DESC
                LIMIT {placeholder}
            ''', (limit,))
            rows = cursor.fetchall()
            results = []
            for row in rows:
                results.append({
                    "_id": str(row['timestamp']),
                    "sgv": row['sgv'],
                    "date": row['timestamp'],
                    "dateString": row['dateString'],
                    "direction": row['direction'],
                    "device": row['device'],
                    "type": "sgv"
                })
            return results
        except Exception as e:
            print(f"[SQL Get Nightscout Error] {e}")
            return []
        finally:
            conn.close()

def get_recent_entries(limit=288):
    if IS_MONGO:
        try:
            db = get_mongo_db()
            cursor = db.entries.find().sort("date", -1).limit(limit)
            rows = list(cursor)
            results = []
            for r in rows:
                results.append({
                    "sgv": r.get("sgv"),
                    "direction": r.get("direction"),
                    "dateString": r.get("dateString"),
                    "timestamp": r.get("date"),
                    "device": r.get("device")
                })
            results.reverse()
            return results
        except Exception as e:
            print(f"[MongoDB Get Recent Error] {e}")
            return []
    else:
        conn = get_sql_connection()
        cursor = get_sql_cursor(conn)
        placeholder = "%s" if IS_POSTGRES else "?"
        try:
            cursor.execute(f'''
                SELECT sgv, direction, dateString, timestamp, device
                FROM entries
                ORDER BY timestamp DESC
                LIMIT {placeholder}
            ''', (limit,))
            rows = cursor.fetchall()
            results = [dict(r) for r in rows]
            results.reverse()
            return results
        except Exception as e:
            print(f"[SQL Get Recent Error] {e}")
            return []
        finally:
            conn.close()

def get_daily_stats(hours=24):
    entries = get_recent_entries(limit=int(hours * 12))
    if not entries:
        return {"avg": 0, "tir": 0, "high": 0, "low": 0, "gmi": 0, "count": 0}
    
    sgvs = [e['sgv'] for e in entries if 'sgv' in e and isinstance(e['sgv'], (int, float))]
    if not sgvs:
        return {"avg": 0, "tir": 0, "high": 0, "low": 0, "gmi": 0, "count": 0}

    total = len(sgvs)
    avg_sgv = sum(sgvs) / total
    in_range = sum(1 for v in sgvs if 70 <= v <= 180)
    high = sum(1 for v in sgvs if v > 180)
    low = sum(1 for v in sgvs if v < 70)
    gmi = 3.31 + (0.02392 * avg_sgv)
    
    return {
        "avg": round(avg_sgv, 1),
        "tir": round((in_range / total) * 100, 1),
        "high": round((high / total) * 100, 1),
        "low": round((low / total) * 100, 1),
        "gmi": round(gmi, 2),
        "count": total
    }
