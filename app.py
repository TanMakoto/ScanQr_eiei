from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import csv
import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import socket
import sqlite3
import time
from datetime import datetime, timedelta
import requests
import student_registry

app = Flask(__name__)
CORS(app)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if os.environ.get('VERCEL') or os.environ.get('AWS_LAMBDA_FUNCTION_NAME'):
    DB_FILE = '/tmp/attendance.db'
else:
    DB_FILE = os.path.join(BASE_DIR, 'attendance.db')
STUDENTS_FILE = os.path.join(BASE_DIR, 'students.csv')
QR_TOKEN_TTL_SECONDS = 60
QR_SECRET = os.environ.get('QR_SECRET', '')
REMOTE_API_BASE_URL = os.environ.get('REMOTE_API_BASE_URL', 'https://new-data2.onrender.com').rstrip('/')
REMOTE_STUDENTS_CSV_URL = os.environ.get(
    'REMOTE_STUDENTS_CSV_URL',
    'https://docs.google.com/spreadsheets/d/11szmicddC2FZeLsgM4DZXzA87zBNgeSOvDwQ_-2gKWU/export?format=csv&gid=0',
).strip()
REMOTE_STUDENTS_CACHE_SECONDS = 60
REMOTE_STUDENTS_RETRY_SECONDS = 15
LAST_SCAN = {"student_id": "รอสแกน QR...", "student_name": "กำลังรอการเช็คชื่อ..."}
QR_TOKEN_MAP = {}
REMOTE_STUDENTS_CACHE = {
    "students": None,
    "expires_at": datetime.min,
}


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_attendance_table():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        '''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            time TEXT,
            student_id TEXT,
            name TEXT,
            status TEXT
        )
        '''
    )
    conn.commit()
    conn.close()


def fetch_remote_students():
    if not REMOTE_API_BASE_URL and not REMOTE_STUDENTS_CSV_URL:
        return {}

    now = datetime.utcnow()
    cached_students = REMOTE_STUDENTS_CACHE.get("students")
    if cached_students is not None and now < REMOTE_STUDENTS_CACHE.get("expires_at", datetime.min):
        return cached_students

    students = {}
    try:
        if REMOTE_STUDENTS_CSV_URL:
            response = requests.get(REMOTE_STUDENTS_CSV_URL, timeout=5)
            if response.ok:
                csv_text = response.content.decode('utf-8-sig')
                reader = csv.DictReader(io.StringIO(csv_text))
                for row in reader:
                    student_id = str(row.get('student_id', '')).strip()
                    name = str(row.get('name') or row.get('full_name') or '').strip()
                    if student_id and name:
                        students[student_id] = {
                            "student_id": student_id,
                            "name": name,
                        }

        if not students and REMOTE_API_BASE_URL:
            response = requests.get(f"{REMOTE_API_BASE_URL}/api/users", timeout=5)
            data = response.json()
            if response.ok and isinstance(data, list):
                for row in data:
                    student_id = str(row.get('user_id', '')).strip()
                    name = str(row.get('full_name') or row.get('name') or '').strip()
                    if student_id and name:
                        students[student_id] = {
                            "student_id": student_id,
                            "name": name,
                        }
    except (requests.RequestException, ValueError):
        students = {}

    cache_seconds = REMOTE_STUDENTS_CACHE_SECONDS if students else REMOTE_STUDENTS_RETRY_SECONDS
    REMOTE_STUDENTS_CACHE["students"] = students
    REMOTE_STUDENTS_CACHE["expires_at"] = now + timedelta(seconds=cache_seconds)
    return students


def load_local_students():
    students = {}
    if not os.path.exists(STUDENTS_FILE):
        return students

    with open(STUDENTS_FILE, 'r', encoding='utf-8-sig', newline='') as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            student_id = str(row.get('student_id', '')).strip()
            name = str(row.get('name', '')).strip()
            if student_id and name:
                students[student_id] = {
                    "student_id": student_id,
                    "name": name,
                }
    return students


def load_students():
    remote_students = fetch_remote_students()
    local_students = load_local_students()
    if remote_students:
        merged_students = dict(remote_students)
        merged_students.update(local_students)
        return merged_students
    return local_students


def lookup_student(sid):
    return student_registry.find_student(sid) or load_students().get(sid)


@app.errorhandler(student_registry.RegistryUnavailable)
def registry_unavailable(error):
    return jsonify(status='error', message=str(error)), 503


@app.route('/admin/students')
def student_admin_page():
    return send_from_directory(BASE_DIR, 'student-admin.html')


@app.route('/api/admin/students', methods=['POST'])
def add_student():
    if not student_registry.admin_authorized(request.headers.get('X-Admin-Key', '')):
        return jsonify(status='error', message='รหัสผู้ดูแลไม่ถูกต้อง หรือยังไม่ได้เปิดใช้งาน'), 401
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(status='error', message='ข้อมูลไม่ถูกต้อง'), 400
    try:
        sid, name = student_registry.validate_student(data)
    except ValueError as error:
        return jsonify(status='error', message=str(error)), 400
    if load_students().get(sid) or not student_registry.create_student(sid, name):
        return jsonify(status='error', message='มีรหัสนักศึกษานี้แล้ว ไม่ได้แก้ไขข้อมูลเดิม'), 409
    return jsonify(status='success', student_id=sid, name=name,
                   message='เพิ่มนักศึกษาแล้ว สามารถกลับไป Login เพื่อสร้าง QR ได้ทันที'), 201


