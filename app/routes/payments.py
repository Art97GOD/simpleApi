from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role
import uuid
from datetime import datetime

bp = Blueprint("payments", __name__, url_prefix="/payments")


@bp.route("/bookings/<int:booking_id>/invoice", methods=["POST"])
def create_invoice(booking_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    db = get_db()
    cursor = db.cursor()

    # Проверяем бронирование и права
    cursor.execute(
        """
        SELECT b.id, b.client_id, b.master_id, b.price, b.status,
               s.name as service_name,
               u.first_name as client_first_name, u.last_name as client_last_name,
               u.email as client_email, u.phone as client_phone
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN users u ON b.client_id = u.id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем права
    if session['role'] != 'admin' and session['user_id'] not in [booking[1], booking[2]]:
        return jsonify({"error": "access denied"}), 403

    if booking[4] not in ['confirmed', 'in_progress']:
        return jsonify({"error": "cannot create invoice for this booking status"}), 400

    # Генерируем номер транзакции
    transaction_id = str(uuid.uuid4())

    # Создаем запись о платеже
    cursor.execute(
        """
        INSERT INTO payments 
        (booking_id, amount, status, payment_method,
         transaction_id, created_at)
        VALUES (%s, %s, 'pending', 'card', %s, NOW())
        RETURNING id, amount, status, transaction_id, created_at
        """,
        (booking_id, booking[3], transaction_id)
    )

    payment = cursor.fetchone()
    db.commit()

    return jsonify({
        "payment": {
            "id": payment[0],
            "booking_id": booking_id,
            "amount": float(payment[1]),
            "status": payment[2],
            "transaction_id": payment[3],
            "created_at": payment[4],
            "payment_url": f"https://payment.example.com/pay/{payment[3]}"
        },
        "booking_info": {
            "service_name": booking[5],
            "client": {
                "first_name": booking[6],
                "last_name": booking[7],
                "email": booking[8],
                "phone": booking[9]
            }
        }
    }), 201


@bp.route("/webhook", methods=["POST"])
def payment_webhook():
    # Этот endpoint вызывается платежной системой
    # В реальном проекте здесь должна быть проверка подписи

    data = request.json
    if not data:
        return jsonify({"error": "no data"}), 400

    # Проверяем обязательные поля
    required_fields = ['transaction_id', 'status', 'amount']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400

    db = get_db()
    cursor = db.cursor()

    # Ищем платеж
    cursor.execute(
        "SELECT id, booking_id, status FROM payments WHERE transaction_id = %s",
        (data['transaction_id'],)
    )

    payment = cursor.fetchone()
    if not payment:
        return jsonify({"error": "payment not found"}), 404

    # Обновляем статус платежа
    cursor.execute(
        """
        UPDATE payments 
        SET status = %s, 
            paid_at = CASE WHEN %s = 'paid' THEN NOW() ELSE NULL END
        WHERE transaction_id = %s
        RETURNING id, status
        """,
        (data['status'], data['status'], data['transaction_id'])
    )

    updated_payment = cursor.fetchone()

    # Если платеж успешен, обновляем статус бронирования
    if data['status'] == 'paid':
        cursor.execute(
            """
            UPDATE bookings 
            SET status = 'in_progress'
            WHERE id = %s
            """,
            (payment[1],)
        )

    db.commit()

    return jsonify({
        "message": "webhook processed",
        "payment_id": updated_payment[0],
        "status": updated_payment[1]
    })


@bp.route("/<string:transaction_id>", methods=["GET"])
def get_payment_status(transaction_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT p.id, p.booking_id, p.amount, p.status, 
               p.payment_method, p.created_at, p.paid_at,
               b.id as booking_id, s.name as service_name,
               u.first_name as client_first_name, u.last_name as client_last_name
        FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        JOIN services s ON b.service_id = s.id
        JOIN users u ON b.client_id = u.id
        WHERE p.transaction_id = %s
        """,
        (transaction_id,)
    )

    payment = cursor.fetchone()
    if not payment:
        return jsonify({"error": "payment not found"}), 404

    # Проверяем права
    if session['role'] != 'admin' and session['user_id'] != payment[1]:
        return jsonify({"error": "access denied"}), 403

    return jsonify({
        "payment": {
            "id": payment[0],
            "booking_id": payment[1],
            "amount": float(payment[2]),
            "status": payment[3],
            "payment_method": payment[4],
            "created_at": payment[5],
            "paid_at": payment[6],
            "booking_info": {
                "id": payment[7],
                "service_name": payment[8],
                "client": {
                    "first_name": payment[9],
                    "last_name": payment[10]
                }
            }
        }
    })