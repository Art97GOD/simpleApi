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
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.avatar_url,
               m.city, m.rating, m.experience_years,
               m.verification_status, m.completed_orders
        FROM users u
        JOIN master_profiles m ON u.id = m.user_id
        WHERE u.role = 'master' AND m.is_active = true
    """
    params = []

    if service_id:
        query += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = u.id 
                AND ms.service_id = %s 
                AND ms.is_active = true
            )
        """
        params.append(service_id)

    if category_id:
        query += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                JOIN services s ON ms.service_id = s.id
                WHERE ms.master_id = u.id 
                AND s.category_id = %s
                AND ms.is_active = true
            )
        """
        params.append(category_id)

    if city:
        query += " AND m.city = %s"
        params.append(city)

    if float(min_rating) > 0:
        query += " AND m.rating >= %s"
        params.append(min_rating)

    query += " ORDER BY m.rating DESC, m.completed_orders DESC"
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
            WHERE ms.master_id = %s AND ms.is_active = true
            LIMIT 3
            """,
            (master[0],)
        )

        services = cursor.fetchall()

        masters_data.append({
            "id": master[0],
            "first_name": master[1],
            "last_name": master[2],
            "avatar_url": master[3],
            "city": master[4],
            "rating": master[5],
            "experience_years": master[6],
            "verification_status": master[7],
            "completed_orders": master[8],
            "services": [
                {
                    "id": s[0],
                    "name": s[1],
                    "price": s[2]
                } for s in services
            ]
        })

    # Получаем общее количество
    count_query = """
        SELECT COUNT(DISTINCT u.id)
        FROM users u
        JOIN master_profiles m ON u.id = m.user_id
        WHERE u.role = 'master' AND m.is_active = true
    """
    count_params = []

    if service_id:
        count_query += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = u.id 
                AND ms.service_id = %s 
                AND ms.is_active = true
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
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT u.id, u.first_name, u.last_name, u.avatar_url, u.phone,
               m.description, m.experience_years, m.city, m.rating,
               m.completed_orders, m.verification_status,
               m.portfolio_photos, m.created_at as master_since
        FROM users u
        JOIN master_profiles m ON u.id = m.user_id
        WHERE u.id = %s AND u.role = 'master' AND m.is_active = true
        """,
        (master_id,)
    )

    master = cursor.fetchone()

    if not master:
        return jsonify({"error": "master not found"}), 404

    # Получаем услуги
    cursor.execute(
        """
        SELECT s.id, s.name, s.description, ms.price, ms.duration_minutes,
               c.name as category_name
        FROM master_services ms
        JOIN services s ON ms.service_id = s.id
        JOIN categories c ON s.category_id = c.id
        WHERE ms.master_id = %s AND ms.is_active = true
        """,
        (master_id,)
    )

    services = cursor.fetchall()

    # Получаем отзывы
    cursor.execute(
        """
        SELECT r.id, r.rating, r.comment, r.created_at,
               u.first_name, u.last_name, u.avatar_url
        FROM reviews r
        JOIN users u ON r.client_id = u.id
        WHERE r.master_id = %s
        ORDER BY r.created_at DESC
        LIMIT 5
        """,
        (master_id,)
    )

    reviews = cursor.fetchall()

    return jsonify({
        "master": {
            "id": master[0],
            "first_name": master[1],
            "last_name": master[2],
            "avatar_url": master[3],
            "phone": master[4],
            "profile": {
                "description": master[5],
                "experience_years": master[6],
                "city": master[7],
                "rating": master[8],
                "completed_orders": master[9],
                "verification_status": master[10],
                "portfolio_photos": master[11],
                "master_since": master[12]
            },
            "services": [
                {
                    "id": s[0],
                    "name": s[1],
                    "description": s[2],
                    "price": s[3],
                    "duration_minutes": s[4],
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
               m.description, m.experience_years, m.city, m.rating,
               m.completed_orders, m.verification_status,
               m.portfolio_photos, m.work_schedule, m.is_active
        FROM users u
        JOIN master_profiles m ON u.id = m.user_id
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
                "description": master[6],
                "experience_years": master[7],
                "city": master[8],
                "rating": master[9],
                "completed_orders": master[10],
                "verification_status": master[11],
                "portfolio_photos": master[12],
                "work_schedule": master[13],
                "is_active": master[14]
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

    # Проверяем существование профиля
    cursor.execute(
        "SELECT id FROM master_profiles WHERE user_id = %s",
        (session['user_id'],)
    )

    if not cursor.fetchone():
        # Создаем профиль если не существует
        cursor.execute(
            """
            INSERT INTO master_profiles 
            (user_id, description, experience_years, city, created_at)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (session['user_id'],
             data.get('description', ''),
             data.get('experience_years', 0),
             data.get('city', ''))
        )

    # Обновляем поля
    update_fields = []
    values = []

    fields_mapping = {
        'description': 'description',
        'experience_years': 'experience_years',
        'city': 'city',
        'work_schedule': 'work_schedule',
        'portfolio_photos': 'portfolio_photos'
    }

    for field, db_field in fields_mapping.items():
        if field in data:
            update_fields.append(f"{db_field} = %s")
            values.append(data[field])

    if update_fields:
        values.append(session['user_id'])
        cursor.execute(
            f"""
            UPDATE master_profiles
            SET {', '.join(update_fields)}, updated_at = NOW()
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
        (session['user_id'], data["service_id"])
    )

    if cursor.fetchone():
        return jsonify({"error": "service already added"}), 409

    # Добавляем услугу
    cursor.execute(
        """
        INSERT INTO master_services 
        (master_id, service_id, price, duration_minutes, description, is_active, created_at)
        VALUES (%s, %s, %s, %s, %s, true, NOW())
        RETURNING id
        """,
        (session['user_id'], data["service_id"],
         data.get("price"), data.get("duration_minutes"),
         data.get("description", ""))
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

    cursor.execute(
        """
        DELETE FROM master_services 
        WHERE master_id = %s AND service_id = %s
        RETURNING id
        """,
        (session['user_id'], service_id)
    )

    if not cursor.fetchone():
        return jsonify({"error": "service not found"}), 404

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
        SELECT DISTINCT u.id, u.first_name, u.last_name, u.avatar_url,
               m.city, m.rating, m.experience_years,
               m.verification_status, m.completed_orders
        FROM users u
        JOIN master_profiles m ON u.id = m.user_id
        WHERE u.role = 'master' AND m.is_active = true
    """

    params = []

    if query:
        sql += """
            AND (u.first_name ILIKE %s OR u.last_name ILIKE %s 
                 OR m.description ILIKE %s)
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
                WHERE ms.master_id = u.id 
                AND s.category_id = %s
                AND ms.is_active = true
            )
        """
        params.append(category_id)

    if min_price:
        sql += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = u.id 
                AND ms.price >= %s
                AND ms.is_active = true
            )
        """
        params.append(min_price)

    if max_price:
        sql += """
            AND EXISTS (
                SELECT 1 FROM master_services ms
                WHERE ms.master_id = u.id 
                AND ms.price <= %s
                AND ms.is_active = true
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
                "first_name": m[1],
                "last_name": m[2],
                "avatar_url": m[3],
                "city": m[4],
                "rating": m[5],
                "experience_years": m[6],
                "verification_status": m[7],
                "completed_orders": m[8]
            } for m in masters
        ]
    })


