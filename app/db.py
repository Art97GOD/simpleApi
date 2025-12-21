# import pyodbc
# from flask import g
# from app.config import Config
#
# def get_db():
#     if "db" not in g:
#         g.db = pyodbc.connect(Config.DB_CONN_STR)
#     return g.db
#
# def close_db(e=None):
#     db = g.pop("db", None)
#     if db is not None:
#         db.close()


import psycopg2
from flask import g
from app.config import Config

def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(Config.conn_str)
    return g.db

def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()

