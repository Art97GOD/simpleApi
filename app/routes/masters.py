from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role

bp = Blueprint("masters", __name__, url_prefix="/masters")


@bp.route("/", methods=["GET"])
def get_masters():
    db = get_db()
    cursor = db.cursor()

    # Фильтры
    service_id = request.args.get('service_id')
    category_id = request.args.get('category_id')
    city = request.args.get('city')
    min_rating = request.args.get('min_rating', 0)
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    query = """
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.avatar_url, u.phone,
               m.city, m.rating, m.experience, m.verified, m.id as master_id
        FROM users u
        JOIN masters m ON u.id = m.user_id
        WHERE u.role = 'master'
    """
    params = []

    if service_id:
        query += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = m.id 
                AND ms.service_id = %s
            )
        """
        params.append(service_id)

    if category_id:
        query += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                JOIN services s ON ms.service_id = s.id
                WHERE ms.master_id = m.id 
                AND s.category_id = %s
            )
        """
        params.append(category_id)

    if city:
        query += " AND m.city = %s"
        params.append(city)

    if float(min_rating) > 0:
        query += " AND m.rating >= %s"
        params.append(min_rating)

    query += " ORDER BY m.rating DESC, m.experience DESC"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(query, params)
    masters = cursor.fetchall()

    # Получаем услуги для каждого мастера
    masters_data = []
    for master in masters:
        cursor.execute(
            """
            SELECT s.id, s.name, ms.price
            FROM master_services ms
            JOIN services s ON ms.service_id = s.id
            WHERE ms.master_id = %s
            LIMIT 3
            """,
            (master[9],)  # master_id
        )

        services = cursor.fetchall()

        masters_data.append({
            "id": master[0],  # user_id
            "master_id": master[9],  # master.id
            "first_name": master[1],
            "last_name": master[2],
            "avatar_url": master[3],
            "phone": master[4],
            "city": master[5],
            "rating": float(master[6]) if master[6] else 0,
            "experience": master[7],
            "verified": master[8],
            "services": [
                {
                    "id": s[0],
                    "name": s[1],
                    "price": float(s[2]) if s[2] else 0
                } for s in services
            ]
        })

    # Получаем общее количество
    count_query = """
        SELECT COUNT(DISTINCT u.id)
        FROM users u
        JOIN masters m ON u.id = m.user_id
        WHERE u.role = 'master'
    """
    count_params = []

    if service_id:
        count_query += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = m.id 
                AND ms.service_id = %s
            )
        """
        count_params.append(service_id)

    if city:
        count_query += " AND m.city = %s"
        count_params.append(city)

    cursor.execute(count_query, count_params)
    total = cursor.fetchone()[0]

    return jsonify({
        "masters": masters_data,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })


@bp.route("/<int:master_id>", methods=["GET"])
def get_master(master_id):
    """master_id здесь это user_id"""
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT u.id, u.first_name, u.last_name, u.avatar_url, u.phone, u.email,
               m.id as master_profile_id, m.description, m.experience, m.city, m.rating,
               m.verified, m.verified_at, m.created_at as master_since
        FROM users u
        JOIN masters m ON u.id = m.user_id
        WHERE u.id = %s AND u.role = 'master'
        """,
        (master_id,)
    )

    master = cursor.fetchone()

    if not master:
        return jsonify({"error": "master not found"}), 404

    # Получаем услуги
    cursor.execute(
        """
        SELECT s.id, s.name, s.description, ms.price, ms.duration,
               c.name as category_name
        FROM master_services ms
        JOIN services s ON ms.service_id = s.id
        JOIN categories c ON s.category_id = c.id
        WHERE ms.master_id = %s
        """,
        (master[6],)  # master_profile_id
    )

    services = cursor.fetchall()

    # Получаем отзывы
    cursor.execute(
        """
        SELECT r.id, r.rating, r.comment, r.created_at,
               u.first_name, u.last_name, u.avatar_url
        FROM reviews r
        JOIN users u ON r.author_id = u.id
        WHERE r.master_id = %s
        ORDER BY r.created_at DESC
        LIMIT 5
        """,
        (master[6],)  # master_profile_id
    )

    reviews = cursor.fetchall()

    return jsonify({
        "master": {
            "id": master[0],  # user_id
            "first_name": master[1],
            "last_name": master[2],
            "avatar_url": master[3],
            "phone": master[4],
            "email": master[5],
            "profile": {
                "id": master[6],
                "description": master[7],
                "experience": master[8],
                "city": master[9],
                "rating": float(master[10]) if master[10] else 0,
                "verified": master[11],
                "verified_at": master[12],
                "master_since": master[13]
            },
            "services": [
                {
                    "id": s[0],
                    "name": s[1],
                    "description": s[2],
                    "price": float(s[3]) if s[3] else 0,
                    "duration": s[4],
                    "category": s[5]
                } for s in services
            ],
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
                    }
                } for r in reviews
            ]
        }
    })


