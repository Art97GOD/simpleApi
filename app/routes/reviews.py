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

    rating = int(data["rating"])
    if rating < 1 or rating > 5:
        return jsonify({"error": "rating must be between 1 and 5"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем бронирование
    cursor.execute(
        """
        SELECT b.id,
               b.client_id,
               b.master_id,
               b.service_id,
               b.status,
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
    if booking[1] != session['user_id']:  # client_id
        return jsonify({"error": "only client can leave review"}), 403

    if booking[4] != 'completed':  # status
        return jsonify({"error": "can only review completed bookings"}), 400

    if booking[5]:  # existing_review_id
        return jsonify({"error": "review already exists for this booking"}), 409

    # Получаем ID мастера и service_id из master_services
    cursor.execute(
        """
        SELECT ms.id
        FROM master_services ms
                 JOIN bookings b ON ms.master_id = b.master_id AND ms.service_id = b.service_id
        WHERE b.id = %s
        """,
        (booking_id,)
    )

    master_service = cursor.fetchone()
    if not master_service:
        return jsonify({"error": "master service not found"}), 404

    master_service_id = master_service[0]

    # Создаем отзыв
    cursor.execute(
        """
        INSERT INTO reviews
        (booking_id, author_id, master_id, service_id,
         rating, comment, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, NOW()) RETURNING id, rating, comment, created_at
        """,
        (booking_id, session['user_id'], booking[2], master_service_id,
         rating, data.get("comment", ""))
    )

    review = cursor.fetchone()

    # Обновляем рейтинг мастера
    cursor.execute(
        """
        UPDATE masters
        SET rating = (SELECT AVG(rating)
                      FROM reviews r
                               JOIN bookings b ON r.booking_id = b.id
                      WHERE b.master_id = %s)
        WHERE id = %s
        """,
        (booking[2], booking[2])
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
    """master_id здесь это ID из таблицы masters, а не user_id"""
    db = get_db()
    cursor = db.cursor()

    # Проверяем существование мастера
    cursor.execute(
        "SELECT id FROM masters WHERE id = %s",
        (master_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "master not found"}), 404

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    cursor.execute(
        """
        SELECT r.id,
               r.rating,
               r.comment,
               r.created_at,
               u.first_name,
               u.last_name,
               u.avatar_url,
               s.name as service_name
        FROM reviews r
                 JOIN users u ON r.author_id = u.id
                 JOIN master_services ms ON r.service_id = ms.id
                 JOIN services s ON ms.service_id = s.id
        WHERE r.master_id = %s
        ORDER BY r.created_at DESC
            LIMIT %s
        OFFSET %s
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
    """service_id здесь это ID из таблицы services"""
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
        SELECT r.id,
               r.rating,
               r.comment,
               r.created_at,
               u.first_name,
               u.last_name,
               u.avatar_url,
               m.first_name as master_first_name,
               m.last_name  as master_last_name
        FROM reviews r
                 JOIN users u ON r.author_id = u.id
                 JOIN master_services ms ON r.service_id = ms.id
                 JOIN masters m2 ON ms.master_id = m2.id
                 JOIN users m ON m2.user_id = m.id
                 JOIN services s ON ms.service_id = s.id
        WHERE s.id = %s
        ORDER BY r.created_at DESC
            LIMIT %s
        OFFSET %s
        """,
        (service_id, limit, offset)
    )

    reviews = cursor.fetchall()

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM reviews r
                 JOIN master_services ms ON r.service_id = ms.id
        WHERE ms.service_id = %s
        """,
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
        "SELECT id, author_id FROM reviews WHERE id = %s",
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
        rating = int(data["rating"])
        if rating < 1 or rating > 5:
            return jsonify({"error": "rating must be between 1 and 5"}), 400
        update_fields.append("rating = %s")
        values.append(rating)

    if "comment" in data:
        update_fields.append("comment = %s")
        values.append(data["comment"])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(review_id)

    cursor.execute(
        f"""
        UPDATE reviews 
        SET {', '.join(update_fields)}
        WHERE id = %s
        RETURNING id, rating, comment
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
            "comment": updated[2]
        }
    })