from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role

bp = Blueprint("services", __name__, url_prefix="/services")


@bp.route("/", methods=["GET"])
def get_services():
    db = get_db()
    cursor = db.cursor()

    # Параметры пагинации и фильтрации
    category_id = request.args.get('category_id')
    search = request.args.get('search')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    sql = """
        SELECT s.id, s.name, s.description, s.base_price, 
               s.duration_minutes, s.is_active, s.created_at,
               c.id as category_id, c.name as category_name,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(ms.price), s.base_price) as avg_price,
               COALESCE(AVG(r.rating), 0) as rating,
               COUNT(r.id) as review_count
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.is_active = true
    """

    params = []

    if category_id:
        sql += " AND s.category_id = %s"
        params.append(category_id)

    if search:
        sql += " AND (s.name ILIKE %s OR s.description ILIKE %s)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])

    sql += " GROUP BY s.id, c.id"
    sql += " ORDER BY master_count DESC, rating DESC"
    sql += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(sql, params)
    services = cursor.fetchall()

    # Получаем общее количество
    count_sql = "SELECT COUNT(*) FROM services WHERE is_active = true"
    count_params = []

    if category_id:
        count_sql += " AND category_id = %s"
        count_params.append(category_id)

    cursor.execute(count_sql, count_params)
    total = cursor.fetchone()[0]

    return jsonify({
        "services": [
            {
                "id": s[0],
                "name": s[1],
                "description": s[2],
                "base_price": s[3],
                "duration_minutes": s[4],
                "is_active": s[5],
                "created_at": s[6],
                "category": {
                    "id": s[7],
                    "name": s[8]
                },
                "master_count": s[9],
                "avg_price": float(s[10]) if s[10] else s[3],
                "rating": float(s[11]) if s[11] else 0,
                "review_count": s[12]
            } for s in services
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })


@bp.route("/<int:service_id>", methods=["GET"])
def get_service(service_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT s.id, s.name, s.description, s.base_price, 
               s.duration_minutes, s.is_active, s.created_at,
               c.id as category_id, c.name as category_name,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(ms.price), s.base_price) as avg_price,
               COALESCE(AVG(r.rating), 0) as rating,
               COUNT(r.id) as review_count
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.id = %s
        GROUP BY s.id, c.id
        """,
        (service_id,)
    )

    service = cursor.fetchone()

    if not service:
        return jsonify({"error": "service not found"}), 404

    # Получаем мастеров, оказывающих эту услугу
    cursor.execute(
        """
        SELECT u.id, u.first_name, u.last_name, u.avatar_url,
               m.city, m.rating, m.experience_years,
               ms.price, ms.duration_minutes, ms.description as master_description
        FROM master_services ms
        JOIN users u ON ms.master_id = u.id
        JOIN master_profiles m ON u.id = m.user_id
        WHERE ms.service_id = %s AND ms.is_active = true
        AND u.role = 'master' AND m.is_active = true
        ORDER BY m.rating DESC, ms.price
        LIMIT 10
        """,
        (service_id,)
    )

    masters = cursor.fetchall()

    # Получаем последние отзывы
    cursor.execute(
        """
        SELECT r.id, r.rating, r.comment, r.created_at,
               u.first_name, u.last_name, u.avatar_url
        FROM reviews r
        JOIN users u ON r.client_id = u.id
        WHERE r.service_id = %s
        ORDER BY r.created_at DESC
        LIMIT 5
        """,
        (service_id,)
    )

    reviews = cursor.fetchall()

    return jsonify({
        "service": {
            "id": service[0],
            "name": service[1],
            "description": service[2],
            "base_price": service[3],
            "duration_minutes": service[4],
            "is_active": service[5],
            "created_at": service[6],
            "category": {
                "id": service[7],
                "name": service[8]
            },
            "master_count": service[9],
            "avg_price": float(service[10]) if service[10] else service[3],
            "rating": float(service[11]) if service[11] else 0,
            "review_count": service[12],
            "masters": [
                {
                    "id": m[0],
                    "first_name": m[1],
                    "last_name": m[2],
                    "avatar_url": m[3],
                    "city": m[4],
                    "rating": m[5],
                    "experience_years": m[6],
                    "price": m[7],
                    "duration_minutes": m[8],
                    "description": m[9]
                } for m in masters
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


@bp.route("/", methods=["POST"])
def create_service():
    session = require_role(['admin', 'master'])
    if not session:
        return jsonify({"error": "admin or master access required"}), 403

    data = request.json
    if not data or "name" not in data or "category_id" not in data:
        return jsonify({"error": "name and category_id are required"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем существование категории
    cursor.execute(
        "SELECT id FROM categories WHERE id = %s",
        (data["category_id"],)
    )

    if not cursor.fetchone():
        return jsonify({"error": "category not found"}), 404

    # Создаем услугу
    cursor.execute(
        """
        INSERT INTO services 
        (name, description, category_id, base_price, duration_minutes, 
         is_active, created_by, created_at)
        VALUES (%s, %s, %s, %s, %s, true, %s, NOW())
        RETURNING id, name, description, category_id, base_price, 
                  duration_minutes, is_active, created_at
        """,
        (data["name"], data.get("description", ""),
         data["category_id"], data.get("base_price", 0),
         data.get("duration_minutes", 60),
         session['user_id'])
    )

    service = cursor.fetchone()
    db.commit()

    # Если создал мастер, автоматически добавляем услугу к нему
    if session['role'] == 'master':
        cursor.execute(
            """
            INSERT INTO master_services 
            (master_id, service_id, price, duration_minutes, description, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, true, NOW())
            """,
            (session['user_id'], service[0],
             data.get("price", data.get("base_price", 0)),
             data.get("duration_minutes", 60),
             data.get("description", ""))
        )
        db.commit()

    return jsonify({
        "message": "service created",
        "service": {
            "id": service[0],
            "name": service[1],
            "description": service[2],
            "category_id": service[3],
            "base_price": service[4],
            "duration_minutes": service[5],
            "is_active": service[6],
            "created_at": service[7]
        }
    }), 201


@bp.route("/<int:service_id>", methods=["PUT"])
def update_service(service_id):
    session = require_role(['admin', 'master'])
    if not session:
        return jsonify({"error": "admin or master access required"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "no data provided"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем права доступа
    if session['role'] == 'master':
        # Мастер может обновлять только свои услуги
        cursor.execute(
            """
            SELECT 1 FROM master_services 
            WHERE master_id = %s AND service_id = %s
            """,
            (session['user_id'], service_id)
        )
        if not cursor.fetchone():
            return jsonify({"error": "access denied"}), 403

    # Обновляем услугу
    update_fields = []
    values = []

    fields_mapping = {
        'name': 'name',
        'description': 'description',
        'category_id': 'category_id',
        'base_price': 'base_price',
        'duration_minutes': 'duration_minutes',
        'is_active': 'is_active'
    }

    for field, db_field in fields_mapping.items():
        if field in data:
            update_fields.append(f"{db_field} = %s")
            values.append(data[field])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(service_id)

    cursor.execute(
        f"""
        UPDATE services
        SET {', '.join(update_fields)}, updated_at = NOW()
        WHERE id = %s
        RETURNING id, name, description, category_id, base_price, 
                  duration_minutes, is_active, updated_at
        """,
        values
    )

    service = cursor.fetchone()
    db.commit()

    if not service:
        return jsonify({"error": "service not found"}), 404

    return jsonify({
        "message": "service updated",
        "service": {
            "id": service[0],
            "name": service[1],
            "description": service[2],
            "category_id": service[3],
            "base_price": service[4],
            "duration_minutes": service[5],
            "is_active": service[6],
            "updated_at": service[7]
        }
    })


@bp.route("/<int:service_id>", methods=["DELETE"])
def delete_service(service_id):
    session = require_role(['admin', 'master'])
    if not session:
        return jsonify({"error": "admin or master access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Проверяем права доступа
    if session['role'] == 'master':
        # Мастер может удалять только свои услуги из своего списка
        cursor.execute(
            """
            DELETE FROM master_services 
            WHERE master_id = %s AND service_id = %s
            RETURNING id
            """,
            (session['user_id'], service_id)
        )

        if not cursor.fetchone():
            return jsonify({"error": "service not found in your list"}), 404

        db.commit()
        return jsonify({"message": "service removed from your list"})

    # Админ удаляет услугу полностью
    cursor.execute(
        "UPDATE services SET is_active = false WHERE id = %s RETURNING id",
        (service_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "service not found"}), 404

    db.commit()

    return jsonify({"message": "service deactivated"})


@bp.route("/search", methods=["GET"])
def search_services():
    db = get_db()
    cursor = db.cursor()

    query = request.args.get('q', '')
    if not query:
        return jsonify({"error": "search query is required"}), 400

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    search_term = f"%{query}%"

    cursor.execute(
        """
        SELECT s.id, s.name, s.description, s.base_price, 
               c.name as category_name,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(r.rating), 0) as rating
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.is_active = true 
        AND (s.name ILIKE %s OR s.description ILIKE %s)
        GROUP BY s.id, c.id
        ORDER BY 
          CASE 
            WHEN s.name ILIKE %s THEN 1
            WHEN s.description ILIKE %s THEN 2
            ELSE 3
          END,
          master_count DESC
        LIMIT %s OFFSET %s
        """,
        (search_term, search_term, f"{query}%", search_term, limit, offset)
    )

    services = cursor.fetchall()

    return jsonify({
        "services": [
            {
                "id": s[0],
                "name": s[1],
                "description": s[2],
                "base_price": s[3],
                "category": s[4],
                "master_count": s[5],
                "rating": float(s[6]) if s[6] else 0
            } for s in services
        ]
    })


@bp.route("/category/<int:category_id>", methods=["GET"])
def get_services_by_category(category_id):
    db = get_db()
    cursor = db.cursor()

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    # Проверяем существование категории
    cursor.execute(
        "SELECT name FROM categories WHERE id = %s",
        (category_id,)
    )

    category = cursor.fetchone()
    if not category:
        return jsonify({"error": "category not found"}), 404

    cursor.execute(
        """
        SELECT s.id, s.name, s.description, s.base_price, 
               s.duration_minutes, s.created_at,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(r.rating), 0) as rating
        FROM services s
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.category_id = %s AND s.is_active = true
        GROUP BY s.id
        ORDER BY master_count DESC, rating DESC
        LIMIT %s OFFSET %s
        """,
        (category_id, limit, offset)
    )

    services = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM services WHERE category_id = %s AND is_active = true",
        (category_id,)
    )
    total = cursor.fetchone()[0]

    return jsonify({
        "category": {
            "id": category_id,
            "name": category[0]
        },
        "services": [
            {
                "id": s[0],
                "name": s[1],
                "description": s[2],
                "base_price": s[3],
                "duration_minutes": s[4],
                "created_at": s[5],
                "master_count": s[6],
                "rating": float(s[7]) if s[7] else 0
            } for s in services
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })


@bp.route("/popular", methods=["GET"])
def get_popular_services():
    db = get_db()
    cursor = db.cursor()

    limit = int(request.args.get('limit', 10))

    cursor.execute(
        """
        SELECT s.id, s.name, s.description, s.base_price,
               c.name as category_name,
               COUNT(DISTINCT ms.master_id) as master_count,
               COUNT(DISTINCT b.id) as booking_count,
               COALESCE(AVG(r.rating), 0) as rating
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        LEFT JOIN bookings b ON s.id = b.service_id 
            AND b.status = 'completed'
            AND b.created_at >= NOW() - INTERVAL '30 days'
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.is_active = true
        GROUP BY s.id, c.id
        ORDER BY booking_count DESC, master_count DESC
        LIMIT %s
        """,
        (limit,)
    )

    services = cursor.fetchall()

    return jsonify({
        "services": [
            {
                "id": s[0],
                "name": s[1],
                "description": s[2],
                "base_price": s[3],
                "category": s[4],
                "master_count": s[5],
                "booking_count": s[6],
                "rating": float(s[7]) if s[7] else 0
            } for s in services
        ]
    })