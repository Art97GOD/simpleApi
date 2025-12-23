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
        SELECT c.id, c.name, c.description, c.icon_url,
               COUNT(DISTINCT s.id) as service_count,
               COUNT(DISTINCT ms.master_id) as master_count
        FROM categories c
        LEFT JOIN services s ON c.id = s.category_id
        LEFT JOIN master_services ms ON s.id = ms.service_id
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
                "service_count": c[4],
                "master_count": c[5]
            } for c in categories
        ]
    })


@bp.route("/<int:category_id>", methods=["GET"])
def get_category(category_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        """
        SELECT c.id, c.name, c.description, c.icon_url, c.created_at
        FROM categories c
        WHERE c.id = %s
        """,
        (category_id,)
    )

    category = cursor.fetchone()

    if not category:
        return jsonify({"error": "category not found"}), 404

    # Получаем услуги категории
    cursor.execute(
        """
        SELECT s.id, s.name, s.description, s.base_price,
               COUNT(DISTINCT ms.master_id) as master_count,
               COALESCE(AVG(r.rating), 0) as rating
        FROM services s
        LEFT JOIN master_services ms ON s.id = ms.service_id
        LEFT JOIN reviews r ON s.id = r.service_id
        WHERE s.category_id = %s
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
            "created_at": category[4]
        },
        "services": [
            {
                "id": s[0],
                "name": s[1],
                "description": s[2],
                "base_price": float(s[3]) if s[3] else 0,
                "master_count": s[4],
                "rating": float(s[5]) if s[5] else 0
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
        INSERT INTO categories (name, description, icon_url)
        VALUES (%s, %s, %s)
        RETURNING id, name, description, icon_url, created_at
        """,
        (data["name"], data.get("description", ""), data.get("icon_url"))
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
            "created_at": category[4]
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

    if 'name' in data:
        update_fields.append("name = %s")
        values.append(data['name'])

    if 'description' in data:
        update_fields.append("description = %s")
        values.append(data['description'])

    if 'icon_url' in data:
        update_fields.append("icon_url = %s")
        values.append(data['icon_url'])

    if not update_fields:
        return jsonify({"error": "no fields to update"}), 400

    values.append(category_id)

    cursor.execute(
        f"""
        UPDATE categories
        SET {', '.join(update_fields)}
        WHERE id = %s
        RETURNING id, name, description, icon_url, created_at
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
            "created_at": category[4]
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
        "SELECT COUNT(*) FROM services WHERE category_id = %s",
        (category_id,)
    )

    service_count = cursor.fetchone()[0]
    if service_count > 0:
        return jsonify({
            "error": "cannot delete category with services",
            "service_count": service_count
        }), 400

    cursor.execute(
        "DELETE FROM categories WHERE id = %s RETURNING id",
        (category_id,)
    )

    if not cursor.fetchone():
        return jsonify({"error": "category not found"}), 404

    db.commit()

    return jsonify({"message": "category deleted"})