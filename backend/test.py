import requests, pymysql

from common import DB_CONFIG


class MyMysql:
    def __init__(self, host, port, user, password, name):
        self.conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=name,
            charset='utf8mb4'
        )
        self.cursor = self.conn.cursor()


    def query(self, sql):
        self.cursor.execute(sql)

        return self.cursor.fetchall()

db = MyMysql(DB_CONFIG["host"], DB_CONFIG["port"], DB_CONFIG["user"], DB_CONFIG["password"], DB_CONFIG["database"])
rows = db.query("SELECT * FROM users WHERE username='admin'")  
for row in rows:
    print(row)