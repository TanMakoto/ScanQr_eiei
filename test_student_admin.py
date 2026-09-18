import os
import unittest
from unittest.mock import patch
import student_registry
from app import app


class StudentAdminTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.env = patch.dict(os.environ, {'QR_ADMIN_KEY': 'a' * 32})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.headers = {'X-Admin-Key': 'a' * 32}
        self.student = {'student_id': 'STAFF-0099', 'name': 'เจ้าหน้าที่ ทดสอบ'}

    def test_unauthorized_cannot_write(self):
        with patch('student_registry.create_student') as write:
            self.assertEqual(self.client.post('/api/admin/students', json=self.student).status_code, 401)
            write.assert_not_called()

    def test_invalid_inputs(self):
        for payload in [[], {'student_id': '../bad', 'name': 'Test'}, {'student_id': '6612247099', 'name': ''}]:
            self.assertEqual(self.client.post('/api/admin/students', json=payload, headers=self.headers).status_code, 400)

    def test_create_then_login_generate_and_resolve(self):
        from types import SimpleNamespace
        records = {}

        class MemoryCollection:
            def update_one(self, query, update, upsert):
                sid = query['_id']
                if sid in records:
                    return SimpleNamespace(upserted_id=None)
                records[sid] = {'_id': sid, **update['$setOnInsert']}
                return SimpleNamespace(upserted_id=sid)

            def find_one(self, query):
                return records.get(query['_id'])

        with patch.dict(os.environ, {'MONGODB_URI': 'mock'}), patch('student_registry.collection', return_value=MemoryCollection()), patch('app.load_students', return_value={}), patch('app.QR_SECRET', 'q' * 32):
            self.assertEqual(self.client.post('/api/admin/students', json=self.student, headers=self.headers).status_code, 201)
            self.assertEqual(self.client.post('/login', json={'id': self.student['student_id']}).json['name'], self.student['name'])
            response = self.client.post('/update_qr', json={'student_id': self.student['student_id']})
            self.assertEqual(response.status_code, 200)
            token = response.json['token']
            resolved = self.client.get('/resolve_qr', query_string={'token': token})
            self.assertEqual(resolved.json['student_id'], self.student['student_id'])
            self.assertEqual(resolved.json['name'], self.student['name'])
            duplicate = self.client.post('/api/admin/students', json={**self.student, 'name': 'Different Name'}, headers=self.headers)
            self.assertEqual(duplicate.status_code, 409)
            self.assertEqual(records[self.student['student_id']]['name'], self.student['name'])

    def test_existing_legacy_student_not_overwritten(self):
        with patch('app.load_students', return_value={self.student['student_id']: self.student}), patch('student_registry.create_student') as write:
            self.assertEqual(self.client.post('/api/admin/students', json=self.student, headers=self.headers).status_code, 409)
            write.assert_not_called()

    def test_database_failure_is_not_student_not_found(self):
        with patch('student_registry.find_student', side_effect=student_registry.RegistryUnavailable('ฐานข้อมูลไม่พร้อม')):
            self.assertEqual(self.client.post('/login', json={'id':'6612247099'}).status_code, 503)

    def test_general_user_ids(self):
        for sid in ['RECTOR-001', 'STAFF_42', 'A', '0012345678', 'บุคลากร-01']:
            self.assertEqual(student_registry.validate_student({'student_id': sid, 'name': 'ผู้ใช้ ทดสอบ'})[0], sid)
        for sid in ['bad id', '../bad', 'A' * 65, '']:
            with self.assertRaises(ValueError):
                student_registry.validate_student({'student_id': sid, 'name': 'ผู้ใช้ ทดสอบ'})

    def test_admin_page(self):
        self.assertEqual(self.client.get('/admin/students').status_code, 200)


if __name__ == '__main__':
    unittest.main()
