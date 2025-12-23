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
               avatar_url, created_at, updated_at
        FROM users
        WHERE id = %s
        """,
        (session['user_id'],)
    )

    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "user not found"}), 404

    # Если пользователь мастер, получаем дополнительную информацию
    if user[4] == 'master':  # role
        cursor.execute(
            """
            SELECT m.id, m.description, m.experience, m.rating, 
                   m.city, m.verified, m.verified_at, m.created_at
            FROM masters m
            WHERE m.user_id = %s
            """,
            (user[0],)
        )
        master_profile = cursor.fetchone()
    else:
        master_profile = None

    # Получаем статистику
    cursor.execute(
        """
        SELECT 
            COUNT(CASE WHEN b.status = 'completed' THEN 1 END) as completed_bookings,
            COUNT(CASE WHEN b.status = 'cancelled' THEN 1 END) as cancelled_bookings,
            COUNT(CASE WHEN b.status = 'pending' THEN 1 END) as pending_bookings
        FROM bookings b
        WHERE b.client_id = %s
        """,
        (user[0],)
    )
    stats = cursor.fetchone()

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
            "updated_at": user[8],
            "master_profile": {
                "id": master_profile[0],
                "description": master_profile[1],
                "experience": master_profile[2],
                "rating": float(master_profile[3]) if master_profile[3] else 0,
                "city": master_profile[4],
                "verified": master_profile[5],
                "verified_at": master_profile[6],
                "created_at": master_profile[7]
            } if master_profile else None,
            "stats": {
                "completed_bookings": stats[0] or 0,
                "cancelled_bookings": stats[1] or 0,
                "pending_bookings": stats[2] or 0,
                "total_bookings": (stats[0] or 0) + (stats[1] or 0) + (stats[2] or 0)
            } if stats else None
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
        SET {', '.join(update_fields)}
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
               m.description, m.experience, m.city, m.rating,
               m.verified, m.verified_at
        FROM users u
        LEFT JOIN masters m ON u.id = m.user_id
        WHERE u.id = %s
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:
        return jsonify({"error": "user not found"}), 404

    response = {
        "user": {
            "id": user[0],
            "first_name": user[1],
            "last_name": user[2],
            "avatar_url": user[3],
            "role": user[4]
        }
    }

    # Если пользователь мастер, добавляем дополнительную информацию
    if user[4] == 'master' and user[5]:  # role и description
        response["user"]["master_profile"] = {
            "description": user[5],
            "experience": user[6],
            "city": user[7],
            "rating": float(user[8]) if user[8] else 0,
            "verified": user[9],
            "verified_at": user[10]
        }

        # Получаем услуги мастера
        cursor.execute(
            """
            SELECT s.id, s.name, ms.price, ms.duration
            FROM master_services ms
            JOIN services s ON ms.service_id = s.id
            JOIN masters m ON ms.master_id = m.id
            WHERE m.user_id = %s
            LIMIT 10
            """,
            (user_id,)
        )

        services = cursor.fetchall()
        if services:
            response["user"]["services"] = [
                {
                    "id": s[0],
                    "name": s[1],
                    "price": float(s[2]) if s[2] else 0,
                    "duration": s[3]
                } for s in services
            ]

    return jsonify(response)


@bp.route("/", methods=["GET"])
def get_users():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Пагинация и фильтрация
    role = request.args.get('role')
    search = request.args.get('search')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    query = """
        SELECT u.id, u.email, u.first_name, u.last_name, u.role, u.phone, 
               u.avatar_url, u.created_at
        FROM users u
        WHERE 1=1
    """
    params = []

    if role:
        query += " AND u.role = %s"
        params.append(role)

    if search:
        query += " AND (u.email LIKE %s OR u.first_name LIKE %s OR u.last_name LIKE %s)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term, search_term])

    query += " ORDER BY u.created_at DESC"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(query, params)
    users = cursor.fetchall()

    # Получаем общее количество
    count_query = "SELECT COUNT(*) FROM users WHERE 1=1"
    count_params = []

    if role:
        count_query += " AND role = %s"
        count_params.append(role)

    cursor.execute(count_query, count_params)
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
                "avatar_url": u[6],
                "created_at": u[7]
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
        SET role = %s
        WHERE id = %s
        RETURNING id, email, role
        """,
        (data["role"], user_id)
    )

    user = cursor.fetchone()
    db.commit()

    if not user:
        return jsonify({"error": "user not found"}), 404

    # Если меняем на мастера, создаем запись в masters если ее нет
    if data["role"] == 'master':
        cursor.execute(
            """
            SELECT id FROM masters WHERE user_id = %s
            """,
            (user_id,)
        )
        if not cursor.fetchone():
            cursor.execute(
                """
                INSERT INTO masters (user_id, city)
                VALUES (%s, '')
                """,
                (user_id,)
            )
            db.commit()

    return jsonify({
        "message": "role updated",
        "user": {
            "id": user[0],
            "email": user[1],
            "role": user[2]
        }
    })


@bp.route("/me/password", methods=["PUT"])
def update_password():
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    data = request.json
    if not data or "current_password" not in data or "new_password" not in data:
        return jsonify({"error": "current_password and new_password are required"}), 400

    import hashlib
    current_password_hash = hashlib.sha256(data["current_password"].encode()).hexdigest()
    new_password_hash = hashlib.sha256(data["new_password"].encode()).hexdigest()

    db = get_db()
    cursor = db.cursor()

    # Проверяем текущий пароль
    cursor.execute(
        """
        SELECT id FROM users 
        WHERE id = %s AND password = %s
        """,
        (session['user_id'], current_password_hash)
    )

    if not cursor.fetchone():
        return jsonify({"error": "current password is incorrect"}), 401

    # Обновляем пароль
    cursor.execute(
        """
        UPDATE users
        SET password = %s
        WHERE id = %s
        RETURNING id
        """,
        (new_password_hash, session['user_id'])
    )

    db.commit()

    return jsonify({"message": "password updated successfully"})