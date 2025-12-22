from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role

bp = Blueprint("categories", __name__, url_prefix="/categories")


@bp.route("/", methods=["GET"])
def get_categories():
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT c.id, c.name, c.description, c.icon_url, c.is_active,
               COUNT(DISTINCT s.id) as service_count,
               COUNT(DISTINCT ms.master_id) as master_count
        FROM categories c
        LEFT JOIN services s ON c.id = s.category_id AND s.is_active = true
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        WHERE c.is_active = true
        GROUP BY c.id
        ORDER BY service_count DESC, c.name
        """
    )

    categories = cursor.fetchall()

    return jsonify({
        "categories": [
            {
                "id": c[0],
                "name": c[1],
                "description": c[2],
                "icon_url": c[3],
                "is_active": c[4],
                "service_count": c[5],
                "master_count": c[6]
            } for c in categories
        ]
    })


@bp.route("/<int:category_id>", methods=["GET"])
def get_category(category_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT c.id, c.name, c.description, c.icon_url, c.is_active, c.created_at
        FROM categories c
        WHERE c.id = %s AND c.is_active = true
        """,
        (category_id,)
    )

    category = cursor.fetchone()

    if not category:
        return jsonify({"error": "category not found"}), 404

    # Получаем услуги категории
    cursor.execute(
        """
        SELECT s.id, s.name, s.description, s.base_price, s.duration_minutes,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(r.rating), 0) as rating
        FROM services s
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.category_id = %s AND s.is_active = true
        GROUP BY s.id
        ORDER BY master_count DESC
        LIMIT 20
        """,
        (category_id,)
    )

    services = cursor.fetchall()

    return jsonify({
        "category": {
            "id": category[0],
            "name": category[1],
            "description": category[2],
            "icon_url": category[3],
            "is_active": category[4],
            "created_at": category[5]
        },
        "services": [
            {
                "id": s[0],
                "name": s[1],
                "description": s[2],
                "base_price": s[3],
                "duration_minutes": s[4],
                "master_count": s[5],
                "rating": float(s[6]) if s[6] else 0
            } for s in services
        ]
    })


@bp.route("/", methods=["POST"])
def create_category():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    data = request.json
    if not data or "name" not in data:
        return jsonify({"error": "name is required"}), 400

    db = get_db()
    cursor = db.cursor()

    # Проверяем существование категории с таким именем
    cursor.execute(
        "SELECT id FROM categories WHERE name = %s",
        (data["name"],)
    )

    if cursor.fetchone():
        return jsonify({"error": "category with this name already exists"}), 409

    cursor.execute(
        """
        INSERT INTO categories 
        (name, description, icon_url, is_active, created_by, created_at)
        VALUES (%s, %s, %s, true, %s, NOW())
        RETURNING id, name, description, icon_url, is_active, created_at
        """,
        (data["name"], data.get("description", ""),
         data.get("icon_url"), session['user_id'])
    )

    category = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "category created",
        "category": {
            "id": category[0],
            "name": category[1],
            "description": category[2],
            "icon_url": category[3],
            "is_active": category[4],
            "created_at": category[5]
        }
    }), 201


@bp.route("/<int:category_id>", methods=["PUT"])
def update_category(category_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    data = request.json
    if not data:
        return jsonify({"error": "no data provided"}), 400

    db = get_db()
    cursor = db.cursor()

    update_fields = []
    values = []

    fields_mapping = {
        'name': 'name',
        'description': 'description',
        'icon_url': 'icon_url',
        'is_active': 'is_active'
    }

    for field, db_field in fields_mapping.items():
        if field in data:
            update_fields.append(f"{db_field} = %s")
            values.append(data[field])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(category_id)

    cursor.execute(
        f"""
        UPDATE categories
        SET {', '.join(update_fields)}, updated_at = NOW()
        WHERE id = %s
        RETURNING id, name, description, icon_url, is_active, updated_at
        """,
        values
    )

    category = cursor.fetchone()
    db.commit()

    if not category:
        return jsonify({"error": "category not found"}), 404

    return jsonify({
        "message": "category updated",
        "category": {
            "id": category[0],
            "name": category[1],
            "description": category[2],
            "icon_url": category[3],
            "is_active": category[4],
            "updated_at": category[5]
        }
    })


@bp.route("/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Проверяем, есть ли услуги в этой категории
    cursor.execute(
        "SELECT COUNT(*) FROM services WHERE category_id = %s AND is_active = true",
        (category_id,)
    )

    service_count = cursor.fetchone()[0]
    if service_count > 0:
        return jsonify({
            "error": "cannot delete category with active services",
            "service_count": service_count
        }), 400

    cursor.execute(
        "UPDATE categories SET is_active = false WHERE id = %s RETURNING id",
        (category_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "category not found"}), 404

    db.commit()

    return jsonify({"message": "category deactivated"})