@bp.route("/me", methods=["GET"])
def get_my_master_profile():
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT u.id, u.first_name, u.last_name, u.email, u.phone, u.avatar_url,
               m.id as master_id, m.description, m.experience, m.city, m.rating,
               m.verified, m.verified_at, m.created_at
        FROM users u
        JOIN masters m ON u.id = m.user_id
        WHERE u.id = %s
        """,
        (session['user_id'],)
    )

    master = cursor.fetchone()

    if not master:
        return jsonify({"error": "master profile not found"}), 404

    return jsonify({
        "master": {
            "id": master[0],
            "first_name": master[1],
            "last_name": master[2],
            "email": master[3],
            "phone": master[4],
            "avatar_url": master[5],
            "profile": {
                "id": master[6],
                "description": master[7],
                "experience": master[8],
                "city": master[9],
                "rating": float(master[10]) if master[10] else 0,
                "verified": master[11],
                "verified_at": master[12],
                "created_at": master[13]
            }
        }
    })


@bp.route("/me", methods=["PUT"])
def update_my_master_profile():
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "no data provided"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем существование профиля мастера
    cursor.execute(
        "SELECT id FROM masters WHERE user_id = %s",
        (session['user_id'],)
    )

    master_profile = cursor.fetchone()
    if not master_profile:
        # Создаем профиль мастера если не существует
        cursor.execute(
            """
            INSERT INTO masters (user_id, description, experience, city)
            VALUES (%s, %s, %s, %s)
            """,
            (session['user_id'],
             data.get('description', ''),
             data.get('experience', 0),
             data.get('city', ''))
        )
    else:
        # Обновляем поля
        update_fields = []
        values = []

        fields_mapping = {
            'description': 'description',
            'experience': 'experience',
            'city': 'city'
        }

        for field, db_field in fields_mapping.items():
            if field in data:
                update_fields.append(f"{db_field} = %s")
                values.append(data[field])

        if update_fields:
            values.append(session['user_id'])
            cursor.execute(
                f"""
                UPDATE masters
                SET {', '.join(update_fields)}
                WHERE user_id = %s
                """,
                values
            )

    db.commit()

    return jsonify({"message": "master profile updated"})


@bp.route("/me/services", methods=["POST"])
def add_master_service():
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    data = request.json
    if not data or "service_id" not in data:
        return jsonify({"error": "service_id is required"}), 400

    db = get_db()
    cursor = db.cursor()

    # Получаем ID профиля мастера
    cursor.execute(
        "SELECT id FROM masters WHERE user_id = %s",
        (session['user_id'],)
    )
    master = cursor.fetchone()
    if not master:
        return jsonify({"error": "master profile not found"}), 404

    master_id = master[0]

    # Проверяем существование услуги
    cursor.execute(
        "SELECT id FROM services WHERE id = %s",
        (data["service_id"],)
    )

    if not cursor.fetchone():
        return jsonify({"error": "service not found"}), 404

    # Проверяем, не добавлена ли уже услуга
    cursor.execute(
        """
        SELECT id FROM master_services 
        WHERE master_id = %s AND service_id = %s
        """,
        (master_id, data["service_id"])
    )

    if cursor.fetchone():
        return jsonify({"error": "service already added"}), 409

    # Добавляем услугу
    cursor.execute(
        """
        INSERT INTO master_services 
        (master_id, service_id, price, duration)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (master_id, data["service_id"],
         data.get("price"), data.get("duration", 60))
    )

    service_id = cursor.fetchone()[0]
    db.commit()

    return jsonify({
        "message": "service added to master",
        "master_service_id": service_id
    }), 201