@bp.route("/<int:master_id>/schedule", methods=["GET"])
def get_master_schedule(master_id):
    db = get_db()
    cursor = db.cursor()

    # Проверяем существование мастера
    cursor.execute(
        "SELECT id FROM users WHERE id = %s AND role = 'master'",
        (master_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "master not found"}), 404

    # Получаем занятые слоты
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    sql = """
        SELECT booking_date, start_time, end_time, status
        FROM bookings
        WHERE master_id = %s AND status NOT IN ('cancelled', 'rejected')
    """
    params = [master_id]

    if start_date:
        sql += " AND booking_date >= %s"
        params.append(start_date)

    if end_date:
        sql += " AND booking_date <= %s"
        params.append(end_date)

    sql += " ORDER BY booking_date, start_time"

    cursor.execute(sql, params)
    slots = cursor.fetchall()

    return jsonify({
        "master_id": master_id,
        "busy_slots": [
            {
                "date": slot[0],
                "start_time": slot[1],
                "end_time": slot[2],
                "status": slot[3]
            } for slot in slots
        ]
    })


@bp.route("/<int:master_id>/verification", methods=["PUT"])
def verify_master(master_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    data = request.json
    if not data or "status" not in data:
        return jsonify({"error": "status is required"}), 400

    if data["status"] not in ['pending', 'verified', 'rejected']:
        return jsonify({"error": "invalid status"}), 400

    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        UPDATE master_profiles
        SET verification_status = %s, 
            verified_at = CASE WHEN %s = 'verified' THEN NOW() ELSE NULL END,
            verified_by = CASE WHEN %s = 'verified' THEN %s ELSE NULL END,
            updated_at = NOW()
        WHERE user_id = %s
        RETURNING user_id
        """,
        (data["status"], data["status"], data["status"],
         session['user_id'], master_id)
    )

    if not cursor.fetchone():
        return jsonify({"error": "master not found"}), 404

    db.commit()

    return jsonify({
        "message": f"master verification status updated to {data['status']}"
    })