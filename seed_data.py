"""Create demo users and load bug_reports_FINAL_v7.csv into MySQL.

Usage:  python seed_data.py
Run `mysql -u root -p < schema.sql` first.
"""
import pandas as pd
import mysql.connector
from werkzeug.security import generate_password_hash
from config import DB_CONFIG

DEMO_USERS = [
    ("admin", "admin123", "System Admin", "admin@example.com", "admin"),
    ("manager1", "manager123", "Project Manager", "manager@example.com", "manager"),
    ("dev_alice", "dev123", "Alice", "alice@example.com", "developer"),
    ("dev_bob", "dev123", "Bob", "bob@example.com", "developer"),
    ("dev_charlie", "dev123", "Charlie", "charlie@example.com", "developer"),
    ("dev_diana", "dev123", "Diana", "diana@example.com", "developer"),
    ("dev_evan", "dev123", "Evan", "evan@example.com", "developer"),
    ("qa_sarah", "qa123", "Sarah", "sarah@example.com", "tester"),
    ("qa_john", "qa123", "John", "john@example.com", "tester"),
    ("qa_mike", "qa123", "Mike", "mike@example.com", "tester"),
    ("qa_shivani", "qa123", "Shivani", "shivani@example.com", "tester"),
]

def parse_date(series):
    """The CSV mixes DD-MM-YY and ISO (YYYY-MM-DD) dates; parse each form explicitly."""
    s = series.astype("string")
    iso = pd.to_datetime(s.where(s.str.match(r"^\d{4}-\d{2}-\d{2}$", na=False)), format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(s.where(s.str.match(r"^\d{2}-\d{2}-\d{2}$", na=False)), format="%d-%m-%y", errors="coerce")
    return iso.fillna(dmy)

def nn(v):
    return None if pd.isna(v) else v

def main():
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor()
    for u, pw, name, email, role in DEMO_USERS:
        cur.execute(
            "INSERT IGNORE INTO users (username,password,full_name,email,role) VALUES (%s,%s,%s,%s,%s)",
            (u, generate_password_hash(pw), name, email, role),
        )
    df = pd.read_csv("bug_reports_FINAL_v7.csv")
    for c in ("created_date", "closed_date"):
        df[c] = parse_date(df[c]).dt.date
    for _, r in df.iterrows():
        cur.execute(
            """INSERT IGNORE INTO bugs (bug_id,title,description,severity,priority,component,
               assigned_to,reporter,reported_by,created_date,closed_date,status,resolution_time,reopen_count)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(nn(r[c]) for c in ["bug_id","title","description","severity","priority","component",
                  "assigned_to","reporter","reported_by","created_date","closed_date","status",
                  "resolution_time","reopen_count"]),
        )
    conn.commit()
    print(f"Seeded {len(DEMO_USERS)} users and {len(df)} bugs.")
    conn.close()

if __name__ == "__main__":
    main()
