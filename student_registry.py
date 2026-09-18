"""Persistent student registration shared by all Vercel instances."""
import os
import unicodedata
import hmac
from functools import lru_cache


class RegistryUnavailable(Exception):
    pass


@lru_cache(maxsize=1)
def collection():
    uri = os.environ.get('MONGODB_URI', '').strip()
    if not uri:
        raise RegistryUnavailable('ยังไม่ได้ตั้งค่าฐานข้อมูลผู้ใช้งาน')
    try:
        from pymongo import MongoClient
        client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        return client[os.environ.get('MONGODB_DATABASE', 'attendanceDB')]['qr_students']
    except Exception as exc:
        raise RegistryUnavailable('เชื่อมต่อฐานข้อมูลผู้ใช้งานไม่ได้') from exc


def admin_authorized(value):
    expected = os.environ.get('QR_ADMIN_KEY', '')
    return len(expected) >= 32 and hmac.compare_digest(
        expected.encode('utf-8'), value.encode('utf-8'))


def validate_student(data):
    sid = data.get('student_id', '')
    name = data.get('name', '')
    if not isinstance(sid, str) or not (1 <= len(sid.strip()) <= 64 and all(c in '_-' or unicodedata.category(c)[0] in 'LNM' for c in sid.strip())):
        raise ValueError('รหัสผู้ใช้งานต้องมี 1–64 ตัวอักษร ใช้ตัวอักษร ตัวเลข _ หรือ - โดยไม่มีช่องว่าง')
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 150:
        raise ValueError('กรุณากรอกชื่อและนามสกุล 2–150 ตัวอักษร')
    return sid.strip(), name.strip()


def find_student(sid):
    if not os.environ.get('MONGODB_URI'):
        return None
    try:
        record = collection().find_one({'_id': sid})
        return {'student_id': record['_id'], 'name': record['name']} if record else None
    except Exception as exc:
        raise RegistryUnavailable('ไม่สามารถค้นหาผู้ใช้งานได้ กรุณาลองใหม่') from exc


def create_student(sid, name):
    try:
        # MongoDB's unique _id prevents duplicates across concurrent requests.
        result = collection().update_one(
            {'_id': sid}, {'$setOnInsert': {'name': name}}, upsert=True)
        return result.upserted_id is not None
    except Exception as exc:
        raise RegistryUnavailable('บันทึกข้อมูลไม่ได้ กรุณาลองใหม่') from exc
