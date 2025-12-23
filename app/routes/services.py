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
               s.created_at,
               c.id as category_id, c.name as category_name,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(ms.price), s.base_price) as avg_price,
               COALESCE(AVG(r.rating), 0) as rating,
               COUNT(r.id) as review_count
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN master_services ms ON s.id = ms.service_id
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE 1=1
    """

    params = []

    if category_id:
        sql += " AND s.category_id = %s"
        params.append(category_id)

    if search:
        sql += " AND (s.name LIKE %s OR s.description LIKE %s)"
        search_term = f"%{search}%"
        params.extend([search_term, search_term])

    sql += " GROUP BY s.id, c.id"
    sql += " ORDER BY master_count DESC, rating DESC"
    sql += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(sql, params)
    services = cursor.fetchall()

    # Получаем общее количество
    count_sql = "SELECT COUNT(*) FROM services WHERE 1=1"
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
                "base_price": float(s[3]),
                "created_at": s[4],
                "category": {
                    "id": s[5],
                    "name": s[6]
                },
                "master_count": s[7],
                "avg_price": float(s[8]) if s[8] else float(s[3]),
                "rating": float(s[9]) if s[9] else 0,
                "review_count": s[10]
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
               s.created_at,
               c.id as category_id, c.name as category_name,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(ms.price), s.base_price) as avg_price,
               COALESCE(AVG(r.rating), 0) as rating,
               COUNT(r.id) as review_count
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN master_services ms ON s.id = ms.service_id
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
               m.city, m.rating, m.experience,
               ms.price, ms.duration
        FROM master_services ms
        JOIN masters m ON ms.master_id = m.id
        JOIN users u ON m.user_id = u.id
        WHERE ms.service_id = %s
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
        JOIN users u ON r.author_id = u.id
        JOIN master_services ms ON r.service_id = ms.id
        WHERE ms.service_id = %s
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
            "base_price": float(service[3]),
            "created_at": service[4],
            "category": {
                "id": service[5],
                "name": service[6]
            },
            "master_count": service[7],
            "avg_price": float(service[8]) if service[8] else float(service[3]),
            "rating": float(service[9]) if service[9] else 0,
            "review_count": service[10],
            "masters": [
                {
                    "id": m[0],
                    "first_name": m[1],
                    "last_name": m[2],
                    "avatar_url": m[3],
                    "city": m[4],
                    "rating": float(m[5]) if m[5] else 0,
                    "experience": m[6],
                    "price": float(m[7]) if m[7] else 0,
                    "duration": m[8]
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
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

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
        (name, description, category_id, base_price)
        VALUES (%s, %s, %s, %s)
        RETURNING id, name, description, category_id, base_price, created_at
        """,
        (data["name"], data.get("description", ""),
         data["category_id"], data.get("base_price", 0))
    )

    service = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "service created",
        "service": {
            "id": service[0],
            "name": service[1],
            "description": service[2],
            "category_id": service[3],
            "base_price": float(service[4]),
            "created_at": service[5]
        }
    }), 201


@bp.route("/<int:service_id>", methods=["PUT"])
def update_service(service_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "no data provided"}), 400

    db = get_db()
    cursor = db.cursor()

    # Обновляем услугу
    update_fields = []
    values = []

    if 'name' in data:
        update_fields.append("name = %s")
        values.append(data['name'])

    if 'description' in data:
        update_fields.append("description = %s")
        values.append(data['description'])

    if 'category_id' in data:
        update_fields.append("category_id = %s")
        values.append(data['category_id'])

    if 'base_price' in data:
        update_fields.append("base_price = %s")
        values.append(data['base_price'])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(service_id)

    cursor.execute(
        f"""
        UPDATE services
        SET {', '.join(update_fields)}
        WHERE id = %s
        RETURNING id, name, description, category_id, base_price, created_at
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
            "base_price": float(service[4]),
            "created_at": service[5]
        }
    })


@bp.route("/<int:service_id>", methods=["DELETE"])
def delete_service(service_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Проверяем, есть ли связанные записи
    cursor.execute(
        "SELECT COUNT(*) FROM master_services WHERE service_id = %s",
        (service_id,)
    )
    master_count = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM bookings WHERE service_id = %s",
        (service_id,)
    )
    booking_count = cursor.fetchone()[0]

    if master_count > 0 or booking_count > 0:
        return jsonify({
            "error": "cannot delete service with existing masters or bookings",
            "master_count": master_count,
            "booking_count": booking_count
        }), 400

    cursor.execute(
        "DELETE FROM services WHERE id = %s RETURNING id",
        (service_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "service not found"}), 404

    db.commit()

    return jsonify({"message": "service deleted"})


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
        LEFT JOIN master_services ms ON s.id = ms.service_id
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.name LIKE %s OR s.description LIKE %s
        GROUP BY s.id, c.id
        ORDER BY 
          CASE 
            WHEN s.name LIKE %s THEN 1
            WHEN s.description LIKE %s THEN 2
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
                "base_price": float(s[3]),
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
               s.created_at,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(r.rating), 0) as rating
        FROM services s
        LEFT JOIN master_services ms ON s.id = ms.service_id
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.category_id = %s
        GROUP BY s.id
        ORDER BY master_count DESC, rating DESC
        LIMIT %s OFFSET %s
        """,
        (category_id, limit, offset)
    )

    services = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM services WHERE category_id = %s",
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
                "base_price": float(s[3]),
                "created_at": s[4],
                "master_count": s[5],
                "rating": float(s[6]) if s[6] else 0
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
        LEFT JOIN master_services ms ON s.id = ms.service_id
        LEFT JOIN bookings b ON s.id = b.service_id 
            AND b.status = 'completed'
            AND b.created_at >= NOW() - INTERVAL '30 days'
        LEFT JOIN reviews r ON s.id = r.service_id
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
                "base_price": float(s[3]),
                "category": s[4],
                "master_count": s[5],
                "booking_count": s[6],
                "rating": float(s[7]) if s[7] else 0
            } for s in services
        ]
    })