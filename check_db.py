import sqlite3

conn = sqlite3.connect('attendance.db')
c = conn.cursor()

# ตรวจสอบตาราง
c.execute('SELECT name FROM sqlite_master WHERE type="table" AND name="attendance"')
result = c.fetchone()
print('Table attendance exists:', result is not None)

if result:
    c.execute('SELECT COUNT(*) FROM attendance')
    count = c.fetchone()[0]
    print('Current records in attendance:', count)
    
    # แสดง 5 รายการล่าสุด
    c.execute('SELECT * FROM attendance ORDER BY id DESC LIMIT 5')
    rows = c.fetchall()
    print('Last 5 records:')
    for row in rows:
        print(row)

conn.close()