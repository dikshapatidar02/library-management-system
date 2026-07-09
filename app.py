"""
Library Book Tracking System
A Flask-based web application for managing library books, members, and transactions.
Run with: python app.py
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, jsonify)
import sqlite3
from datetime import datetime, date
from functools import wraps

app = Flask(__name__)
app.secret_key = "library_secret_key_2024"
import os
import shutil

# On Vercel / Serverless environments, the root directory is read-only at runtime.
# We redirect to /tmp/database.db where SQLite can read and write freely.
if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME") or os.path.exists("/var/task"):
    DATABASE = "/tmp/database.db"
    if not os.path.exists(DATABASE):
        src_db = os.path.join(os.path.dirname(__file__), "database.db")
        if os.path.exists(src_db):
            try:
                shutil.copyfile(src_db, DATABASE)
            except Exception as e:
                print(f"[WARN] Could not copy database to /tmp: {e}")
else:
    DATABASE = "database.db"

# ─────────────────────────────────────────────
# DATABASE HELPERS
# ─────────────────────────────────────────────

def get_db():
    """Open a new database connection, ensuring tables exist if needed."""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row   # Return rows as dict-like objects
    conn.execute("PRAGMA foreign_keys = ON")
    return conn



def init_db():
    """Create all tables and seed an admin account if needed."""
    conn = get_db()
    cur = conn.cursor()

    # Books table (no ISBN)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS books (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            title    TEXT    NOT NULL,
            author   TEXT    NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Members table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS members (
            id    INTEGER PRIMARY KEY AUTOINCREMENT,
            name  TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL
        )
    """)

    # Transactions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id     INTEGER NOT NULL REFERENCES books(id),
            member_id   INTEGER NOT NULL REFERENCES members(id),
            issue_date  TEXT NOT NULL,
            return_date TEXT,
            status      TEXT NOT NULL DEFAULT 'issued'
        )
    """)

    # Admin table (for login)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    # Seed default admin  (username: admin | password: admin123)
    cur.execute("""
        INSERT OR IGNORE INTO admins (username, password)
        VALUES ('admin', 'admin123')
    """)

    conn.commit()
    conn.close()


def migrate_db():
    """Remove the isbn column from books if it still exists (SQLite-compatible)."""
    conn = get_db()
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(books)").fetchall()]
        if "isbn" not in cols:
            return  # Already migrated

        # SQLite <3.35 doesn't support DROP COLUMN — rebuild the table instead
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS books_new (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                title    TEXT    NOT NULL,
                author   TEXT    NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("""
            INSERT INTO books_new (id, title, author, quantity)
            SELECT id, title, author, quantity FROM books
        """)
        conn.execute("DROP TABLE books")
        conn.execute("ALTER TABLE books_new RENAME TO books")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        print("[OK] migrate_db: isbn column removed from books table.")
    except Exception as e:
        conn.rollback()
        print(f"[WARN] migrate_db failed: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# AUTH HELPERS
# ─────────────────────────────────────────────

def login_required(f):
    """Decorator: redirect to login if user is not authenticated."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────
# ERROR HANDLERS
# ─────────────────────────────────────────────

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def internal_error(e):
    return render_template("500.html"), 500


# ─────────────────────────────────────────────
# AUTH ROUTES
# ─────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            flash("Username and password are required.", "danger")
            return render_template("login.html")
        conn = get_db()
        try:
            admin = conn.execute(
                "SELECT * FROM admins WHERE username=? AND password=?",
                (username, password)
            ).fetchone()
        finally:
            conn.close()
        if admin:
            session["logged_in"] = True
            session["username"] = username
            flash("Welcome back, " + username + "!", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@app.route("/")
@login_required
def index():
    """Home dashboard with summary statistics."""
    conn = get_db()
    try:
        total_books   = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        total_members = conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        issued_books  = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE status='issued'"
        ).fetchone()[0]

        overdue = conn.execute("""
            SELECT COUNT(*) FROM transactions
            WHERE status='issued'
              AND julianday(date('now', 'localtime')) - julianday(issue_date) > 14
        """).fetchone()[0]

        recent = conn.execute("""
            SELECT t.id, b.title, m.name, t.issue_date, t.status
            FROM transactions t
            JOIN books   b ON b.id = t.book_id
            JOIN members m ON m.id = t.member_id
            ORDER BY t.id DESC LIMIT 5
        """).fetchall()
    finally:
        conn.close()

    return render_template(
        "index.html",
        total_books=total_books,
        total_members=total_members,
        issued_books=issued_books,
        overdue=overdue,
        recent=recent
    )


