from flask import request, jsonify
from functools import wraps

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        role = request.headers.get("Role")
        if role != "admin":
            return jsonify({"error": "Admin only"}), 403
        return func(*args, **kwargs)
    return wrapper
