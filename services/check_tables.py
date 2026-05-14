import sqlite3

db = r"C:\Users\huzeyfe\AppData\Local\MatadorsApp\MatadorsApp_Data\local\mdfitness\db\sales.db"

con = sqlite3.connect(db)

tables = con.execute(
    "select name from sqlite_master where type='table'"
).fetchall()

print(tables)