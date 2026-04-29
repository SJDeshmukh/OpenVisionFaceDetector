from db_factory import get_db_connection
conn = get_db_connection()
c = conn.cursor()
c.execute("SELECT COUNT(*) FROM lecture_attendance")
print('Total lecture_attendance:', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM attendance")
print('Total attendance:', c.fetchone()[0])
