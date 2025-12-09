from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import sqlite3
from datetime import datetime

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = 'your-secret-key-12345'

ADMIN_PASSWORD = '1234'

# ============ DB 연결 함수 ============
def get_db():
    conn = sqlite3.connect('courses.db')
    conn.row_factory = sqlite3.Row
    return conn

# ============ 신청 가능 시간 확인 함수 ============
def check_enroll_time():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT enroll_start, enroll_end FROM settings WHERE id = 1')
    settings = cursor.fetchone()
    conn.close()
    
    if not settings or not settings['enroll_start'] or not settings['enroll_end']:
        return {"allowed": False, "message": "신청 시간이 설정되지 않았습니다.", "start": None, "end": None}
    
    now = datetime.now()
    start = datetime.strptime(settings['enroll_start'], '%Y-%m-%dT%H:%M')
    end = datetime.strptime(settings['enroll_end'], '%Y-%m-%dT%H:%M')
    
    if now < start:
        return {
            "allowed": False, 
            "message": f"신청 시작 전입니다.",
            "start": settings['enroll_start'],
            "end": settings['enroll_end']
        }
    elif now > end:
        return {
            "allowed": False, 
            "message": "신청이 마감되었습니다.",
            "start": settings['enroll_start'],
            "end": settings['enroll_end']
        }
    else:
        return {
            "allowed": True, 
            "message": "신청 가능",
            "start": settings['enroll_start'],
            "end": settings['enroll_end']
        }

# ============ API: 신청 시간 정보 ============
@app.route('/api/enroll-time', methods=['GET'])
def get_enroll_time():
    return jsonify(check_enroll_time())

# ============ API 1: 강좌 목록 조회 ============
@app.route('/api/courses', methods=['GET'])
def get_courses():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT id, name, limit_num as "limit", enrolled FROM courses')
    courses = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(courses)

# ============ API 2: 수강신청 ============
@app.route('/api/enroll', methods=['POST'])
def enroll():
    # 시간 확인
    time_check = check_enroll_time()
    if not time_check['allowed']:
        return jsonify({"success": False, "message": time_check['message']})
    
    data = request.get_json()
    course_id = data.get('course_id')
    student_id = data.get('student_id')
    student_name = data.get('student_name')
    
    if not student_id or not student_name:
        return jsonify({"success": False, "message": "학번과 이름을 입력하세요."})
    
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
        
        cursor.execute(
            'SELECT * FROM enrollments WHERE course_id = ? AND student_id = ?',
            (course_id, student_id)
        )
        if cursor.fetchone():
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "이미 신청한 강좌입니다."})
        
        if course['enrolled'] >= course['limit_num']:
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "마감되었습니다."})
        
        cursor.execute(
            'INSERT INTO enrollments (course_id, student_id, student_name) VALUES (?, ?, ?)',
            (course_id, student_id, student_name)
        )
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
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "message": "오류가 발생했습니다."})

# ============ API: 내 신청 목록 조회 ============
@app.route('/api/my-enrollments', methods=['POST'])
def my_enrollments():
    data = request.get_json()
    student_id = data.get('student_id')
    
    if not student_id:
        return jsonify([])
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT e.id, e.course_id, c.name as course_name, e.enrolled_at
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        WHERE e.student_id = ?
        ORDER BY e.enrolled_at DESC
    ''', (student_id,))
    enrollments = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return jsonify(enrollments)

# ============ API: 신청 취소 ============
@app.route('/api/cancel', methods=['POST'])
def cancel_enrollment():
    # 시간 확인
    time_check = check_enroll_time()
    if not time_check['allowed']:
        return jsonify({"success": False, "message": time_check['message']})
    
    data = request.get_json()
    enrollment_id = data.get('enrollment_id')
    student_id = data.get('student_id')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('BEGIN IMMEDIATE')
        
        cursor.execute(
            'SELECT * FROM enrollments WHERE id = ? AND student_id = ?',
            (enrollment_id, student_id)
        )
        enrollment = cursor.fetchone()
        
        if not enrollment:
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "신청 내역을 찾을 수 없습니다."})
        
        course_id = enrollment['course_id']
        
        cursor.execute('DELETE FROM enrollments WHERE id = ?', (enrollment_id,))
        cursor.execute(
            'UPDATE courses SET enrolled = enrolled - 1 WHERE id = ?',
            (course_id,)
        )
        
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "신청이 취소되었습니다."})
        
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
    cursor.execute('DELETE FROM enrollments WHERE course_id = ?', (course_id,))
    cursor.execute('DELETE FROM courses WHERE id = ?', (course_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "강좌 삭제 완료!"})

# ============ API: 신청 인원 초기화 ============
@app.route('/api/admin/course/<int:course_id>/reset', methods=['POST'])
def reset_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM enrollments WHERE course_id = ?', (course_id,))
    cursor.execute('UPDATE courses SET enrolled = 0 WHERE id = ?', (course_id,))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "신청 인원 초기화 완료!"})

# ============ API: 강좌별 신청자 목록 ============
@app.route('/api/admin/course/<int:course_id>/enrollments', methods=['GET'])
def get_enrollments(course_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT student_id, student_name, enrolled_at 
        FROM enrollments 
        WHERE course_id = ? 
        ORDER BY enrolled_at
    ''', (course_id,))
    enrollments = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(enrollments)

# ============ API: 신청 시간 설정 ============
@app.route('/api/admin/settings/time', methods=['POST'])
def set_enroll_time():
    data = request.get_json()
    start = data.get('start')
    end = data.get('end')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE settings SET enroll_start = ?, enroll_end = ? WHERE id = 1',
        (start, end)
    )
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "신청 시간이 설정되었습니다."})

# ============ API: 신청 시간 조회 (관리자용) ============
@app.route('/api/admin/settings/time', methods=['GET'])
def get_admin_enroll_time():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT enroll_start, enroll_end FROM settings WHERE id = 1')
    settings = cursor.fetchone()
    conn.close()
    
    return jsonify({
        "start": settings['enroll_start'] if settings else None,
        "end": settings['enroll_end'] if settings else None
    })

if __name__ == '__main__':
    app.run(debug=True)
