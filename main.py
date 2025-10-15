from flask import Flask, request, jsonify, redirect
import psycopg2
import os
from psycopg2.errors import UniqueViolation
import string, random, os, sys, traceback

app = Flask(__name__)

# --- DB config (set these as env vars on the EC2/service) ---
DB_HOST = os.environ.get("DB_HOST")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = os.environ.get("DB_USER")
DB_PASS = os.environ.get("DB_PASS")

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS
    )

def generate_short_code(length=6):
    """Return a random alphanumeric short code."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def normalize_url(u: str) -> str:
    if not u:
        return u
    if u.startswith("http://") or u.startswith("https://"):
        return u
    return "http://" + u

@app.route("/api/shorten", methods=["POST"])
def shorten_url():
    try:
        data = request.get_json(force=True)
        long_url = data.get("url")
        if not long_url:
            return jsonify({"error": "URL is required"}), 400

        long_url = normalize_url(long_url)

        conn = get_db_connection()
        cur = conn.cursor()

        short_code = None
        max_attempts = 5
        for _ in range(max_attempts):
            candidate = generate_short_code()
            try:
                cur.execute(
                    "INSERT INTO urls (short_code, long_url) VALUES (%s, %s) RETURNING id",
                    (candidate, long_url)
                )
                conn.commit()
                short_code = candidate
                break
            except UniqueViolation:
                conn.rollback()
                continue

        cur.close()
        conn.close()

        if not short_code:
            return jsonify({"error": "Could not generate unique short code"}), 500

        return jsonify({"short_code": short_code}), 201

    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        return jsonify({"error": "Internal server error"}), 500

@app.route("/r/<short_code>")
def redirect_r(short_code):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT long_url FROM urls WHERE short_code = %s", (short_code,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            return redirect(row[0], code=302)
        else:
            return jsonify({"error": "Not found"}), 404
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        return jsonify({"error": "Internal server error"}), 500

@app.route("/<short_code>")
def redirect_rootstyle(short_code):
    # Works if ALB forwards /<short_code> to backend
    return redirect_r(short_code)

@app.route("/api/urls", methods=["GET"])
def list_urls():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT short_code, long_url, created_at FROM urls ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        conn.close()

        urls = [{"short_code": r[0], "long_url": r[1], "created_at": r[2].isoformat()} for r in rows]
        return jsonify(urls)
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        return jsonify({"error": "Internal server error"}), 500

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    if not DB_HOST:
        raise SystemExit("DB_HOST not set")
    app.run(host="0.0.0.0", port=5000)