# ─────────────────────────────────────────────
# JSON API
# ─────────────────────────────────────────────

@app.route("/api/books/search")
@login_required
def api_books_search():
    """Return books matching a query as JSON (for autocomplete)."""
    q = request.args.get("q", "").strip()
    conn = get_db()
    try:
        if q:
            rows = conn.execute(
                "SELECT id, title, author, quantity FROM books WHERE title LIKE ? OR author LIKE ?",
                (f"%{q}%", f"%{q}%")
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, title, author, quantity FROM books"
            ).fetchall()
    finally:
        conn.close()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────
# BOOK ROUTES
# ─────────────────────────────────────────────

@app.route("/recommendations")
@login_required
def recommendations():
    """Display modern book browsing interface across curated categories."""
    conn = get_db()
    try:
        books = conn.execute("SELECT * FROM books").fetchall()
    finally:
        conn.close()
    return render_template("recommendations.html", books=books)


@app.route("/books")
@login_required
def view_books():
    """Display all books; supports optional search query."""
    query = request.args.get("q", "").strip()
    conn  = get_db()
    try:
        if query:
            books = conn.execute(
                "SELECT * FROM books WHERE title LIKE ? OR author LIKE ?",
                (f"%{query}%", f"%{query}%")
            ).fetchall()
        else:
            books = conn.execute("SELECT * FROM books").fetchall()
    finally:
        conn.close()
    return render_template("view_books.html", books=books, query=query)


@app.route("/books/add", methods=["GET", "POST"])
@login_required
def add_book():
    """Add a new book to the library."""
    if request.method == "POST":
        title    = request.form.get("title", "").strip()
        author   = request.form.get("author", "").strip()
        qty_raw  = request.form.get("quantity", "").strip()

        # Validate
        errors = []
        if not title:
            errors.append("Book title is required.")
        if not author:
            errors.append("Author is required.")
        try:
            quantity = int(qty_raw)
            if quantity < 0:
                errors.append("Quantity cannot be negative.")
        except ValueError:
            errors.append("Quantity must be a whole number.")
            quantity = 1

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("add_book.html",
                                   form_title=title, form_author=author,
                                   form_quantity=qty_raw)

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO books (title, author, quantity) VALUES (?, ?, ?)",
                (title, author, quantity)
            )
            conn.commit()
        finally:
            conn.close()
        flash(f'Book "{title}" added successfully!', "success")
        return redirect(url_for("view_books"))

    return render_template("add_book.html")


@app.route("/books/edit/<int:book_id>", methods=["GET", "POST"])
@login_required
def edit_book(book_id):
    """Edit an existing book."""
    conn = get_db()
    try:
        book = conn.execute("SELECT * FROM books WHERE id=?", (book_id,)).fetchone()
        if not book:
            flash("Book not found.", "danger")
            return redirect(url_for("view_books"))

        if request.method == "POST":
            title   = request.form.get("title", "").strip()
            author  = request.form.get("author", "").strip()
            qty_raw = request.form.get("quantity", "").strip()

            errors = []
            if not title:
                errors.append("Book title is required.")
            if not author:
                errors.append("Author is required.")
            try:
                quantity = int(qty_raw)
                if quantity < 0:
                    errors.append("Quantity cannot be negative.")
            except ValueError:
                errors.append("Quantity must be a whole number.")
                quantity = book["quantity"]

            if errors:
                for e in errors:
                    flash(e, "danger")
                return render_template("add_book.html", book=book, editing=True,
                                       form_title=title, form_author=author,
                                       form_quantity=qty_raw)

            conn.execute(
                "UPDATE books SET title=?, author=?, quantity=? WHERE id=?",
                (title, author, quantity, book_id)
            )
            conn.commit()
            flash("Book updated!", "success")
            return redirect(url_for("view_books"))
    finally:
        conn.close()

    return render_template("add_book.html", book=book, editing=True)


