from flask import Flask, jsonify, request, render_template
import sqlite3

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# ============ DB 연결 함수 ============
def get_db():
    conn = sqlite3.connect('courses.db')
    conn.row_factory = sqlite3.Row
    return conn

# ============ API 1: 강좌 목록 조회 ============
@app.route('/api/courses', methods=['GET'])
def get_courses():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, limit_num as "limit", enrolled FROM courses')
    courses = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(courses)

# ============ API 2: 수강신청 (동시접속 안전) ============
@app.route('/api/enroll', methods=['POST'])
def enroll():
    data = request.get_json()
    course_id = data.get('course_id')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('BEGIN IMMEDIATE')
        
        cursor.execute('SELECT * FROM courses WHERE id = ?', (course_id,))
        course = cursor.fetchone()
        
        if course is None:
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "강좌를 찾을 수 없습니다."})
        
        if course['enrolled'] < course['limit_num']:
            cursor.execute(
                'UPDATE courses SET enrolled = enrolled + 1 WHERE id = ?', 
                (course_id,)
            )
            conn.commit()
            conn.close()
            return jsonify({
                "success": True,
                "message": f"{course['name']} 신청 완료!"
            })
        else:
            conn.rollback()
            conn.close()
            return jsonify({
                "success": False,
                "message": "마감되었습니다."
            })
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "message": "오류가 발생했습니다."})

# ============ 메인 페이지 ============
@app.route('/')
def home():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)
