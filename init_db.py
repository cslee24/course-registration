import sqlite3

conn = sqlite3.connect('courses.db')
cursor = conn.cursor()

# 기존 courses 테이블
cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        limit_num INTEGER NOT NULL,
        enrolled INTEGER DEFAULT 0
    )
''')

# 새로운 enrollments 테이블 (신청 내역)
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

# 기존 데이터 확인 (courses가 비어있으면 초기 데이터 삽입)
cursor.execute('SELECT COUNT(*) FROM courses')
if cursor.fetchone()[0] == 0:
    courses = [
        (1, '파이썬 기초', 20, 0),
        (2, '웹개발 입문', 20, 0),
        (3, '데이터분석 기초', 15, 0),
    ]
    cursor.executemany('''
        INSERT INTO courses (id, name, limit_num, enrolled) 
        VALUES (?, ?, ?, ?)
    ''', courses)

conn.commit()
conn.close()

print('✅ 데이터베이스 업데이트 완료!')
