from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role
from datetime import datetime, timedelta

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.route("/statistics", methods=["GET"])
def get_statistics():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Период для статистики
    period = request.args.get('period', 'month')  # day, week, month, year
    end_date = datetime.now()

    if period == 'day':
        start_date = end_date - timedelta(days=1)
    elif period == 'week':
        start_date = end_date - timedelta(weeks=1)
    elif period == 'month':
        start_date = end_date - timedelta(days=30)
    else:  # year
        start_date = end_date - timedelta(days=365)

    # Общая статистика
    cursor.execute(
        """
        SELECT 
            COUNT(DISTINCT u.id) as total_users,
            COUNT(DISTINCT CASE WHEN u.role = 'master' THEN u.id END) as total_masters,
            COUNT(DISTINCT CASE WHEN u.role = 'client' THEN u.id END) as total_clients,
            COUNT(DISTINCT b.id) as total_bookings,
            SUM(CASE WHEN b.status = 'completed' THEN b.total_price ELSE 0 END) as total_revenue,
            COUNT(DISTINCT CASE WHEN b.status = 'completed' THEN b.id END) as completed_bookings,
            COUNT(DISTINCT CASE WHEN b.status = 'cancelled' THEN b.id END) as cancelled_bookings
        FROM users u
        LEFT JOIN bookings b ON u.id = b.client_id OR u.id = b.master_id
        WHERE u.created_at >= %s
        """,
        (start_date,)
    )

    stats = cursor.fetchone()

    # Статистика за период
    cursor.execute(
        """
        SELECT 
            COUNT(DISTINCT u.id) as new_users,
            COUNT(DISTINCT CASE WHEN u.role = 'master' THEN u.id END) as new_masters,
            COUNT(DISTINCT b.id) as new_bookings,
            SUM(CASE WHEN b.status = 'completed' THEN b.total_price ELSE 0 END) as period_revenue
        FROM users u
        LEFT JOIN bookings b ON u.id = b.client_id OR u.id = b.master_id
        WHERE u.created_at BETWEEN %s AND %s
        """,
        (start_date, end_date)
    )

    period_stats = cursor.fetchone()

    # Активность
    cursor.execute(
        """
        SELECT 
            COUNT(DISTINCT CASE WHEN u.last_login_at >= %s THEN u.id END) as active_users,
            COUNT(DISTINCT CASE WHEN b.created_at >= %s THEN b.id END) as recent_bookings
        FROM users u
        LEFT JOIN bookings b ON u.id = b.client_id
        """,
        (end_date - timedelta(days=7), end_date - timedelta(days=7))
    )

    activity_stats = cursor.fetchone()

    return jsonify({
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "type": period
        },
        "overall": {
            "users": {
                "total": stats[0] or 0,
                "masters": stats[1] or 0,
                "clients": stats[2] or 0
            },
            "bookings": {
                "total": stats[3] or 0,
                "completed": stats[5] or 0,
                "cancelled": stats[6] or 0,
                "completion_rate": round((stats[5] or 0) / (stats[3] or 1) * 100, 2)
            },
            "revenue": stats[4] or 0
        },
        "current_period": {
            "new_users": period_stats[0] or 0,
            "new_masters": period_stats[1] or 0,
            "new_bookings": period_stats[2] or 0,
            "revenue": period_stats[3] or 0
        },
        "activity": {
            "active_users_last_7_days": activity_stats[0] or 0,
            "recent_bookings_last_7_days": activity_stats[1] or 0
        }
    })


