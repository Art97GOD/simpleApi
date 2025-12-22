from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role
import uuid
import hashlib
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
        SELECT b.id, b.client_id, b.master_id, b.total_price, b.status,
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

    # Генерируем номер счета
    invoice_id = f"INV-{datetime.now().strftime('%Y%m%d')}-{booking_id:06d}"
    payment_id = str(uuid.uuid4())

    # Создаем запись о платеже
    cursor.execute(
        """
        INSERT INTO payments 
        (invoice_id, booking_id, client_id, master_id,
         amount, currency, status, payment_method,
         description, created_at, expires_at)
        VALUES (%s, %s, %s, %s, %s, 'RUB', 'pending', 
                'card', %s, NOW(), NOW() + INTERVAL '24 hours')
        RETURNING id, invoice_id, amount, status, created_at, expires_at
        """,
        (invoice_id, booking_id, booking[1], booking[2],
         booking[3], f"Оплата услуги: {booking[5]}")
    )

    payment = cursor.fetchone()
    db.commit()

    # Генерируем URL для оплаты
    payment_url = f"https://payment.example.com/pay/{payment[0]}"

    return jsonify({
        "invoice": {
            "id": payment[0],
            "invoice_id": payment[1],
            "booking_id": booking_id,
            "amount": payment[2],
            "currency": "RUB",
            "status": payment[3],
            "created_at": payment[4],
            "expires_at": payment[5],
            "payment_url": payment_url,
            "qr_code_url": f"{payment_url}/qr"
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
    required_fields = ['payment_id', 'status', 'amount', 'currency']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"missing field: {field}"}), 400

    db = get_db()
    cursor = db.cursor()

    # Ищем платеж
    cursor.execute(
        "SELECT id, booking_id, status FROM payments WHERE id = %s",
        (data['payment_id'],)
    )

    payment = cursor.fetchone()
    if not payment:
        return jsonify({"error": "payment not found"}), 404

    # Обновляем статус платежа
    cursor.execute(
        """
        UPDATE payments 
        SET status = %s, 
            paid_at = CASE WHEN %s = 'succeeded' THEN NOW() ELSE NULL END,
            updated_at = NOW()
        WHERE id = %s
        RETURNING id, status
        """,
        (data['status'], data['status'], data['payment_id'])
    )

    updated_payment = cursor.fetchone()

    # Если платеж успешен, обновляем статус бронирования
    if data['status'] == 'succeeded':
        cursor.execute(
            """
            UPDATE bookings 
            SET status = 'in_progress', 
                payment_status = 'paid',
                paid_at = NOW(),
                updated_at = NOW()
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


@bp.route("/<string:payment_id>", methods=["GET"])
def get_payment_status(payment_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT p.id, p.invoice_id, p.booking_id, p.amount, p.currency,
               p.status, p.payment_method, p.created_at, p.paid_at, p.expires_at,
               b.booking_number, s.name as service_name,
               u.first_name as client_first_name, u.last_name as client_last_name
        FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        JOIN services s ON b.service_id = s.id
        JOIN users u ON p.client_id = u.id
        WHERE p.id = %s
        """,
        (payment_id,)
    )

    payment = cursor.fetchone()
    if not payment:
        return jsonify({"error": "payment not found"}), 404

    # Проверяем права
    if session['role'] != 'admin' and session['user_id'] not in [payment[2], payment[1]]:
        # В реальном проекте нужно проверить client_id и master_id
        return jsonify({"error": "access denied"}), 403

    return jsonify({
        "payment": {
            "id": payment[0],
            "invoice_id": payment[1],
            "booking_id": payment[2],
            "amount": payment[3],
            "currency": payment[4],
            "status": payment[5],
            "payment_method": payment[6],
            "created_at": payment[7],
            "paid_at": payment[8],
            "expires_at": payment[9],
            "booking_info": {
                "booking_number": payment[10],
                "service_name": payment[11],
                "client": {
                    "first_name": payment[12],
                    "last_name": payment[13]
                }
            }
        }
    })