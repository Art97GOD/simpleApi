from flask import Blueprint, request, jsonify
from app.db import get_db
import hashlib
import uuid
from datetime import datetime, timedelta

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Хранилище сессий (временное, в продакшене используйте Redis/БД)
sessions = {}


def require_auth():
    """Проверка аутентификации через куки сессии"""
    session_id = request.cookies.get('session_id')
    if not session_id or session_id not in sessions:
        return None
    session = sessions[session_id]
    if datetime.now() > session['expires_at']:
        del sessions[session_id]
        return None
    return session


def require_role(role):
    """Проверка роли пользователя"""
    session = require_auth()
    if not session:
        return None
    if session['role'] not in role if isinstance(role, list) else session['role'] != role:
        return None
    return session


@bp.route("/register", methods=["POST"])
def register():
    data = request.json

    if not data or "email" not in data or "password" not in data:
        return jsonify({"error": "email and password required"}), 400

    if "first_name" not in data or "last_name" not in data:
        return jsonify({"error": "first_name and last_name required"}), 400

    password_hash = hashlib.sha256(data["password"].encode()).hexdigest()
    role = data.get("role", "client")

    db = get_db()
    cursor = db.cursor()

    # Проверка существования пользователя
    cursor.execute(
        "SELECT id FROM users WHERE email = %s",
        (data["email"],)
    )
    if cursor.fetchone():
        return jsonify({"error": "user already exists"}), 409

    # Создание пользователя
    cursor.execute(
        """
        INSERT INTO users (email, password, first_name, last_name, role, phone)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (data["email"], password_hash, data["first_name"],
         data["last_name"], role, data.get("phone"))
    )

    # Получаем созданного пользователя
    cursor.execute(
        """
        SELECT id, email, first_name, last_name, role, phone, created_at
        FROM users WHERE email = %s
        """,
        (data["email"],)
    )

    user = cursor.fetchone()
    db.commit()

    # Создание сессии
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        'user_id': user[0],
        'role': user[4],
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(days=30)
    }

    response = jsonify({
        "message": "user registered successfully",
        "user": {
            "id": user[0],
            "email": user[1],
            "first_name": user[2],
            "last_name": user[3],
            "role": user[4],
            "phone": user[5],
            "created_at": user[6]
        }
    })

    # Устанавливаем куки сессии
    response.set_cookie('session_id', session_id, httponly=True, max_age=30 * 24 * 60 * 60)
    return response, 201


@bp.route("/login", methods=["POST"])
def login():
    data = request.json

    if not data or "email" not in data or "password" not in data:
        return jsonify({"error": "email and password required"}), 400

    password_hash = hashlib.sha256(data["password"].encode()).hexdigest()

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT id, email, first_name, last_name, role, phone, created_at
        FROM users
        WHERE email = %s AND password = %s
        """,
        (data["email"], password_hash)
    )

    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "invalid credentials"}), 401

    # Создание сессии
    session_id = str(uuid.uuid4())
    sessions[session_id] = {
        'user_id': user[0],
        'role': user[4],
        'created_at': datetime.now(),
        'expires_at': datetime.now() + timedelta(days=30)
    }

    response = jsonify({
        "message": "login successful",
        "user": {
            "id": user[0],
            "email": user[1],
            "first_name": user[2],
            "last_name": user[3],
            "role": user[4],
            "phone": user[5],
            "created_at": user[6]
        }
    })

    response.set_cookie('session_id', session_id, httponly=True, max_age=30 * 24 * 60 * 60)
    return response


@bp.route("/logout", methods=["POST"])
def logout():
    session_id = request.cookies.get('session_id')
    if session_id and session_id in sessions:
        del sessions[session_id]

    response = jsonify({"message": "logout successful"})
    response.set_cookie('session_id', '', expires=0)
    return response


@bp.route("/refresh", methods=["POST"])
def refresh():
    session_id = request.cookies.get('session_id')
    if not session_id or session_id not in sessions:
        return jsonify({"error": "invalid session"}), 401

    # Обновляем срок действия сессии
    sessions[session_id]['expires_at'] = datetime.now() + timedelta(days=30)

    response = jsonify({"message": "session refreshed"})
    response.set_cookie('session_id', session_id, httponly=True, max_age=30 * 24 * 60 * 60)
    return response