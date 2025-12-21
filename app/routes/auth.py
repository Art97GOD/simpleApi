from flask import Blueprint, request, jsonify
from app.db import get_db
import hashlib

bp = Blueprint("auth", __name__, url_prefix="/auth")

@bp.route("/login", methods=["GET"])
def login():
    data = request.json

    if not data or "email" not in data or "password" not in data:
        return jsonify({"error": "email and password required"}), 400

    password_hash = hashlib.sha256(
        data["password"].encode()
    ).hexdigest()

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT id, role
        FROM customers
        WHERE email = ? AND password_hash = ?
        """,
        data["email"],
        password_hash
    )

    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "invalid credentials"}), 401

    return jsonify({
        "message": "login successful",
        "user_id": user[0],
        "role": user[1]
    })



@bp.route("/register", methods=["POST"])
def register():
    data = request.json

    if not data or "email" not in data or "password" not in data:
        return jsonify({"error": "email and password required"}), 400

    password_hash = hashlib.sha256(
        data["password"].encode()
    ).hexdigest()

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT id FROM customers WHERE email = ?",
        data["email"]
    )

    if cursor.fetchone():
        return jsonify({"error": "user already exists"}), 409

    cursor.execute(
        """
        INSERT INTO customers (email, password_hash, role)
        VALUES (?, ?, 'user')
        """,
        data["email"],
        password_hash
    )

    db.commit()

    return jsonify({
        "message": "user registered",
        "email": data["email"],
        "role": "user"
    }), 201
