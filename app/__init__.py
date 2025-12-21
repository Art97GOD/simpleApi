from flask import Flask
from app.db import close_db
from app.config import Config

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from app.routes import auth, customers, products, orders
    app.register_blueprint(auth.bp)
    app.register_blueprint(customers.bp)
    app.register_blueprint(products.bp)
    app.register_blueprint(orders.bp)

    app.teardown_appcontext(close_db)
    return app
