from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role

bp = Blueprint("users", __name__, url_prefix="/users")


@bp.route("/me", methods=["GET"])
def get_me():
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT id, email, first_name, last_name, role, phone, 
               avatar_url, created_at, last_login_at,
               is_email_verified, is_phone_verified
        FROM users
        WHERE id = %s
        """,
        (session['user_id'],)
    )

    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "user not found"}), 404

    return jsonify({
        "user": {
            "id": user[0],
            "email": user[1],
            "first_name": user[2],
            "last_name": user[3],
            "role": user[4],
            "phone": user[5],
            "avatar_url": user[6],
            "created_at": user[7],
            "last_login_at": user[8],
            "is_email_verified": user[9],
            "is_phone_verified": user[10]
        }
    })


@bp.route("/me", methods=["PUT"])
def update_me():
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "no data provided"}), 400

    db = get_db()
    cursor = db.cursor()

    # Подготовка полей для обновления
    update_fields = []
    values = []

    if "first_name" in data:
        update_fields.append("first_name = %s")
        values.append(data["first_name"])

    if "last_name" in data:
        update_fields.append("last_name = %s")
        values.append(data["last_name"])

    if "phone" in data:
        update_fields.append("phone = %s")
        values.append(data["phone"])

    if "avatar_url" in data:
        update_fields.append("avatar_url = %s")
        values.append(data["avatar_url"])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(session['user_id'])

    cursor.execute(
        f"""
        UPDATE users
        SET {', '.join(update_fields)}, updated_at = NOW()
        WHERE id = %s
        RETURNING id, email, first_name, last_name, role, phone, avatar_url
        """,
        values
    )

    user = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "profile updated",
        "user": {
            "id": user[0],
            "email": user[1],
            "first_name": user[2],
            "last_name": user[3],
            "role": user[4],
            "phone": user[5],
            "avatar_url": user[6]
        }
    })


@bp.route("/<int:user_id>", methods=["GET"])
def get_user(user_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT u.id, u.first_name, u.last_name, u.avatar_url, u.role,
               m.description, m.experience_years, m.city, m.rating,
               m.completed_orders, m.verification_status
        FROM users u
        LEFT JOIN master_profiles m ON u.id = m.user_id
        WHERE u.id = %s AND u.role = 'master'
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "master not found"}), 404

    # Получаем услуги мастера
    cursor.execute(
        """
        SELECT s.id, s.name, ms.price, ms.duration_minutes
        FROM master_services ms
        JOIN services s ON ms.service_id = s.id
        WHERE ms.master_id = %s AND ms.is_active = true
        """,
        (user_id,)
    )

    services = cursor.fetchall()

    return jsonify({
        "user": {
            "id": user[0],
            "first_name": user[1],
            "last_name": user[2],
            "avatar_url": user[3],
            "role": user[4],
            "master_profile": {
                "description": user[5],
                "experience_years": user[6],
                "city": user[7],
                "rating": user[8],
                "completed_orders": user[9],
                "verification_status": user[10]
            } if user[5] else None,
            "services": [
                {
                    "id": s[0],
                    "name": s[1],
                    "price": s[2],
                    "duration_minutes": s[3]
                } for s in services
            ]
        }
    })


@bp.route("/", methods=["GET"])
def get_users():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Пагинация
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    cursor.execute(
        """
        SELECT id, email, first_name, last_name, role, phone, 
               created_at, last_login_at
        FROM users
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset)
    )

    users = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]

    return jsonify({
        "users": [
            {
                "id": u[0],
                "email": u[1],
                "first_name": u[2],
                "last_name": u[3],
                "role": u[4],
                "phone": u[5],
                "created_at": u[6],
                "last_login_at": u[7]
            } for u in users
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })


@bp.route("/<int:user_id>/role", methods=["PUT"])
def update_role(user_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    data = request.json
    if not data or "role" not in data:
        return jsonify({"error": "role is required"}), 400

    if data["role"] not in ['client', 'master', 'admin']:
        return jsonify({"error": "invalid role"}), 400

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        UPDATE users
        SET role = %s, updated_at = NOW()
        WHERE id = %s
        RETURNING id, email, role
        """,
        (data["role"], user_id)
    )

    user = cursor.fetchone()
    db.commit()

    if not user:
        return jsonify({"error": "user not found"}), 404

    return jsonify({
        "message": "role updated",
        "user": {
            "id": user[0],
            "email": user[1],
            "role": user[2]
        }
    })