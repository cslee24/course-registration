from flask import Flask, jsonify, request, render_template, session, redirect, url_for, send_file, flash
from datetime import datetime, timedelta
import os
import requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
import google.auth.transport.requests
import certifi
from io import BytesIO
from openpyxl import Workbook

# SSL 인증서 경로 설정
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-12345')

# ============ Google OAuth 설정 ============
GOOGLE_CLIENT_ID = "52508210754-0b48t9qq6m6jpudvd0j9up5ss7rp85c1.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET = "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"
ALLOWED_DOMAIN = "jeongeui.sen.ms.kr"

if os.environ.get('RENDER'):
    REDIRECT_URI = "https://course-registration-68kh.onrender.com/callback"
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '0'
else:
    REDIRECT_URI = "http://127.0.0.1:5000/callback"
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

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
    database_url = os.environ.get('DATABASE_URL')
    
    if database_url:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        return conn
    else:
        import sqlite3
        conn = sqlite3.connect('courses.db')
        conn.row_factory = sqlite3.Row
        return conn

def is_postgres():
    return os.environ.get('DATABASE_URL') is not None

# ============ 신청 가능 시간 확인 함수 ============
def check_enroll_time():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT enroll_start, enroll_end FROM settings WHERE id = 1')
    settings = cursor.fetchone()
    conn.close()
    
    if not settings or not settings['enroll_start'] or not settings['enroll_end']:
        return {"allowed": False, "message": "신청 시간이 설정되지 않았습니다."}
    
    # 한국 시간 (UTC+9)
    now = datetime.utcnow() + timedelta(hours=9)
    
    start_str = settings['enroll_start']
    end_str = settings['enroll_end']
    
    if isinstance(start_str, str):
        start = datetime.strptime(start_str, '%Y-%m-%dT%H:%M')
        end = datetime.strptime(end_str, '%Y-%m-%dT%H:%M')
    else:
        start = start_str
        end = end_str
    
    if now < start:
        return {"allowed": False, "message": "신청 시작 전입니다."}
    elif now > end:
        return {"allowed": False, "message": "신청이 마감되었습니다."}
    else:
        return {"allowed": True, "message": "신청 가능"}

# ============ 메인 페이지 (SSR 방식 적용) ============
@app.route('/')
def home():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. 강좌 목록 가져오기
    if is_postgres():
        cursor.execute('SELECT id, name, limit_num, enrolled FROM courses ORDER BY id')
    else:
        cursor.execute('SELECT id, name, limit_num, enrolled FROM courses ORDER BY id')
    courses = [dict(row) for row in cursor.fetchall()]
    
    my_enrollments = []
    user = session.get('user')
    
    # 2. 로그인한 경우 내 신청 내역 가져오기
    if user:
        student_id = user['student_id']
        if is_postgres():
            cursor.execute('''
                SELECT e.course_id, c.name as course_name
                FROM enrollments e
                JOIN courses c ON e.course_id = c.id
                WHERE e.student_id = %s
            ''', (student_id,))
        else:
            cursor.execute('''
                SELECT e.course_id, c.name as course_name
                FROM enrollments e
                JOIN courses c ON e.course_id = c.id
                WHERE e.student_id = ?
            ''', (student_id,))
        my_enrollments = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template('index.html', user=user, courses=courses, my_enrollments=my_enrollments)

# ============ 수강신청 처리 (Form POST 방식) ============
@app.route('/enroll', methods=['POST'])
def enroll_action():
    user = session.get('user')
    if not user:
        flash("로그인이 필요합니다.")
        return redirect('/login')
    
    time_check = check_enroll_time()
    if not time_check['allowed']:
        flash(time_check['message'])
        return redirect('/')
    
    course_id = request.form.get('course_id')
    student_id = user['student_id']
    student_name = user['name']
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 트랜잭션 시작
        if is_postgres():
            cursor.execute('SELECT * FROM courses WHERE id = %s FOR UPDATE', (course_id,))
        else:
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute('SELECT * FROM courses WHERE id = ?', (course_id,))
            
        course = cursor.fetchone()
        
        if not course:
            flash("존재하지 않는 강좌입니다.")
            conn.close()
            return redirect('/')

        # 중복 신청 체크
        if is_postgres():
            cursor.execute('SELECT 1 FROM enrollments WHERE course_id = %s AND student_id = %s', (course_id, student_id))
        else:
            cursor.execute('SELECT 1 FROM enrollments WHERE course_id = ? AND student_id = ?', (course_id, student_id))
            
        if cursor.fetchone():
            flash("이미 신청한 강좌입니다.")
            conn.close()
            return redirect('/')
            
        # 정원 체크
        if course['enrolled'] >= course['limit_num']:
            flash("정원이 마감되었습니다.")
            conn.close()
            return redirect('/')
            
        # 신청 처리
        if is_postgres():
            cursor.execute('INSERT INTO enrollments (course_id, student_id, student_name) VALUES (%s, %s, %s)', (course_id, student_id, student_name))
            cursor.execute('UPDATE courses SET enrolled = enrolled + 1 WHERE id = %s', (course_id,))
        else:
            cursor.execute('INSERT INTO enrollments (course_id, student_id, student_name) VALUES (?, ?, ?)', (course_id, student_id, student_name))
            cursor.execute('UPDATE courses SET enrolled = enrolled + 1 WHERE id = ?', (course_id,))
            
        conn.commit()
        flash(f"[{course['name']}] 신청이 완료되었습니다!")
        
    except Exception as e:
        conn.rollback()
        flash("신청 중 오류가 발생했습니다.")
        print(e)
    finally:
        conn.close()
        
    return redirect('/')

