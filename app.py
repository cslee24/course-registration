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
from supabase import create_client, Client

# SSL 인증서 경로 설정
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-12345')

# ============ Supabase 설정 ============
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

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

# ============ 신청 가능 시간 확인 함수 ============
def check_enroll_time():
    result = supabase.table('settings').select('*').eq('id', 1).execute()
    settings = result.data[0] if result.data else None
    
    if not settings or not settings.get('enroll_start') or not settings.get('enroll_end'):
        return {"allowed": False, "message": "신청 시간이 설정되지 않았습니다."}
    
    # 한국 시간 (UTC+9)
    now = datetime.utcnow() + timedelta(hours=9)
    
    start_str = settings['enroll_start']
    end_str = settings['enroll_end']
    
    start = datetime.fromisoformat(start_str.replace('Z', '+00:00')) if isinstance(start_str, str) else start_str
    end = datetime.fromisoformat(end_str.replace('Z', '+00:00')) if isinstance(end_str, str) else end_str
    
    if now < start:
        return {"allowed": False, "message": "신청 시작 전입니다."}
    elif now > end:
        return {"allowed": False, "message": "신청이 마감되었습니다."}
    else:
        return {"allowed": True, "message": "신청 가능"}

# ============ 메인 페이지 (SSR 방식 적용) ============
@app.route('/')
def home():
    # 1. 강좌 목록 가져오기
    courses_result = supabase.table('courses').select('*').order('id').execute()
    courses = courses_result.data
    
    my_enrollments = []
    user = session.get('user')
    
    # 2. 로그인한 경우 내 신청 내역 가져오기
    if user:
        student_id = user['student_id']
        enrollments_result = supabase.table('enrollments').select('course_id, courses(name)').eq('student_id', student_id).execute()
        my_enrollments = [{'course_id': e['course_id'], 'course_name': e['courses']['name']} for e in enrollments_result.data]
    
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
    
    try:
        # 강좌 정보 조회
        course_result = supabase.table('courses').select('*').eq('id', course_id).execute()
        course = course_result.data[0] if course_result.data else None
        
        if not course:
            flash("존재하지 않는 강좌입니다.")
            return redirect('/')

        # 중복 신청 체크
        duplicate_check = supabase.table('enrollments').select('id').eq('course_id', course_id).eq('student_id', student_id).execute()
        if duplicate_check.data:
            flash("이미 신청한 강좌입니다.")
            return redirect('/')
            
        # 정원 체크
        if course['enrolled'] >= course['limit_num']:
            flash("정원이 마감되었습니다.")
            return redirect('/')
            
        # 신청 처리
        supabase.table('enrollments').insert({
            'course_id': course_id,
            'student_id': student_id,
            'student_name': student_name
        }).execute()
        
        supabase.table('courses').update({'enrolled': course['enrolled'] + 1}).eq('id', course_id).execute()
        
        flash(f"[{course['name']}] 신청이 완료되었습니다!")
        
    except Exception as e:
        flash("신청 중 오류가 발생했습니다.")
        print(e)
        
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
    
    try:
        # 신청 내역 확인
        enrollment_result = supabase.table('enrollments').select('id').eq('course_id', course_id).eq('student_id', student_id).execute()
        
        if not enrollment_result.data:
            flash("취소할 신청 내역이 없습니다.")
        else:
            enrollment_id = enrollment_result.data[0]['id']
            
            # 삭제
            supabase.table('enrollments').delete().eq('id', enrollment_id).execute()
            
            # 인원 감소
            course_result = supabase.table('courses').select('enrolled').eq('id', course_id).execute()
            if course_result.data:
                current_enrolled = course_result.data[0]['enrolled']
                supabase.table('courses').update({'enrolled': max(0, current_enrolled - 1)}).eq('id', course_id).execute()
            
            flash("신청이 취소되었습니다.")
            
    except Exception as e:
        flash("취소 중 오류가 발생했습니다.")
        print(e)
        
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

