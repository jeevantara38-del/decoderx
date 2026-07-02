import os
import sqlite3
try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None
import random
import string
import csv
import io
import time
import uuid
import re
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from functools import wraps
import logging
from flask import (
    Flask, render_template, request, jsonify, session, 
    redirect, url_for, flash, stream_with_context, Response, send_file, g, has_app_context
)
import firebase_admin
from firebase_admin import auth as firebase_auth

try:
    if not firebase_admin._apps:
        firebase_admin.initialize_app()
except Exception as e:
    print("Firebase initialization failed:", e)

from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Regexp
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# Real-time Pusher
import pusher
# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from flask_wtf.csrf import CSRFProtect
from flask_compress import Compress

app = Flask(__name__)
# The secret key will be overridden by the .env file value after load_env() is called below.
app.secret_key = "FALLBACK_SECRET_KEY"
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('VERCEL'))

csrf = CSRFProtect(app)
Compress(app)

# Load environment variables from .env if it exists
def load_env():
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    if "=" in line:
                        key, val = line.split("=", 1)
                        os.environ[key.strip()] = val.strip()

load_env()

# Update secret key if provided in .env
if os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY"):
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.environ.get("SECRET_KEY")

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

# Pusher Configuration for Real-time Updates
PUSHER_APP_ID = os.environ.get("PUSHER_APP_ID") or os.environ.get("PUSHER_ID")
PUSHER_KEY = os.environ.get("PUSHER_KEY")
PUSHER_SECRET = os.environ.get("PUSHER_SECRET")
PUSHER_CLUSTER = os.environ.get("PUSHER_CLUSTER")

pusher_client = None
if PUSHER_APP_ID and PUSHER_KEY and PUSHER_SECRET and PUSHER_CLUSTER:
    pusher_client = pusher.Pusher(
        app_id=PUSHER_APP_ID,
        key=PUSHER_KEY,
        secret=PUSHER_SECRET,
        cluster=PUSHER_CLUSTER,
        ssl=True
    )

def trigger_pusher_event(channel, event_name, data):
    if pusher_client:
        try:
            pusher_client.trigger(channel, event_name, data)
        except Exception as e:
            logger.error(f"Pusher error: {e}")

import urllib.request
import urllib.parse
import json

import requests

def verify_google_token(token):
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            aud = data.get("aud")
            azp = data.get("azp")
            if aud == GOOGLE_CLIENT_ID or azp == GOOGLE_CLIENT_ID:
                return data
            else:
                print("Token audience mismatch:", aud)
        else:
            print("Token verification failed with status:", response.status_code, response.text)
    except Exception as e:
        print("Google token verification exception:", e)
    return None

def exchange_code_for_token(code):
    token_url = "https://oauth2.googleapis.com/token"
    redirect_uri = request.base_url
    if os.environ.get("VERCEL"):
        redirect_uri = redirect_uri.replace("http://", "https://")
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    try:
        response = requests.post(token_url, data=data, timeout=10)
        if response.status_code == 200:
            res_data = response.json()
            return res_data.get("id_token")
        else:
            print("Failed to exchange auth code for token. Status:", response.status_code, response.text)
    except Exception as e:
        print("Failed to exchange auth code for token exception:", e)
    return None

import shutil

if os.environ.get("VERCEL"):
    DATABASE = "/tmp/users.db"
    if not os.path.exists(DATABASE):
        src_db = os.path.join(app.root_path, "users.db")
        if os.path.exists(src_db):
            try:
                shutil.copyfile(src_db, DATABASE)
            except Exception as e:
                logger.error(f"Failed to copy bundled DB to /tmp: {e}")
else:
    DATABASE = os.path.join(app.root_path, "users.db")


if psycopg2:
    IntegrityError = (sqlite3.IntegrityError, psycopg2.IntegrityError)
else:
    IntegrityError = sqlite3.IntegrityError

class CursorWrapper:
    def __init__(self, cursor, is_postgres=False):
        self._cursor = cursor
        self._is_postgres = is_postgres
        
    def _translate_query(self, query):
        if self._is_postgres:
            return query.replace('?', '%s')
        return query
        
    def execute(self, query, params=None):
        query = self._translate_query(query)
        if params is not None:
            return self._cursor.execute(query, params)
        return self._cursor.execute(query)
        
    def fetchone(self):
        return self._cursor.fetchone()
        
    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size=None):
        return self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        
    def close(self):
        self._cursor.close()
        
    @property
    def rowcount(self):
        return self._cursor.rowcount
        
    @property
    def lastrowid(self):
        if self._is_postgres:
            self._cursor.execute("SELECT LASTVAL()")
            res = self._cursor.fetchone()
            return res[0] if res else None
        return getattr(self._cursor, 'lastrowid', None)

    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

