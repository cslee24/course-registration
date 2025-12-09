from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import sqlite3

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = 'your-secret-key-12345'

# ============ 관리자 비밀번호 설정 ============
ADMIN_PASSWORD = '1234'  # 원하는 비밀번호로 변경!

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

# ============ 관리자 로그인 페이지 ============
@app.route('/admin')
def admin():
    if session.get('admin_logged_in'):
        return render_template('admin.html')
    return render_template('admin_login.html')

# ============ 관리자 로그인 처리 ============
@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    password = data.get('password')
    
    if password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "비밀번호가 틀렸습니다."})

# ============ 관리자 로그아웃 ============
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin')

# ============ API: 강좌 추가 ============
@app.route('/api/admin/course', methods=['POST'])
def add_course():
    data = request.get_json()
    name = data.get('name')
    limit = data.get('limit')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO courses (name, limit_num, enrolled) VALUES (?, ?, 0)',
        (name, limit)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": f"'{name}' 강좌 추가 완료!"})

# ============ API: 강좌 삭제 ============
@app.route('/api/admin/course/<int:course_id>', methods=['DELETE'])
def delete_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM courses WHERE id = ?', (course_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "강좌 삭제 완료!"})

# ============ API: 신청 인원 초기화 ============
@app.route('/api/admin/course/<int:course_id>/reset', methods=['POST'])
def reset_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE courses SET enrolled = 0 WHERE id = ?', (course_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "신청 인원 초기화 완료!"})

if __name__ == '__main__':
    app.run(debug=True)