@bp.route("/sales-report", methods=["GET"])
def get_sales_report():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date') or datetime.now().date().isoformat()

    if not start_date:
        start_date = (datetime.now() - timedelta(days=30)).date().isoformat()

    cursor.execute(
        """
        SELECT 
            DATE(b.completed_at) as date,
            COUNT(b.id) as booking_count,
            SUM(b.total_price) as daily_revenue,
            AVG(b.total_price) as avg_ticket
        FROM bookings b
        WHERE b.status = 'completed' 
        AND b.completed_at BETWEEN %s AND %s
        GROUP BY DATE(b.completed_at)
        ORDER BY date
        """,
        (start_date, end_date)
    )

    daily_sales = cursor.fetchall()

    cursor.execute(
        """
        SELECT 
            c.name as category,
            COUNT(b.id) as booking_count,
            SUM(b.total_price) as category_revenue
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN categories c ON s.category_id = c.id
        WHERE b.status = 'completed' 
        AND b.completed_at BETWEEN %s AND %s
        GROUP BY c.id, c.name
        ORDER BY category_revenue DESC
        """,
        (start_date, end_date)
    )

    by_category = cursor.fetchall()

    cursor.execute(
        """
        SELECT 
            u.first_name || ' ' || u.last_name as master_name,
            COUNT(b.id) as booking_count,
            SUM(b.total_price) as master_revenue,
            AVG(r.rating) as avg_rating
        FROM bookings b
        JOIN users u ON b.master_id = u.id
        LEFT JOIN reviews r ON b.id = r.booking_id
        WHERE b.status = 'completed' 
        AND b.completed_at BETWEEN %s AND %s
        GROUP BY u.id, u.first_name, u.last_name
        ORDER BY master_revenue DESC
        LIMIT 10
        """,
        (start_date, end_date)
    )

    top_masters = cursor.fetchall()

    return jsonify({
        "period": {
            "start": start_date,
            "end": end_date
        },
        "daily_sales": [
            {
                "date": sale[0].isoformat() if sale[0] else None,
                "booking_count": sale[1],
                "revenue": sale[2] or 0,
                "avg_ticket": float(sale[3]) if sale[3] else 0
            } for sale in daily_sales
        ],
        "by_category": [
            {
                "category": cat[0],
                "booking_count": cat[1],
                "revenue": cat[2] or 0
            } for cat in by_category
        ],
        "top_masters": [
            {
                "master": master[0],
                "booking_count": master[1],
                "revenue": master[2] or 0,
                "avg_rating": float(master[3]) if master[3] else 0
            } for master in top_masters
        ]
    })


@bp.route("/popular-services", methods=["GET"])
def get_popular_services():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    limit = int(request.args.get('limit', 10))

    cursor.execute(
        """
        SELECT 
            s.id, s.name, c.name as category,
            COUNT(b.id) as booking_count,
            SUM(b.total_price) as revenue,
            AVG(r.rating) as avg_rating,
            COUNT(DISTINCT ms.master_id) as master_count
        FROM services s
        JOIN categories c ON s.category_id = c.id
        LEFT JOIN bookings b ON s.id = b.service_id AND b.status = 'completed'
        LEFT JOIN reviews r ON s.id = r.service_id
        LEFT JOIN master_services ms ON s.id = ms.service_id AND ms.is_active = true
        WHERE s.is_active = true
        GROUP BY s.id, s.name, c.name
        ORDER BY booking_count DESC, revenue DESC
        LIMIT %s
        """,
        (limit,)
    )

    services = cursor.fetchall()

    return jsonify({
        "popular_services": [
            {
                "id": s[0],
                "name": s[1],
                "category": s[2],
                "booking_count": s[3] or 0,
                "revenue": s[4] or 0,
                "avg_rating": float(s[5]) if s[5] else 0,
                "master_count": s[6] or 0
            } for s in services
        ]
    })


@bp.route("/best-masters", methods=["GET"])
def get_best_masters():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    limit = int(request.args.get('limit', 10))

    cursor.execute(
        """
        SELECT 
            u.id, u.first_name || ' ' || u.last_name as master_name,
            m.rating, m.review_count, m.completed_orders,
            COUNT(DISTINCT b.id) as recent_bookings,
            SUM(CASE WHEN b.status = 'completed' THEN b.total_price ELSE 0 END) as recent_revenue,
            m.verification_status
        FROM users u
        JOIN master_profiles m ON u.id = m.user_id
        LEFT JOIN bookings b ON u.id = b.master_id 
            AND b.created_at >= NOW() - INTERVAL '30 days'
        WHERE u.role = 'master' AND m.is_active = true
        GROUP BY u.id, u.first_name, u.last_name, m.rating, 
                 m.review_count, m.completed_orders, m.verification_status
        ORDER BY m.rating DESC, m.completed_orders DESC
        LIMIT %s
        """,
        (limit,)
    )

    masters = cursor.fetchall()

    return jsonify({
        "best_masters": [
            {
                "id": m[0],
                "name": m[1],
                "rating": float(m[2]) if m[2] else 0,
                "review_count": m[3] or 0,
                "completed_orders": m[4] or 0,
                "recent_bookings": m[5] or 0,
                "recent_revenue": m[6] or 0,
                "verification_status": m[7]
            } for m in masters
        ]
    })