def get_ip_address():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        ip = sock.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        sock.close()
    return ip


def purge_expired_qr_tokens():
    now = datetime.utcnow()
    expired_tokens = [
        token for token, payload in QR_TOKEN_MAP.items()
        if payload.get("expires_at") <= now
    ]
    for token in expired_tokens:
        QR_TOKEN_MAP.pop(token, None)


def create_signed_qr_token(student_id, expires_in=QR_TOKEN_TTL_SECONDS):
    if not QR_SECRET:
        raise RuntimeError('QR_SECRET is not configured')
    payload = {
        'student_id': student_id,
        'exp': int(time.time()) + expires_in,
        'nonce': secrets.token_urlsafe(6),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ).decode('ascii').rstrip('=')
    signature = hmac.new(
        QR_SECRET.encode('utf-8'), encoded.encode('ascii'), hashlib.sha256
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')
    return f'Q2.{encoded}.{encoded_signature}'


def resolve_signed_qr_token(token):
    if not QR_SECRET or not token.startswith('Q2.'):
        return None
    try:
        _, encoded, signature = token.split('.', 2)
        expected = hmac.new(
            QR_SECRET.encode('utf-8'), encoded.encode('ascii'), hashlib.sha256
        ).digest()
        actual = base64.urlsafe_b64decode(signature + '=' * (-len(signature) % 4))
        if not hmac.compare_digest(actual, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(
            encoded + '=' * (-len(encoded) % 4)
        ).decode('utf-8'))
        if int(payload.get('exp', 0)) <= int(time.time()):
            return None
        student_id = str(payload.get('student_id', '')).strip()
        return student_id if student_id else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def fetch_remote_history():
    if not REMOTE_API_BASE_URL:
        return None

    try:
        response = requests.get(f"{REMOTE_API_BASE_URL}/api/report", timeout=5)
        data = response.json()
        if not response.ok or not isinstance(data, list):
            return None

        students = load_students()
        normalized = []
        for item in data:
            user_id = str(item.get('user_id', '')).strip()
            name = (
                students.get(user_id, {}).get('name')
                or item.get('full_name')
                or item.get('name')
                or user_id
            )
            normalized.append({
                "date": item.get('attend_date') or item.get('date'),
                "time": item.get('time'),
                "name": name,
            })

        normalized.sort(
            key=lambda row: ((row.get("date") or ""), (row.get("time") or "")),
            reverse=True,
        )
        return normalized[:10]
    except (requests.RequestException, ValueError):
        return None


@app.route('/')
def index():
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    sid = str(data.get('id', '')).strip()
    user = lookup_student(sid)

    if user:
        return jsonify({"status": "success", "name": user['name']})
    return jsonify({"status": "error", "message": "ไม่พบรหัสนักศึกษา"})


@app.route('/update_attendance_status', methods=['POST'])
def update_status():
    global LAST_SCAN
    data = request.get_json(silent=True) or {}
    LAST_SCAN = {
        "student_id": data.get("student_id"),
        "student_name": data.get("student_name")
    }
    return jsonify({"status": "success"})


@app.route('/get_last_student', methods=['GET'])
def get_last_student():
    return jsonify(LAST_SCAN)


@app.route('/get_history', methods=['GET'])
def get_history():
    try:
        remote_history = fetch_remote_history()
        if remote_history is not None:
            return jsonify(remote_history)

        ensure_attendance_table()
        conn = get_db_connection()
        records = conn.execute(
            'SELECT date, time, name FROM attendance ORDER BY id DESC LIMIT 10'
        ).fetchall()
        conn.close()
        return jsonify([dict(row) for row in records])
    except Exception:
        return jsonify([])


@app.route('/update_qr', methods=['POST'])
def update_qr():
    data = request.get_json(silent=True) or {}
    student_id = str(data.get('student_id', '')).strip()
    expires_in = data.get('expires_in', QR_TOKEN_TTL_SECONDS)

    try:
        expires_in = int(expires_in)
    except (TypeError, ValueError):
        expires_in = QR_TOKEN_TTL_SECONDS

    expires_in = max(1, min(expires_in, 300))
    if not student_id or not lookup_student(student_id):
        return jsonify({"status": "error", "message": "student not found"}), 404
    try:
        token = create_signed_qr_token(student_id, expires_in)
    except RuntimeError as error:
        return jsonify({"status": "error", "message": str(error)}), 503
    return jsonify({"status": "success", "token": token, "expires_in": expires_in})


@app.route('/resolve_qr', methods=['GET'])
def resolve_qr():
    purge_expired_qr_tokens()
    token = str(request.args.get('token', '')).strip()
    if not token:
        return jsonify({"status": "error", "message": "missing token"}), 400

    signed_student_id = resolve_signed_qr_token(token)
    if signed_student_id:
        student = lookup_student(signed_student_id)
        if student:
            return jsonify({"status": "success", "student_id": signed_student_id, "name": student['name']})

    # Compatibility for old tokens when running a local single-process server.
    payload = QR_TOKEN_MAP.pop(token, None)
    if payload:
        return jsonify({"status": "success", "student_id": payload["student_id"]})

    students = load_students()
    if token in students:
        return jsonify({"status": "success", "student_id": token})

    return jsonify({"status": "error", "message": "not found"}), 404


if __name__ == '__main__':
    ensure_attendance_table()
    ip = get_ip_address()
    print("\n" + "=" * 50)
    print(f"SERVER RUNNING AT: http://{ip}:5000")
    print("=" * 50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
