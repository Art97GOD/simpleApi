from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role

bp = Blueprint("reviews", __name__, url_prefix="/reviews")


@bp.route("/bookings/<int:booking_id>/review", methods=["POST"])
def create_review(booking_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    data = request.json
    if not data or "rating" not in data:
        return jsonify({"error": "rating is required"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем бронирование
    cursor.execute(
        """
        SELECT b.id, b.client_id, b.master_id, b.service_id, b.status,
               r.id as existing_review_id
        FROM bookings b
        LEFT JOIN reviews r ON b.id = r.booking_id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    booking = cursor.fetchone()
    if not booking:
        return jsonify({"error": "booking not found"}), 404

    # Проверяем условия для отзыва
    if booking[0] != session['user_id']:  # client_id
        return jsonify({"error": "only client can leave review"}), 403

    if booking[4] != 'completed':  # status
        return jsonify({"error": "can only review completed bookings"}), 400

    if booking[5]:  # existing_review_id
        return jsonify({"error": "review already exists for this booking"}), 409

    # Создаем отзыв
    cursor.execute(
        """
        INSERT INTO reviews 
        (booking_id, client_id, master_id, service_id,
         rating, comment, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW())
        RETURNING id, rating, comment, created_at
        """,
        (booking_id, session['user_id'], booking[2], booking[3],
         data["rating"], data.get("comment", ""))
    )

    review = cursor.fetchone()

    # Обновляем рейтинг мастера
    cursor.execute(
        """
        UPDATE master_profiles 
        SET rating = (
            SELECT AVG(rating) 
            FROM reviews 
            WHERE master_id = %s
        ),
        review_count = (
            SELECT COUNT(*) 
            FROM reviews 
            WHERE master_id = %s
        ),
        updated_at = NOW()
        WHERE user_id = %s
        """,
        (booking[2], booking[2], booking[2])
    )

    # Обновляем рейтинг услуги
    cursor.execute(
        """
        UPDATE services 
        SET rating = (
            SELECT AVG(rating) 
            FROM reviews 
            WHERE service_id = %s
        ),
        review_count = (
            SELECT COUNT(*) 
            FROM reviews 
            WHERE service_id = %s
        ),
        updated_at = NOW()
        WHERE id = %s
        """,
        (booking[3], booking[3], booking[3])
    )

    db.commit()

    return jsonify({
        "message": "review created",
        "review": {
            "id": review[0],
            "rating": review[1],
            "comment": review[2],
            "created_at": review[3]
        }
    }), 201


@bp.route("/masters/<int:master_id>/reviews", methods=["GET"])
def get_master_reviews(master_id):
    db = get_db()
    cursor = db.cursor()

    # Проверяем существование мастера
    cursor.execute(
        "SELECT id FROM users WHERE id = %s AND role = 'master'",
        (master_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "master not found"}), 404

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    cursor.execute(
        """
        SELECT r.id, r.rating, r.comment, r.created_at,
               u.first_name, u.last_name, u.avatar_url,
               s.name as service_name
        FROM reviews r
        JOIN users u ON r.client_id = u.id
        JOIN services s ON r.service_id = s.id
        WHERE r.master_id = %s
        ORDER BY r.created_at DESC
        LIMIT %s OFFSET %s
        """,
        (master_id, limit, offset)
    )

    reviews = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM reviews WHERE master_id = %s",
        (master_id,)
    )
    total = cursor.fetchone()[0]

    cursor.execute(
        "SELECT AVG(rating), COUNT(*) FROM reviews WHERE master_id = %s",
        (master_id,)
    )
    stats = cursor.fetchone()

    return jsonify({
        "master_id": master_id,
        "stats": {
            "average_rating": float(stats[0]) if stats[0] else 0,
            "total_reviews": stats[1]
        },
        "reviews": [
            {
                "id": r[0],
                "rating": r[1],
                "comment": r[2],
                "created_at": r[3],
                "client": {
                    "first_name": r[4],
                    "last_name": r[5],
                    "avatar_url": r[6]
                },
                "service_name": r[7]
            } for r in reviews
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })


@bp.route("/services/<int:service_id>/reviews", methods=["GET"])
def get_service_reviews(service_id):
    db = get_db()
    cursor = db.cursor()

    # Проверяем существование услуги
    cursor.execute(
        "SELECT id FROM services WHERE id = %s",
        (service_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "service not found"}), 404

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    cursor.execute(
        """
        SELECT r.id, r.rating, r.comment, r.created_at,
               u.first_name, u.last_name, u.avatar_url,
               m.first_name as master_first_name, m.last_name as master_last_name
        FROM reviews r
        JOIN users u ON r.client_id = u.id
        JOIN users m ON r.master_id = m.id
        WHERE r.service_id = %s
        ORDER BY r.created_at DESC
        LIMIT %s OFFSET %s
        """,
        (service_id, limit, offset)
    )

    reviews = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM reviews WHERE service_id = %s",
        (service_id,)
    )
    total = cursor.fetchone()[0]

    return jsonify({
        "service_id": service_id,
        "reviews": [
            {
                "id": r[0],
                "rating": r[1],
                "comment": r[2],
                "created_at": r[3],
                "client": {
                    "first_name": r[4],
                    "last_name": r[5],
                    "avatar_url": r[6]
                },
                "master": {
                    "first_name": r[7],
                    "last_name": r[8]
                }
            } for r in reviews
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })


@bp.route("/<int:review_id>", methods=["PUT"])
def update_review(review_id):
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    data = request.json
    if not data:
        return jsonify({"error": "no data provided"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем существование отзыва и права
    cursor.execute(
        "SELECT id, client_id FROM reviews WHERE id = %s",
        (review_id,)
    )

    review = cursor.fetchone()
    if not review:
        return jsonify({"error": "review not found"}), 404

    if review[1] != session['user_id'] and session['role'] != 'admin':
        return jsonify({"error": "can only update your own reviews"}), 403

    # Обновляем отзыв
    update_fields = []
    values = []

    if "rating" in data:
        update_fields.append("rating = %s")
        values.append(data["rating"])

    if "comment" in data:
        update_fields.append("comment = %s")
        values.append(data["comment"])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(review_id)

    cursor.execute(
        f"""
        UPDATE reviews 
        SET {', '.join(update_fields)}, updated_at = NOW()
        WHERE id = %s
        RETURNING id, rating, comment, updated_at
        """,
        values
    )

    updated = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "review updated",
        "review": {
            "id": updated[0],
            "rating": updated[1],
            "comment": updated[2],
            "updated_at": updated[3]
        }
    })