import sqlite3, pprint

conn = sqlite3.connect('attendance.db')
c = conn.cursor()
print('Tables:')
for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'"):
    print(' ', row[0])

print('\nSchema students:')
for row in c.execute("PRAGMA table_info(students)"):
    print(' ', row)

print('\nFirst 10 students:')
for row in c.execute('SELECT * FROM students LIMIT 10'):
    pprint.pprint(row)

conn.close()
