from db_factory import get_db_connection
conn = get_db_connection()
c = conn.cursor()
c.execute("SELECT person_id, name, timestamp, device_id FROM attendance WHERE LOWER(name) LIKE '%nisha mehta%'")
print('Attendance:', c.fetchall())
