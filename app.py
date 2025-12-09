from flask import Flask, jsonify, request, render_template, session, redirect, url_for
import sqlite3
from datetime import datetime
import os
import pathlib
import requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests
import certifi

# SSL 인증서 경로 설정
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = 'your-secret-key-12345'


# ============ Google OAuth 설정 ============
GOOGLE_CLIENT_ID = "52508210754-0b48t9qq6m6jpudvd0j9up5ss7rp85c1.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
ALLOWED_DOMAIN = "jeongeui.sen.ms.kr"  # 학교 도메인

# 개발/배포 환경 자동 감지
if os.environ.get('RENDER'):
    REDIRECT_URI = "https://course-registration-68kh.onrender.com/callback"
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '0'
else:
    REDIRECT_URI = "http://127.0.0.1:5000/callback"
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # 개발용 HTTP 허용

# OAuth 클라이언트 설정
client_config = {
    "web": {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [REDIRECT_URI]
    }
}

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
    
     # 한국 시간으로 변환 (UTC+9)
    from datetime import timedelta
    now = datetime.now() + timedelta(hours=9)
    
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

# ============ Google 로그인 ============
@app.route('/login')
def login():
    flow = Flow.from_client_config(
        client_config,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
    )
    flow.redirect_uri = REDIRECT_URI
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='select_account'
    )
    
    session['state'] = state
    return redirect(authorization_url)

# ============ Google 로그인 콜백 ============
@app.route('/callback')
def callback():
    flow = Flow.from_client_config(
        client_config,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile'],
        state=session.get('state')
    )
    flow.redirect_uri = REDIRECT_URI
    
    authorization_response = request.url
    if request.url.startswith('http://') and os.environ.get('RENDER'):
        authorization_response = request.url.replace('http://', 'https://', 1)
    
    flow.fetch_token(authorization_response=authorization_response)
    credentials = flow.credentials
    
    # 사용자 정보 가져오기
    request_session = requests.Session()
    token_request = google.auth.transport.requests.Request(session=request_session)
    
    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        token_request,
        GOOGLE_CLIENT_ID
    )
    
    email = id_info.get('email', '')
    name = id_info.get('name', '')
    
    # 학교 도메인 확인
    if not email.endswith('@' + ALLOWED_DOMAIN):
        return render_template('login_error.html', 
            message=f"학교 계정(@{ALLOWED_DOMAIN})으로만 로그인할 수 있습니다.")
    
    # 세션에 사용자 정보 저장
    session['user'] = {
        'email': email,
        'name': name,
        'student_id': email.split('@')[0]  # 이메일 앞부분을 학번으로 사용
    }
    
    return redirect('/')

# ============ 로그아웃 ============
@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

# ============ API: 현재 로그인 정보 ============
@app.route('/api/user', methods=['GET'])
def get_user():
    user = session.get('user')
    if user:
        return jsonify({"logged_in": True, "user": user})
    return jsonify({"logged_in": False})

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
    # 로그인 확인
    user = session.get('user')
    if not user:
        return jsonify({"success": False, "message": "로그인이 필요합니다."})
    
    # 시간 확인
    time_check = check_enroll_time()
    if not time_check['allowed']:
        return jsonify({"success": False, "message": time_check['message']})
    
    data = request.get_json()
    course_id = data.get('course_id')
    student_id = user['student_id']
    student_name = user['name']
    
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
@app.route('/api/my-enrollments', methods=['GET'])
def my_enrollments():
    user = session.get('user')
    if not user:
        return jsonify([])
    
    student_id = user['student_id']
    
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
    user = session.get('user')
    if not user:
        return jsonify({"success": False, "message": "로그인이 필요합니다."})
    
    time_check = check_enroll_time()
    if not time_check['allowed']:
        return jsonify({"success": False, "message": time_check['message']})
    
    data = request.get_json()
    enrollment_id = data.get('enrollment_id')
    student_id = user['student_id']
    
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
