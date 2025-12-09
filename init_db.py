import sqlite3

conn = sqlite3.connect('courses.db')
cursor = conn.cursor()

# courses 테이블
cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        limit_num INTEGER NOT NULL,
        enrolled INTEGER DEFAULT 0
    )
''')

# enrollments 테이블
cursor.execute('''
    CREATE TABLE IF NOT EXISTS enrollments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_id INTEGER NOT NULL,
        student_id TEXT NOT NULL,
        student_name TEXT NOT NULL,
        enrolled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (course_id) REFERENCES courses (id)
    )
''')

# settings 테이블 (신청 시간 설정)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        enroll_start DATETIME,
        enroll_end DATETIME
    )
''')

# 기본 설정 삽입 (없으면)
cursor.execute('SELECT COUNT(*) FROM settings')
if cursor.fetchone()[0] == 0:
    cursor.execute('INSERT INTO settings (id, enroll_start, enroll_end) VALUES (1, NULL, NULL)')

conn.commit()
conn.close()

print('✅ 데이터베이스 업데이트 완료!')