@app.route("/books/delete/<int:book_id>", methods=["POST"])
@login_required
def delete_book(book_id):
    """Delete a book (only if no active issues)."""
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE book_id=? AND status='issued'",
            (book_id,)
        ).fetchone()[0]
        if active:
            flash("Cannot delete a book with active issues.", "danger")
        else:
            try:
                conn.execute("DELETE FROM transactions WHERE book_id=? AND status='returned'", (book_id,))
                conn.execute("DELETE FROM books WHERE id=?", (book_id,))
                conn.commit()
                flash("Book deleted.", "info")
            except sqlite3.IntegrityError:
                flash("Cannot delete book because it is referenced in active transaction records.", "danger")
    finally:
        conn.close()
    return redirect(url_for("view_books"))


# ─────────────────────────────────────────────
# MEMBER ROUTES
# ─────────────────────────────────────────────

@app.route("/members")
@login_required
def view_members():
    """Display all registered members."""
    query = request.args.get("q", "").strip()
    conn  = get_db()
    try:
        if query:
            members = conn.execute(
                "SELECT * FROM members WHERE name LIKE ? OR email LIKE ?",
                (f"%{query}%", f"%{query}%")
            ).fetchall()
        else:
            members = conn.execute("SELECT * FROM members").fetchall()
    finally:
        conn.close()
    return render_template("view_members.html", members=members, query=query)


@app.route("/members/register", methods=["GET", "POST"])
@login_required
def register_member():
    """Register a new library member."""
    if request.method == "POST":
        name  = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()

        errors = []
        if not name:
            errors.append("Full name is required.")
        if not email:
            errors.append("Email address is required.")
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("register_member.html",
                                   form_name=name, form_email=email)

        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO members (name, email) VALUES (?, ?)", (name, email)
            )
            conn.commit()
            flash(f'Member "{name}" registered!', "success")
            return redirect(url_for("view_members"))
        except sqlite3.IntegrityError:
            flash("A member with that email already exists.", "danger")
            return render_template("register_member.html",
                                   form_name=name, form_email=email)
        finally:
            conn.close()

    return render_template("register_member.html")


@app.route("/members/delete/<int:member_id>", methods=["POST"])
@login_required
def delete_member(member_id):
    """Delete a member (only if no active issues)."""
    conn = get_db()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE member_id=? AND status='issued'",
            (member_id,)
        ).fetchone()[0]
        if active:
            flash("Cannot delete a member with active issued books.", "danger")
        else:
            try:
                conn.execute("DELETE FROM transactions WHERE member_id=? AND status='returned'", (member_id,))
                conn.execute("DELETE FROM members WHERE id=?", (member_id,))
                conn.commit()
                flash("Member deleted.", "info")
            except sqlite3.IntegrityError:
                flash("Cannot delete member because they are referenced in active transaction records.", "danger")
    finally:
        conn.close()
    return redirect(url_for("view_members"))


# ─────────────────────────────────────────────
# TRANSACTION ROUTES
# ─────────────────────────────────────────────

@app.route("/issue", methods=["GET", "POST"])
@login_required
def issue_book():
    """Issue a book to a member."""
    conn = get_db()
    try:
        books   = conn.execute("SELECT * FROM books WHERE quantity > 0").fetchall()
        members = conn.execute("SELECT * FROM members").fetchall()

        if request.method == "POST":
            book_id_raw   = request.form.get("book_id", "").strip()
            member_id_raw = request.form.get("member_id", "").strip()

            if not book_id_raw or not member_id_raw:
                flash("Please select both a book and a member.", "danger")
            else:
                book_id   = int(book_id_raw)
                member_id = int(member_id_raw)
                today     = date.today().isoformat()

                book = conn.execute(
                    "SELECT * FROM books WHERE id=? AND quantity > 0", (book_id,)
                ).fetchone()
                if not book:
                    flash("Selected book is not available.", "danger")
                else:
                    conn.execute(
                        "INSERT INTO transactions (book_id, member_id, issue_date, status) "
                        "VALUES (?, ?, ?, 'issued')",
                        (book_id, member_id, today)
                    )
                    conn.execute(
                        "UPDATE books SET quantity = quantity - 1 WHERE id=?", (book_id,)
                    )
                    conn.commit()
                    flash(f'"{book["title"]}" issued successfully!', "success")
                    return redirect(url_for("index"))

        return render_template("issue_book.html", books=books, members=members,
                               today=date.today().isoformat())
    finally:
        conn.close()


