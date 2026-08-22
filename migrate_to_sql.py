import os
import sqlite3

import pandas as pd


def migrate_data():
    csv_file = 'students.csv'
    db_file = 'attendance.db'

    if not os.path.exists(csv_file):
        print(f"❌ ไม่พบไฟล์ {csv_file} กรุณาตรวจสอบชื่อไฟล์!")
        return

    print(f"🔄 กำลังอ่านข้อมูลจาก {csv_file}...")

    try:
        df = pd.read_csv(csv_file)
        df.columns = [str(col).strip() for col in df.columns]

        required_columns = ['student_id', 'name']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            print(f"❌ students.csv ไม่มีคอลัมน์ที่จำเป็น: {', '.join(missing_columns)}")
            return

        df = df[['student_id', 'name']].copy()
        df['student_id'] = df['student_id'].astype(str).str.strip()
        df['name'] = df['name'].astype(str).str.strip()
        df = df[(df['student_id'] != '') & (df['name'] != '')]

        conn = sqlite3.connect(db_file)
        df.to_sql('students', conn, if_exists='replace', index=False)

        cursor = conn.cursor()
        cursor.execute(
            '''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                time TEXT,
                student_id TEXT,
                name TEXT,
                status TEXT
            )
            '''
        )

        conn.commit()
        conn.close()

        print("-" * 30)
        print("✅ ย้ายข้อมูลสำเร็จ!")
        print(f"📂 ไฟล์ฐานข้อมูลที่ได้: {db_file}")
        print(f"📊 จำนวนนักเรียนที่นำเข้า: {len(df)} คน")
        print("-" * 30)

    except Exception as e:
        print(f"❌ เกิดข้อผิดพลาด: {e}")


if __name__ == '__main__':
    migrate_data()
