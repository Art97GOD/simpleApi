from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role
from datetime import datetime

bp = Blueprint("bookings", __name__, url_prefix="/bookings")


@bp.route("/", methods=["POST"])
def create_booking():
    # Можно создавать бронирование без авторизации
    # но для зарегистрированных пользователей связываем с аккаунтом
    data = request.json
    if not data or "service_id" not in data:
        return jsonify({"error": "service_id is required"}), 400

    if "scheduled_time" not in data:
        return jsonify({"error": "scheduled_time is required"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем существование услуги
    cursor.execute(
        "SELECT id, name, base_price FROM services WHERE id = %s",
        (data["service_id"],)
    )

    service = cursor.fetchone()
    if not service:
        return jsonify({"error": "service not found"}), 404

    # Если указан мастер, проверяем его
    master_id = data.get("master_id")
    price = service[2]  # Базовая цена услуги

    if master_id:
        # Проверяем, существует ли мастер и предоставляет ли эту услугу
        cursor.execute(
            """
            SELECT ms.price, ms.duration
            FROM master_services ms
            JOIN masters m ON ms.master_id = m.id
            JOIN users u ON m.user_id = u.id
            WHERE ms.service_id = %s AND ms.master_id = %s AND u.role = 'master'
            """,
            (data["service_id"], master_id)
        )

        master_service = cursor.fetchone()
        if master_service:
            price = master_service[0]  # Цена мастера
        else:
            return jsonify({"error": "master not found or doesn't provide this service"}), 404

    # Проверяем сессию для определения клиента
    session = require_auth()
    client_id = session['user_id'] if session else None

    # Проверяем и создаем адрес если нужно
    address_id = data.get("address_id")
    if not address_id and data.get("address"):
        # Если передан адрес, создаем запись в addresses
        cursor.execute(
            """
            INSERT INTO addresses (user_id, city, street, house, apartment, is_primary)
            VALUES (%s, %s, %s, %s, %s, true)
            RETURNING id
            """,
            (client_id if client_id else None,
             data["address"].get("city", ""),
             data["address"].get("street", ""),
             data["address"].get("house", ""),
             data["address"].get("apartment"))
        )
        address_id = cursor.fetchone()[0]

    # Создаем бронирование
    cursor.execute(
        """
        INSERT INTO bookings 
        (client_id, master_id, service_id, address_id, status, 
         problem_description, scheduled_time, price, created_at)
        VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, NOW())
        RETURNING id
        """,
        (client_id, master_id, data["service_id"], address_id,
         data.get("problem_description"), data["scheduled_time"], price)
    )

    booking_id = cursor.fetchone()[0]
    db.commit()

    return jsonify({
        "message": "booking created",
        "booking": {
            "id": booking_id,
            "status": "pending",
            "service_id": data["service_id"],
            "master_id": master_id,
            "price": float(price)
        }
    }), 201


@bp.route("/me", methods=["GET"])
def get_my_bookings():
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    db = get_db()
    cursor = db.cursor()

    # Параметры фильтрации
    status = request.args.get('status')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    query = """
        SELECT b.id, b.status, b.price,
               b.scheduled_time, b.created_at, b.completed_at,
               s.name as service_name,
               CONCAT(u.first_name, ' ', u.last_name) as master_name,
               u.avatar_url as master_avatar
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        LEFT JOIN users u ON b.master_id = u.id
        WHERE b.client_id = %s
    """
    params = [session['user_id']]

    if status:
        query += " AND b.status = %s"
        params.append(status)

    query += " ORDER BY b.created_at DESC"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(query, params)
    bookings = cursor.fetchall()

    return jsonify({
        "bookings": [
            {
                "id": b[0],
                "status": b[1],
                "price": float(b[2]),
                "scheduled_time": b[3],
                "created_at": b[4],
                "completed_at": b[5],
                "service_name": b[6],
                "master": {
                    "name": b[7],
                    "avatar_url": b[8]
                } if b[7] else None
            } for b in bookings
        ]
    })


@bp.route("/masters/me", methods=["GET"])
def get_master_bookings():
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Получаем ID мастера
    cursor.execute(
        "SELECT id FROM masters WHERE user_id = %s",
        (session['user_id'],)
    )
    master = cursor.fetchone()
    if not master:
        return jsonify({"error": "master profile not found"}), 404

    master_id = master[0]

    status = request.args.get('status')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    query = """
        SELECT b.id, b.status, b.price,
               b.scheduled_time, b.created_at,
               s.name as service_name,
               CONCAT(c.first_name, ' ', c.last_name) as client_name,
               c.phone as client_phone, c.email as client_email,
               b.problem_description,
               CONCAT(a.city, ', ', a.street, ', ', a.house, 
                      CASE WHEN a.apartment IS NOT NULL THEN ', кв. ' || a.apartment ELSE '' END) as address
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN users c ON b.client_id = c.id
        LEFT JOIN addresses a ON b.address_id = a.id
        WHERE b.master_id = %s
    """
    params = [master_id]

    if status:
        query += " AND b.status = %s"
        params.append(status)

    query += " ORDER BY b.scheduled_time"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(query, params)
    bookings = cursor.fetchall()

    return jsonify({
        "bookings": [
            {
                "id": b[0],
                "status": b[1],
                "price": float(b[2]),
                "scheduled_time": b[3],
                "created_at": b[4],
                "service_name": b[5],
                "client": {
                    "name": b[6],
                    "phone": b[7],
                    "email": b[8]
                },
                "problem_description": b[9],
                "address": b[10]
            } for b in bookings
        ]
    })


@bp.route("/<int:booking_id>", methods=["GET"])
def get_booking(booking_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT b.id, b.status, b.price,
               b.scheduled_time, b.created_at, b.completed_at,
               b.problem_description,
               s.id as service_id, s.name as service_name, s.description as service_description,
               u_master.id as master_user_id, 
               CONCAT(u_master.first_name, ' ', u_master.last_name) as master_name,
               u_master.avatar_url as master_avatar, u_master.phone as master_phone,
               m.rating as master_rating,
               u_client.id as client_id, 
               CONCAT(u_client.first_name, ' ', u_client.last_name) as client_name,
               u_client.phone as client_phone, u_client.email as client_email,
               CONCAT(a.city, ', ', a.street, ', ', a.house, 
                      CASE WHEN a.apartment IS NOT NULL THEN ', кв. ' || a.apartment ELSE '' END) as address
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        LEFT JOIN masters m ON b.master_id = m.id
        LEFT JOIN users u_master ON m.user_id = u_master.id
        JOIN users u_client ON b.client_id = u_client.id
        LEFT JOIN addresses a ON b.address_id = a.id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем права доступа
    is_admin = session['role'] == 'admin'
    is_master = session['user_id'] == booking[9] if booking[9] else False  # master_user_id
    is_client = session['user_id'] == booking[16]  # client_id

    if not (is_admin or is_master or is_client):
        return jsonify({"error": "access denied"}), 403

    return jsonify({
        "booking": {
            "id": booking[0],
            "status": booking[1],
            "price": float(booking[2]),
            "scheduled_time": booking[3],
            "created_at": booking[4],
            "completed_at": booking[5],
            "problem_description": booking[6],
            "service": {
                "id": booking[7],
                "name": booking[8],
                "description": booking[9]
            },
            "master": {
                "id": booking[10],
                "name": booking[11],
                "avatar_url": booking[12],
                "phone": booking[13],
                "rating": float(booking[14]) if booking[14] else 0
            } if booking[10] else None,
            "client": {
                "id": booking[15],
                "name": booking[16],
                "phone": booking[17],
                "email": booking[18]
            },
            "address": booking[19]
        }
    })


@bp.route("/<int:booking_id>/status", methods=["PUT"])
def update_booking_status(booking_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    data = request.json
    if not data or "status" not in data:
        return jsonify({"error": "status is required"}), 400

    valid_statuses = ['pending', 'confirmed', 'in_progress', 'completed', 'cancelled']
    if data["status"] not in valid_statuses:
        return jsonify({"error": "invalid status"}), 400

    db = get_db()
    cursor = db.cursor()

    # Получаем текущее бронирование
    cursor.execute(
        """
        SELECT b.master_id, b.client_id, b.status, m.user_id as master_user_id
        FROM bookings b
        LEFT JOIN masters m ON b.master_id = m.id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем права
    can_update = False
    new_status = data["status"]

    if session['role'] == 'admin':
        can_update = True
    elif session['role'] == 'master' and booking[3] == session['user_id']:  # master_user_id
        # Мастер может: подтвердить, начать, завершить, отменить
        if booking[2] == 'pending' and new_status in ['confirmed', 'cancelled']:
            can_update = True
        elif booking[2] == 'confirmed' and new_status == 'in_progress':
            can_update = True
        elif booking[2] == 'in_progress' and new_status == 'completed':
            can_update = True
        elif new_status == 'cancelled' and booking[2] in ['pending', 'confirmed', 'in_progress']:
            can_update = True
    elif booking[1] == session['user_id']:  # Клиент
        # Клиент может отменить pending бронирование
        if new_status == 'cancelled' and booking[2] == 'pending':
            can_update = True

    if not can_update:
        return jsonify({"error": "cannot update status"}), 403

    # Обновляем статус
    update_query = "UPDATE bookings SET status = %s"
    params = [new_status]

    if new_status == 'completed':
        update_query += ", completed_at = NOW()"

    update_query += " WHERE id = %s RETURNING id, status"
    params.append(booking_id)

    cursor.execute(update_query, params)
    updated = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "booking status updated",
        "booking": {
            "id": updated[0],
            "status": updated[1]
        }
    })


@bp.route("/<int:booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    data = request.json

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT b.master_id, b.client_id, b.status, m.user_id as master_user_id
        FROM bookings b
        LEFT JOIN masters m ON b.master_id = m.id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем права
    can_cancel = False
    if session['role'] == 'admin':
        can_cancel = True
    elif session['role'] == 'master' and booking[3] == session['user_id']:  # master_user_id
        can_cancel = True
    elif booking[1] == session['user_id']:  # Клиент
        can_cancel = booking[2] == 'pending'

    if not can_cancel:
        return jsonify({"error": "cannot cancel booking"}), 403

    # Отменяем
    cursor.execute(
        """
        UPDATE bookings 
        SET status = 'cancelled'
        WHERE id = %s
        RETURNING id
        """,
        (booking_id,)
    )

    updated = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "booking cancelled",
        "booking_id": updated[0]
    })