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
        SET avatar_url = %s, updated_at = NOW()
        WHERE id = %s
        RETURNING id, avatar_url
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

    # Получаем описание из формы
    description = request.form.get('description', '')
    category = request.form.get('category', '')

    # Генерируем имя файла
    filename = generate_filename(session['user_id'], file.filename)

    # В реальном проекте здесь будет сохранение файла
    file_url = f"/uploads/portfolio/{filename}"

    db = get_db()
    cursor = db.cursor()

    # Сохраняем информацию о портфолио
    cursor.execute(
        """
        INSERT INTO portfolio_items 
        (master_id, image_url, description, category, created_at)
        VALUES (%s, %s, %s, %s, NOW())
        RETURNING id, image_url, description, category, created_at
        """,
        (session['user_id'], file_url, description, category)
    )

    portfolio_item = cursor.fetchone()

    # Обновляем список фото в профиле мастера
    cursor.execute(
        """
        UPDATE master_profiles 
        SET portfolio_photos = array_append(
            COALESCE(portfolio_photos, '{}'), 
            %s
        ),
        updated_at = NOW()
        WHERE user_id = %s
        """,
        (file_url, session['user_id'])
    )

    db.commit()

    return jsonify({
        "message": "portfolio item uploaded",
        "portfolio_item": {
            "id": portfolio_item[0],
            "image_url": portfolio_item[1],
            "description": portfolio_item[2],
            "category": portfolio_item[3],
            "created_at": portfolio_item[4]
        }
    }), 201