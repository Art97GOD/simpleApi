from flask import Blueprint, request, jsonify
from app.db import get_db
from .auth import require_auth, require_role
import os
import uuid
from datetime import datetime

bp = Blueprint("upload", __name__, url_prefix="/upload")

# Конфигурация загрузки файлов
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def generate_filename(user_id, original_filename):
    ext = original_filename.rsplit('.', 1)[1].lower()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    unique_id = str(uuid.uuid4())[:8]
    return f"{user_id}_{timestamp}_{unique_id}.{ext}"


@bp.route("/avatar", methods=["POST"])
def upload_avatar():
    session = require_auth()
    if not session:
        return jsonify({"error": "authentication required"}), 401

    # Проверяем наличие файла
    if 'file' not in request.files:
        return jsonify({"error": "no file part"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "no selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "file type not allowed"}), 400

    # Проверяем размер файла
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "file too large"}), 400

    # Генерируем имя файла
    filename = generate_filename(session['user_id'], file.filename)

    # В реальном проекте здесь будет сохранение файла в S3 или файловую систему
    # Для примера просто сохраняем информацию о файле в БД

    db = get_db()
    cursor = db.cursor()

    # Сохраняем URL аватара
    avatar_url = f"/uploads/avatars/{filename}"

    cursor.execute(
        """
        UPDATE users
        SET avatar_url = %s
        WHERE id = %s RETURNING id, avatar_url
        """,
        (avatar_url, session['user_id'])
    )

    user = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "avatar uploaded successfully",
        "avatar_url": user[1]
    })


@bp.route("/portfolio", methods=["POST"])
def upload_portfolio():
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    # Проверяем наличие файла
    if 'file' not in request.files:
        return jsonify({"error": "no file part"}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({"error": "no selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "file type not allowed"}), 400

    # Проверяем размер файла
    file.seek(0, os.SEEK_END)
    file_size = file.tell()
    file.seek(0)

    if file_size > MAX_FILE_SIZE:
        return jsonify({"error": "file too large"}), 400

    # Получаем ID мастера
    cursor = get_db().cursor()
    cursor.execute(
        "SELECT id FROM masters WHERE user_id = %s",
        (session['user_id'],)
    )
    master = cursor.fetchone()
    if not master:
        return jsonify({"error": "master profile not found"}), 404

    master_id = master[0]
    cursor.close()

    # Получаем описание из формы
    description = request.form.get('description', '')
    booking_id = request.form.get('booking_id')

    # Генерируем имя файла
    filename = generate_filename(session['user_id'], file.filename)

    # В реальном проекте здесь будет сохранение файла
    file_url = f"/uploads/portfolio/{filename}"

    db = get_db()
    cursor = db.cursor()

    # Сохраняем информацию о портфолио
    cursor.execute(
        """
        INSERT INTO portfolio
            (master_id, booking_id, filename, file_url, file_type, description)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, filename, file_url, file_type, description, created_at
        """,
        (master_id, booking_id, filename, file_url,
         file.content_type, description)
    )

    portfolio_item = cursor.fetchone()
    db.commit()

    return jsonify({
        "message": "portfolio item uploaded",
        "portfolio_item": {
            "id": portfolio_item[0],
            "filename": portfolio_item[1],
            "file_url": portfolio_item[2],
            "file_type": portfolio_item[3],
            "description": portfolio_item[4],
            "created_at": portfolio_item[5]
        }
    }), 201


@bp.route("/portfolio/<int:portfolio_id>", methods=["DELETE"])
def delete_portfolio_item(portfolio_id):
    session = require_role(['master'])
    if not session:
        return jsonify({"error": "master access required"}), 403

    db = get_db()
    cursor = db.cursor()

    # Получаем ID мастера
    cursor.execute(
        "SELECT id FROM masters WHERE user_id = %s",
        (session['user_id'],)
    )
    master = cursor.fetchone()
    if not master:
        return jsonify({"error": "master profile not found"}), 404

    master_id = master[0]

    # Удаляем запись портфолио
    cursor.execute(
        """
        DELETE
        FROM portfolio
        WHERE id = %s
          AND master_id = %s RETURNING id
        """,
        (portfolio_id, master_id)
    )

    if not cursor.fetchone():
        return jsonify({"error": "portfolio item not found or access denied"}), 404

    db.commit()

    return jsonify({"message": "portfolio item deleted"})


@bp.route("/master/<int:master_id>/portfolio", methods=["GET"])
def get_master_portfolio(master_id):
    """master_id здесь это ID из таблицы masters"""
    db = get_db()
    cursor = db.cursor()

    page = int(request.args.get('page', 1))
    limit = int(request.args.get('limit', 20))
    offset = (page - 1) * limit

    cursor.execute(
        """
        SELECT p.id,
               p.filename,
               p.file_url,
               p.file_type,
               p.description,
               p.created_at,
               b.id   as booking_id,
               s.name as service_name
        FROM portfolio p
                 LEFT JOIN bookings b ON p.booking_id = b.id
                 LEFT JOIN services s ON b.service_id = s.id
        WHERE p.master_id = %s
        ORDER BY p.created_at DESC
            LIMIT %s
        OFFSET %s
        """,
        (master_id, limit, offset)
    )

    portfolio_items = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM portfolio WHERE master_id = %s",
        (master_id,)
    )
    total = cursor.fetchone()[0]

    return jsonify({
        "master_id": master_id,
        "portfolio": [
            {
                "id": p[0],
                "filename": p[1],
                "file_url": p[2],
                "file_type": p[3],
                "description": p[4],
                "created_at": p[5],
                "booking": {
                    "id": p[6],
                    "service_name": p[7]
                } if p[6] else None
            } for p in portfolio_items
        ],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": (total + limit - 1) // limit
        }
    })