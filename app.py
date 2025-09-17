import os, re, secrets, string, smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv  # <-- NEW

# ---------- App & DB ----------
load_dotenv()  # <-- NEW: load .env from project root

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError(
        "MONGO_URL is not set. Put it in your .env (with ?authSource=admin) "
        "or export it in the environment."
    )

print("[DB] Using MONGO_URL:", re.sub(r":([^@/]+)@", ":****@", MONGO_URL))

client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
client.admin.command("ping")
db = client["campus_circle"]
users = db["users"]
events = db["events"]
otps = db["otps"]          # registration OTPs
resets = db["resets"]      # password reset OTP / tokens
contacts = db["contacts"]

# ---------- Env mail / admin ----------

SMTP_HOST = os.getenv("BREVO_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
SMTP_USER = os.getenv("BREVO_SMTP_USER")
SMTP_PASS = os.getenv("BREVO_SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "noreply@example.com")

COLLEGE_EMAIL_DOMAIN = os.getenv("COLLEGE_EMAIL_DOMAIN", "@example.edu").lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
ADMIN_NOTIFY_EMAIL = os.getenv("ADMIN_NOTIFY_EMAIL", EMAIL_FROM)

# ---------- Time helpers (aware UTC everywhere) ----------

def utcnow():
    return datetime.now(timezone.utc)

def as_aware_utc(dt):
    if not dt:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

# ---------- Validators (server-side, per OWASP) ----------

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z '’.-]{1,49}$")  # 2–50 chars, allow apostrophes/hyphens
PHONE_RE = re.compile(r"^\+?[1-9]\d{7,14}$")           # E.164: 8–15 digits, country code ≠ 0
LINKEDIN_RE = re.compile(r"^https?://(www\.)?linkedin\.com/(in|company)/[A-Za-z0-9\-_%]+/?$")

def validate_profile_fields(data):
    errs = []
    name = data.get("full_name", "").strip()
    if name and not NAME_RE.fullmatch(name):
        errs.append("Enter a valid full name (letters, spaces, ' . -)")
    phone = data.get("phone", "").strip()
    if phone and not PHONE_RE.fullmatch(phone):
        errs.append("Phone must be E.164 (like +14155552671)")
    mobile = data.get("mobile", "").strip()
    if mobile and not PHONE_RE.fullmatch(mobile):
        errs.append("Mobile must be E.164 (like +14155552671)")
    linkedin = data.get("linkedin", "").strip()
    if linkedin and not LINKEDIN_RE.fullmatch(linkedin):
        errs.append("LinkedIn must look like https://linkedin.com/in/username")
    year = data.get("graduation_year", "").strip()
    if year:
        if not year.isdigit():
            errs.append("Graduation year must be numeric")
        else:
            y = int(year)
            if y < 1950 or y > 2099:
                errs.append("Graduation year out of range")
    return errs

# ---------- Utilities ----------

def generate_otp():
    return "".join(secrets.choice(string.digits) for _ in range(6))

def slugify(s):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s.strip().lower()).strip("-")
    return f"{s}-{secrets.token_hex(3)}"

def safe_url(url):
    if not url:
        return ""
    try:
        p = urlparse(url)
        return url if p.scheme in ("http", "https") and p.netloc else ""
    except Exception:
        return ""

def send_mail(to_email, subject, body):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS):
        return
    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

def require_login():
    return "user_id" in session

def require_admin():
    return session.get("is_admin") is True

# ---------- Routes: Core ----------

@app.route("/")
def home():
    if not require_login():
        return redirect(url_for("login"))
    today = utcnow()
    up = list(events.find({"published": True, "date": {"$gte": today}})
              .sort("date", ASCENDING).limit(6))
    latest = list(events.find({"published": True})
                  .sort("created_at", DESCENDING).limit(6))
    return render_template("home.html", upcoming=up, latest=latest)

# ---------- Routes: Alumni (PUBLIC) ----------

@app.route("/alumni")
def alumni():
    q = request.args.get("q", "").strip()
    year = request.args.get("year", "").strip()
    branch = request.args.get("branch", "").strip()

    filt = {"verified_at": {"$ne": None}}
    if q:
        filt["full_name"] = {"$regex": re.escape(q), "$options": "i"}
    if year and year.isdigit():
        filt["graduation_year"] = int(year)
    if branch:
        filt["branch"] = {"$regex": f"^{re.escape(branch)}$", "$options": "i"}

    cur = users.find(filt).sort("graduation_year", DESCENDING).limit(100)
    rows = []
    for u in cur:
        rows.append({
            "id": str(u["_id"]),
            "full_name": u.get("full_name"),
            "graduation_year": u.get("graduation_year"),
            "branch": u.get("branch"),
            "company": u.get("company"),
            "linkedin": u.get("linkedin"),
        })
    return render_template("alumni.html", rows=rows, q=q, year=year, branch=branch, logged_in=require_login())