@app.route('/api/courses', methods=['GET'])
def get_all_courses():
    result = supabase.table('courses').select('*').order('id').execute()
    return jsonify(result.data)

@app.route('/api/admin/course', methods=['POST'])
def add_course():
    data = request.get_json()
    name = data.get('name')
    limit = data.get('limit')
    
    supabase.table('courses').insert({'name': name, 'limit_num': limit, 'enrolled': 0}).execute()
    
    return jsonify({"success": True, "message": f"'{name}' 강좌 추가 완료!"})

@app.route('/api/admin/course/<int:course_id>', methods=['DELETE'])
def delete_course(course_id):
    supabase.table('enrollments').delete().eq('course_id', course_id).execute()
    supabase.table('courses').delete().eq('id', course_id).execute()
    
    return jsonify({"success": True, "message": "강좌 삭제 완료!"})

@app.route('/api/admin/courses/delete-all', methods=['POST'])
def delete_all_courses():
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "관리자 로그인 필요"})
    
    try:
        supabase.table('enrollments').delete().neq('id', 0).execute()
        supabase.table('courses').delete().neq('id', 0).execute()
        return jsonify({"success": True, "message": "모든 강좌가 삭제되었습니다."})
    except Exception as e:
        return jsonify({"success": False, "message": f"오류 발생: {str(e)}"})

@app.route('/api/admin/course/<int:course_id>/reset', methods=['POST'])
def reset_course(course_id):
    supabase.table('enrollments').delete().eq('course_id', course_id).execute()
    supabase.table('courses').update({'enrolled': 0}).eq('id', course_id).execute()
    
    return jsonify({"success": True, "message": "신청 인원 초기화 완료!"})

@app.route('/api/admin/course/<int:course_id>/enrollments', methods=['GET'])
def get_enrollments(course_id):
    result = supabase.table('enrollments').select('student_id, student_name, enrolled_at').eq('course_id', course_id).order('enrolled_at').execute()
    return jsonify(result.data)

@app.route('/api/admin/settings/time', methods=['POST'])
def set_enroll_time():
    data = request.get_json()
    start = data.get('start')
    end = data.get('end')
    
    supabase.table('settings').update({'enroll_start': start, 'enroll_end': end}).eq('id', 1).execute()
    
    return jsonify({"success": True, "message": "신청 시간이 설정되었습니다."})

@app.route('/api/admin/settings/time', methods=['GET'])
def get_admin_enroll_time():
    result = supabase.table('settings').select('enroll_start, enroll_end').eq('id', 1).execute()
    settings = result.data[0] if result.data else None
    
    if settings:
        return jsonify({"start": settings.get('enroll_start'), "end": settings.get('enroll_end')})
    
    return jsonify({"start": None, "end": None})

@app.route('/api/admin/download/all', methods=['GET'])
def download_all_enrollments():
    if not session.get('admin_logged_in'):
        return jsonify({"success": False, "message": "관리자 로그인 필요"})
    
    result = supabase.table('enrollments').select('*, courses(name)').order('courses(name), enrolled_at').execute()
    
    wb = Workbook()
    ws = wb.active
    ws.title = "전체 신청자"
    ws.append(['강좌명', '학번', '이름', '신청시간'])
    
    for row in result.data:
        ws.append([row['courses']['name'], row['student_id'], row['student_name'], row['enrolled_at']])
    
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
    
    course_result = supabase.table('courses').select('name').eq('id', course_id).execute()
    course_name = course_result.data[0]['name'] if course_result.data else '강좌'
    
    result = supabase.table('enrollments').select('student_id, student_name, enrolled_at').eq('course_id', course_id).order('enrolled_at').execute()
    
    wb = Workbook()
    ws = wb.active
    ws.title = course_name[:30]
    ws.append(['순번', '학번', '이름', '신청시간'])
    
    for idx, row in enumerate(result.data, 1):
        ws.append([idx, row['student_id'], row['student_name'], row['enrolled_at']])
    
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