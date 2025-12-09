from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import sqlite3

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = 'your-secret-key-12345'

# ============ 관리자 비밀번호 설정 ============
ADMIN_PASSWORD = '1234'

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

# ============ API 2: 수강신청 (학생 정보 저장) ============
@app.route('/api/enroll', methods=['POST'])
def enroll():
    data = request.get_json()
    course_id = data.get('course_id')
    student_id = data.get('student_id')
    student_name = data.get('student_name')
    
    # 입력 확인
    if not student_id or not student_name:
        return jsonify({"success": False, "message": "학번과 이름을 입력하세요."})
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('BEGIN IMMEDIATE')
        
        # 강좌 정보 조회
        cursor.execute('SELECT * FROM courses WHERE id = ?', (course_id,))
        course = cursor.fetchone()
        
        if course is None:
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "강좌를 찾을 수 없습니다."})
        
        # 중복 신청 확인
        cursor.execute(
            'SELECT * FROM enrollments WHERE course_id = ? AND student_id = ?',
            (course_id, student_id)
        )
        if cursor.fetchone():
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "이미 신청한 강좌입니다."})
        
        # 자리 확인
        if course['enrolled'] >= course['limit_num']:
            conn.rollback()
            conn.close()
            return jsonify({"success": False, "message": "마감되었습니다."})
        
        # 신청 처리
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
    # 신청 내역도 함께 삭제
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
    # 신청 내역도 함께 삭제
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
    data = request.get_json()
    enrollment_id = data.get('enrollment_id')
    student_id = data.get('student_id')
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('BEGIN IMMEDIATE')
        
        # 신청 내역 확인 (본인 것인지)
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
        
        # 신청 삭제
        cursor.execute('DELETE FROM enrollments WHERE id = ?', (enrollment_id,))
        
        # 강좌 인원 감소
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


if __name__ == '__main__':
    app.run(debug=True)
