import sqlite3
import json

conn = sqlite3.connect('faces.db')
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute("SELECT * FROM vendors")
for r in c.fetchall():
    print(r.keys())
    break
