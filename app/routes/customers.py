from flask import Blueprint, request, jsonify
from app.db import get_db
import hashlib

bp = Blueprint("customers", __name__, url_prefix="/customers")

@bp.route("/<int:customer_id>/orders", methods=["GET"])
def customer_orders(customer_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT id, total_price, created_at FROM orders WHERE customer_id = ?",
        customer_id
    )

    orders = [
        {
            "order_id": row[0],
            "total_price": float(row[1]),
            "created_at": row[2]
        }
        for row in cursor.fetchall()
    ]

    return jsonify(orders)
