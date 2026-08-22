import csv
import io
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta

import cv2
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, 'attendance.db')
STUDENTS_FILE = os.path.join(BASE_DIR, 'students.csv')
SERVER_URL = os.environ.get('ATTENDANCE_SERVER_URL', 'http://127.0.0.1:5000')
REMOTE_API_BASE_URL = os.environ.get('REMOTE_API_BASE_URL', 'https://new-data2.onrender.com').rstrip('/')
REMOTE_STUDENTS_CSV_URL = os.environ.get(
    'REMOTE_STUDENTS_CSV_URL',
    'https://docs.google.com/spreadsheets/d/11szmicddC2FZeLsgM4DZXzA87zBNgeSOvDwQ_-2gKWU/export?format=csv&gid=0',
).strip()
REMOTE_SYNC_CACHE_FILE = os.path.join(BASE_DIR, 'remote_user_sync_cache.json')
REMOTE_STUDENTS_CACHE_SECONDS = 60
REMOTE_STUDENTS_RETRY_SECONDS = 15
SUCCESS_DISPLAY_SECONDS = 3
ERROR_DISPLAY_SECONDS = 2
RECENT_SCAN_COOLDOWN_SECONDS = 3
QR_DETECTOR = cv2.QRCodeDetector()
REMOTE_STUDENTS_CACHE = {
    "students": None,
    "expires_at": datetime.min,
}


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
                        students[student_id] = name

        if not students and REMOTE_API_BASE_URL:
            response = requests.get(f"{REMOTE_API_BASE_URL}/api/users", timeout=5)
            data = response.json()
            if response.ok and isinstance(data, list):
                for row in data:
                    student_id = str(row.get('user_id', '')).strip()
                    name = str(row.get('full_name') or row.get('name') or '').strip()
                    if student_id and name:
                        students[student_id] = name
    except (requests.RequestException, ValueError):
        students = {}

    cache_seconds = REMOTE_STUDENTS_CACHE_SECONDS if students else REMOTE_STUDENTS_RETRY_SECONDS
    REMOTE_STUDENTS_CACHE["students"] = students
    REMOTE_STUDENTS_CACHE["expires_at"] = now + timedelta(seconds=cache_seconds)
    return students


def load_local_students():
    students = {}
    try:
        with open(STUDENTS_FILE, 'r', encoding='utf-8-sig', newline='') as csv_file:
            reader = csv.DictReader(csv_file)
            for row in reader:
                student_id = str(row.get('student_id', '')).strip()
                name = str(row.get('name', '')).strip()
                if student_id and name:
                    students[student_id] = name
    except FileNotFoundError:
        print("ERROR: students.csv not found")
    except Exception as e:
        print(f"ERROR: failed to read students: {e}")
    return students


def load_students():
    remote_students = fetch_remote_students()
    local_students = load_local_students()
    if remote_students:
        merged_students = dict(remote_students)
        merged_students.update(local_students)
        return merged_students
    return local_students


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


def load_remote_sync_cache():
    try:
        with open(REMOTE_SYNC_CACHE_FILE, 'r', encoding='utf-8') as cache_file:
            payload = json.load(cache_file)
            if isinstance(payload, dict):
                return payload
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"WARNING: failed to read remote sync cache: {e}")
    return {}


def save_remote_sync_cache(cache):
    try:
        with open(REMOTE_SYNC_CACHE_FILE, 'w', encoding='utf-8') as cache_file:
            json.dump(cache, cache_file, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"WARNING: failed to save remote sync cache: {e}")


def resolve_qr_token(token):
    try:
        response = requests.get(
            f"{SERVER_URL}/resolve_qr",
            params={"token": token},
            timeout=3,
        )
        data = response.json()
        if response.ok and data.get("status") == "success":
            return str(data.get("student_id"))
    except requests.RequestException as e:
        print(f"WARNING: resolve_qr request failed: {e}")
    except ValueError:
        print("WARNING: resolve_qr returned invalid data")
    return None


