from flask import Flask
from app.db import close_db
from app.config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from app.routes import admin, auth, bookings, categories, masters, payments, reviews, services, upload, users
    app.register_blueprint(admin.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(bookings.bp)
    app.register_blueprint(categories.bp)
    app.register_blueprint(masters.bp)
    app.register_blueprint(payments.bp)
    app.register_blueprint(reviews.bp)
    app.register_blueprint(services.bp)
    app.register_blueprint(upload.bp)
    app.register_blueprint(users.bp)


    app.teardown_appcontext(close_db)
    return app