class DBWrapper:
    def __init__(self, conn, is_postgres=False):
        self._conn = conn
        self._is_postgres = is_postgres
        
    def cursor(self):
        if self._is_postgres:
            cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        else:
            cur = self._conn.cursor()
        return CursorWrapper(cur, self._is_postgres)
        
    def commit(self):
        self._conn.commit()
        
    def rollback(self):
        self._conn.rollback()
        
    def close(self):
        self._conn.close()

    def execute(self, query, params=None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur
        
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        self.close()

def get_db():
    postgres_url = os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get("PRISMA_DATABASE_URL")
    
    if has_app_context():
        db = getattr(g, '_database', None)
        if db is None:
            if postgres_url and psycopg2:
                conn = psycopg2.connect(postgres_url)
                conn.autocommit = False
                db = g._database = DBWrapper(conn, is_postgres=True)
            else:
                conn = sqlite3.connect(DATABASE, timeout=30.0)
                try:
                    conn.execute("PRAGMA journal_mode=WAL;")
                except Exception:
                    pass
                conn.row_factory = sqlite3.Row
                db = g._database = DBWrapper(conn, is_postgres=False)
        return db
    else:
        if postgres_url and psycopg2:
            conn = psycopg2.connect(postgres_url)
            conn.autocommit = False
            return DBWrapper(conn, is_postgres=True)
        else:
            conn = sqlite3.connect(DATABASE, timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except Exception:
                pass
            conn.row_factory = sqlite3.Row
            return DBWrapper(conn, is_postgres=False)

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.before_request
def make_session_permanent():
    session.permanent = True

def init_db():
    is_pg = bool(os.environ.get("POSTGRES_URL") or os.environ.get("DATABASE_URL") or os.environ.get("PRISMA_DATABASE_URL"))
    pk_type = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    ts_type = "TIMESTAMP" if is_pg else "DATETIME"
    
    with get_db() as db:
        cursor = db.cursor()
        
        # Create users table
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS users (
                id {pk_type},
                fullname TEXT NOT NULL,
                email TEXT UNIQUE,
                phone TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                upi_id TEXT DEFAULT NULL,
                payment_number TEXT DEFAULT NULL,
                role TEXT DEFAULT 'user',
                google_id TEXT,
                profile_image TEXT,
                phone_number TEXT
            )
        ''')
        
        # Create quiz_questions table
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS quiz_questions (
            id {pk_type},
            question TEXT NOT NULL,
            option1 TEXT NOT NULL,
            option2 TEXT NOT NULL,
            option3 TEXT NOT NULL,
            option4 TEXT NOT NULL,
            correct_answer INTEGER NOT NULL
        )
        """)
        
        # Create quiz_settings table
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS quiz_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            is_active INTEGER DEFAULT 0,
            time_limit INTEGER DEFAULT 300,
            prize_pool REAL DEFAULT 1000.00,
            quiz_password TEXT DEFAULT '',
            allow_multiple_attempts INTEGER DEFAULT 0,
            admin_message TEXT DEFAULT ''
        )
        """)
        db.commit()
        
        def safe_alter(query):
            try:
                cursor.execute(query)
                db.commit()
            except Exception:
                db.rollback()
                
        safe_alter("ALTER TABLE quiz_settings ADD COLUMN quiz_password TEXT DEFAULT ''")
        safe_alter("ALTER TABLE quiz_settings ADD COLUMN allow_multiple_attempts INTEGER DEFAULT 0")
        safe_alter("ALTER TABLE quiz_settings ADD COLUMN admin_message TEXT DEFAULT ''")
        safe_alter("ALTER TABLE users ADD COLUMN google_id TEXT")
        safe_alter("ALTER TABLE users ADD COLUMN profile_image TEXT")
        safe_alter("ALTER TABLE users ADD COLUMN phone_number TEXT UNIQUE")
        
        safe_alter(f"ALTER TABLE quiz_settings ADD COLUMN started_at {ts_type}")
        safe_alter(f"ALTER TABLE quiz_settings ADD COLUMN stopped_at {ts_type}")
        safe_alter(f"ALTER TABLE quiz_settings ADD COLUMN end_time {ts_type}")
        safe_alter(f"ALTER TABLE quiz_settings ADD COLUMN start_time {ts_type}")
        safe_alter("ALTER TABLE quiz_settings ADD COLUMN duration_days INTEGER")
        safe_alter("ALTER TABLE quiz_settings ADD COLUMN stopped_by_admin INTEGER DEFAULT 0")
        
        # Create quiz_progress table
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS quiz_progress (
            id {pk_type},
            user_id INTEGER NOT NULL UNIQUE,
            current_question INTEGER DEFAULT 0,
            selected_answers TEXT DEFAULT '{{}}',
            remaining_time INTEGER,
            total_time INTEGER,
            quiz_questions TEXT,
            quiz_status TEXT DEFAULT 'in_progress',
            started_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        db.commit()
        
        # Migrate: add total_time column if missing
        safe_alter("ALTER TABLE quiz_progress ADD COLUMN total_time INTEGER")
        
        # Ensure default row in settings exists
        cursor.execute("""
        INSERT INTO quiz_settings (id, is_active, time_limit, prize_pool)
        VALUES (1, 0, 300, 1000.00)
        ON CONFLICT(id) DO NOTHING
        """)
        
        # Create quiz_attempts table
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS quiz_attempts (
            id {pk_type},
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL,
            time_taken INTEGER NOT NULL,
            warnings_count INTEGER DEFAULT 0,
            submitted_at {ts_type} DEFAULT CURRENT_TIMESTAMP,
            is_disqualified INTEGER DEFAULT 0,
            disqualification_reason TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        
        # Ensure migration: Add warnings_count to quiz_attempts if it doesn't exist
        try:
            cursor.execute("SELECT warnings_count FROM quiz_attempts LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE quiz_attempts ADD COLUMN warnings_count INTEGER DEFAULT 0")
            
        try:
            cursor.execute("SELECT is_disqualified FROM quiz_attempts LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE quiz_attempts ADD COLUMN is_disqualified INTEGER DEFAULT 0")
            
        try:
            cursor.execute("SELECT disqualification_reason FROM quiz_attempts LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE quiz_attempts ADD COLUMN disqualification_reason TEXT")
            
        # Create transactions table
        cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS transactions (
            id {pk_type},
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'Pending',
            date {ts_type} DEFAULT CURRENT_TIMESTAMP,
            utr_id TEXT DEFAULT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """)
        
        # Create indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_quiz_attempts_user_id ON quiz_attempts(user_id);")
        
        # Performance Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_qa_perf ON quiz_attempts(score DESC, time_taken ASC, submitted_at ASC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date DESC);")
        
        # Seed default admin user if none exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] == 0:
            admin_pass = generate_password_hash("DECODER@2026")
            # Clear any conflicting standard user with phone 9999999999 first
            cursor.execute("DELETE FROM users WHERE phone = '9999999999'")
            cursor.execute(
                "INSERT INTO users (fullname, phone, password, role) VALUES ('Admin Console', '9999999999', ?, 'admin')",
                (admin_pass,)
            )

        # Seed Jeevantara admin user if none exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE email = 'jeevantara38@gmail.com'")
        if cursor.fetchone()[0] == 0:
            # Delete if the dummy phone number is already taken to avoid unique constraint error
            cursor.execute("DELETE FROM users WHERE phone = '0000000000'")
            user_pass = generate_password_hash("google_auth_dummy_pass")
            cursor.execute(
                "INSERT INTO users (fullname, email, phone, password, role) VALUES ('Jeevantara Admin', 'jeevantara38@gmail.com', '0000000000', ?, 'admin')",
                (user_pass,)
            )

        # Seed Jeevan Kumar user if none exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE phone = 'jeevan@gmail.com'")
        if cursor.fetchone()[0] == 0:
            user_pass = generate_password_hash("google_auth_dummy_pass")
            cursor.execute(
                "INSERT INTO users (fullname, phone, password, role) VALUES ('Jeevan Kumar', 'jeevan@gmail.com', ?, 'user')",
                (user_pass,)
            )

        # Seed Demo Trader user if none exists
        cursor.execute("SELECT COUNT(*) FROM users WHERE phone = 'demotrader@decoder.com'")
        if cursor.fetchone()[0] == 0:
            user_pass = generate_password_hash("google_auth_dummy_pass")
            cursor.execute(
                "INSERT INTO users (fullname, phone, password, role) VALUES ('Demo Trader', 'demotrader@decoder.com', ?, 'user')",
                (user_pass,)
            )
# Initialize DB when import happens
try:
    init_db()
except Exception as e:
    logger.error(f"Failed to initialize database on startup: {e}")

@app.context_processor
def inject_pusher():
    return {
        'PUSHER_KEY': PUSHER_KEY,
        'PUSHER_CLUSTER': PUSHER_CLUSTER
    }

# Decorators for auth check
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to access this page.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("admin") or session.get("role") != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function

# Standard Routes
@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    
    if request.method == "POST":
        fullname = request.form.get("fullname", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        
        if not email or not password:
            flash("Email and password are required.", "danger")
            return redirect(url_for("register"))
            
        import uuid
        dummy_phone = f"PENDING_{uuid.uuid4().hex[:10]}"
        hashed_password = generate_password_hash(password)
        
        db = get_db()
        cursor = db.cursor()
        
        try:
            cursor.execute(
                "INSERT INTO users (fullname, email, phone, password, role) VALUES (?, ?, ?, ?, 'user')",
                (fullname, email, dummy_phone, hashed_password)
            )
            db.commit()
            
            cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
            user = cursor.fetchone()
            
            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["phone"] = user["phone"]
            session["role"] = user["role"]
            flash(f"Account created! Welcome, {user['fullname']}!", "success")
            return redirect(url_for("dashboard"))
        except IntegrityError:
            flash("Email is already registered. Please login.", "danger")
            return redirect(url_for("register"))
            
    return render_template("register.html", google_client_id=GOOGLE_CLIENT_ID)

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        
        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return redirect(url_for("login"))
            
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        
        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["fullname"] = user["fullname"]
            session["phone"] = user["phone"]
            session["role"] = user["role"]
            if user["role"] == "admin":
                session["admin"] = True
            flash(f"Welcome back, {user['fullname']}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))
            
    return render_template("login.html", google_client_id=GOOGLE_CLIENT_ID)

@app.route("/complete_profile")
def complete_profile():
    if "user_id" not in session:
        return redirect(url_for("login"))
    phone = session.get("phone", "")
    if not phone.startswith("PENDING_") and not phone.startswith("GOOG_"):
        return redirect(url_for("dashboard"))
    return render_template("complete_profile.html")

@app.route("/api/user/complete_profile", methods=["POST"])
def api_complete_profile():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json() or {}
    phone = data.get("phone", "").strip()
    
    if not phone or len(phone) < 10:
        return jsonify({"success": False, "message": "Valid phone number required."}), 400
        
    normalized_phone = phone
    if normalized_phone.startswith("+91"):
        normalized_phone = normalized_phone[3:]
    elif normalized_phone.startswith("91") and len(normalized_phone) > 10:
        normalized_phone = normalized_phone[2:]
        
    db = get_db()
    cursor = db.cursor()
    
    # Check for duplicate
    cursor.execute("SELECT id FROM users WHERE phone = ? AND id != ?", (normalized_phone, session["user_id"]))
    if cursor.fetchone():
        return jsonify({"success": False, "message": "Phone number is already associated with another account."}), 400
        
    try:
        cursor.execute("UPDATE users SET phone = ? WHERE id = ?", (normalized_phone, session["user_id"]))
        db.commit()
        session["phone"] = normalized_phone
        session.modified = True
        return jsonify({"success": True})
    except IntegrityError:
        return jsonify({"success": False, "message": "Failed to update phone number."}), 400

@app.route("/api/user/update_name", methods=["POST"])
@login_required
def api_update_name():
    data = request.get_json() or {}
    fullname = data.get("fullname", "").strip()
    
    if not fullname or len(fullname) < 2 or len(fullname) > 50:
        return jsonify({"success": False, "message": "Name must be between 2 and 50 characters."}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    try:
        cursor.execute("UPDATE users SET fullname = ? WHERE id = ?", (fullname, session["user_id"]))
        db.commit()
        session["fullname"] = fullname
        session.modified = True
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 400

@app.route("/api/auth/phone", methods=["POST"])
def api_auth_phone():
    """Handle Firebase Phone OTP authentication for both login and registration."""
    data = request.get_json() or {}
    id_token = data.get("idToken")
    fullname = data.get("fullname", "").strip()
    action = data.get("action", "login")  # 'login' or 'register'
    
    if not id_token:
        return jsonify({"success": False, "message": "Missing authentication token."}), 400
    
    # Verify Firebase ID Token
    try:
        decoded_token = firebase_auth.verify_id_token(id_token)
        phone_number = decoded_token.get("phone_number")
        
        if not phone_number:
            return jsonify({"success": False, "message": "Phone number not found in token."}), 400
        
        # Normalize: strip leading +91 for storage, keep the raw digits
        normalized_phone = phone_number
        if normalized_phone.startswith("+91"):
            normalized_phone = normalized_phone[3:]
        elif normalized_phone.startswith("91") and len(normalized_phone) > 10:
            normalized_phone = normalized_phone[2:]
        
    except firebase_admin.exceptions.FirebaseError as e:
        return jsonify({"success": False, "message": f"Token verification failed: {str(e)}"}), 400
    except Exception as e:
        return jsonify({"success": False, "message": f"Authentication error: {str(e)}"}), 400
    
    db = get_db()
    cursor = db.cursor()
    
    # Check if user exists
    cursor.execute("SELECT * FROM users WHERE phone = ?", (normalized_phone,))
    user = cursor.fetchone()
    
    if action == "register":
        if user:
            return jsonify({"success": False, "message": "This phone number is already registered. Please login instead."}), 400
        
        if not fullname or len(fullname) < 2 or len(fullname) > 50:
            return jsonify({"success": False, "message": "Please provide a valid name (between 2 and 50 characters)."}), 400
        
        # Create user
        hashed_password = generate_password_hash("firebase_otp_verified")
        try:
            cursor.execute(
                "INSERT INTO users (fullname, phone, password, role) VALUES (?, ?, ?, 'user')",
                (fullname, normalized_phone, hashed_password)
            )
            db.commit()
            cursor.execute("SELECT * FROM users WHERE phone = ?", (normalized_phone,))
            user = cursor.fetchone()
        except IntegrityError:
            return jsonify({"success": False, "message": "Registration failed. Phone may already be registered."}), 400
    
    elif action == "login":
        if not user:
            return jsonify({"success": False, "message": "No account found with this phone number. Please register first.", "needsRegister": True}), 404
    
    # Set session
    session["user_id"] = user["id"]
    session["fullname"] = user["fullname"]
    session["phone"] = user["phone"]
    session["role"] = user["role"]
    
    if user["role"] == "admin":
        session["admin"] = True
    
    msg = f"Welcome back, {user['fullname']}!" if action == "login" else f"Account created! Welcome, {user['fullname']}!"
    return jsonify({"success": True, "message": msg})

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/google/login")
def google_login():
    import secrets
    import urllib.parse
    redirect_uri = url_for("google_callback", _external=True)
    if os.environ.get("VERCEL"):
        redirect_uri = redirect_uri.replace("http://", "https://")
    state = secrets.token_urlsafe(16)
    session['oauth_state'] = state
    
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account"
    }
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)
    return redirect(url)

@app.route("/google/callback")
def google_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    
    if not code:
        flash("Google Sign-In failed or was cancelled.", "danger")
        return redirect(url_for("login"))
        
    token = exchange_code_for_token(code)
    if not token:
        flash("Failed to exchange token with Google.", "danger")
        return redirect(url_for("login"))
        
    id_info = verify_google_token(token)
    if not id_info:
        flash("Failed to verify Google token.", "danger")
        return redirect(url_for("login"))
        
    email = id_info.get("email")
    name = id_info.get("name", "Google User")
    google_id = id_info.get("sub")
    profile_image = id_info.get("picture", "")
    
    db = get_db()
    cursor = db.cursor()
    
    # Check if user exists by google_id or email
    cursor.execute("SELECT * FROM users WHERE google_id = ? OR email = ?", (google_id, email))
    user = cursor.fetchone()
    
    if not user:
        # Create new user
        import uuid
        import secrets
        dummy_phone = f"GOOG_{uuid.uuid4().hex[:10]}"
        dummy_password = generate_password_hash(secrets.token_urlsafe(16))
        role = "admin" if email and email.lower() == "jeevantara38@gmail.com" else "user"
        
        try:
            cursor.execute(
                "INSERT INTO users (fullname, email, phone, password, role, google_id, profile_image) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, email, dummy_phone, dummy_password, role, google_id, profile_image)
            )
            db.commit()
            cursor.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
            user = cursor.fetchone()
        except Exception as e:
            print("Failed to auto-create Google user:", e)
            flash("Error creating account. Please try again.", "danger")
            return redirect(url_for("login"))
    else:
        # Update google_id and profile_image if missing
        if not user["google_id"] or user["profile_image"] != profile_image:
            cursor.execute("UPDATE users SET google_id = ?, profile_image = ? WHERE id = ?", (google_id, profile_image, user["id"]))
            db.commit()
            
    session["user_id"] = user["id"]
    session["fullname"] = user["fullname"]
    session["phone"] = user["phone"]
    session["role"] = user["role"]
    session["profile_image"] = profile_image
    
    if user["role"] == "admin":
        session["admin"] = True
        
    flash(f"Logged in successfully via Google as {user['fullname']}!", "success")
    return redirect(url_for("dashboard"))

@app.route("/api/auth/verify_email_step", methods=["POST"])
def verify_email_step():
    data = request.get_json()
    token = data.get("credential")
    access_token = data.get("access_token")
    simulated_email = data.get("email") # For fallback
    
    email = None
    if token:
        id_info = verify_google_token(token)
        if id_info:
            email = id_info.get("email")
    elif access_token:
        import urllib.request
        import urllib.parse
        import json
        try:
            userinfo_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={urllib.parse.quote(access_token)}"
            req = urllib.request.Request(userinfo_url)
            with urllib.request.urlopen(req) as response:
                user_data = json.loads(response.read().decode())
                email = user_data.get("email")
        except Exception as e:
            print("Verify email step access token error:", e)
    elif simulated_email:
        email = simulated_email
        
    if email:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ? OR phone = ?", (email, email))
        if cursor.fetchone():
            return jsonify({"success": False, "message": "Email is already registered. Please login."})
        return jsonify({"success": True, "email": email})
        
    return jsonify({"success": False, "message": "Verification failed. Invalid token."})

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
        
    if request.method == "POST":
        fullname = request.form.get("fullname").strip()
        phone = request.form.get("phone").strip()
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        if not fullname or not phone or not new_password or not confirm_password:
            flash("All fields are required.", "danger")
            return redirect(url_for("forgot_password"))
            
        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect(url_for("forgot_password"))
            
        db = get_db()
        cursor = db.cursor()
        
        # Verify if user exists with this fullname AND phone
        cursor.execute("SELECT * FROM users WHERE fullname = ? AND phone = ?", (fullname, phone))
        user = cursor.fetchone()
        
        if not user:
            flash("No account matches these details.", "danger")
            return redirect(url_for("forgot_password"))
            
        # Update password
        hashed_password = generate_password_hash(new_password)
        cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hashed_password, user["id"]))
        db.commit()
        
        flash("Password reset successfully! Please log in with your new credentials.", "success")
        return redirect(url_for("login"))
        
    return render_template("forgot_password.html")

@app.context_processor
def inject_google_client_id():
    return {
        "google_client_id": os.environ.get("GOOGLE_CLIENT_ID", "YOUR_GOOGLE_CLIENT_ID.apps.googleusercontent.com"),
        "pusher_key": os.environ.get("PUSHER_KEY", ""),
        "pusher_cluster": os.environ.get("PUSHER_CLUSTER", "")
    }

@app.route("/api/auth/google", methods=["POST"])
def api_auth_google():
    data = request.get_json() or {}
    credential = data.get("credential")
    access_token = data.get("access_token")
    
    email = None
    name = None
    
    import urllib.request
    import urllib.parse
    import json

    if credential:
        # Verify Google JWT token using Google's tokeninfo endpoint
        try:
            tokeninfo_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={urllib.parse.quote(credential)}"
            req = urllib.request.Request(tokeninfo_url)
            with urllib.request.urlopen(req) as response:
                token_data = json.loads(response.read().decode())
                
            # Verify issuer
            if token_data.get("iss") not in ["accounts.google.com", "https://accounts.google.com"]:
                return jsonify({"success": False, "message": "Invalid token issuer."}), 400
                
            # Retrieve profile details
            email = token_data.get("email")
            name = token_data.get("name")
            
            if not email or not name:
                return jsonify({"success": False, "message": "Failed to retrieve Google profile information."}), 400
                
        except Exception as e:
            return jsonify({"success": False, "message": f"Token verification failed: {str(e)}"}), 400
    elif access_token:
        # Verify using access token via UserInfo endpoint
        try:
            userinfo_url = f"https://www.googleapis.com/oauth2/v3/userinfo?access_token={urllib.parse.quote(access_token)}"
            req = urllib.request.Request(userinfo_url)
            with urllib.request.urlopen(req) as response:
                user_data = json.loads(response.read().decode())
            
            email = user_data.get("email")
            name = user_data.get("name")
            
            if not email or not name:
                return jsonify({"success": False, "message": "Failed to retrieve Google profile information from access token."}), 400
        except Exception as e:
            return jsonify({"success": False, "message": f"Access token verification failed: {str(e)}"}), 400
    else:
        # Fallback to mock/demo sign-in details if credential is not provided
        email = data.get("email")
        name = data.get("name")
        
        if not email or not name:
            return jsonify({"success": False, "message": "Missing credentials."}), 400
            
    db = get_db()
    cursor = db.cursor()
    
    # Determine role based on email
    role = "admin" if email and email.lower() == "jeevantara38@gmail.com" else "user"

    # Check if user with this email (stored in phone column) exists
    cursor.execute("SELECT * FROM users WHERE phone = ?", (email,))
    user = cursor.fetchone()
    
    if not user:
        # Create a new user for Google Sign-In
        hashed_password = generate_password_hash("google_auth_dummy_pass")
        try:
            cursor.execute(
                "INSERT INTO users (fullname, phone, password, role) VALUES (?, ?, ?, ?)",
                (name, email, hashed_password, role)
            )
            db.commit()
            cursor.execute("SELECT * FROM users WHERE phone = ?", (email,))
            user = cursor.fetchone()
        except IntegrityError:
            return jsonify({"success": False, "message": "Registration failed."}), 400
    else:
        # Auto-upgrade if needed
        if role == "admin" and user["role"] != "admin":
            cursor.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (email,))
            db.commit()
            cursor.execute("SELECT * FROM users WHERE phone = ?", (email,))
            user = cursor.fetchone()
            
    # Set user session
    session["user_id"] = user["id"]
    session["fullname"] = user["fullname"]
    session["phone"] = user["phone"]
    session["role"] = user["role"]
    
    if user["role"] == "admin":
        session["admin"] = True
        
    return jsonify({"success": True, "message": f"Welcome back, {user['fullname']}!"})

@app.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    cursor = db.cursor()
    
    # Check if user needs phone verification (has attempt but no phone_number)
    try:
        cursor.execute("SELECT phone_number FROM users WHERE id = ?", (session["user_id"],))
        user_row = cursor.fetchone()
        if not user_row or not user_row["phone_number"]:
            cursor.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id = ?", (session["user_id"],))
            if cursor.fetchone()[0] > 0:
                return redirect(url_for("reward_verification"))
    except Exception:
        db.rollback()
        pass  # phone_number column may not exist yet, skip verification check
            
    # Get user profile info
    cursor.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],))
    user_info = cursor.fetchone()
    
    if user_info is None:
        session.clear()
        flash("Your session has expired or the database was reset. Please log in or register again.", "warning")
        return redirect(url_for("login"))
    
    # Get current quiz settings
    cursor.execute("SELECT * FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    
    # Get user's attempts
    cursor.execute("""
        SELECT * FROM quiz_attempts
        WHERE user_id = ?
        ORDER BY submitted_at DESC
    """, (session["user_id"],))
    attempts = cursor.fetchall()
    
    # Check if user already attempted the active quiz (if active)
    has_attempted_active = False
    if settings and settings["is_active"] == 1:
        # To make it secure, we can check if they have any attempt. For simplicity, since there is only one active quiz at a time:
        cursor.execute("SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?", (session["user_id"],))
        has_attempted_active = cursor.fetchone()["count"] > 0
    
    # Get Leaderboard: best attempt per user, ordered by score DESC, time_taken ASC, submitted_at ASC
    cursor.execute("""
        SELECT u.id as user_id, u.fullname, u.phone_number, MAX(qa.score) as top_score, MIN(qa.time_taken) as best_time, MIN(qa.submitted_at) as submitted_at
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        WHERE u.role != 'admin' AND qa.is_disqualified = 0
        GROUP BY u.id, u.fullname, u.phone
        ORDER BY top_score DESC, best_time ASC, submitted_at ASC
        LIMIT 10
    """)
    leaderboard = cursor.fetchall()
    
    # Get User's Reward/Transaction History
    cursor.execute("""
        SELECT * FROM transactions
        WHERE user_id = ?
        ORDER BY date DESC
    """, (session["user_id"],))
    transactions = cursor.fetchall()
    
    # Total earnings
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions
        WHERE user_id = ? AND status = 'Paid'
    """, (session["user_id"],))
    total_earnings = cursor.fetchone()["total"] or 0.0
    
    # Check if the user has any pending rewards that need payment details
    needs_claim = False
    pending_reward = None
    if user_info["role"] != "admin":
        cursor.execute("""
            SELECT id, amount FROM transactions
            WHERE user_id = ? AND status = 'Pending'
            ORDER BY date DESC
            LIMIT 1
        """, (session["user_id"],))
        pending_tx = cursor.fetchone()
        if pending_tx and not user_info["payment_number"]:
            needs_claim = True
            pending_reward = {"id": pending_tx["id"], "amount": pending_tx["amount"]}
    
    return render_template(
        "dashboard.html",
        user=user_info,
        settings=settings,
        attempts=attempts,
        has_attempted_active=has_attempted_active,
        leaderboard=leaderboard,
        transactions=transactions,
        total_earnings=total_earnings,
        needs_claim=needs_claim,
        pending_reward=pending_reward
    )

@app.route("/leaderboard")
@login_required
def leaderboard_page():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.id as user_id, u.fullname, u.phone_number, MAX(qa.score) as top_score, MIN(qa.time_taken) as best_time, MIN(qa.submitted_at) as submitted_at
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        WHERE u.role != 'admin' AND qa.is_disqualified = 0
        GROUP BY u.id, u.fullname, u.phone
        ORDER BY top_score DESC, best_time ASC, submitted_at ASC
        LIMIT 25
    """)
    leaderboard = cursor.fetchall()
    return render_template("leaderboard.html", leaderboard=leaderboard)

@app.route("/api/leaderboard/data")
@login_required
def api_leaderboard_data():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.id as user_id, u.fullname, u.profile_image, MAX(qa.score) as top_score, MIN(qa.time_taken) as best_time, MIN(qa.submitted_at) as submitted_at
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        WHERE u.role != 'admin' AND qa.is_disqualified = 0
        GROUP BY u.id, u.fullname, u.phone_number
        ORDER BY top_score DESC, best_time ASC, submitted_at ASC
        LIMIT 25
    """)
    leaderboard = cursor.fetchall()
    return render_template("leaderboard_rows.html", leaderboard=leaderboard)

@app.route("/api/leaderboard/data_dashboard")
@login_required
def api_leaderboard_data_dashboard():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.id as user_id, u.fullname, u.profile_image, MAX(qa.score) as top_score, MIN(qa.time_taken) as best_time, MIN(qa.submitted_at) as submitted_at
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        WHERE u.role != 'admin' AND qa.is_disqualified = 0
        GROUP BY u.id, u.fullname, u.phone_number
        ORDER BY top_score DESC, best_time ASC, submitted_at ASC
        LIMIT 10
    """)
    leaderboard = cursor.fetchall()
    return render_template("dashboard_leaderboard_rows.html", leaderboard=leaderboard)

@app.route("/rewards")
@login_required
def rewards_page():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM transactions
        WHERE user_id = ?
        ORDER BY date DESC
    """, (session["user_id"],))
    transactions = cursor.fetchall()
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions
        WHERE user_id = ? AND status = 'Paid'
    """, (session["user_id"],))
    total_earnings = cursor.fetchone()["total"] or 0.0
    return render_template("rewards.html", transactions=transactions, total_earnings=total_earnings)

@app.route("/profile")
@login_required
def profile_page():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],))
    user_info = cursor.fetchone()
    
    cursor.execute("""
        SELECT * FROM quiz_attempts
        WHERE user_id = ?
        ORDER BY submitted_at DESC
    """, (session["user_id"],))
    attempts = cursor.fetchall()
    
    cursor.execute("""
        SELECT SUM(amount) as total FROM transactions
        WHERE user_id = ? AND status = 'Paid'
    """, (session["user_id"],))
    total_earnings = cursor.fetchone()["total"] or 0.0
    
    cursor.execute("""
        SELECT * FROM transactions
        WHERE user_id = ?
        ORDER BY date DESC
    """, (session["user_id"],))
    transactions = cursor.fetchall()
    
    return render_template("profile.html", user=user_info, attempts=attempts, total_earnings=total_earnings, transactions=transactions)

@app.route("/api/user/upi", methods=["POST"])
@login_required
def update_upi():
    upi_id = request.form.get("upi_id", "").strip()
    payment_number = request.form.get("payment_number", "").strip()
    
    # Mobile number is mandatory for winners claiming rewards
    if not payment_number:
        return jsonify({"success": False, "message": "Mobile number is required to claim your reward."}), 400
    
    # Validate mobile number: must be exactly 10 digits
    if not payment_number.isdigit() or len(payment_number) != 10:
        return jsonify({"success": False, "message": "Please enter a valid 10-digit mobile number."}), 400
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE users SET upi_id = ?, payment_number = ? WHERE id = ?",
        (upi_id if upi_id else None, payment_number, session["user_id"])
    )
    db.commit()
    
    # Notify admin: mark that payment details have been submitted by checking pending transactions
    cursor.execute("""
        SELECT id FROM transactions
        WHERE user_id = ? AND status = 'Pending'
    """, (session["user_id"],))
    pending = cursor.fetchone()
    if pending:
        # We use a simple flag approach: the admin will see the payment details in the ledger
        # No separate notification table needed — the admin sees payment_number populated = details submitted
        pass
    
    return jsonify({"success": True, "message": "Payment details saved! Your reward will be processed shortly."})

@app.route("/quiz", methods=["GET", "POST"])
@login_required
def quiz():
    db = get_db()
    cursor = db.cursor()
    
    fullname = session.get("fullname", "")
    if not fullname or fullname.strip() == "" or fullname == "Google User":
        flash("Please enter your name first.", "warning")
        return redirect(url_for("dashboard"))
    
    # Check if quiz is active
    cursor.execute("SELECT * FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    
    # Auto-expire after end_time
    if settings and settings["is_active"] == 1 and settings["end_time"]:
        end_time_val = settings["end_time"]
        end_time_dt = end_time_val if isinstance(end_time_val, datetime) else datetime.fromisoformat(end_time_val)
        if datetime.now() >= end_time_dt:
            cursor.execute("UPDATE quiz_settings SET is_active=0, stopped_at=CURRENT_TIMESTAMP WHERE id = 1")
            cursor.execute("UPDATE quiz_progress SET quiz_status = 'completed' WHERE quiz_status = 'in_progress'")
            db.commit()
            trigger_pusher_event('decoder-channel', 'quiz_status_changed', {'is_active': 0})
            flash("The quiz has ended (duration expired).", "info")
            return redirect(url_for("dashboard"))
            
    if not settings or settings["is_active"] == 0:
        flash("There is no active quiz right now.", "warning")
        return redirect(url_for("dashboard"))
        
    # Check if already attempted
    if not settings or "allow_multiple_attempts" not in settings.keys() or settings["allow_multiple_attempts"] == 0:
        cursor.execute("SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?", (session["user_id"],))
        if cursor.fetchone()["count"] > 0:
            flash("You have already participated in this quiz.", "warning")
            return redirect(url_for("dashboard"))
        
    # Check quiz password if set
    if "quiz_password" in settings.keys() and settings["quiz_password"]:
        if request.method == "POST":
            entered_password = request.form.get("quiz_password", "").strip()
            if entered_password == settings["quiz_password"]:
                session["quiz_authenticated"] = True
            else:
                flash("Incorrect quiz password.", "danger")
                
        if not session.get("quiz_authenticated"):
            return render_template("quiz_password.html")
            
    cursor.execute("SELECT fullname, phone_number FROM users WHERE id = ?", (session["user_id"],))
    current_user = cursor.fetchone()
    return render_template("quiz.html", settings=settings, current_user=current_user)

# JSON API for Quiz execution
import base64

def obfuscate_answer(ans):
    # Obfuscate answer (ans * 13 + 7), base64 encoded
    val_str = str(ans * 13 + 7).encode("utf-8")
    return base64.b64encode(val_str).decode("utf-8")

@app.route("/api/ping", methods=["GET"])
def api_ping():
    return jsonify({"status": "ok"})

@app.route("/api/stream", methods=["GET"])
def api_stream():
    # Deprecated: We now use Pusher for real-time updates.
    def event_stream():
        yield 'data: {"deprecated": true}\n\n'
    return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

def auto_close_quiz_if_expired(cursor, db, settings):
    """Check if quiz end_time has passed and auto-close it if active. Returns True if closed."""
    if not settings or settings.get("is_active") == 0 or not settings.get("end_time"):
        return False
        
    end_time_val = settings["end_time"]
    end_time = end_time_val if isinstance(end_time_val, datetime) else datetime.fromisoformat(end_time_val)
    
    if datetime.now() > end_time:
        cursor.execute("UPDATE quiz_settings SET is_active = 0, stopped_at = CURRENT_TIMESTAMP WHERE id = 1")
        cursor.execute("UPDATE quiz_progress SET quiz_status = 'completed' WHERE quiz_status = 'in_progress'")
        db.commit()
        trigger_pusher_event('decoder-channel', 'quiz_status_changed', {'is_active': 0})
        return True
        
    return False

@app.route("/api/quiz/start", methods=["POST"])
@login_required
def api_start_quiz():
    db = get_db()
    cursor = db.cursor()
    
    # Validate quiz active
    cursor.execute("SELECT * FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    if not settings or settings["is_active"] == 0:
        return jsonify({"success": False, "message": "Quiz is not active."}), 400
        
    # Check if time has expired
    if auto_close_quiz_if_expired(cursor, db, settings):
        return jsonify({"success": False, "message": "Quiz is not active."}), 400
    # Check if already attempted
    if not settings or "allow_multiple_attempts" not in settings.keys() or settings["allow_multiple_attempts"] == 0:
        cursor.execute("SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?", (session["user_id"],))
        if cursor.fetchone()[0] > 0:
            return jsonify({"success": False, "message": "You have already attempted the quiz."}), 400
        
    # Check quiz password if set
    if "quiz_password" in settings.keys() and settings["quiz_password"]:
        if not session.get("quiz_authenticated"):
            return jsonify({"success": False, "message": "Quiz requires a password. Please authenticate via the dashboard."}), 403
            
    # Check for existing completed quiz (block restart after submission)
    cursor.execute("SELECT * FROM quiz_progress WHERE user_id = ? AND quiz_status = 'completed'", (session["user_id"],))
    completed_progress = cursor.fetchone()
    if completed_progress:
        return jsonify({"success": False, "message": "You have already completed this quiz. Only an admin can reset your attempt."}), 400
    
    # Check for existing in_progress quiz (Refresh Protection)
    cursor.execute("SELECT * FROM quiz_progress WHERE user_id = ? AND quiz_status = 'in_progress'", (session["user_id"],))
    progress = cursor.fetchone()
    if progress:
        saved_questions = json.loads(progress["quiz_questions"])
        saved_answers = json.loads(progress["selected_answers"])
        total_time = progress["total_time"] if progress["total_time"] else settings["time_limit"]
        return jsonify({
            "success": True,
            "quiz_id": settings["id"] if settings else 1,
            "questions": saved_questions,
            "time_limit": progress["remaining_time"],
            "total_time": total_time,
            "saved_answers": saved_answers,
            "saved_question_index": progress["current_question"]
        })
        
    # Load questions, randomize order
    cursor.execute("SELECT id, question, option1, option2, option3, option4, correct_answer FROM quiz_questions")
    questions = cursor.fetchall()
    
    if not questions:
        return jsonify({"success": False, "message": "No questions available in the database."}), 404
        
    # Format questions and randomize options
    formatted_questions = []
    for q in questions:
        options = [
            {"index": 1, "text": q["option1"]},
            {"index": 2, "text": q["option2"]},
            {"index": 3, "text": q["option3"]},
            {"index": 4, "text": q["option4"]}
        ]
        random.shuffle(options) # Randomize option sequence
        
        # Obfuscate correct answer
        correct_enc = obfuscate_answer(q["correct_answer"])
        
        formatted_questions.append({
            "id": q["id"],
            "question": q["question"],
            "options": options,
            "correct_enc": correct_enc
        })
        
    # Shuffle question order
    random.shuffle(formatted_questions)
    
    # Save to quiz_progress (include total_time for accurate timer restoration on refresh)
    cursor.execute("""
        INSERT INTO quiz_progress (user_id, remaining_time, total_time, quiz_questions)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            remaining_time=excluded.remaining_time,
            total_time=excluded.total_time,
            quiz_questions=excluded.quiz_questions,
            current_question=0,
            selected_answers='{}',
            quiz_status='in_progress',
            started_at=CURRENT_TIMESTAMP
    """, (session["user_id"], settings["time_limit"], settings["time_limit"], json.dumps(formatted_questions)))
    db.commit()
    
    trigger_pusher_event('decoder-channel', 'participant_joined', {
                'user': session.get('fullname', 'A user')
            })
            
    # Save quiz start time and question ordering in session for verification
    session["quiz_start_time"] = datetime.now().isoformat()
    session["quiz_questions_sent"] = [q["id"] for q in formatted_questions]
    
    return jsonify({
        "success": True,
        "quiz_id": settings["id"] if settings else 1,
        "questions": formatted_questions,
        "time_limit": settings["time_limit"],
        "total_time": settings["time_limit"]
    })

@app.route("/api/quiz/status", methods=["GET"])
def api_quiz_status():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT is_active, end_time FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    is_active = False
    
    if settings and settings["is_active"] == 1:
        if auto_close_quiz_if_expired(cursor, db, settings):
            is_active = False
        else:
            is_active = True

    return jsonify({"is_active": is_active, "quiz_status": "LIVE" if is_active else "CLOSED"})

@app.route("/api/quiz/save_progress", methods=["POST"])
@login_required
def api_save_progress():
    data = request.get_json() or {}
    user_answers = data.get("answers", {})
    if not isinstance(user_answers, dict):
        user_answers = {}
        
    try:
        current_question = int(data.get("current_question", 0))
    except (ValueError, TypeError):
        current_question = 0
        
    try:
        remaining_time = int(data.get("remaining_time", 30))
    except (ValueError, TypeError):
        remaining_time = 30
    
    db = get_db()
    cursor = db.cursor()
    
    # Check if quiz is still active
    cursor.execute("SELECT is_active FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    if not settings or settings["is_active"] == 0:
        return jsonify({"success": False, "message": "Quiz is closed."}), 400
        
    try:
        cursor.execute("""
            UPDATE quiz_progress 
            SET selected_answers = ?, current_question = ?, remaining_time = ?
            WHERE user_id = ? AND quiz_status = 'in_progress'
        """, (json.dumps(user_answers), current_question, remaining_time, session["user_id"]))
        db.commit()
    except Exception as e:
        print("Save progress error:", e)
        return jsonify({"success": False, "message": "Failed to save progress."}), 500
        
    return jsonify({"success": True})

@app.route("/api/quiz/submit", methods=["POST"])
@login_required
def api_submit_quiz():
    db = get_db()
    cursor = db.cursor()
    
    # Fetch quiz settings
    cursor.execute("SELECT * FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    
    if not settings or settings["is_active"] == 0:
        return jsonify({"success": False, "message": "Quiz has been closed by the admin."}), 400
    
    # Check duplicate submission again
    if not settings or "allow_multiple_attempts" not in settings.keys() or settings["allow_multiple_attempts"] == 0:
        cursor.execute("SELECT COUNT(*) as count FROM quiz_attempts WHERE user_id = ?", (session["user_id"],))
        if cursor.fetchone()[0] > 0:
            return jsonify({"success": False, "message": "Duplicate submission detected."}), 400
        
    # Get answers from POST data
    user_answers = request.json.get("answers", {}) # Format: {"question_id": selected_option_index}
    if not isinstance(user_answers, dict):
        return jsonify({"success": False, "message": "Invalid answer format."}), 400
    
    # Get saved progress to calculate score
    cursor.execute("SELECT * FROM quiz_progress WHERE user_id = ? AND quiz_status = 'in_progress'", (session["user_id"],))
    progress = cursor.fetchone()
    
    if not progress:
        return jsonify({"success": False, "message": "No active quiz session found."}), 400
        
    saved_questions = json.loads(progress["quiz_questions"])
    sent_questions = [q["id"] for q in saved_questions]
    
    time_taken = request.json.get("time_taken")
    if time_taken is None:
        time_taken = 300
    else:
        try:
            time_taken = int(time_taken)
        except ValueError:
            time_taken = 300
    
    max_allowed_time = settings["time_limit"] + 60 if settings else 360 # Allow 60 seconds buffer
    
    # Calculate Score
    score = 0
    if not sent_questions:
        return jsonify({"success": False, "message": "No answers submitted or invalid session."}), 400
        
    # Fetch correct answers
    placeholders = ",".join("?" for _ in sent_questions)
    cursor.execute(f"SELECT id, correct_answer FROM quiz_questions WHERE id IN ({placeholders})", sent_questions)
    correct_answers_map = {row["id"]: row["correct_answer"] for row in cursor.fetchall()}
    
    for q_id_str, selected_index in user_answers.items():
        try:
            q_id = int(q_id_str)
        except ValueError:
            continue
            
        if q_id in correct_answers_map:
            try:
                selected_idx_int = int(selected_index)
            except (ValueError, TypeError):
                continue
                
            if selected_idx_int == correct_answers_map[q_id]:
                score += 1
                
    if time_taken > max_allowed_time:
        time_taken = max_allowed_time
    if time_taken < 1:
        time_taken = 1
        
    warnings_count = request.json.get("warnings_count", 0)
    try:
        warnings_count = int(warnings_count)
    except ValueError:
        warnings_count = 0
        
    is_disqualified = 1 if request.json.get("is_disqualified") else 0
    disqualification_reason = request.json.get("disqualification_reason", None)

    # Insert attempt
    cursor.execute(
        "INSERT INTO quiz_attempts (user_id, score, time_taken, warnings_count, is_disqualified, disqualification_reason) VALUES (?, ?, ?, ?, ?, ?)",
        (session["user_id"], score, time_taken, warnings_count, is_disqualified, disqualification_reason)
    )
    
    # Mark progress as completed
    cursor.execute("UPDATE quiz_progress SET quiz_status = 'completed' WHERE id = ?", (progress["id"],))
    db.commit()
    
    # Check if user needs to provide a mobile number
    cursor.execute("SELECT phone_number FROM users WHERE id = ?", (session["user_id"],))
    user_row = cursor.fetchone()
    needs_phone = False if (user_row and user_row["phone_number"]) else True
    
    trigger_pusher_event('decoder-channel', 'leaderboard_updated', {
                'user': session.get('fullname', 'User'),
                'score': score
            })
            
    return jsonify({
        "success": True,
        "score": score,
        "total": len(sent_questions),
        "time_taken": time_taken,
        "needs_phone": needs_phone
    })


# SECRET ADMIN SYSTEM
@app.route("/api/admin/auth_secret", methods=["POST"])
def admin_auth_secret():
    if not session.get("user_id"):
        return jsonify({"success": False, "message": "You must be logged in to authenticate."}), 401
        
    data = request.get_json()
    if not data or not data.get("secret_key"):
        return jsonify({"success": False, "message": "Secret key is required."}), 400
        
    secret_key = data.get("secret_key")
    configured_secret = os.environ.get("ADMIN_SECRET_KEY", "DECODER@2026")
    
    if secret_key != configured_secret:
        return jsonify({"success": False, "message": "Invalid Secret Key. Access Denied."}), 403
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (session.get("user_id"),))
    user = cursor.fetchone()
    
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    # Check if user is one of the authorized accounts
    admin_email_1 = os.environ.get("ADMIN_EMAIL_1", "jeevantara38@gmail.com")
    admin_email_2 = os.environ.get("ADMIN_EMAIL_2", "jeevantara38@gmail.com")
    
    # Authorized if their email matches OR if they are already flagged as admin in DB
    is_authorized = False
    if user["email"] and (user["email"].lower() == admin_email_1.lower() or user["email"].lower() == admin_email_2.lower()):
        is_authorized = True
    elif user["role"] == "admin":
        is_authorized = True
        
    if is_authorized:
        # Upgrade session to admin
        session["admin"] = True
        session["role"] = "admin"
        
        # Ensure database reflects this
        if user["role"] != "admin":
            cursor.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user["id"],))
            db.commit()
            
        return jsonify({"success": True, "message": "Admin authenticated successfully."})
    else:
        return jsonify({"success": False, "message": "Your account is not authorized for Admin access."}), 403


@app.route("/api/admin/users/create", methods=["POST"])
@admin_required
def api_admin_create_user():
    db = get_db()
    cursor = db.cursor()
    
    # Generate unique placeholder phone to avoid unique key crash
    temp_phone = str(random.randint(1100000000, 1999999999))
    while True:
        cursor.execute("SELECT COUNT(*) FROM users WHERE phone = ?", (temp_phone,))
        if cursor.fetchone()[0] == 0:
            break
        temp_phone = str(random.randint(1100000000, 1999999999))
        
    placeholder_pass = generate_password_hash("default_pass")
    
    try:
        cursor.execute(
            "INSERT INTO users (fullname, phone, password, role) VALUES (?, ?, ?, 'user')",
            ("New User", temp_phone, placeholder_pass)
        )
        db.commit()
        
        # Get the newly created user's ID
        new_id = cursor.lastrowid
        return jsonify({
            "success": True,
            "user": {
                "id": new_id,
                "fullname": "New User",
                "phone": temp_phone,
                "upi_id": "",
                "payment_number": "",
                "role": "user"
            }
        })
    except IntegrityError as e:
        return jsonify({"success": False, "message": f"Database insertion failed: {str(e)}"}), 400


@app.route("/api/admin/users/update", methods=["POST"])
@admin_required
def api_admin_update_user():
    data = request.get_json() or {}
    user_id = data.get("user_id")
    field = data.get("field")
    value = data.get("value", "").strip()
    
    if not user_id or not field:
        return jsonify({"success": False, "message": "Missing required fields."}), 400
        
    allowed_fields = ["fullname", "phone", "upi_id", "payment_number", "role"]
    if field not in allowed_fields:
        return jsonify({"success": False, "message": f"Modification of '{field}' is restricted."}), 400
        
    # Check phone validation
    if field == "phone":
        if not value:
            return jsonify({"success": False, "message": "Phone number/Email cannot be empty."}), 400
        if "@" not in value:
            if not value.isdigit() or len(value) != 10:
                return jsonify({"success": False, "message": "Please enter a valid 10-digit phone number."}), 400
        
    if field == "fullname":
        if not value:
            return jsonify({"success": False, "message": "Name cannot be empty."}), 400
        if len(value) < 2:
            return jsonify({"success": False, "message": "Name must be at least 2 characters long."}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Check if changing admin role
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    target_user = cursor.fetchone()
    if not target_user:
        return jsonify({"success": False, "message": "User not found."}), 404
        
    # Prevent removing last admin role
    if field == "role" and target_user["role"] == "admin" and value != "admin":
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] <= 1:
            return jsonify({"success": False, "message": "Cannot demote the last remaining administrator."}), 400
            
    try:
        # UPI or Payment phone can be null if empty
        val_to_save = None if (field in ["upi_id", "payment_number"] and not value) else value
        cursor.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (val_to_save, user_id))
        db.commit()
        return jsonify({"success": True})
    except IntegrityError:
        return jsonify({"success": False, "message": "Phone number/Email already registered to another user."}), 400


@app.route("/api/admin/users/delete/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_delete_user(user_id):
    if user_id == session.get("user_id"):
        return jsonify({"success": False, "message": "You cannot delete your own logged-in admin account."}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Prevent deleting last admin
    cursor.execute("SELECT role FROM users WHERE id = ?", (user_id,))
    target_user = cursor.fetchone()
    if target_user and target_user["role"] == "admin":
        cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'")
        if cursor.fetchone()[0] <= 1:
            return jsonify({"success": False, "message": "Cannot delete the last remaining administrator."}), 400
            
    # Delete associated records
    cursor.execute("DELETE FROM quiz_progress WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM quiz_attempts WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM transactions WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    
    return jsonify({"success": True})


@app.route("/api/admin/attempts/update", methods=["POST"])
@admin_required
def api_admin_update_attempt():
    data = request.get_json() or {}
    attempt_id = data.get("attempt_id")
    score = data.get("score")
    time_taken = data.get("time_taken")
    
    if attempt_id is None or score is None or time_taken is None:
        return jsonify({"success": False, "message": "Missing score, time, or attempt ID."}), 400
        
    try:
        score = int(score)
        time_taken = int(time_taken)
        if score < 0:
            return jsonify({"success": False, "message": "Score cannot be negative."}), 400
        if time_taken < 1:
            return jsonify({"success": False, "message": "Duration must be at least 1 second."}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Score and duration must be integers."}), 400
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE quiz_attempts SET score = ?, time_taken = ? WHERE id = ?",
        (score, time_taken, attempt_id)
    )
    db.commit()
    return jsonify({"success": True})


@app.route("/api/admin/attempts/delete/<int:attempt_id>", methods=["POST"])
@admin_required
def api_admin_delete_attempt(attempt_id):
    db = get_db()
    cursor = db.cursor()
    # Get the user_id for this attempt so we can also clear their quiz_progress
    cursor.execute("SELECT user_id FROM quiz_attempts WHERE id = ?", (attempt_id,))
    attempt_row = cursor.fetchone()
    cursor.execute("DELETE FROM quiz_attempts WHERE id = ?", (attempt_id,))
    # Also clear quiz_progress so the user can retake the quiz
    if attempt_row:
        # Only clear if the user has no other attempts remaining
        cursor.execute("SELECT COUNT(*) FROM quiz_attempts WHERE user_id = ? AND id != ?", (attempt_row["user_id"], attempt_id))
        if cursor.fetchone()[0] == 0:
            cursor.execute("DELETE FROM quiz_progress WHERE user_id = ?", (attempt_row["user_id"],))
    db.commit()
    return jsonify({"success": True})


@app.route("/api/admin/quiz/reset/<int:user_id>", methods=["POST"])
@admin_required
def api_admin_reset_quiz(user_id):
    """Reset a user's quiz attempt so they can retake the quiz.
    Deletes their quiz_progress and all quiz_attempts."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM quiz_progress WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM quiz_attempts WHERE user_id = ?", (user_id,))
    db.commit()
    
    trigger_pusher_event('decoder-channel', 'user_quiz_reset', {'user_id': user_id})
    
    return jsonify({"success": True, "message": "Quiz reset successfully. The user can now retake the quiz."})


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    cursor = db.cursor()
    
    # Fetch quiz settings
    cursor.execute("SELECT * FROM quiz_settings WHERE id = 1")
    settings = cursor.fetchone()
    
    # Fetch all questions
    cursor.execute("SELECT * FROM quiz_questions ORDER BY id DESC")
    questions = cursor.fetchall()
    
    # Fetch all users and calculate their rank and best score (Limit 1000 for performance)
    cursor.execute("SELECT * FROM users ORDER BY id DESC LIMIT 1000")
    raw_participants = cursor.fetchall()
    
    cursor.execute("""
        SELECT user_id, MAX(score) as best_score, MIN(time_taken) as best_time 
        FROM quiz_attempts 
        GROUP BY user_id 
        ORDER BY best_score DESC, best_time ASC
        LIMIT 1000
    """)
    leaderboard = cursor.fetchall()
    
    user_stats = {}
    for index, row in enumerate(leaderboard):
        user_stats[row["user_id"]] = {
            "rank": index + 1,
            "best_score": row["best_score"]
        }
        
    participants = []
    for user in raw_participants:
        user_dict = dict(user)
        stats = user_stats.get(user["id"], {"rank": "-", "best_score": "-"})
        user_dict["rank"] = stats["rank"]
        user_dict["best_score"] = stats["best_score"]
        participants.append(user_dict)
    
    # Fetch scores/attempts sorted by best performers (leaderboard format, Limit 1000)
    cursor.execute("""
        SELECT qa.id as attempt_id, u.id as user_id, u.fullname, u.phone_number, u.role as role, qa.score, qa.time_taken, qa.warnings_count, qa.submitted_at, qa.is_disqualified, qa.disqualification_reason
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        ORDER BY qa.score DESC, qa.time_taken ASC, qa.submitted_at ASC
        LIMIT 1000
    """)
    attempts = cursor.fetchall()
    
    # Fetch transaction ledger (include payment details for admin view, Limit 1000)
    cursor.execute("""
        SELECT t.id as transaction_id, u.fullname, u.phone_number, u.role as role, t.amount, t.status, t.date, t.utr_id,
               u.payment_number as winner_mobile, u.upi_id as winner_upi
        FROM transactions t
        JOIN users u ON t.user_id = u.id
        ORDER BY t.date DESC
        LIMIT 1000
    """)
    transactions = cursor.fetchall()
    
    # Build contacts data for the Participant Contacts tab (Limit 2000 to allow dedup to 1000)
    cursor.execute("""
        SELECT u.id as user_id, u.fullname, u.phone_number,
               qa.score, qa.time_taken, qa.submitted_at
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        WHERE u.role != 'admin' AND qa.is_disqualified = 0
        ORDER BY qa.score DESC, qa.time_taken ASC, qa.submitted_at ASC
        LIMIT 2000
    """)
    contacts_raw = cursor.fetchall()
    
    # Build contacts with rank, dedup to best attempt per user
    contacts = []
    seen_users = set()
    rank = 0
    for row in contacts_raw:
        if row["user_id"] in seen_users:
            continue
        seen_users.add(row["user_id"])
        rank += 1
        
        # Determine quiz status
        cursor.execute("SELECT quiz_status FROM quiz_progress WHERE user_id = ?", (row["user_id"],))
        prog = cursor.fetchone()
        if prog:
            quiz_status = "Completed" if prog["quiz_status"] == "completed" else "In Progress"
        else:
            quiz_status = "Completed"  # has attempt but no progress row
        
        contacts.append({
            "rank": rank,
            "fullname": row["fullname"],
            "phone_number": row["phone_number"] or "Unverified",
            "score": row["score"],
            "time_taken": row["time_taken"],
            "submitted_at": row["submitted_at"],
            "quiz_status": quiz_status
        })
    
    return render_template(
        "admin_dashboard.html",
        settings=settings,
        questions=questions,
        participants=participants,
        attempts=attempts,
        transactions=transactions,
        contacts=contacts
    )

@app.route("/admin/quiz/toggle", methods=["POST"])
@admin_required
def admin_toggle_quiz():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT is_active FROM quiz_settings WHERE id = 1")
    current_status = cursor.fetchone()["is_active"]
    
    if current_status == 0:
        # Starting the quiz — just flip status. Do NOT delete progress/attempts.
        new_status = 1
        duration_days = request.form.get("duration_days", type=int, default=1)
        end_time = datetime.now() + timedelta(days=duration_days)
        cursor.execute("UPDATE quiz_settings SET is_active = ?, started_at = CURRENT_TIMESTAMP, start_time = CURRENT_TIMESTAMP, stopped_at = NULL, end_time = ?, duration_days = ?, stopped_by_admin = 0 WHERE id = 1", (new_status, end_time.isoformat(), duration_days))
    else:
        # Stopping the quiz
        new_status = 0
        cursor.execute("UPDATE quiz_settings SET is_active = ?, stopped_at = CURRENT_TIMESTAMP, stopped_by_admin = 1 WHERE id = 1", (new_status,))
        # Auto-submit for users still taking it
        cursor.execute("UPDATE quiz_progress SET quiz_status = 'completed' WHERE quiz_status = 'in_progress'")
        
    db.commit()
    
    trigger_pusher_event('decoder-channel', 'quiz_status_changed', {
                'is_active': new_status
            })
            
    status_str = "started" if new_status == 1 else "stopped"
    flash(f"Quiz status updated. The quiz has been {status_str}!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/quiz/reset_all", methods=["POST"])
@admin_required
def admin_reset_all_quiz_data():
    """Reset ALL quiz progress and attempts. Use when starting a brand new quiz round."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM quiz_progress")
    cursor.execute("DELETE FROM quiz_attempts")
    db.commit()
    trigger_pusher_event('decoder-channel', 'quiz_reset', {})
    flash("All quiz progress and attempt data has been reset.", "success")
    return redirect(url_for("admin_dashboard"))

import csv
import io
from flask import Response

@app.route("/admin/participants/export_csv")
@admin_required
def admin_export_contacts_csv():
    """Export participant contacts as a CSV file. Admin-only."""
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        SELECT u.id as user_id, u.fullname, u.phone_number,
               qa.score, qa.time_taken, qa.submitted_at
        FROM quiz_attempts qa
        JOIN users u ON qa.user_id = u.id
        WHERE u.role != 'admin' AND qa.is_disqualified = 0
        ORDER BY qa.score DESC, qa.time_taken ASC, qa.submitted_at ASC
    """)
    rows = cursor.fetchall()
    
    # Dedup to best attempt per user
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rank", "Full Name", "Mobile Number", "Score", "Time Taken (s)", "Submitted At", "Quiz Status"])
    
    seen = set()
    rank = 0
    for row in rows:
        if row["user_id"] in seen:
            continue
        seen.add(row["user_id"])
        rank += 1
        
        cursor.execute("SELECT quiz_status FROM quiz_progress WHERE user_id = ?", (row["user_id"],))
        prog = cursor.fetchone()
        status = "Completed"
        if prog:
            status = "Completed" if prog["quiz_status"] == "completed" else "In Progress"
        
        writer.writerow([
            rank,
            row["fullname"],
            row["phone_number"] or "Unverified",
            row["score"],
            row["time_taken"],
            row["submitted_at"],
            status
        ])
    
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=participant_contacts.csv"}
    )

@app.route("/admin/quiz/settings", methods=["POST"])
@admin_required
def admin_update_settings():
    time_limit = request.form.get("time_limit", type=int)
    prize_pool = request.form.get("prize_pool", type=float)
    quiz_password = request.form.get("quiz_password", "").strip()
    allow_multiple_attempts = 1 if request.form.get("allow_multiple_attempts") == '1' else 0
    
    if not time_limit or time_limit < 10 or prize_pool is None or prize_pool < 0:
        flash("Invalid settings values. Timer must be at least 10s and Prize Pool must be positive.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    if len(quiz_password) > 50:
        flash("Quiz password cannot exceed 50 characters.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE quiz_settings SET time_limit = ?, prize_pool = ?, quiz_password = ?, allow_multiple_attempts = ? WHERE id = 1",
        (time_limit, prize_pool, quiz_password, allow_multiple_attempts)
    )
    db.commit()
    trigger_pusher_event('decoder-channel', 'quiz_settings_changed', {
        'time_limit': time_limit,
        'prize_pool': prize_pool
    })
    flash("Settings updated successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/questions/add", methods=["POST"])
@admin_required
def admin_add_question():
    question = request.form.get("question").strip()
    option1 = request.form.get("option1").strip()
    option2 = request.form.get("option2").strip()
    option3 = request.form.get("option3").strip()
    option4 = request.form.get("option4").strip()
    correct_answer = request.form.get("correct_answer", type=int)
    
    if not question or not option1 or not option2 or not option3 or not option4 or correct_answer not in [1, 2, 3, 4]:
        flash("All question fields are required, and correct answer must be between 1 and 4.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO quiz_questions (question, option1, option2, option3, option4, correct_answer) VALUES (?, ?, ?, ?, ?, ?)",
        (question, option1, option2, option3, option4, correct_answer)
    )
    db.commit()
    flash("Question added successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/questions/import_json", methods=["POST"])
@admin_required
def admin_import_questions_json():
    json_data = request.form.get("questions_json", "").strip()
    if not json_data:
        flash("JSON input is empty.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    try:
        import json
        questions_list = json.loads(json_data)
        if not isinstance(questions_list, list):
            flash("JSON must be an array of questions.", "danger")
            return redirect(url_for("admin_dashboard"))
            
        db = get_db()
        cursor = db.cursor()
        
        imported_count = 0
        for item in questions_list:
            question = item.get("question", "").strip()
            option1 = item.get("option1", "").strip()
            option2 = item.get("option2", "").strip()
            option3 = item.get("option3", "").strip()
            option4 = item.get("option4", "").strip()
            correct_answer = item.get("correct_answer")
            
            if not question or not option1 or not option2 or not option3 or not option4 or correct_answer is None:
                continue
                
            cursor.execute(
                "INSERT INTO quiz_questions (question, option1, option2, option3, option4, correct_answer) VALUES (?, ?, ?, ?, ?, ?)",
                (question, option1, option2, option3, option4, int(correct_answer))
            )
            imported_count += 1
            
        db.commit()
        flash(f"Successfully imported {imported_count} questions from JSON!", "success")
    except Exception as e:
        flash(f"Error parsing JSON: {str(e)}", "danger")
        
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/questions/edit/<int:q_id>", methods=["POST"])
@admin_required
def admin_edit_question(q_id):
    question = request.form.get("question").strip()
    option1 = request.form.get("option1").strip()
    option2 = request.form.get("option2").strip()
    option3 = request.form.get("option3").strip()
    option4 = request.form.get("option4").strip()
    correct_answer = request.form.get("correct_answer", type=int)
    
    if not question or not option1 or not option2 or not option3 or not option4 or correct_answer not in [1, 2, 3, 4]:
        flash("All question fields are required, and correct answer must be between 1 and 4.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""
        UPDATE quiz_questions
        SET question = ?, option1 = ?, option2 = ?, option3 = ?, option4 = ?, correct_answer = ?
        WHERE id = ?
    """, (question, option1, option2, option3, option4, correct_answer, q_id))
    db.commit()
    flash("Question updated successfully.", "success")
    return redirect(url_for("admin_dashboard"))

def _renumber_questions(cursor, db):
    cursor.execute("SELECT id FROM quiz_questions ORDER BY id ASC")
    rows = cursor.fetchall()
    for new_id, row in enumerate(rows, start=1):
        old_id = row["id"]
        if old_id != new_id:
            cursor.execute("UPDATE quiz_questions SET id = ? WHERE id = ?", (new_id, old_id))
    try:
        cursor.execute("UPDATE sqlite_sequence SET seq = (SELECT MAX(id) FROM quiz_questions) WHERE name='quiz_questions'")
    except Exception:
        pass
    db.commit()

@app.route("/admin/questions/delete/<int:q_id>", methods=["POST"])
@admin_required
def admin_delete_question(q_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM quiz_questions WHERE id = ?", (q_id,))
    db.commit()
    _renumber_questions(cursor, db)
    flash("Question deleted successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/questions/delete_bulk", methods=["POST"])
@admin_required
def admin_delete_bulk_questions():
    question_ids = request.form.getlist("question_ids")
    if not question_ids:
        flash("No questions selected for deletion.", "warning")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    placeholders = ",".join("?" * len(question_ids))
    cursor.execute(f"DELETE FROM quiz_questions WHERE id IN ({placeholders})", question_ids)
    db.commit()
    _renumber_questions(cursor, db)
    flash(f"Deleted {len(question_ids)} questions successfully.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/questions/delete_all", methods=["POST"])
@admin_required
def admin_delete_all_questions():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("DELETE FROM quiz_questions")
    try:
        cursor.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name='quiz_questions'")
    except Exception:
        pass
    db.commit()
    flash("All questions have been deleted.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/payout/create", methods=["POST"])
@admin_required
def admin_create_payout():
    user_id = request.form.get("user_id", type=int)
    amount = request.form.get("amount", type=float)
    
    if not user_id or not amount:
        flash("Invalid payout values.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "INSERT INTO transactions (user_id, amount, status) VALUES (?, ?, 'Pending')",
        (user_id, amount)
    )
    db.commit()
    flash("Payout created. Pending transaction logged.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/payout/update/<int:t_id>", methods=["POST"])
@admin_required
def admin_update_payout(t_id):
    status = request.form.get("status")
    utr_id = request.form.get("utr_id", "").strip()
    
    if status not in ["Pending", "Paid", "Rejected"]:
        flash("Invalid status value.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        "UPDATE transactions SET status = ?, utr_id = ? WHERE id = ?",
        (status, utr_id if utr_id else None, t_id)
    )
    db.commit()
    flash("Transaction ledger updated successfully.", "success")
    return redirect(url_for("admin_dashboard"))

# Helper for creating initial admin in code (e.g. if the user wants an admin login, they can login directly via secret key,
# but we also allow user registration. To create an admin account, they can do so in the DB or use the secret url)
@app.route("/admin/create_admin_account", methods=["POST"])
@admin_required
def create_admin_account():
    # Helper to convert an existing user to admin by phone number
    phone = request.form.get("phone", "").strip()
    if not phone:
        flash("Phone is required.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET role = 'admin' WHERE phone = ?", (phone,))
    db.commit()
    flash(f"User with phone {phone} has been promoted to Admin.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/announce", methods=["POST"])
@admin_required
def admin_announce():
    message = request.form.get("message", "").strip()
    if not message:
        flash("Announcement message cannot be empty.", "danger")
        return redirect(url_for("admin_dashboard"))
        
    trigger_pusher_event('decoder-channel', 'admin_announcement', {
        'message': message
    })
    flash("Announcement broadcasted successfully to all connected users.", "success")
    return redirect(url_for("admin_dashboard"))


import re

@app.route("/reward_verification")
@login_required
def reward_verification():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("SELECT phone_number FROM users WHERE id = ?", (session["user_id"],))
    user_row = cursor.fetchone()
    if user_row and user_row["phone_number"]:
        return redirect(url_for("dashboard"))
    
    return render_template("reward_verification.html")

@app.route("/api/user/verify_mobile", methods=["POST"])
@login_required
def api_verify_mobile():
    phone = request.form.get("phone_number", "").strip()
    
    # Validation
    if not phone or not re.match(r"^[6-9]\d{9}$", phone):
        return jsonify({"success": False, "message": "Please enter a valid 10-digit Indian mobile number."}), 400
        
    db = get_db()
    cursor = db.cursor()
    
    # Check duplicate
    cursor.execute("SELECT id FROM users WHERE phone_number = ? AND id != ?", (phone, session["user_id"]))
    if cursor.fetchone():
        return jsonify({"success": False, "message": "This mobile number is already registered to another account."}), 400
        
    # Update user
    cursor.execute("UPDATE users SET phone_number = ? WHERE id = ?", (phone, session["user_id"]))
    db.commit()
    
    return jsonify({"success": True, "message": "Mobile number verified successfully."})


if __name__ == "__main__":
    app.run(debug=not os.environ.get('VERCEL'), host="0.0.0.0", port=5000)