# ---------- Routes: Auth (login / register + OTP verify) ----------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pwd = request.form.get("password", "")
        u = users.find_one({"$or": [{"personal_email": email}, {"college_email": email}]})
        if u and check_password_hash(u.get("password_hash", ""), pwd):
            session["user_id"] = str(u["_id"])
            flash("Logged in.", "success")
            return redirect(url_for("home"))
        flash("Invalid credentials.", "danger")
        return redirect(url_for("login"))
    return render_template("auth_login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        college_email = request.form.get("college_email", "").strip().lower()
        personal_email = request.form.get("personal_email", "").strip().lower()
        pwd = request.form.get("password", "")
        if COLLEGE_EMAIL_DOMAIN and not college_email.endswith(COLLEGE_EMAIL_DOMAIN):
            flash(f"Use your college email ({COLLEGE_EMAIL_DOMAIN}).", "danger")
            return redirect(url_for("register"))
        if users.find_one({"$or":[{"college_email": college_email},{"personal_email": personal_email}]}):
            flash("Email already registered.", "danger")
            return redirect(url_for("register"))
        code = generate_otp()
        otps.update_one(
            {"college_email": college_email},
            {"$set":{
                "personal_email": personal_email,
                "password_hash": generate_password_hash(pwd),
                "otp_hash": generate_password_hash(code),
                "expires_at": utcnow() + timedelta(minutes=10),
                "created_at": utcnow()
            }},
            upsert=True
        )
        try:
            send_mail(college_email, "Campus Circle – Verify your email", f"Your OTP is {code}. It expires in 10 minutes.")
        except:
            pass
        flash("OTP sent to your college email.", "info")
        return redirect(url_for("verify", email=college_email))
    return render_template("auth_register.html")

@app.route("/verify", methods=["GET", "POST"])
def verify():
    email = (request.args.get("email") or request.form.get("college_email") or "").strip().lower()
    if request.method == "POST":
        otp = request.form.get("otp", "").strip()
        doc = otps.find_one({"college_email": email})
        if not doc:
            flash("Request a new OTP.", "danger")
            return redirect(url_for("register"))
        if utcnow() > as_aware_utc(doc["expires_at"]):
            otps.delete_one({"_id": doc["_id"]})
            flash("OTP expired. Try again.", "danger")
            return redirect(url_for("register"))
        if not check_password_hash(doc["otp_hash"], otp):
            flash("Invalid OTP.", "danger")
            return redirect(url_for("verify", email=email))
        ins = {
            "college_email": email,
            "personal_email": doc["personal_email"],
            "password_hash": doc["password_hash"],
            "verified_at": utcnow(),
            "created_at": utcnow()
        }
        res = users.insert_one(ins)
        otps.delete_one({"_id": doc["_id"]})
        session["user_id"] = str(res.inserted_id)
        flash("Account created.", "success")
        return redirect(url_for("profile"))
    return render_template("auth_verify.html", email=email)

# ---------- Routes: Forgot / Reset (two-step with OTP + token) ----------

@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = users.find_one({"$or":[{"personal_email": email},{"college_email": email}]})
        flash("If the email exists, an OTP has been sent.", "info")
        if not u:
            return redirect(url_for("forgot", email=email))
        now = utcnow()
        doc = resets.find_one({"email": email})
        last_sent = as_aware_utc(doc.get("last_sent")) if doc else None
        if last_sent and now - last_sent < timedelta(seconds=60):
            return redirect(url_for("verify_reset", email=email))
        code = generate_otp()
        resets.update_one(
            {"email": email},
            {"$set":{
                "otp_hash": generate_password_hash(code),
                "expires_at": now + timedelta(minutes=10),
                "last_sent": now,
                "attempts": 0
            },
             "$unset":{"token":"","token_expires":""},
             "$setOnInsert":{"window_start": now, "resend_count": 0}
            },
            upsert=True
        )
        try:
            send_mail(email, "Campus Circle – Password Reset OTP", f"Your OTP is {code}. It expires in 10 minutes.")
        except:
            pass
        return redirect(url_for("verify_reset", email=email))
    return render_template("auth_forgot.html", email=request.args.get("email",""))

@app.route("/reset/verify", methods=["GET","POST"])
def verify_reset():
    email = (request.args.get("email") or request.form.get("email") or "").strip().lower()
    if request.method == "POST":
        otp = request.form.get("otp","").strip()
        doc = resets.find_one({"email": email})
        if not doc:
            flash("Request a new OTP.", "danger")
            return redirect(url_for("forgot", email=email))
        now = utcnow()
        exp = as_aware_utc(doc.get("expires_at"))
        if not exp or now > exp:
            resets.delete_one({"_id": doc["_id"]})
            flash("OTP expired.", "danger")
            return redirect(url_for("forgot", email=email))
        if not check_password_hash(doc["otp_hash"], otp):
            attempts = int(doc.get("attempts",0)) + 1
            upd = {"$set":{"attempts": attempts}}
            if attempts >= 3:
                upd["$set"]["expires_at"] = now
            resets.update_one({"_id": doc["_id"]}, upd)
            flash("Invalid OTP.", "danger")
            return redirect(url_for("verify_reset", email=email))
        token = secrets.token_urlsafe(24)
        resets.update_one({"_id": doc["_id"]}, {"$set":{"token": token, "token_expires": now + timedelta(minutes=10)}})
        return redirect(url_for("password_reset", token=token))
    return render_template("auth_reset_verify.html", email=email)

@app.route("/reset/resend")
def resend_reset():
    email = request.args.get("email","").strip().lower()
    if not email:
        return redirect(url_for("forgot"))
    doc = resets.find_one({"email": email})
    now = utcnow()
    last_sent = as_aware_utc(doc.get("last_sent")) if doc else None
    if last_sent and now - last_sent < timedelta(seconds=60):
        flash("Wait 60 seconds before requesting another OTP.", "danger")
        return redirect(url_for("verify_reset", email=email))
    window_start = as_aware_utc(doc.get("window_start")) if doc else None
    resend_count = int(doc.get("resend_count",0)) if doc else 0
    if window_start and now - window_start < timedelta(hours=1) and resend_count >= 5:
        flash("OTP request limit reached. Try after 1 hour.", "danger")
        return redirect(url_for("verify_reset", email=email))
    if not window_start or now - window_start > timedelta(hours=1):
        window_start = now
        resend_count = 0
    code = generate_otp()
    resets.update_one(
        {"email": email},
        {"$set":{
            "otp_hash": generate_password_hash(code),
            "expires_at": now + timedelta(minutes=10),
            "last_sent": now,
            "window_start": window_start
        }, "$setOnInsert":{"attempts":0}, "$inc":{"resend_count":1}},
        upsert=True
    )
    try:
        send_mail(email, "Campus Circle – Password Reset OTP", f"Your OTP is {code}. It expires in 10 minutes.")
    except:
        pass
    flash("OTP sent.", "success")
    return redirect(url_for("verify_reset", email=email))

@app.route("/reset/password", methods=["GET","POST"])
def password_reset():
    token = request.args.get("token","")
    doc = resets.find_one({"token": token})
    if not doc:
        flash("Invalid or expired link.", "danger")
        return redirect(url_for("forgot"))
    now = utcnow()
    texp = as_aware_utc(doc.get("token_expires"))
    if not texp or now > texp:
        resets.delete_one({"_id": doc["_id"]})
        flash("Link expired.", "danger")
        return redirect(url_for("forgot"))
    if request.method == "POST":
        p1 = request.form.get("password","")
        p2 = request.form.get("confirm","")
        if p1 != p2 or len(p1) < 6:
            flash("Passwords must match and be at least 6 characters.", "danger")
            return redirect(url_for("password_reset", token=token))
        users.update_one(
            {"$or":[{"personal_email": doc["email"]},{"college_email": doc["email"]}]},
            {"$set":{"password_hash": generate_password_hash(p1)}}
        )
        resets.delete_one({"_id": doc["_id"]})
        flash("Password updated. Login now.", "success")
        return redirect(url_for("login"))
    return render_template("auth_reset_password.html")

# ---------- Routes: Profile ----------

@app.route("/profile", methods=["GET","POST"])
def profile():
    if not require_login():
        return redirect(url_for("login"))
    u = users.find_one({"_id": ObjectId(session["user_id"])})
    if not u:
        session.pop("user_id", None)
        return redirect(url_for("login"))
    if request.method == "POST":
        data = {
            "full_name": request.form.get("full_name",""),
            "branch": request.form.get("branch",""),
            "graduation_year": request.form.get("graduation_year",""),
            "company": request.form.get("company",""),
            "phone": request.form.get("phone",""),
            "mobile": request.form.get("mobile",""),
            "linkedin": request.form.get("linkedin",""),
        }
        errs = validate_profile_fields(data)
        if errs:
            for e in errs: flash(e, "danger")
            return redirect(url_for("profile"))
        yr = int(data["graduation_year"]) if data["graduation_year"].isdigit() else None
        users.update_one({"_id": u["_id"]}, {"$set":{
            "full_name": data["full_name"].strip() or None,
            "branch": data["branch"].strip() or None,
            "graduation_year": yr,
            "company": data["company"].strip() or None,
            "phone": data["phone"].strip() or None,
            "mobile": data["mobile"].strip() or None,
            "linkedin": data["linkedin"].strip() or None,
        }})
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", u=u)

# ---------- Routes: Contact ----------

@app.route("/contact", methods=["GET","POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        email = request.form.get("email","").strip()
        msg = request.form.get("message","").strip()
        contacts.insert_one({"name": name, "email": email, "message": msg, "created_at": utcnow()})
        try:
            send_mail(ADMIN_NOTIFY_EMAIL, "Campus Circle – Contact", f"From: {name} <{email}>\n\n{msg}")
        except:
            pass
        flash("Message sent.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# ---------- Routes: Static / About ----------

@app.route("/about")
def about():
    return render_template("about.html")

# ---------- Routes: Events (detail) ----------

@app.route("/event/<slug>")
def event_detail(slug):
    e = events.find_one({"slug": slug, "published": True})
    if not e:
        abort(404)
    return render_template("event_detail.html", e=e)

# ---------- Routes: Admin ----------

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password","")
        if pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Admin logged in.", "success")
            return redirect(url_for("admin"))
        flash("Wrong admin password.", "danger")
        return redirect(url_for("admin_login"))
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("login"))

@app.route("/admin", methods=["GET","POST"])
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        title = request.form.get("title","").strip()
        description = request.form.get("description","").strip()
        date_str = request.form.get("date","").strip()
        venue = request.form.get("venue","").strip()
        mode = request.form.get("mode","in-person").strip()
        join_url = safe_url(request.form.get("join_url","").strip())
        publish = True if request.form.get("publish") == "on" else False

        if not title or len(title) < 3:
            flash("Title too short.", "danger")
            return redirect(url_for("admin"))
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str)
        else:
            dt = datetime.strptime(date_str, "%d-%m-%Y %H:%M")
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)

        events.insert_one({
            "title": title,
            "description": description,
            "date": dt,
            "venue": venue,
            "mode": mode,
            "join_url": join_url,
            "published": publish,
            "slug": slugify(title),
            "created_at": utcnow(),
            "updated_at": utcnow()
        })
        flash("Event saved.", "success")
        return redirect(url_for("admin"))

    ev = []
    for e in events.find({}).sort("date", DESCENDING):
        e["id"] = str(e["_id"])
        ev.append(e)

    # alumni snapshot for admin manage/delete
    latest_alumni = []
    for u in users.find({}).sort("created_at", DESCENDING).limit(20):
        latest_alumni.append({
            "id": str(u["_id"]),
            "full_name": u.get("full_name"),
            "college_email": u.get("college_email"),
            "personal_email": u.get("personal_email"),
            "graduation_year": u.get("graduation_year"),
            "branch": u.get("branch"),
        })
    total_alumni = users.count_documents({})
    return render_template("admin_dashboard.html", events=ev, total_alumni=total_alumni, latest_alumni=latest_alumni)

@app.route("/admin/event/toggle/<id>")
def admin_event_toggle(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    e = events.find_one({"_id": ObjectId(id)})
    if e:
        events.update_one({"_id": e["_id"]}, {"$set":{"published": not bool(e.get("published")),"updated_at":utcnow()}})
        flash("Event status updated.", "success")
    return redirect(url_for("admin"))

@app.route("/admin/event/delete/<id>")
def admin_event_delete(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    events.delete_one({"_id": ObjectId(id)})
    flash("Event deleted.", "warning")
    return redirect(url_for("admin"))

@app.route("/admin/user/delete/<id>")
def admin_user_delete(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    users.delete_one({"_id": ObjectId(id)})
    flash("Alumnus deleted.", "warning")
    return redirect(url_for("admin"))

# ---------- Run ----------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
