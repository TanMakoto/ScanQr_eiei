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
        return {'student_id': record['_id'], 'name': record['name'], 'role': record.get('role', ''), 'dept': record.get('dept', '')} if record else None
    except Exception as exc:
        raise RegistryUnavailable('ไม่สามารถค้นหาผู้ใช้งานได้ กรุณาลองใหม่') from exc


def create_student(sid, name, role="", dept=""):
    try:
        # MongoDB's unique _id prevents duplicates across concurrent requests.
        result = collection().update_one(
            {'_id': sid}, {'$setOnInsert': {'name': name, 'role': role, 'dept': dept}}, upsert=True)
        return result.upserted_id is not None
    except Exception as exc:
        raise RegistryUnavailable('บันทึกข้อมูลไม่ได้ กรุณาลองใหม่') from exc

def validate_details(data):
    values = []
    for key in ('role', 'dept'):
        value = data.get(key, '')
        if not isinstance(value, str) or len(value.strip()) > 150:
            raise ValueError('ตำแหน่งและสาขา/หน่วยงานต้องเป็นข้อความไม่เกิน 150 ตัวอักษร')
        values.append(value.strip())
    return values

def update_student(sid, name, role, dept):
    try:
        collection().update_one({'_id': sid}, {'$set': {'name': name, 'role': role, 'dept': dept}}, upsert=True)
    except Exception as exc:
        raise RegistryUnavailable('แก้ไขข้อมูลไม่ได้ กรุณาลองใหม่') from exc
