import unittest
import os
import sqlite3
import json
import base64
from app import app, DATABASE, get_db

class DecoderAppTests(unittest.TestCase):
    
    def setUp(self):
        # Configure app for testing
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        
        # Ensure database is clean or set up
        # We check database tables exist
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row['name'] for row in cursor.fetchall()]
        self.assertIn('users', tables)
        self.assertIn('quiz_questions', tables)
        self.assertIn('quiz_settings', tables)
        self.assertIn('quiz_attempts', tables)
        self.assertIn('transactions', tables)
        db.close()

    def test_anonymous_redirect(self):
        """Verify that anonymous users are redirected to login."""
        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_user_registration_and_login(self):
        """Verify user registration, duplicate prevention, and login flow."""
        # Use random/unique test phone to avoid database conflicts
        test_phone = "9876543210"
        test_fullname = "Test User"
        test_password = "password123"
        
        # Check database for existing test phone and clean it up
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_phone,))
        db.commit()
        db.close()

        # Register User
        response = self.client.post('/register', data={
            'fullname': test_fullname,
            'email': 'testuser@example.com',
            'email': 'testuser@example.com',
            'password': test_password
        }, follow_redirects=True)
        self.assertIn(b"Account registered successfully", response.data)
        
        # Logout first so registration route is accessible
        self.client.get('/logout')
        
        # Try registering same user (should fail)
        response_dup = self.client.post('/register', data={
            'fullname': test_fullname,
            'email': 'testuser@example.com',
            'email': 'testuser@example.com',
            'password': test_password
        }, follow_redirects=True)
        self.assertIn(b"Phone number is already registered", response_dup.data)

        # Test login with non-existent phone number
        response_bad_phone = self.client.post('/login', data={
            'email': 'bad@example.com'
        }, follow_redirects=True)
        self.assertIn(b"No account found with this email", response_bad_phone.data)

        # Test login with correct phone number
        response_ok = self.client.post('/login', data={
            'email': 'testuser@example.com'
        }, follow_redirects=True)
        self.assertIn(b"Welcome back", response_ok.data)
        self.assertIn(b"Test User", response_ok.data)

    def test_admin_routing_and_secret(self):
        """Verify secret admin authentication and dashboard locking."""
        # Clean up database first
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = '1111111111'")
        db.commit()
        db.close()

        # Register and login a normal user
        self.client.post('/register', data={
            'fullname': 'Normal User',
            'email': 'normal@example.com',
            'password': 'password123'
        })
        # Try to access admin dashboard (should block and redirect)
        response = self.client.get('/admin', follow_redirects=True)
        self.assertIn(b"Secret Admin Key", response.data)
        
        # Log out normal user
        self.client.get('/logout')

        # Clean up database after
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = '1111111111'")
        db.commit()
        db.close()

        # Access admin dashboard directly (should redirect to admin login)
        response = self.client.get('/admin', follow_redirects=True)
        self.assertIn(b"Secret Admin Key", response.data)

        # Try bad key
        response_bad_key = self.client.post('/api/admin/auth_secret', json={
            'secret_key': 'WRONG_KEY'
        }, follow_redirects=True)
        self.assertIn(b"Invalid Secret Key", response_bad_key.data)

        # Try correct secret key
        response_ok = self.client.post('/api/admin/auth_secret', json={
            'secret_key': 'DECODER@2026'
        }, follow_redirects=True)
        self.assertIn(b"Admin authenticated successfully", response_ok.data)
        self.assertIn(b"DECODER Administration", response_ok.data)

        # Verify admin session lets us view admin page
        response_admin = self.client.get('/admin')
        self.assertEqual(response_admin.status_code, 200)
        self.assertIn(b"Active Questions Library", response_admin.data)

    def test_question_crud_and_settings(self):
        """Verify that admin can add, update, and toggle quiz settings."""
        # Authenticate as admin
        self.client.post('/api/admin/auth_secret', json={
            'secret_key': 'DECODER@2026'
        })

        # Add question
        response_add = self.client.post('/admin/questions/add', data={
            'question': 'What is short selling?',
            'option1': 'Buying a stock',
            'option2': 'Selling borrowed shares to buy back cheaper later',
            'option3': 'A type of market order',
            'option4': 'Investing for dividends',
            'correct_answer': '2'
        }, follow_redirects=True)
        self.assertIn(b"Question added successfully", response_add.data)

        # Check DB to get ID
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM quiz_questions WHERE question = 'What is short selling?'")
        row = cursor.fetchone()
        self.assertIsNotNone(row)
        q_id = row['id']

        # Edit Question
        response_edit = self.client.post(f'/admin/questions/edit/{q_id}', data={
            'question': 'What is short selling modified?',
            'option1': 'Opt A',
            'option2': 'Opt B',
            'option3': 'Opt C',
            'option4': 'Opt D',
            'correct_answer': '1'
        }, follow_redirects=True)
        self.assertIn(b"Question updated successfully", response_edit.data)

        # Check DB modification
        cursor.execute(f"SELECT question, correct_answer FROM quiz_questions WHERE id = {q_id}")
        modified_row = cursor.fetchone()
        self.assertEqual(modified_row['question'], 'What is short selling modified?')
        self.assertEqual(modified_row['correct_answer'], 1)

        # Toggle Quiz Active Status
        response_toggle = self.client.post('/admin/quiz/toggle', follow_redirects=True)
        self.assertIn(b"Quiz status updated", response_toggle.data)
        
        # Verify status in database
        cursor.execute("SELECT is_active FROM quiz_settings WHERE id = 1")
        settings_row = cursor.fetchone()
        self.assertIn(settings_row['is_active'], [0, 1])

        # Delete Question
        response_del = self.client.post(f'/admin/questions/delete/{q_id}', follow_redirects=True)
        self.assertIn(b"Question deleted successfully", response_del.data)
        
        # Check DB deletion
        cursor.execute(f"SELECT COUNT(*) as count FROM quiz_questions WHERE id = {q_id}")
        self.assertEqual(cursor.fetchone()['count'], 0)
        db.close()

    def test_bulk_json_import(self):
        """Verify bulk importing questions via a JSON payload."""
        # Authenticate as admin
        self.client.post('/api/admin/auth_secret', json={
            'secret_key': 'DECODER@2026'
        })
        
        # Define JSON questions payload
        import_payload = [
            {
                "question": "Bulk Question 1?",
                "option1": "O1",
                "option2": "O2",
                "option3": "O3",
                "option4": "O4",
                "correct_answer": 3
            },
            {
                "question": "Bulk Question 2?",
                "option1": "O1",
                "option2": "O2",
                "option3": "O3",
                "option4": "O4",
                "correct_answer": 4
            }
        ]
        
        response = self.client.post('/admin/questions/import_json', data={
            'questions_json': json.dumps(import_payload)
        }, follow_redirects=True)
        self.assertIn(b"Successfully imported 2 questions from JSON", response.data)
        
        # Check database
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM quiz_questions WHERE question LIKE 'Bulk Question %'")
        self.assertEqual(cursor.fetchone()['count'], 2)
        
        # Clean up
        cursor.execute("DELETE FROM quiz_questions WHERE question LIKE 'Bulk Question %'")
        db.commit()
        db.close()

    def test_forgot_password(self):
        """Verify forgot password credential validation and reset flow."""
        # Create a user to test password reset
        test_phone = "9555555555"
        test_fullname = "Recovery User"
        test_password = "oldpassword"
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_phone,))
        db.commit()
        db.close()
        
        # Register the user first
        self.client.post('/register', data={
            'fullname': test_fullname,
            'email': 'recovery@example.com',
            'email': 'testuser@example.com',
            'password': test_password
        })
        self.client.get('/logout') # Log out
        
        # Try retrieving with incorrect details
        response_bad = self.client.post('/forgot_password', data={
            'fullname': 'Wrong Name',
            'email': 'testuser@example.com',
            'new_password': 'newpassword123',
            'confirm_password': 'newpassword123'
        }, follow_redirects=True)
        self.assertIn(b"No account matches these details", response_bad.data)
        
        # Try retrieving with mismatched passwords
        response_mismatch = self.client.post('/forgot_password', data={
            'fullname': test_fullname,
            'email': 'testuser@example.com',
            'new_password': 'newpassword123',
            'confirm_password': 'differentpassword'
        }, follow_redirects=True)
        self.assertIn(b"Passwords do not match", response_mismatch.data)
        
        # Try retrieving with correct details
        response_ok = self.client.post('/forgot_password', data={
            'fullname': test_fullname,
            'email': 'testuser@example.com',
            'new_password': 'newpassword123',
            'confirm_password': 'newpassword123'
        }, follow_redirects=True)
        self.assertIn(b"Password reset successfully", response_ok.data)
        
        # Check login works with new password
        response_login = self.client.post('/login', data={
            'email': 'testuser@example.com',
            'password': 'newpassword123'
        }, follow_redirects=True)
        self.assertIn(b"Welcome back", response_login.data)
        
        # Clean up database
        self.client.get('/logout')
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_phone,))
        db.commit()
        db.close()

    def test_google_sign_in(self):
        """Verify that Google Sign-in API successfully registers and logs in users."""
        test_email = "testgoogle@gmail.com"
        test_name = "Google Test User"
        
        # Clean up existing user if any
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_email,))
        db.commit()
        db.close()
        
        # Send Google Sign-In request
        response = self.client.post('/api/auth/google', data=json.dumps({
            'email': test_email,
            'name': test_name
        }), content_type='application/json')
        
        data = json.loads(response.data)
        self.assertTrue(data['success'])
        self.assertIn("Welcome back", data['message'])
        
        # Verify user is logged in (session has user_id)
        with self.client.session_transaction() as sess:
            self.assertIn('user_id', sess)
            self.assertEqual(sess['fullname'], test_name)
            self.assertEqual(sess['phone'], test_email)
            
        # Clean up database
        self.client.get('/logout')
        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_email,))
        db.commit()
        db.close()

    def test_admin_excel_crud(self):
        """Verify the AJAX CRUD routes for user accounts and quiz attempts."""
        # Authenticate as admin
        self.client.post('/api/admin/auth_secret', json={
            'secret_key': 'DECODER@2026'
        })
        
        # 1. Create User
        response_create = self.client.post('/api/admin/users/create')
        self.assertEqual(response_create.status_code, 200)
        data_create = json.loads(response_create.data)
        self.assertTrue(data_create['success'])
        user_id = data_create['user']['id']
        temp_phone = data_create['user']['phone']
        
        # 2. Update User Details (Name, Phone, UPI)
        response_update_name = self.client.post('/api/admin/users/update', data=json.dumps({
            'user_id': user_id,
            'field': 'fullname',
            'value': 'Excel Edited User'
        }), content_type='application/json')
        self.assertTrue(json.loads(response_update_name.data)['success'])
        
        response_update_upi = self.client.post('/api/admin/users/update', data=json.dumps({
            'user_id': user_id,
            'field': 'upi_id',
            'value': 'edited@upi'
        }), content_type='application/json')
        self.assertTrue(json.loads(response_update_upi.data)['success'])
        
        # Verify changes in DB
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT fullname, upi_id FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        self.assertEqual(row['fullname'], 'Excel Edited User')
        self.assertEqual(row['upi_id'], 'edited@upi')
        
        # 3. Create a Mock Attempt for this user and edit/delete it
        cursor.execute(
            "INSERT INTO quiz_attempts (user_id, score, time_taken) VALUES (?, 8, 120)",
            (user_id,)
        )
        db.commit()
        attempt_id = cursor.lastrowid
        db.close()
        
        # Update attempt
        response_update_attempt = self.client.post('/api/admin/attempts/update', data=json.dumps({
            'attempt_id': attempt_id,
            'score': 10,
            'time_taken': 90
        }), content_type='application/json')
        self.assertTrue(json.loads(response_update_attempt.data)['success'])
        
        # Verify attempt update in DB
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT score, time_taken FROM quiz_attempts WHERE id = ?", (attempt_id,))
        row_att = cursor.fetchone()
        self.assertEqual(row_att['score'], 10)
        self.assertEqual(row_att['time_taken'], 90)
        
        # Delete attempt
        response_del_attempt = self.client.post(f'/api/admin/attempts/delete/{attempt_id}')
        self.assertTrue(json.loads(response_del_attempt.data)['success'])
        cursor.execute("SELECT COUNT(*) as count FROM quiz_attempts WHERE id = ?", (attempt_id,))
        self.assertEqual(cursor.fetchone()['count'], 0)
        
        # 4. Delete User (should clean up user)
        response_delete = self.client.post(f'/api/admin/users/delete/{user_id}')
        self.assertEqual(response_delete.status_code, 200)
        self.assertTrue(json.loads(response_delete.data)['success'])
        
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE id = ?", (user_id,))
        self.assertEqual(cursor.fetchone()['count'], 0)
        db.close()

    def test_offline_api_flow(self):
        """Verify api/ping, correct answer obfuscation, and session-less sync submission logic."""
        # 1. Test ping
        res_ping = self.client.get('/api/ping')
        self.assertEqual(res_ping.status_code, 200)
        self.assertEqual(json.loads(res_ping.data)['status'], 'ok')

        # 2. Register & Login test user
        test_phone = "9777777777"
        test_fullname = "Offline Test User"
        test_password = "password123"

        db = get_db()
        cursor = db.cursor()
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_phone,))
        db.commit()
        
        # Add a test question first to guarantee questions exist
        cursor.execute("DELETE FROM quiz_questions WHERE question = 'Test Offline Q?'")
        cursor.execute(
            "INSERT INTO quiz_questions (question, option1, option2, option3, option4, correct_answer) VALUES ('Test Offline Q?', 'A', 'B', 'C', 'D', 3)"
        )
        db.commit()
        cursor.execute("SELECT id FROM quiz_questions WHERE question = 'Test Offline Q?'")
        q_id = cursor.fetchone()['id']
        db.close()

        # Register
        self.client.post('/register', data={
            'fullname': test_fullname,
            'email': 'offline@example.com',
            'email': 'testuser@example.com',
            'password': test_password
        })

        # Ensure quiz settings active
        self.client.post('/api/admin/auth_secret', json={'secret_key': 'DECODER@2026'})
        self.client.post('/admin/quiz/settings', data={'time_limit': '300', 'prize_pool': '500'})
        db = get_db()
        cursor = db.cursor()
        cursor.execute("UPDATE quiz_settings SET is_active = 1 WHERE id = 1")
        db.commit()
        db.close()

        # Log back in as standard user
        self.client.get('/logout')
        self.client.post('/login', data={'email': 'testuser@example.com', 'password': test_password})

        # Start Quiz
        res_start = self.client.post('/api/quiz/start')
        data_start = json.loads(res_start.data)
        self.assertTrue(data_start['success'])
        
        # Verify correct_enc exists
        target_q = None
        for q in data_start['questions']:
            self.assertIn('correct_enc', q)
            if q['id'] == q_id:
                target_q = q
        
        self.assertIsNotNone(target_q)
        
        # Verify correct_enc decrypts to correct answer index (3)
        enc_val = target_q['correct_enc']
        decoded = base64.b64decode(enc_val.encode('utf-8')).decode('utf-8')
        decrypted_index = (int(decoded) - 7) // 13
        self.assertEqual(decrypted_index, 3)

        # Clear session quiz start times to simulate total offline page reload / session loss
        with self.client.session_transaction() as sess:
            sess.pop("quiz_start_time", None)
            sess.pop("quiz_questions_sent", None)

        # Submit session-less payload (offline sync payload)
        sync_payload = {
            'answers': {str(q_id): 3},
            'time_taken': 85
        }
        res_submit = self.client.post('/api/quiz/submit', data=json.dumps(sync_payload), content_type='application/json')
        self.assertEqual(res_submit.status_code, 200)
        data_submit = json.loads(res_submit.data)
        self.assertTrue(data_submit['success'])
        self.assertEqual(data_submit['score'], 1)
        self.assertEqual(data_submit['time_taken'], 85)

        # Verify entry in database
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM quiz_attempts WHERE score = 1 AND time_taken = 85")
        attempt_row = cursor.fetchone()
        self.assertIsNotNone(attempt_row)

        # Cleanup
        cursor.execute("DELETE FROM quiz_attempts WHERE id = ?", (attempt_row['id'],))
        cursor.execute("DELETE FROM users WHERE phone = ?", (test_phone,))
        cursor.execute("DELETE FROM quiz_questions WHERE id = ?", (q_id,))
        db.commit()
        db.close()


    def test_live_quiz_toggle_and_persistence(self):
        """Verify admin can toggle quiz and users can only access it while LIVE, with state preserved."""
        # 1. Setup Admin and User
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute("DELETE FROM users WHERE phone IN ('9999999998', '9999999999')")
            
            # Insert admin
            cursor.execute("INSERT INTO users (fullname, phone, password, role) VALUES ('Admin', '9999999999', 'dummy', 'admin')")
            admin_id = cursor.lastrowid
            # Insert user
            cursor.execute("INSERT INTO users (fullname, phone, password, role) VALUES ('User', '9999999998', 'dummy', 'user')")
            user_id = cursor.lastrowid
            
            # Reset quiz settings
            cursor.execute("UPDATE quiz_settings SET is_active = 0 WHERE id = 1")
            db.commit()
        finally:
            db.close()

        # Login User
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['role'] = 'user'

        # User tries to access quiz while CLOSED -> Should be rejected
        resp_closed = self.client.post('/api/quiz/start', headers={'X-CSRFToken': 'dummy'})
        self.assertEqual(resp_closed.status_code, 400)
        self.assertIn(b"Quiz is not active", resp_closed.data)

        # Login Admin
        with self.client.session_transaction() as sess:
            sess['user_id'] = admin_id
            sess['role'] = 'admin'
            sess['admin'] = True

        # Admin starts the quiz
        self.client.post('/admin/quiz/toggle')
        
        # Verify DB says it's active
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute("SELECT is_active, started_at FROM quiz_settings WHERE id = 1")
            settings = cursor.fetchone()
            self.assertEqual(settings['is_active'], 1)
            self.assertIsNotNone(settings['started_at'])
        finally:
            db.close()

        # Login User again
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['role'] = 'user'

        # User starts quiz while LIVE
        resp_start = self.client.post('/api/quiz/start', headers={'X-CSRFToken': 'dummy'})
        self.assertEqual(resp_start.status_code, 200)
        data = json.loads(resp_start.data)
        self.assertTrue(data['success'])
        
        # Check DB for progress
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute("SELECT * FROM quiz_progress WHERE user_id = ?", (user_id,))
            progress = cursor.fetchone()
            self.assertIsNotNone(progress)
            self.assertEqual(progress['quiz_status'], 'in_progress')
        finally:
            db.close()
        
        # Simulate User answering a question (save progress)
        self.client.post('/api/quiz/save_progress', json={
            "answers": {"1": 2},
            "current_question": 1,
            "remaining_time": 250
        }, headers={'X-CSRFToken': 'dummy'})
        
        # User refreshes/restarts the quiz
        resp_resume = self.client.post('/api/quiz/start', headers={'X-CSRFToken': 'dummy'})
        data_resume = json.loads(resp_resume.data)
        self.assertEqual(data_resume['saved_answers'], {"1": 2})
        self.assertEqual(data_resume['saved_question_index'], 1)
        self.assertEqual(data_resume['time_limit'], 250)
        
        # Login Admin to stop quiz
        with self.client.session_transaction() as sess:
            sess['user_id'] = admin_id
            sess['role'] = 'admin'
            sess['admin'] = True

        # Admin stops the quiz
        self.client.post('/admin/quiz/toggle')
        
        # Verify DB says it's stopped and user progress is locked
        db = get_db()
        try:
            cursor = db.cursor()
            cursor.execute("SELECT is_active, stopped_at FROM quiz_settings WHERE id = 1")
            settings = cursor.fetchone()
            self.assertEqual(settings['is_active'], 0)
            self.assertIsNotNone(settings['stopped_at'])
            
            cursor.execute("SELECT quiz_status FROM quiz_progress WHERE user_id = ?", (user_id,))
            progress_after = cursor.fetchone()
            self.assertEqual(progress_after['quiz_status'], 'completed')  # Submissions locked
        finally:
            db.close()

if __name__ == '__main__':
    unittest.main()

