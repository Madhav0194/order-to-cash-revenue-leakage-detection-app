
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "order_to_cash.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"

connection = sqlite3.connect(DB_PATH)

with open(SCHEMA_PATH, "r", encoding="utf-8") as file:
    schema = file.read()

connection.executescript(schema)

tables = connection.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name
""").fetchall()

print("Database created successfully!")
print(f"Total tables: {len(tables)}")

for table in tables:
    print(table[0])

connection.close()