@bp.route("/me/services/<int:service_id>", methods=["DELETE"])
def remove_master_service(service_id):
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Получаем ID профиля мастера
    cursor.execute(
        "SELECT id FROM masters WHERE user_id = %s",
        (session['user_id'],)
    )
    master = cursor.fetchone()
    if not master:
        return jsonify({"error": "master profile not found"}), 404

    master_id = master[0]

    cursor.execute(
        """
        DELETE FROM master_services 
        WHERE master_id = %s AND service_id = %s
        RETURNING id
        """,
        (master_id, service_id)
    )

    if not cursor.fetchone():
        return jsonify({"error": "service not found in your list"}), 404

    db.commit()

    return jsonify({"message": "service removed from master"})


@bp.route("/search", methods=["GET"])
def search_masters():
    db = get_db()
    cursor = db.cursor()

    query = request.args.get('q', '')
    city = request.args.get('city')
    category_id = request.args.get('category_id')
    min_price = request.args.get('min_price')
    max_price = request.args.get('max_price')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    sql = """
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.avatar_url, u.phone,
               m.city, m.rating, m.experience, m.verified, m.id as master_id
        FROM users u
        JOIN masters m ON u.id = m.user_id
        WHERE u.role = 'master'
    """

    params = []

    if query:
        sql += """
            AND (u.first_name LIKE %s OR u.last_name LIKE %s 
                 OR m.description LIKE %s)
        """
        search_term = f"%{query}%"
        params.extend([search_term, search_term, search_term])

    if city:
        sql += " AND m.city = %s"
        params.append(city)

    if category_id:
        sql += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                JOIN services s ON ms.service_id = s.id
                WHERE ms.master_id = m.id 
                AND s.category_id = %s
            )
        """
        params.append(category_id)

    if min_price:
        sql += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = m.id 
                AND ms.price >= %s
            )
        """
        params.append(min_price)

    if max_price:
        sql += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = m.id 
                AND ms.price <= %s
            )
        """
        params.append(max_price)

    sql += " ORDER BY m.rating DESC"
    sql += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(sql, params)
    masters = cursor.fetchall()

    return jsonify({
        "masters": [
            {
                "id": m[0],
                "master_id": m[9],
                "first_name": m[1],
                "last_name": m[2],
                "avatar_url": m[3],
                "phone": m[4],
                "city": m[5],
                "rating": float(m[6]) if m[6] else 0,
                "experience": m[7],
                "verified": m[8]
            } for m in masters
        ]
    })


@bp.route("/<int:master_id>/schedule", methods=["GET"])
def get_master_schedule(master_id):
    """master_id здесь это user_id"""
    db = get_db()
    cursor = db.cursor()

    # Получаем ID профиля мастера
    cursor.execute(
        "SELECT m.id FROM masters m WHERE m.user_id = %s",
        (master_id,)
    )
    master = cursor.fetchone()
    if not master:
        return jsonify({"error": "master not found"}), 404

    master_profile_id = master[0]

    # Получаем занятые слоты
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    sql = """
        SELECT b.scheduled_time, s.duration
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        WHERE b.master_id = %s AND b.status NOT IN ('cancelled')
    """
    params = [master_profile_id]

    if start_date:
        sql += " AND DATE(b.scheduled_time) >= %s"
        params.append(start_date)

    if end_date:
        sql += " AND DATE(b.scheduled_time) <= %s"
        params.append(end_date)

    sql += " ORDER BY b.scheduled_time"

    cursor.execute(sql, params)
    bookings = cursor.fetchall()

    return jsonify({
        "master_id": master_id,
        "busy_slots": [
            {
                "time": booking[0],
                "duration": booking[1]
            } for booking in bookings
        ]
    })


@bp.route("/<int:user_id>/verification", methods=["PUT"])
def verify_master(user_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    data = request.json
    if not data or "verified" not in data:
        return jsonify({"error": "verified status is required"}), 400

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        UPDATE masters
        SET verified = %s, 
            verified_at = CASE WHEN %s = true THEN NOW() ELSE NULL END
        WHERE user_id = %s
        RETURNING verified, verified_at
        """,
        (data["verified"], data["verified"], user_id)
    )

    result = cursor.fetchone()
    if not result:
        return jsonify({"error": "master not found"}), 404

    db.commit()

    return jsonify({
        "message": f"master verification {'enabled' if result[0] else 'disabled'}",
        "verified": result[0],
        "verified_at": result[1]
    })