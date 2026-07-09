import sqlite3
import json
import os

def seed_catalog():
    db_path = os.path.join(os.path.dirname(__file__), "database.db")
    catalog_path = os.path.join(os.path.dirname(__file__), "static", "catalog_100.json")

    if not os.path.exists(catalog_path):
        print(f"[ERROR] Catalog file not found: {catalog_path}")
        return

    with open(catalog_path, "r", encoding="utf-8") as f:
        books_data = json.load(f)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get existing book titles to avoid duplicates
    existing_titles = set(
        row[0].lower().strip() for row in cur.execute("SELECT title FROM books").fetchall()
    )

    added_count = 0
    for b in books_data:
        title = b["title"].strip()
        author = b["author"].strip()
        quantity = int(b.get("total_copies", 4))

        if title.lower() not in existing_titles:
            cur.execute(
                "INSERT INTO books (title, author, quantity) VALUES (?, ?, ?)",
                (title, author, quantity)
            )
            existing_titles.add(title.lower())
            added_count += 1

    conn.commit()
    total_books = cur.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    conn.close()

    print(f"[SUCCESS] seed_catalog: Added {added_count} new sample books.")
    print(f"[INFO] Total books in database.db: {total_books}")

if __name__ == "__main__":
    seed_catalog()
