from flask import Blueprint, request, jsonify
from app.db import get_db

bp = Blueprint("orders", __name__, url_prefix="/orders")



@bp.route("/", methods=["POST"])
def create_order():
    data = request.json

    customer_id = data.get("customer_id")
    items = data.get("items")

    if not customer_id or not items:
        return jsonify({"error": "customer_id and items required"}), 400

    db = get_db()
    cursor = db.cursor()

    total_price = 0
    order_items = []

    for item in items:
        cursor.execute(
            "SELECT price FROM products WHERE id = ?",
            item["product_id"]
        )
        product = cursor.fetchone()

        if not product:
            return jsonify({"error": f"product {item['product_id']} not found"}), 404

        price = product[0]
        item_total = price * item["quantity"]
        total_price += item_total

        order_items.append({
            "product_id": item["product_id"],
            "quantity": item["quantity"],
            "price": price
        })

    cursor.execute(
        """
        INSERT INTO orders (customer_id, total_price)
        VALUES (?, ?)
        RETURNING id
        """,
        customer_id,
        total_price
    )

    order_id = cursor.fetchone()[0]

    for item in order_items:
        cursor.execute(
            """
            INSERT INTO order_items
            (order_id, product_id, quantity, price_at_order)
            VALUES (?, ?, ?, ?)
            """,
            order_id,
            item["product_id"],
            item["quantity"],
            item["price"]
        )

    db.commit()

    return jsonify({
        "order_id": order_id,
        "total_price": float(total_price)
    }), 201



@bp.route("/<int:order_id>", methods=["GET"])
def get_order(order_id):
    db = get_db()
    cursor = db.cursor()

    cursor.execute(
        "SELECT id, customer_id, total_price, created_at FROM orders WHERE id = ?",
        order_id
    )
    order = cursor.fetchone()

    if not order:
        return jsonify({"error": "order not found"}), 404

    cursor.execute(
        """
        SELECT p.name, oi.quantity, oi.price_at_order
        FROM order_items oi
        JOIN products p ON p.id = oi.product_id
        WHERE oi.order_id = ?
        """,
        order_id
    )

    items = [
        {
            "product": row[0],
            "quantity": row[1],
            "price": float(row[2])
        }
        for row in cursor.fetchall()
    ]

    return jsonify({
        "order_id": order[0],
        "customer_id": order[1],
        "total_price": float(order[2]),
        "created_at": order[3],
        "items": items
    })