@bp.route("/booking-metrics", methods=["GET"])
def get_booking_metrics():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Конверсия по статусам
    cursor.execute(
        """
        SELECT 
            status,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
        FROM bookings
        WHERE created_at >= NOW() - INTERVAL '30 days'
        GROUP BY status
        ORDER BY count DESC
        """
    )

    status_distribution = cursor.fetchall()

    # Время от создания до подтверждения
    cursor.execute(
        """
        SELECT 
            AVG(EXTRACT(EPOCH FROM (confirmed_at - created_at)) / 3600) as avg_hours_to_confirm,
            AVG(EXTRACT(EPOCH FROM (completed_at - confirmed_at)) / 3600) as avg_hours_to_complete,
            AVG(total_price) as avg_booking_value
        FROM bookings
        WHERE status = 'completed'
        AND created_at >= NOW() - INTERVAL '30 days'
        """
    )

    time_metrics = cursor.fetchone()

    # Отмены по причине
    cursor.execute(
        """
        SELECT 
            cancellation_reason,
            COUNT(*) as count
        FROM bookings
        WHERE status = 'cancelled'
        AND cancellation_reason IS NOT NULL
        AND created_at >= NOW() - INTERVAL '30 days'
        GROUP BY cancellation_reason
        ORDER BY count DESC
        """
    )

    cancellations = cursor.fetchall()

    return jsonify({
        "metrics": {
            "status_distribution": [
                {
                    "status": s[0],
                    "count": s[1],
                    "percentage": float(s[2]) if s[2] else 0
                } for s in status_distribution
            ],
            "time_metrics": {
                "avg_hours_to_confirm": float(time_metrics[0]) if time_metrics[0] else 0,
                "avg_hours_to_complete": float(time_metrics[1]) if time_metrics[1] else 0,
                "avg_booking_value": float(time_metrics[2]) if time_metrics[2] else 0
            },
            "cancellations": [
                {
                    "reason": c[0],
                    "count": c[1]
                } for c in cancellations
            ]
        }
    })


@bp.route("/bookings", methods=["GET"])
def get_all_bookings():
    session = require_role(['admin'])
    if not session:
        return jsonify({"error": "admin access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Параметры фильтрации
    status = request.args.get('status')
    master_id = request.args.get('master_id')
    client_id = request.args.get('client_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 50))
    offset = (page - 1) * limit

    query = """
        SELECT b.id, b.booking_number, b.status, b.total_price,
               b.created_at, b.desired_date, b.desired_time_start,
               s.name as service_name,
               c.first_name as client_first_name, c.last_name as client_last_name,
               c.email as client_email, c.phone as client_phone,
               m.first_name as master_first_name, m.last_name as master_last_name,
               m.email as master_email
        FROM bookings b
        JOIN services s ON b.service_id = s.id
        JOIN users c ON b.client_id = c.id
        LEFT JOIN users m ON b.master_id = m.id
        WHERE 1=1
    """

    params = []

    if status:
        query += " AND b.status = %s"
        params.append(status)

    if master_id:
        query += " AND b.master_id = %s"
        params.append(master_id)

    if client_id:
        query += " AND b.client_id = %s"
        params.append(client_id)

    if start_date:
        query += " AND b.created_at >= %s"
        params.append(start_date)

    if end_date:
        query += " AND b.created_at <= %s"
        params.append(end_date)

    query += " ORDER BY b.created_at DESC"
    query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    cursor.execute(query, params)
    bookings = cursor.fetchall()

    # Общее количество
    count_query = query.replace(
        "SELECT b.id, b.booking_number, b.status, b.total_price,",
        "SELECT COUNT(*)"
    ).split("ORDER BY")[0]

    cursor.execute(count_query, params[:-2])  # Без limit и offset
    total = cursor.fetchone()[0]

    return jsonify({
        "bookings": [
            {
                "id": b[0],
                "booking_number": b[1],
                "status": b[2],
                "total_price": b[3],
                "created_at": b[4],
                "desired_date": b[5],
                "desired_time_start": b[6],
                "service_name": b[7],
                "client": {
                    "first_name": b[8],
                    "last_name": b[9],
                    "email": b[10],
                    "phone": b[11]
                },
                "master": {
                    "first_name": b[12],
                    "last_name": b[13],
                    "email": b[14]
                } if b[12] else None
            } for b in bookings
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })