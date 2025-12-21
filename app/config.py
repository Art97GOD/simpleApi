import os

# class Config:
#     DB_CONN_STR = (
#         "DRIVER={PostgreSQL Unicode(x64)};"
#         "SERVER=localhost;"
#         "PORT=5432;"
#         "DATABASE=shopdb;"
#         "UID=shop_user;"
#         "PWD=shop_pass123;"
#     )
#     SECRET_KEY = "secret"
class Config:
    DB_HOST = "localhost"         # имя контейнера PostgreSQL в docker-compose
    DB_PORT = 5432
    DB_NAME = "shopdb"
    DB_USER = "shop_user"
    DB_PASSWORD = "shop_pass123"

    conn_str = f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD}"