# ============ 수강 취소 처리 (Form POST 방식) ============
@app.route('/cancel', methods=['POST'])
def cancel_action():
    user = session.get('user')
    if not user:
        return redirect('/login')
        
    time_check = check_enroll_time()
    if not time_check['allowed']:
        flash(time_check['message'])
        return redirect('/')
        
    course_id = request.form.get('course_id')
    student_id = user['student_id']
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # 신청 내역 확인
        if is_postgres():
            cursor.execute('SELECT id FROM enrollments WHERE course_id = %s AND student_id = %s', (course_id, student_id))
        else:
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute('SELECT id FROM enrollments WHERE course_id = ? AND student_id = ?', (course_id, student_id))
            
        enrollment = cursor.fetchone()
        
        if not enrollment:
            flash("취소할 신청 내역이 없습니다.")
        else:
            # 삭제 및 인원 감소
            if is_postgres():
                cursor.execute('DELETE FROM enrollments WHERE id = %s', (enrollment['id'],))
                cursor.execute('UPDATE courses SET enrolled = enrolled - 1 WHERE id = %s', (course_id,))
            else:
                cursor.execute('DELETE FROM enrollments WHERE id = ?', (enrollment['id'],))
                cursor.execute('UPDATE courses SET enrolled = enrolled - 1 WHERE id = ?', (course_id,))
            
            conn.commit()
            flash("신청이 취소되었습니다.")
            
    except Exception as e:
        conn.rollback()
        flash("취소 중 오류가 발생했습니다.")
        print(e)
    finally:
        conn.close()
        
    return redirect('/')

# ============ Google 로그인 관련 ============
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
    
    request_session = requests.Session()
    token_request = google.auth.transport.requests.Request(session=request_session)
    
    id_info = id_token.verify_oauth2_token(
        credentials.id_token,
        token_request,
        GOOGLE_CLIENT_ID
    )
    
    email = id_info.get('email', '')
    name = id_info.get('name', '')
    
    if not email.endswith('@' + ALLOWED_DOMAIN):
        return render_template('login_error.html', 
            message=f"학교 계정(@{ALLOWED_DOMAIN})으로만 로그인할 수 있습니다.")
    
    session['user'] = {
        'email': email,
        'name': name,
        'student_id': email.split('@')[0]
    }
    
    return redirect('/')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect('/')

# ============ Admin 및 기존 API (관리자 페이지용) ============

@app.route('/admin')
def admin():
    if session.get('admin_logged_in'):
        return render_template('admin.html')
    return render_template('admin_login.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    password = data.get('password')
    
    if password == ADMIN_PASSWORD:
        session['admin_logged_in'] = True
        return jsonify({"success": True})
    else:
        return jsonify({"success": False, "message": "비밀번호가 틀렸습니다."})

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect('/admin')

@app.route('/api/admin/course', methods=['POST'])
def add_course():
    data = request.get_json()
    name = data.get('name')
    limit = data.get('limit')
    
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute(
            'INSERT INTO courses (name, limit_num, enrolled) VALUES (%s, %s, 0)',
            (name, limit)
        )
    else:
        cursor.execute(
            'INSERT INTO courses (name, limit_num, enrolled) VALUES (?, ?, 0)',
            (name, limit)
        )
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": f"'{name}' 강좌 추가 완료!"})

@app.route('/api/admin/course/<int:course_id>', methods=['DELETE'])
def delete_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('DELETE FROM enrollments WHERE course_id = %s', (course_id,))
        cursor.execute('DELETE FROM courses WHERE id = %s', (course_id,))
    else:
        cursor.execute('DELETE FROM enrollments WHERE course_id = ?', (course_id,))
        cursor.execute('DELETE FROM courses WHERE id = ?', (course_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "강좌 삭제 완료!"})

@app.route('/api/admin/courses/delete-all', methods=['POST'])
def delete_all_courses():
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "관리자 로그인 필요"})
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute('DELETE FROM enrollments')
        cursor.execute('DELETE FROM courses')
        conn.commit()
        conn.close()
        return jsonify({"success": True, "message": "모든 강좌가 삭제되었습니다."})
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({"success": False, "message": f"오류 발생: {str(e)}"})