@app.route("/return", methods=["GET", "POST"])
@login_required
def return_book():
    """Return a previously issued book."""
    conn = get_db()
    try:
        issued = conn.execute("""
            SELECT t.id, b.title, m.name, t.issue_date,
                   CAST(julianday(date('now', 'localtime')) - julianday(t.issue_date) AS INTEGER) AS days_held
            FROM transactions t
            JOIN books   b ON b.id = t.book_id
            JOIN members m ON m.id = t.member_id
            WHERE t.status = 'issued'
            ORDER BY t.issue_date
        """).fetchall()

        if request.method == "POST":
            txn_id_raw = request.form.get("transaction_id", "").strip()
            if not txn_id_raw:
                flash("No transaction selected.", "danger")
            else:
                txn_id = int(txn_id_raw)
                today  = date.today().isoformat()

                txn = conn.execute(
                    "SELECT * FROM transactions WHERE id=? AND status='issued'", (txn_id,)
                ).fetchone()
                if not txn:
                    flash("Transaction not found or already returned.", "danger")
                else:
                    conn.execute(
                        "UPDATE transactions SET return_date=?, status='returned' WHERE id=?",
                        (today, txn_id)
                    )
                    conn.execute(
                        "UPDATE books SET quantity = quantity + 1 WHERE id=?", (txn["book_id"],)
                    )
                    conn.commit()

                    try:
                        issue_date = datetime.strptime(str(txn["issue_date"])[:10], "%Y-%m-%d").date()
                    except Exception:
                        issue_date = date.today()
                    days_held    = (date.today() - issue_date).days
                    overdue_days = max(0, days_held - 14)
                    fine         = overdue_days * 5

                    if fine:
                        flash(f"Book returned. Overdue by {overdue_days} day(s). Fine: Rs.{fine}", "warning")
                    else:
                        flash("Book returned successfully! No fine.", "success")
                    return redirect(url_for("index"))

        return render_template("return_book.html", issued=issued)
    finally:
        conn.close()


@app.route("/transactions")
@login_required
def view_transactions():
    """View all transaction history."""
    conn = get_db()
    try:
        txns = conn.execute("""
            SELECT t.id, b.title, m.name, t.issue_date, t.return_date, t.status,
                   CASE
                       WHEN t.status='issued' AND julianday(date('now', 'localtime')) - julianday(t.issue_date) > 14
                       THEN CAST(julianday(date('now', 'localtime')) - julianday(t.issue_date) - 14 AS INTEGER)
                       ELSE 0
                   END AS overdue_days
            FROM transactions t
            JOIN books   b ON b.id = t.book_id
            JOIN members m ON m.id = t.member_id
            ORDER BY t.id DESC
        """).fetchall()
    finally:
        conn.close()
    return render_template("view_transactions.html", transactions=txns)


@app.route("/transactions/delete/<int:txn_id>", methods=["POST"])
@login_required
def delete_transaction(txn_id):
    """Delete a single transaction record (any status). Restores book qty if issued."""
    conn = get_db()
    try:
        txn = conn.execute(
            "SELECT * FROM transactions WHERE id=?", (txn_id,)
        ).fetchone()
        if not txn:
            flash("Transaction not found.", "danger")
        else:
            if txn["status"] == "issued":
                conn.execute(
                    "UPDATE books SET quantity = quantity + 1 WHERE id=?", (txn["book_id"],)
                )
            conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
            conn.commit()
            flash("Transaction record deleted.", "info")
    finally:
        conn.close()
    return redirect(url_for("view_transactions"))


@app.route("/transactions/clear-history", methods=["POST"])
@login_required
def clear_history():
    """Delete ALL transaction records. Restores book qty for any still-issued ones."""
    conn = get_db()
    try:
        issued = conn.execute(
            "SELECT book_id FROM transactions WHERE status='issued'"
        ).fetchall()
        for row in issued:
            conn.execute(
                "UPDATE books SET quantity = quantity + 1 WHERE id=?", (row["book_id"],)
            )
        deleted = conn.execute("DELETE FROM transactions").rowcount
        conn.commit()
    finally:
        conn.close()
    flash(f"Cleared all {deleted} transaction record(s) from history.", "info")
    return redirect(url_for("view_transactions"))


# ─────────────────────────────────────────────
# MODULE INITIALIZATION (For Vercel & WSGI)
# ─────────────────────────────────────────────
try:
    init_db()
    migrate_db()
except Exception as _e:
    print(f"[WARN] Module DB initialization check: {_e}")

# ─────────────────────────────────────────────
# ENTRY POINT (Local Development)
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("[OK] Library system ready -> http://127.0.0.1:5000")
    print("    Default login: admin / admin123")
    app.run(debug=True)
