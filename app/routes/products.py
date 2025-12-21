from flask import Blueprint, request, jsonify
from app.db import get_db
from app.utils.decorators import admin_required

bp = Blueprint("products", __name__, url_prefix="/products")

# @bp.route("/", methods=["POST"])
# @admin_required
# def create_product():
#     data = request.json
#     db = get_db()
#     cursor = db.cursor()
#
#     cursor.execute(
#         "INSERT INTO products (name, price, quantity) VALUES (?, ?, ?)",
#         data["name"], data["price"], data.get("quantity", 0)
#     )
#     db.commit()
#
#     return jsonify({"status": "product created"})


@bp.route("/", methods=["POST"])
@admin_required
def create_product():
    data = request.json
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "INSERT INTO products (name, price, quantity) VALUES (%s, %s, %s)",
        (data["name"], data["price"], data.get("quantity", 0))
    )
    db.commit()

    return jsonify({"status": "product created"})
