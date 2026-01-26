
import sqlite3
import os
import json

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'faces.db')

def get_schema_info():
    if not os.path.exists(DB_PATH):
        print("Database not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Get list of tables
    c.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in c.fetchall() if row[0] != 'sqlite_sequence']
    
    schema = {}
    
    for table in tables:
        print(f"--- Table: {table} ---")
        c.execute(f"PRAGMA table_info({table})")
        columns = c.fetchall()
        col_details = []
        for col in columns:
            col_details.append({
                "cid": col[0],
                "name": col[1],
                "type": col[2],
                "notnull": col[3],
                "dflt_value": col[4],
                "pk": col[5]
            })
            print(f"  {col[1]} ({col[2]}) PK:{col[5]} Default:{col[4]}")
        schema[table] = col_details
        
        # Check foreign keys
        c.execute(f"PRAGMA foreign_key_list({table})")
        fks = c.fetchall()
        if fks:
            print("  Foreign Keys:")
            for fk in fks:
                print(f"    -> {fk[2]}({fk[4]}) ON UPDATE {fk[5]} ON DELETE {fk[6]}")

    conn.close()

if __name__ == "__main__":
    get_schema_info()