def update_last_scan(student_id, student_name):
    try:
        requests.post(
            f"{SERVER_URL}/update_attendance_status",
            json={"student_id": student_id, "student_name": student_name},
            timeout=3,
        )
    except requests.RequestException as e:
        print(f"WARNING: failed to update last scan: {e}")


REMOTE_SYNC_CACHE = load_remote_sync_cache()


def ensure_remote_user(student_id, student_name):
    if not REMOTE_API_BASE_URL:
        return True, "REMOTE API DISABLED"

    synced_users = REMOTE_SYNC_CACHE.setdefault(REMOTE_API_BASE_URL, [])
    if student_id in synced_users:
        return True, "REMOTE USER ALREADY SYNCED"

    try:
        response = requests.post(
            f"{REMOTE_API_BASE_URL}/api/users",
            json={"user_id": student_id, "full_name": student_name},
            timeout=5,
        )
        data = response.json()
        if response.ok:
            synced_users.append(student_id)
            save_remote_sync_cache(REMOTE_SYNC_CACHE)
            return True, data.get("message", "REMOTE USER SYNCED")
        return False, data.get("message") or data.get("error") or f"HTTP {response.status_code}"
    except requests.RequestException as e:
        return False, str(e)
    except ValueError:
        return False, "remote /api/users returned invalid data"


def submit_remote_checkin(student_id, student_name):
    if not REMOTE_API_BASE_URL:
        return False, "REMOTE API DISABLED"

    synced, sync_message = ensure_remote_user(student_id, student_name)
    if not synced:
        return False, f"REMOTE USER SYNC FAILED: {sync_message}"

    try:
        response = requests.post(
            f"{REMOTE_API_BASE_URL}/api/checkin",
            json={"user_id": student_id},
            timeout=5,
        )
        data = response.json()
        if response.ok:
            return True, data.get("message", "REMOTE CHECK-IN OK")
        return False, data.get("message") or data.get("error") or f"HTTP {response.status_code}"
    except requests.RequestException as e:
        return False, str(e)
    except ValueError:
        return False, "remote /api/checkin returned invalid data"


