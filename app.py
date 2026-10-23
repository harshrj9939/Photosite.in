"""Photosite storefront application.

Run locally with:
    flask --app app run --debug
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from base64 import b64decode
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from notifications import is_email_configured, notify_new_order

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
DATABASE = DATA_DIR / "photosite.db"
load_dotenv(BASE_DIR / ".env")
ALLOWED_IMAGE_TYPES = {"png", "jpg", "jpeg", "webp"}

FRAME_SIZES = {
    "6x8": {"label": "6 × 8 in", "price": 899},
    "8x10": {"label": "8 × 10 in", "price": 1199},
    "12x16": {"label": "12 × 16 in", "price": 1499},
    "16x20": {"label": "16 × 20 in", "price": 1999},
}
FRAME_COLORS = {
    "walnut": "Warm walnut",
    "oak": "Soft oak",
    "charcoal": "Charcoal",
    "brass": "Golden brass",
}
PURPOSES = {
    "family", "friends", "religious", "gifts", "wedding", "birthday",
    "anniversary", "wall-art", "certificate", "custom",
}
PRODUCTS = {
    "everyday": {"name": "The Everyday", "description": "Classic wood · 6 colours", "price": 899},
    "gallery": {"name": "The Gallery", "description": "Modern wood · 4 colours", "price": 1199},
    "heritage": {"name": "The Heritage", "description": "Statement grain · 3 colours", "price": 1499},
    "brass-edit": {"name": "The Brass Edit", "description": "Warm metal · 2 colours", "price": 1699},
}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", secrets.token_urlsafe(32)),
    MAX_CONTENT_LENGTH=48 * 1024 * 1024,
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)
app.jinja_env.filters["from_json"] = json.loads


def db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Create database folders and tables on first deployment."""
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    with db_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                address TEXT NOT NULL,
                city TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                notes TEXT,
                items_json TEXT NOT NULL,
                amount INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'INR',
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL,
                order_status TEXT NOT NULL DEFAULT 'placed',
                razorpay_order_id TEXT,
                razorpay_payment_id TEXT,
                user_id INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        # Small migration for stores created before customer accounts were added.
        order_columns = {row["name"] for row in connection.execute("PRAGMA table_info(orders)")}
        if "user_id" not in order_columns:
            connection.execute("ALTER TABLE orders ADD COLUMN user_id INTEGER")


