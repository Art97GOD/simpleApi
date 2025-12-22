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

    if "desired_date" not in data or "desired_time_start" not in data:
        return jsonify({"error": "desired_date and desired_time_start are required"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем существование услуги
    cursor.execute(
        "SELECT id, name, base_price FROM services WHERE id = %s AND is_active = true",
        (data["service_id"],)
    )

    service = cursor.fetchone()
    if not service:
        return jsonify({"error": "service not found"}), 404

    # Если указан мастер, проверяем его
    master_id = data.get("master_id")
    if master_id:
        cursor.execute(
            """
            SELECT u.id, u.first_name, u.last_name, m.rating,
                   ms.price, ms.duration_minutes
            FROM users u
            JOIN master_profiles m ON u.id = m.user_id
            LEFT JOIN master_services ms ON u.id = ms.master_id AND ms.service_id = %s
            WHERE u.id = %s AND u.role = 'master' AND m.is_active = true
            """,
            (data["service_id"], master_id)
        )

        master = cursor.fetchone()
        if not master:
            return jsonify({"error": "master not found or doesn't provide this service"}), 404

        price = master[4] if master[4] else service[2]
        duration = master[5] if master[5] else 60
    else:
        # Без мастера - используем базовую цену
        price = service[2]
        duration = 60
        master_id = None

    # Проверяем сессию для определения клиента
    session = require_auth()
    client_id = session['user_id'] if session else None

    # Создаем бронирование
    cursor.execute(
        """
        INSERT INTO bookings 
        (service_id, master_id, client_id, 
         desired_date, desired_time_start, desired_time_end,
         address, problem_description, client_name, client_phone, client_email,
         status, total_price, estimated_duration, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, NOW())
        RETURNING id, booking_number
        """,
        (data["service_id"], master_id, client_id,
         data["desired_date"], data["desired_time_start"],
         data.get("desired_time_end"),
         data.get("address"), data.get("problem_description"),
         data.get("client_name"), data.get("client_phone"), data.get("client_email"),
         price, duration)
    )

    booking = cursor.fetchone()
    db.commit()

    # Генерируем номер бронирования если не сгенерировался автоматически
    booking_number = booking[1] if booking[1] else f"BK-{booking[0]:06d}"

    return jsonify({
        "message": "booking created",
        "booking": {
            "id": booking[0],
            "booking_number": booking_number,
            "status": "pending",
            "service_id": data["service_id"],
            "master_id": master_id,
            "total_price": price
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
        SELECT b.id, b.booking_number, b.status, b.total_price,
               b.desired_date, b.desired_time_start, b.created_at,
               s.name as service_name,
               u.first_name as master_first_name, u.last_name as master_last_name,
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
                "booking_number": b[1],
                "status": b[2],
                "total_price": b[3],
                "desired_date": b[4],
                "desired_time_start": b[5],
                "created_at": b[6],
                "service_name": b[7],
                "master": {
                    "first_name": b[8],
                    "last_name": b[9],
                    "avatar_url": b[10]
                } if b[8] else None
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

    status = request.args.get('status')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    query = """
        SELECT b.id, b.booking_number, b.status, b.total_price,
               b.desired_date, b.desired_time_start, b.created_at,
               s.name as service_name,
               c.first_name as client_first_name, c.last_name as client_last_name,
               c.phone as client_phone, c.email as client_email,
               b.problem_description, b.address
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN users c ON b.client_id = c.id
        WHERE b.master_id = %s
    """
    params = [session['user_id']]

    if status:
        query += " AND b.status = %s"
        params.append(status)

    query += " ORDER BY b.desired_date, b.desired_time_start"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(query, params)
    bookings = cursor.fetchall()

    return jsonify({
        "bookings": [
            {
                "id": b[0],
                "booking_number": b[1],
                "status": b[2],
                "total_price": b[3],
                "desired_date": b[4],
                "desired_time_start": b[5],
                "created_at": b[6],
                "service_name": b[7],
                "client": {
                    "first_name": b[8],
                    "last_name": b[9],
                    "phone": b[10],
                    "email": b[11]
                },
                "problem_description": b[12],
                "address": b[13]
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
        SELECT b.id, b.booking_number, b.status, b.total_price,
               b.desired_date, b.desired_time_start, b.desired_time_end,
               b.address, b.problem_description, b.created_at,
               b.confirmed_date, b.confirmed_time_start, b.completed_at,
               b.cancelled_at, b.cancellation_reason,
               s.id as service_id, s.name as service_name, s.description as service_description,
               m.id as master_id, m.first_name as master_first_name, m.last_name as master_last_name,
               m.avatar_url as master_avatar, m.phone as master_phone,
               mp.rating as master_rating,
               c.id as client_id, c.first_name as client_first_name, c.last_name as client_last_name,
               c.phone as client_phone, c.email as client_email
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        LEFT JOIN users m ON b.master_id = m.id
        LEFT JOIN master_profiles mp ON m.id = mp.user_id
        JOIN users c ON b.client_id = c.id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем права доступа
    if session['role'] != 'admin' and \
            session['user_id'] not in [booking[19], booking[27]]:  # master_id, client_id
        return jsonify({"error": "access denied"}), 403

    return jsonify({
        "booking": {
            "id": booking[0],
            "booking_number": booking[1],
            "status": booking[2],
            "total_price": booking[3],
            "dates": {
                "desired_date": booking[4],
                "desired_time_start": booking[5],
                "desired_time_end": booking[6],
                "confirmed_date": booking[10],
                "confirmed_time_start": booking[11],
                "created_at": booking[9],
                "completed_at": booking[12],
                "cancelled_at": booking[13]
            },
            "location": {
                "address": booking[7]
            },
            "problem_description": booking[8],
            "cancellation_reason": booking[14],
            "service": {
                "id": booking[15],
                "name": booking[16],
                "description": booking[17]
            },
            "master": {
                "id": booking[18],
                "first_name": booking[19],
                "last_name": booking[20],
                "avatar_url": booking[21],
                "phone": booking[22],
                "rating": booking[23]
            } if booking[18] else None,
            "client": {
                "id": booking[24],
                "first_name": booking[25],
                "last_name": booking[26],
                "phone": booking[27],
                "email": booking[28]
            }
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

    valid_statuses = ['pending', 'confirmed', 'in_progress', 'completed', 'cancelled', 'rejected']
    if data["status"] not in valid_statuses:
        return jsonify({"error": "invalid status"}), 400

    db = get_db()
    cursor = db.cursor()

    # Получаем текущее бронирование
    cursor.execute(
        "SELECT master_id, client_id, status FROM bookings WHERE id = %s",
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
    elif session['role'] == 'master' and booking[0] == session['user_id']:
        # Мастер может: подтвердить, отклонить, начать, завершить
        if booking[2] == 'pending' and new_status in ['confirmed', 'rejected']:
            can_update = True
        elif booking[2] == 'confirmed' and new_status == 'in_progress':
            can_update = True
        elif booking[2] == 'in_progress' and new_status == 'completed':
            can_update = True
        elif new_status == 'cancelled':
            can_update = True
    elif booking[1] == session['user_id']:  # Клиент
        # Клиент может только отменить
        if new_status == 'cancelled' and booking[2] in ['pending', 'confirmed']:
            can_update = True

    if not can_update:
        return jsonify({"error": "cannot update status"}), 403

    # Обновляем статус
    update_query = "UPDATE bookings SET status = %s, updated_at = NOW()"
    params = [new_status]

    if new_status == 'confirmed':
        update_query += ", confirmed_at = NOW()"
        if 'confirmed_date' in data:
            update_query += ", confirmed_date = %s"
            params.append(data['confirmed_date'])
        if 'confirmed_time_start' in data:
            update_query += ", confirmed_time_start = %s"
            params.append(data['confirmed_time_start'])
    elif new_status == 'completed':
        update_query += ", completed_at = NOW()"
    elif new_status == 'cancelled':
        update_query += ", cancelled_at = NOW()"
        if 'cancellation_reason' in data:
            update_query += ", cancellation_reason = %s"
            params.append(data['cancellation_reason'])

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
        "SELECT master_id, client_id, status FROM bookings WHERE id = %s",
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем права
    can_cancel = False
    if session['role'] == 'admin':
        can_cancel = True
    elif session['role'] == 'master' and booking[0] == session['user_id']:
        can_cancel = True
    elif booking[1] == session['user_id']:  # Клиент
        can_cancel = booking[2] in ['pending', 'confirmed']

    if not can_cancel:
        return jsonify({"error": "cannot cancel booking"}), 403

    # Отменяем
    update_query = """
        UPDATE bookings 
        SET status = 'cancelled', cancelled_at = NOW(), updated_at = NOW()
    """
    params = []

    if data and 'reason' in data:
        update_query += ", cancellation_reason = %s"
        params.append(data['reason'])

    update_query += " WHERE id = %s RETURNING id"
    params.append(booking_id)

    cursor.execute(update_query, params)
    updated = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "booking cancelled",
        "booking_id": updated[0]
    })