def save_attendance(student_id, name):
    try:
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        time_str = now.strftime('%H:%M:%S')

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            '''
            INSERT INTO attendance (date, time, student_id, name, status)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (date_str, time_str, student_id, name, 'Success'),
        )
        conn.commit()
        conn.close()

        print(f"Saved attendance: {name} ({student_id}) at {date_str} {time_str}")
        return True
    except Exception as e:
        print(f"ERROR: failed to save attendance: {e}")
        return False


def detect_qrs(frame):
    variants = []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    enlarged_gray = cv2.resize(gray, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    binary = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        7,
    )
    variants.append((frame, 1.0))
    variants.append((gray, 1.0))
    variants.append((binary, 1.0))
    variants.append((enlarged_gray, 1 / 1.5))

    for variant, scale_back in variants:
        decoded_items = []
        try:
            found, decoded_info, points, _ = QR_DETECTOR.detectAndDecodeMulti(variant)
        except cv2.error:
            found, decoded_info, points = False, [], None

        if found and points is not None:
            for data, qr_points in zip(decoded_info, points):
                if data:
                    decoded_items.append((data, qr_points * scale_back))
            if decoded_items:
                return decoded_items

        data, single_points, _ = QR_DETECTOR.detectAndDecode(variant)
        if data and single_points is not None:
            return [(data, single_points * scale_back)]

    return []


def draw_qr_box(frame, qr_points, color):
    if qr_points is None:
        return

    points = qr_points.reshape(-1, 2)
    if len(points) < 4:
        return

    for idx in range(len(points)):
        start = points[idx]
        end = points[(idx + 1) % len(points)]
        cv2.line(
            frame,
            (int(start[0]), int(start[1])),
            (int(end[0]), int(end[1])),
            color,
            2,
        )


if not REMOTE_STUDENTS_CSV_URL and not os.path.exists(STUDENTS_FILE):
    raise SystemExit("ERROR: students.csv not found")

students = load_students()
if not students:
    raise SystemExit("ERROR: no students found in remote or local student source")


def main():
    ensure_attendance_table()

    print("Starting QR scanner... (press 'q' to quit)")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise SystemExit("ERROR: cannot open camera")

    success_display_until = None
    success_name = None
    error_display_until = None
    error_message = None
    recent_tokens = {}

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            now = datetime.now()
            monotonic_now = time.monotonic()
            recent_tokens = {
                token: expires_at
                for token, expires_at in recent_tokens.items()
                if expires_at > monotonic_now
            }

            decoded_qrs = detect_qrs(frame)
            for _, qr_points in decoded_qrs:
                draw_qr_box(frame, qr_points, (0, 255, 255))

            success_active = success_display_until and now < success_display_until

            if not success_active:
                for qr_token, _ in decoded_qrs:
                    qr_token = qr_token.strip()
                    if not qr_token or qr_token in recent_tokens:
                        continue

                    recent_tokens[qr_token] = monotonic_now + RECENT_SCAN_COOLDOWN_SECONDS
                    student_id = resolve_qr_token(qr_token)
                    if not student_id:
                        students = load_students()
                        if qr_token in students:
                            student_id = qr_token

                    if not student_id:
                        error_message = "QR USED OR EXPIRED - GENERATE NEW QR"
                        error_display_until = now + timedelta(seconds=ERROR_DISPLAY_SECONDS)
                        recent_tokens[qr_token] = monotonic_now + 10
                        print("QR is invalid, already used, or expired")
                        break

                    students = load_students()
                    student_name = students.get(student_id)
                    if not student_name:
                        error_message = f"STUDENT NOT FOUND: {student_id}"
                        error_display_until = now + timedelta(seconds=ERROR_DISPLAY_SECONDS)
                        print(f"Student not found: {student_id}")
                        break

                    remote_ok, remote_message = submit_remote_checkin(student_id, student_name)
                    if remote_ok:
                        print(f"Remote API: {remote_message}")
                    else:
                        print(f"WARNING: remote check-in failed: {remote_message}")

                    already_checked_in = "วันนี้เช็คชื่อแล้ว" in remote_message
                    local_ok = True
                    if not already_checked_in:
                        local_ok = save_attendance(student_id, student_name)

                    if remote_ok or local_ok:
                        update_last_scan(student_id, student_name)
                        success_name = student_name
                        success_display_until = now + timedelta(seconds=SUCCESS_DISPLAY_SECONDS)
                        error_display_until = None
                        error_message = None
                        if already_checked_in:
                            print(f"Already checked in today: {student_name}")
                        else:
                            print(f"Check-in success: {student_name}")
                        cv2.waitKey(500)
                    else:
                        error_message = "CHECK-IN FAILED"
                        error_display_until = now + timedelta(seconds=ERROR_DISPLAY_SECONDS)
                    break

            success_active = success_display_until and now < success_display_until
            error_active = error_display_until and now < error_display_until

            label = "SCAN QR CODE"
            color = (0, 140, 255)

            if success_active:
                label = f"CHECK-IN SUCCESS: {success_name}"
                color = (0, 170, 0)
                cv2.rectangle(frame, (0, 0), (frame.shape[1], frame.shape[0]), color, 10)
            elif error_active:
                label = error_message
                color = (0, 0, 255)

            cv2.rectangle(frame, (0, 0), (frame.shape[1], 50), color, -1)
            cv2.putText(
                frame,
                label,
                (10, 33),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )

            cv2.imshow('Attendance System', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("Scanner stopped by user")
                break

    except KeyboardInterrupt:
        print("\nScanner interrupted by user")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("Camera closed")


if __name__ == '__main__':
    main()
