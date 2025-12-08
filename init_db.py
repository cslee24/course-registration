import sqlite3

# 데이터베이스 연결 (파일 생성)
conn = sqlite3.connect('courses.db')
cursor = conn.cursor()

# 테이블 생성
cursor.execute('''
    CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        limit_num INTEGER NOT NULL,
        enrolled INTEGER DEFAULT 0
    )
''')

# 기존 데이터 삭제 (초기화)
cursor.execute('DELETE FROM courses')

# 초기 데이터 삽입
courses = [
    (1, '파이썬 기초', 20, 15),
    (2, '웹개발 입문', 20, 20),
    (3, '데이터분석 기초', 15, 8),
]

cursor.executemany('''
    INSERT INTO courses (id, name, limit_num, enrolled) 
    VALUES (?, ?, ?, ?)
''', courses)

conn.commit()
conn.close()

print('✅ 데이터베이스 초기화 완료! (courses.db 생성됨)')