def is_allowed_image(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMAGE_TYPES


def save_photos() -> list[str]:
    """Save all collage photos and return their relative upload paths."""
    photos = [photo for photo in request.files.getlist("photos") if photo and photo.filename]

    # Keep backward compatibility with the original single-photo upload field.
    if not photos:
        legacy_photo = request.files.get("photo")
        if legacy_photo and legacy_photo.filename:
            photos = [legacy_photo]

    if len(photos) > 6:
        raise ValueError("A collage can contain at most 6 photos.")

    saved_paths: list[str] = []
    for photo in photos:
        if not is_allowed_image(photo.filename):
            raise ValueError("Upload a PNG, JPG, JPEG, or WEBP photo.")
        extension = secure_filename(photo.filename).rsplit(".", 1)[1].lower()
        saved_name = f"{uuid.uuid4().hex}.{extension}"
        photo.save(UPLOAD_DIR / saved_name)
        saved_paths.append(f"uploads/{saved_name}")
    return saved_paths


COLLAGE_LAYOUTS = {
    "2-side": 2,
    "2-vertical": 2,
    "2-diagonal": 2,
    "3-feature": 3,
    "3-horizontal": 3,
    "3-vertical": 3,
    "4-grid": 4,
    "4-feature": 4,
    "4-portrait": 4,
    "5-grid": 5,
    "5-feature": 5,
    "6-grid": 6,
    "6-landscape": 6,
    "6-creative": 6,
}


def crop_to_fill(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize and crop an image to completely fill a target rectangle."""
    return ImageOps.fit(
        image.convert("RGB"),
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def build_collage(photo_paths: list[str], layout: str) -> str | None:
    """Create a print-ready JPEG collage from 2–6 uploaded photos."""
    if not photo_paths:
        return None

    count = COLLAGE_LAYOUTS.get(layout)
    if count is None or len(photo_paths) != count:
        raise ValueError("The selected collage layout does not match the number of photos.")

    images: list[Image.Image] = []
    try:
        for relative_path in photo_paths:
            image = Image.open(BASE_DIR / relative_path)
            image.load()
            images.append(image.convert("RGB"))

        canvas_size = (1600, 2000)
        margin = 36
        gap = 24
        background = Image.new("RGB", canvas_size, "#f8f6f0")

        def paste(photo: Image.Image, box: tuple[int, int, int, int]) -> None:
            x, y, width, height = box
            background.paste(crop_to_fill(photo, (width, height)), (x, y))

        usable_w = canvas_size[0] - (margin * 2)
        usable_h = canvas_size[1] - (margin * 2)

        if layout == "2-side":
            width = (usable_w - gap) // 2
            paste(images[0], (margin, margin, width, usable_h))
            paste(images[1], (margin + width + gap, margin, width, usable_h))

        elif layout == "2-vertical":
            height = (usable_h - gap) // 2
            paste(images[0], (margin, margin, usable_w, height))
            paste(images[1], (margin, margin + height + gap, usable_w, height))

        elif layout == "2-diagonal":
            paste(images[0], (margin, margin, int(usable_w * 0.62), int(usable_h * 0.55)))
            paste(
                images[1],
                (
                    int(usable_w * 0.38) + margin,
                    int(usable_h * 0.45) + margin,
                    int(usable_w * 0.62),
                    int(usable_h * 0.55),
                ),
            )

        elif layout == "3-feature":
            main_w = int(usable_w * 0.58)
            side_w = usable_w - main_w - gap
            side_h = (usable_h - gap) // 2
            paste(images[0], (margin, margin, main_w, usable_h))
            paste(images[1], (margin + main_w + gap, margin, side_w, side_h))
            paste(images[2], (margin + main_w + gap, margin + side_h + gap, side_w, side_h))

        elif layout == "3-horizontal":
            width = (usable_w - gap * 2) // 3
            for index, image in enumerate(images):
                paste(image, (margin + index * (width + gap), margin, width, usable_h))

        elif layout == "3-vertical":
            height = (usable_h - gap * 2) // 3
            for index, image in enumerate(images):
                paste(image, (margin, margin + index * (height + gap), usable_w, height))

        elif layout == "4-feature":
            main_w = int(usable_w * 0.62)
            side_w = usable_w - main_w - gap
            side_h = (usable_h - gap * 2) // 3
            paste(images[0], (margin, margin, main_w, usable_h))
            for index in range(3):
                paste(
                    images[index + 1],
                    (margin + main_w + gap, margin + index * (side_h + gap), side_w, side_h),
                )

        elif layout in {"4-grid", "4-portrait"}:
            width = (usable_w - gap) // 2
            height = (usable_h - gap) // 2
            for index, image in enumerate(images):
                x = margin + (index % 2) * (width + gap)
                y = margin + (index // 2) * (height + gap)
                paste(image, (x, y, width, height))

        elif layout == "5-feature":
            main_h = int(usable_h * 0.58)
            bottom_h = usable_h - main_h - gap
            paste(images[0], (margin, margin, usable_w, main_h))
            width = (usable_w - gap * 3) // 4
            for index in range(4):
                paste(
                    images[index + 1],
                    (margin + index * (width + gap), margin + main_h + gap, width, bottom_h),
                )

        elif layout == "5-grid":
            top_h = (usable_h - gap) // 2
            width = (usable_w - gap * 2) // 3
            for index in range(3):
                paste(images[index], (margin + index * (width + gap), margin, width, top_h))
            bottom_w = (usable_w - gap) // 2
            paste(images[3], (margin, margin + top_h + gap, bottom_w, top_h))
            paste(images[4], (margin + bottom_w + gap, margin + top_h + gap, bottom_w, top_h))

        else:
            # 6-grid, 6-landscape, 6-creative
            width = (usable_w - gap * 2) // 3
            height = (usable_h - gap) // 2
            for index, image in enumerate(images):
                x = margin + (index % 3) * (width + gap)
                y = margin + (index // 3) * (height + gap)
                paste(image, (x, y, width, height))

        saved_name = f"collage-{uuid.uuid4().hex}.jpg"
        output_path = UPLOAD_DIR / saved_name
        background.save(output_path, "JPEG", quality=92, optimize=True)
        return f"uploads/{saved_name}"

    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("One of the uploaded files is not a valid image.") from error
    finally:
        for image in images:
            image.close()


def calculate_items(
    items: list[dict[str, Any]],
    photo_paths: list[str],
) -> tuple[list[dict[str, Any]], int]:
    """Recalculate every price on the server; never trust a browser-supplied total."""
    if not 1 <= len(items) <= 10:
        raise ValueError("Your cart must contain between 1 and 10 items.")

    safe_items: list[dict[str, Any]] = []
    total = 0
    custom_item_seen = False

    for item in items:
        item_type = item.get("type")
        quantity = item.get("quantity", 1)

        if not isinstance(quantity, int) or not 1 <= quantity <= 5:
            raise ValueError("Each item quantity must be between 1 and 5.")

        if item_type == "custom":
            size = item.get("size")
            color = item.get("color")
            purpose = item.get("purpose")
            layout = item.get("collage_layout", "1-single")
            expected_photos = item.get("photo_count", 1)

            if size not in FRAME_SIZES or color not in FRAME_COLORS or purpose not in PURPOSES:
                raise ValueError("One of your custom frame options is invalid.")

            if custom_item_seen:
                raise ValueError("Only one custom collage frame can be added per order.")
            custom_item_seen = True

            if layout != "1-single":
                if layout not in COLLAGE_LAYOUTS:
                    raise ValueError("The selected collage layout is invalid.")
                if expected_photos != COLLAGE_LAYOUTS[layout]:
                    raise ValueError("The collage photo count does not match its layout.")
                if len(photo_paths) != expected_photos:
                    raise ValueError("Please upload every photo required for your selected collage.")
                collage_path = build_collage(photo_paths, layout)
            else:
                if len(photo_paths) > 1:
                    raise ValueError("Select a collage layout when uploading multiple photos.")
                collage_path = photo_paths[0] if photo_paths else None

            safe_item = {
                "type": "custom",
                "name": "Custom photo frame",
                "size": size,
                "size_label": FRAME_SIZES[size]["label"],
                "color": color,
                "color_label": FRAME_COLORS[color],
                "purpose": purpose,
                "quantity": quantity,
                "unit_price": FRAME_SIZES[size]["price"],
                "photo": collage_path,
                "photos": photo_paths,
                "collage_layout": layout,
                "photo_count": len(photo_paths),
            }

        elif item_type == "product":
            product_id = item.get("product_id")
            product = PRODUCTS.get(product_id)

            if not product:
                raise ValueError("One of the selected products is unavailable.")

            safe_item = {
                "type": "product",
                "product_id": product_id,
                "name": product["name"],
                "description": product["description"],
                "quantity": quantity,
                "unit_price": product["price"],
            }

        else:
            raise ValueError("Invalid item in cart.")

        safe_item["line_total"] = safe_item["quantity"] * safe_item["unit_price"]
        total += safe_item["line_total"]
        safe_items.append(safe_item)

    return safe_items, total

def order_number() -> str:
    return f"PS-{datetime.now(timezone.utc):%Y%m%d}-{secrets.token_hex(3).upper()}"


def current_user() -> sqlite3.Row | None:
    """Return the signed-in customer, dropping a stale session if the account was removed."""
    user_id = session.get("user_id")
    if not user_id:
        return None
    with db_connection() as connection:
        user = connection.execute("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        session.clear()
    return user


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("homepage", signin="1"))
        return view(*args, **kwargs)
    return wrapped


def admin_credentials_valid(username: str, password: str) -> bool:
    load_dotenv(BASE_DIR / ".env", override=True)
    expected_user = os.getenv("ADMIN_USERNAME", "admin").strip()
    expected_password = os.getenv("ADMIN_PASSWORD", "change-this-before-launch").strip()
    provided_user = username.strip()
    provided_password = password.strip()

    candidates = {expected_password}
    if expected_password.endswith(","):
        candidates.add(expected_password.rstrip(","))
    if expected_password.endswith(" "):
        candidates.add(expected_password.rstrip())

    return hmac.compare_digest(provided_user, expected_user) and provided_password in candidates


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("admin_authenticated"):
            return view(*args, **kwargs)

        accepts_html = "html" in request.headers.get("Accept", "").lower() or request.path.startswith("/admin")
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Basic "):
            try:
                decoded = b64decode(authorization.split(" ", 1)[1]).decode("utf-8")
                username, password = decoded.split(":", 1)
            except (ValueError, UnicodeDecodeError):
                return ("Invalid login", 401, {"WWW-Authenticate": 'Basic realm="Photosite admin"'})
            if admin_credentials_valid(username, password):
                session["admin_authenticated"] = True
                return view(*args, **kwargs)
            return ("Invalid login", 401, {"WWW-Authenticate": 'Basic realm="Photosite admin"'})

        if accepts_html:
            return redirect(url_for("admin_login"))
        return ("Login required", 401, {"WWW-Authenticate": 'Basic realm="Photosite admin"'})
    return wrapped


@app.get("/")
def homepage():
    return render_template("index.html", user=current_user())


@app.get("/api/auth/me")
def auth_me():
    user = current_user()
    if not user:
        return jsonify({"user": None})
    return jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"]}})


@app.post("/api/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    if len(name) < 2 or "@" not in email or len(email) > 254:
        return jsonify({"error": "Enter your name and a valid email address."}), 400
    if len(password) < 8:
        return jsonify({"error": "Choose a password with at least 8 characters."}), 400
    with db_connection() as connection:
        try:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (name, email, generate_password_hash(password), datetime.now(timezone.utc).isoformat()),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error": "An account with this email already exists. Please sign in."}), 409
    session.clear()
    session["user_id"] = cursor.lastrowid
    return jsonify({"user": {"id": cursor.lastrowid, "name": name, "email": email}}), 201


@app.post("/api/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = str(data.get("password", ""))
    with db_connection() as connection:
        user = connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Email or password is incorrect."}), 401
    session.clear()
    session["user_id"] = user["id"]
    return jsonify({"user": {"id": user["id"], "name": user["name"], "email": user["email"]}})


@app.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"message": "Signed out."})


@app.get("/account")
@customer_required
def account():
    user = current_user()
    with db_connection() as connection:
        orders = connection.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return render_template("account.html", user=user, orders=orders)


@app.get("/api/config")
def public_config():
    return jsonify({
        "currency": "INR",
        "online_payments": False,
        "razorpay_key_id": "",
    })

@app.get("/api/products")
def product_list():
    return jsonify([{"id": product_id, **product} for product_id, product in PRODUCTS.items()])


@app.get("/uploads/<path:filename>")
@admin_required
def uploaded_photo(filename: str):
    """Customer images remain private to an authenticated store administrator."""
    return send_from_directory(UPLOAD_DIR, filename)


@app.post("/api/orders")
def create_order():
    try:
        items = json.loads(request.form.get("items", "[]"))
    except json.JSONDecodeError:
        return jsonify({"error": "The cart data is invalid."}), 400
    if not isinstance(items, list):
        return jsonify({"error": "The cart data is invalid."}), 400

    fields = {field: request.form.get(field, "").strip() for field in ("name", "email", "phone", "address", "city", "postal_code", "notes", "payment_method")}
    required = ("name", "email", "phone", "address", "city", "postal_code", "payment_method")
    if any(not fields[field] for field in required):
        return jsonify({"error": "Please complete all delivery details."}), 400
    if "@" not in fields["email"] or len(fields["phone"]) < 8:
        return jsonify({"error": "Please enter a valid email and phone number."}), 400
   
    try:
        photo_paths = save_photos()
        safe_items, total = calculate_items(items, photo_paths)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    number = order_number()
    payment_status = "cash_on_delivery"
    created_at = datetime.now(timezone.utc).isoformat()
    signed_in_user = current_user()
    with db_connection() as connection:
        cursor = connection.execute(
            """INSERT INTO orders (order_number, customer_name, email, phone, address, city, postal_code, notes, items_json, amount, payment_method, payment_status, user_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (number, fields["name"], fields["email"], fields["phone"], fields["address"], fields["city"], fields["postal_code"], fields["notes"], json.dumps(safe_items), total, fields["payment_method"], payment_status, signed_in_user["id"] if signed_in_user else None, created_at),
        )
        internal_id = cursor.lastrowid

        response: dict[str, Any] = {
        "order_number": number,
        "amount": total,
        "payment_method": fields["payment_method"],
    }

    notify_new_order({
        "order_number": number,
        "amount": total,
        "payment_method": "cod",
        "payment_status": payment_status,
        "customer_name": fields["name"],
        **fields,
    }, safe_items)

    return jsonify(response), 201


@app.get("/admin")
@admin_required
def admin_dashboard():
    with db_connection() as connection:
        orders = connection.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
        metrics = connection.execute(
            """SELECT COUNT(*) AS total_orders,
                      COALESCE(SUM(CASE WHEN order_status != 'cancelled' THEN amount ELSE 0 END), 0) AS order_value,
                      COALESCE(SUM(CASE WHEN payment_status = 'paid' THEN amount ELSE 0 END), 0) AS paid_value,
                      COALESCE(SUM(CASE WHEN order_status IN ('placed', 'processing') THEN 1 ELSE 0 END), 0) AS action_needed,
                      COALESCE(SUM(CASE WHEN order_status = 'shipped' THEN 1 ELSE 0 END), 0) AS shipped_orders
               FROM orders"""
        ).fetchone()
        customers = connection.execute(
            """SELECT customer_name, email, phone, COUNT(*) AS orders_count,
                      COALESCE(SUM(amount), 0) AS lifetime_value, MAX(created_at) AS last_order
               FROM orders GROUP BY lower(email) ORDER BY last_order DESC"""
        ).fetchall()
    return render_template("admin.html", orders=orders, metrics=metrics, customers=customers,
                           notifications_enabled=is_email_configured(),
                           notification_email=os.getenv("NOTIFICATION_EMAIL", "Not configured"))


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if admin_credentials_valid(username, password):
            session["admin_authenticated"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", error="Incorrect username or password."), 401
    return render_template("admin_login.html", error=None)


@app.patch("/api/admin/orders/<int:order_id>/status")
@admin_required
def update_order_status(order_id: int):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in {"placed", "processing", "shipped", "delivered", "cancelled"}:
        return jsonify({"error": "Invalid order status."}), 400
    with db_connection() as connection:
        result = connection.execute("UPDATE orders SET order_status = ? WHERE id = ?", (status, order_id))
        if result.rowcount == 0:
            return jsonify({"error": "Order not found."}), 404
    return jsonify({"message": "Order updated."})


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    return jsonify({"error": "Photo is too large. Please upload an image under 8 MB."}), 413


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
