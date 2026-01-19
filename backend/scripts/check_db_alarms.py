
import sqlite3
import pandas as pd
from datetime import datetime

# Connect to DB
conn = sqlite3.connect('/home/dlckdgn/personal-portfolio/backend/storage/db/portfolio.db')

# Time range: 2026-01-16 18:30 to 18:50
start_time = "2026-01-16 18:30:00"
end_time = "2026-01-16 18:50:00"

print(f"--- Incoming Alarms ({start_time} ~ {end_time}) ---")
query_incoming = f"""
SELECT id, received_at, app_name, sender, raw_text, status, classification 
FROM incoming_alarms 
WHERE received_at BETWEEN '{start_time}' AND '{end_time}'
ORDER BY received_at ASC
"""
try:
    df_incoming = pd.read_sql_query(query_incoming, conn)
    if not df_incoming.empty:
        print(df_incoming.to_string())
    else:
        print("No incoming alarms found.")
except Exception as e:
    print(f"Error querying incoming_alarms: {e}")

print("\n--- Spam Alarms ({start_time} ~ {end_time}) ---")
query_spam = f"""
SELECT id, created_at, app_name, sender, raw_text, classification, discard_reason 
FROM spam_alarms 
WHERE created_at BETWEEN '{start_time}' AND '{end_time}'
ORDER BY created_at ASC
"""
try:
    df_spam = pd.read_sql_query(query_spam, conn)
    if not df_spam.empty:
        print(df_spam.to_string())
    else:
        print("No spam alarms found.")
except Exception as e:
    print(f"Error querying spam_alarms: {e}")

conn.close()
