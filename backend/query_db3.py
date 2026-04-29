from db_factory import get_db_connection
conn = get_db_connection()
c = conn.cursor()
c.execute("SELECT * FROM lecture_attendance WHERE person_id = 1119")
la = c.fetchall()
print('Lecture Attendance Count:', len(la))
c.execute("SELECT * FROM attendance WHERE person_id = 1119 LIMIT 5")
a = c.fetchall()
print('Attendance Count:', len(a))