@app.route('/api/admin/course/<int:course_id>/reset', methods=['POST'])
def reset_course(course_id):
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('DELETE FROM enrollments WHERE course_id = %s', (course_id,))
        cursor.execute('UPDATE courses SET enrolled = 0 WHERE id = %s', (course_id,))
    else:
        cursor.execute('DELETE FROM enrollments WHERE course_id = ?', (course_id,))
        cursor.execute('UPDATE courses SET enrolled = 0 WHERE id = ?', (course_id,))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "신청 인원 초기화 완료!"})

@app.route('/api/admin/course/<int:course_id>/enrollments', methods=['GET'])
def get_enrollments(course_id):
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('''
            SELECT student_id, student_name, enrolled_at 
            FROM enrollments 
            WHERE course_id = %s 
            ORDER BY enrolled_at
        ''', (course_id,))
    else:
        cursor.execute('''
            SELECT student_id, student_name, enrolled_at 
            FROM enrollments 
            WHERE course_id = ? 
            ORDER BY enrolled_at
        ''', (course_id,))
    
    enrollments = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(enrollments)

@app.route('/api/admin/settings/time', methods=['POST'])
def set_enroll_time():
    data = request.get_json()
    start = data.get('start')
    end = data.get('end')
    
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('UPDATE settings SET enroll_start = %s, enroll_end = %s WHERE id = 1', (start, end))
    else:
        cursor.execute('UPDATE settings SET enroll_start = ?, enroll_end = ? WHERE id = 1', (start, end))
    
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": "신청 시간이 설정되었습니다."})

@app.route('/api/admin/settings/time', methods=['GET'])
def get_admin_enroll_time():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT enroll_start, enroll_end FROM settings WHERE id = 1')
    settings = cursor.fetchone()
    conn.close()
    
    if settings:
        start = settings['enroll_start']
        end = settings['enroll_end']
        
        if start and not isinstance(start, str):
            start = start.strftime('%Y-%m-%dT%H:%M')
        if end and not isinstance(end, str):
            end = end.strftime('%Y-%m-%dT%H:%M')
        
        return jsonify({"start": start, "end": end})
    
    return jsonify({"start": None, "end": None})

@app.route('/api/admin/download/all', methods=['GET'])
def download_all_enrollments():
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "관리자 로그인 필요"})
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT c.name as course_name, e.student_id, e.student_name, e.enrolled_at
        FROM enrollments e
        JOIN courses c ON e.course_id = c.id
        ORDER BY c.name, e.enrolled_at
    ''')
    
    enrollments = cursor.fetchall()
    conn.close()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "전체 신청자"
    ws.append(['강좌명', '학번', '이름', '신청시간'])
    
    for row in enrollments:
        enrolled_at = row['enrolled_at']
        if enrolled_at and not isinstance(enrolled_at, str):
            enrolled_at = enrolled_at.strftime('%Y-%m-%d %H:%M:%S')
        ws.append([row['course_name'], row['student_id'], row['student_name'], enrolled_at])
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='전체_신청자_목록.xlsx'
    )

@app.route('/api/admin/download/<int:course_id>', methods=['GET'])
def download_course_enrollments(course_id):
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "관리자 로그인 필요"})
    
    conn = get_db()
    cursor = conn.cursor()
    
    if is_postgres():
        cursor.execute('SELECT name FROM courses WHERE id = %s', (course_id,))
    else:
        cursor.execute('SELECT name FROM courses WHERE id = ?', (course_id,))
    
    course = cursor.fetchone()
    course_name = course['name'] if course else '강좌'
    
    if is_postgres():
        cursor.execute('''
            SELECT student_id, student_name, enrolled_at
            FROM enrollments
            WHERE course_id = %s
            ORDER BY enrolled_at
        ''', (course_id,))
    else:
        cursor.execute('''
            SELECT student_id, student_name, enrolled_at
            FROM enrollments
            WHERE course_id = ?
            ORDER BY enrolled_at
        ''', (course_id,))
    
    enrollments = cursor.fetchall()
    conn.close()
    
    wb = Workbook()
    ws = wb.active
    ws.title = course_name[:30]
    ws.append(['순번', '학번', '이름', '신청시간'])
    
    for idx, row in enumerate(enrollments, 1):
        enrolled_at = row['enrolled_at']
        if enrolled_at and not isinstance(enrolled_at, str):
            enrolled_at = enrolled_at.strftime('%Y-%m-%d %H:%M:%S')
        ws.append([idx, row['student_id'], row['student_name'], enrolled_at])
    
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{course_name}_신청자_목록.xlsx'
    )

if __name__ == '__main__':
    app.run(debug=True)
