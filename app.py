import os, re, secrets, string, smtplib, requests
from email.message import EmailMessage
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from utils.otp import make_otp
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

REQUIRED_PROFILE_FIELDS = ("name", "year", "branch", "company", "phone", "linkedin")

events = db.events
blogs = db.blogs
users = db.users
otps = db.otps
resets = db.resets
email_changes = db.email_changes  # NEW

# ---------- Env mail / admin ----------

SMTP_HOST = os.getenv("BREVO_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
SMTP_USER = os.getenv("BREVO_SMTP_USER")
SMTP_PASS = os.getenv("BREVO_SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER or "noreply@example.com")

COLLEGE_EMAIL_DOMAIN = os.getenv("COLLEGE_EMAIL_DOMAIN", "@example.edu").lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")
ADMIN_NOTIFY_EMAIL = os.getenv("ADMIN_NOTIFY_EMAIL", EMAIL_FROM)
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "phi3:mini")

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


def _emailchange_doc(uid, new_email):
    return email_changes.find_one({"user_id": ObjectId(uid), "new_email": new_email})

def require_login():
    return "user_id" in session

def require_admin():
    return session.get("is_admin") is True

def is_profile_complete(u: dict | None) -> bool:
    if not u:
        return False
    for k in REQUIRED_PROFILE_FIELDS:
        v = u.get(k)
        if not v or (isinstance(v, str) and not v.strip()):
            return False
    return True

_PROFILE_WHITELIST = {
    "static", "home", "about", "contact",
    "alumni", "alumni_page", "alumni_detail",
    "blog", "blog_list", "blog_detail",
    "login", "logout", "register", "verify",
    "forgot_password", "reset_password",
    "change_email", "change_email_verify",
    "profile"  # allow accessing the profile editor
}

# ---------- Routes: Core ----------

@app.before_request
def enforce_profile_completion():
    if request.endpoint in (None, "static"):
        return

    if request.path.startswith("/admin"):
        return

    user_id = session.get("user_id")
    user_email = session.get("user_email") or session.get("email")

    if not (user_id or user_email):
        return

    if request.endpoint in _PROFILE_WHITELIST:
        return

    u = None
    if user_id:
        try:
            u = users.find_one({"_id": ObjectId(user_id)})
        except Exception:
            u = None
    if not u and user_email:
        u = users.find_one({"email": user_email})

    if not is_profile_complete(u):
        flash("Please complete your profile to continue.", "warning")
        return redirect(url_for("profile"))

@app.route("/")
def home():
    if not require_login():
        return redirect(url_for("login"))
    today = utcnow()
    upcoming = list(events.find({"published": True, "date": {"$gte": today}})
                    .sort("date", ASCENDING).limit(6))
    announcements = []
    try:
        announcements = list(blogs.find({"published": True})
                             .sort("created_at", DESCENDING).limit(6))
    except Exception:
        announcements = []
    return render_template("home.html", upcoming=upcoming, announcements=announcements)


@app.route("/settings/email", methods=["GET","POST"])
def change_email():
    if not require_login():
        return redirect(url_for("login"))
    u = users.find_one({"_id": ObjectId(session["user_id"])})
    if request.method == "POST":
        pwd = request.form.get("password","")
        new_email = (request.form.get("new_email") or "").strip().lower()
        if not (u and check_password_hash(u.get("password_hash",""), pwd)):
            flash("Incorrect password.", "danger"); return redirect(url_for("change_email"))
        if not new_email or "@" not in new_email:
            flash("Enter a valid email.", "danger"); return redirect(url_for("change_email"))

        now = utcnow()
        doc = _emailchange_doc(session["user_id"], new_email)
        if doc:
            last_sent = as_aware_utc(doc.get("last_sent")) if doc.get("last_sent") else None
            if last_sent and now - last_sent < timedelta(seconds=60):
                flash("Please wait before resending OTP.", "warning")
                return redirect(url_for("change_email_verify", new_email=new_email))

        code = make_otp()
        email_changes.update_one(
            {"user_id": ObjectId(session["user_id"]), "new_email": new_email},
            {"$set":{
                "otp_hash": generate_password_hash(code),
                "expires_at": now + timedelta(minutes=10),
                "last_sent": now,
                "attempts": 0
            }},
            upsert=True
        )
        try:
            send_mail(new_email, "Verify your new email", f"Your OTP is {code}. It expires in 10 minutes.")
        except Exception: pass
        flash("OTP sent to the new email.", "info")
        return redirect(url_for("change_email_verify", new_email=new_email))
    return render_template("settings_email.html")

@app.get("/settings/email/verify")
def change_email_verify():
    if not require_login():
        return redirect(url_for("login"))
    new_email = (request.args.get("new_email") or "").strip().lower()
    if not new_email: return redirect(url_for("change_email"))
    return render_template("settings_email_verify.html", new_email=new_email)

@app.post("/settings/email/verify")
def change_email_verify_post():
    if not require_login():
        return redirect(url_for("login"))
    new_email = (request.form.get("new_email") or "").strip().lower()
    otp = (request.form.get("otp") or "").strip()
    doc = _emailchange_doc(session["user_id"], new_email)
    if not doc:
        flash("Request a new OTP.", "danger"); return redirect(url_for("change_email"))
    now = utcnow()
    exp = as_aware_utc(doc.get("expires_at"))
    if not exp or now > exp:
        email_changes.delete_one({"_id": doc["_id"]})
        flash("OTP expired.", "danger"); return redirect(url_for("change_email"))
    if not check_password_hash(doc["otp_hash"], otp):
        attempts = int(doc.get("attempts",0)) + 1
        upd = {"$set":{"attempts": attempts}}
        if attempts >= 5:
            upd["$set"]["expires_at"] = now
        email_changes.update_one({"_id": doc["_id"]}, upd)
        flash("Invalid OTP.", "danger")
        return redirect(url_for("change_email_verify", new_email=new_email))

    users.update_one({"_id": ObjectId(session["user_id"])}, {"$set":{"personal_email": new_email}})
    email_changes.delete_one({"_id": doc["_id"]})
    flash("Email updated.", "success")
    return redirect(url_for("profile"))

@app.get("/settings/email/resend")
def change_email_resend():
    if not require_login():
        return redirect(url_for("login"))
    new_email = (request.args.get("new_email") or "").strip().lower()
    if not new_email: return redirect(url_for("change_email"))
    doc = _emailchange_doc(session["user_id"], new_email)
    now = utcnow()
    if doc:
        last = as_aware_utc(doc.get("last_sent")) if doc.get("last_sent") else None
        if last and now - last < timedelta(seconds=60):
            flash("Please wait before resending.", "warning")
            return redirect(url_for("change_email_verify", new_email=new_email))
    code = make_otp()
    email_changes.update_one(
        {"user_id": ObjectId(session["user_id"]), "new_email": new_email},
        {"$set":{"otp_hash": generate_password_hash(code), "expires_at": now + timedelta(minutes=10), "last_sent": now, "attempts": 0}},
        upsert=True
    )
    try:
        send_mail(new_email, "Verify your new email", f"Your OTP is {code}. It expires in 10 minutes.")
    except Exception: pass
    flash("OTP resent.", "info")
    return redirect(url_for("change_email_verify", new_email=new_email))



# ---------- Routes: Alumni (PUBLIC) ----------

@app.route("/alumni")
def alumni():
    q = (request.args.get("q") or "").strip()
    year = (request.args.get("year") or "").strip()
    branch = (request.args.get("branch") or "").strip()
    try: per_page = int(request.args.get("n", "10"))
    except: per_page = 10
    if per_page not in (10, 25, 50): per_page = 10
    try: page = max(1, int(request.args.get("page", "1")))
    except: page = 1

    filt = {"verified_at": {"$ne": None}}
    ors = []
    if q:
        ors.append({"full_name": {"$regex": re.escape(q), "$options": "i"}})
        ors.append({"company": {"$regex": re.escape(q), "$options": "i"}})
    if ors: filt["$or"] = ors
    if year.isdigit(): filt["graduation_year"] = int(year)
    if branch: filt["branch"] = {"$regex": f"^{re.escape(branch)}$", "$options": "i"}

    total = users.count_documents(filt)
    skip = (page - 1) * per_page
    cur = users.find(filt).sort([("graduation_year", DESCENDING), ("full_name", ASCENDING)]).skip(skip).limit(per_page)

    rows = []
    for u in cur:
        rows.append({
            "id": str(u["_id"]),
            "full_name": u.get("full_name") or "",
            "graduation_year": u.get("graduation_year") or "",
            "branch": u.get("branch") or "",
            "company": u.get("company") or "",
            "linkedin": u.get("linkedin") or "",
        })

    pages = (total + per_page - 1) // per_page
    return render_template("alumni.html", rows=rows, q=q, year=year, branch=branch,
                           page=page, pages=pages, per_page=per_page, total=total)

# ---------- Routes: Auth (login / register + OTP verify) ----------

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pwd = request.form.get("password","")
        u = users.find_one({"personal_email": email})
        if u and check_password_hash(u.get("password_hash",""), pwd):
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

@app.post("/verify/resend")
def verify_resend():
    college_email = (request.args.get("email") or request.form.get("college_email") or "").strip().lower()
    if not college_email:
        flash("Start registration again.", "danger")
        return redirect(url_for("register"))

    rec = otps.find_one({"college_email": college_email})
    if not rec:
        flash("Start registration again.", "danger")
        return redirect(url_for("register"))

    # 60s throttle
    last = rec.get("last_sent")
    now = datetime.now(timezone.utc)
    if last and (now - (last if last.tzinfo else last.replace(tzinfo=timezone.utc))).total_seconds() < 60:
        flash("Please wait before resending.", "warning")
        return redirect(url_for("verify", email=college_email))

    code = make_otp()
    otps.update_one(
        {"_id": rec["_id"]},
        {"$set": {
            "otp_hash": generate_password_hash(code),
            "expires_at": now + timedelta(minutes=10),
            "last_sent": now
        }}
    )
    try:
        send_mail(college_email, "Campus Circle – Verify your email", f"Your OTP is {code}. It expires in 10 minutes.")
    except Exception:
        pass
    flash("OTP resent.", "info")
    return redirect(url_for("verify", email=college_email))

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
            "graduation_year": int(data["graduation_year"]) if data["graduation_year"].isdigit() else None,
            "company": data["company"].strip() or None,
            "phone": data["phone"].strip() or None,
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


@app.route("/blog")
def blog_list():
    rows = []
    for b in blogs.find({"published": True}).sort("created_at", DESCENDING):
        rows.append(b)
    return render_template("blog_list.html", rows=rows)

@app.route("/blog/<slug>")
def blog_detail(slug):
    b = blogs.find_one({"slug": slug, "published": True})
    if not b:
        abort(404)
    return render_template("blog_detail.html", b=b)

@app.route("/event/<slug>")
def event_detail(slug):
    e = events.find_one({"slug": slug, "published": True})
    if not e:
        abort(404)
    return render_template("event_detail.html", e=e)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    q = (request.json or {}).get("message","").strip()
    if not q:
        return {"ok": False, "answer": ""}, 400
    try:
        r = requests.post(f"{OLLAMA_HOST}/api/chat", json={
            "model": OLLAMA_MODEL,
            "messages": [
                {"role":"system","content":"You are Campus Circle assistant."},
                {"role":"user","content": q}
            ],
            "stream": False
        }, timeout=30)
        if r.status_code != 200:
            return {"ok": False, "answer": ""}, 502
        ans = r.json().get("message",{}).get("content","")
        return {"ok": True, "answer": ans}
    except Exception:
        return {"ok": False, "answer": ""}, 500


@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        pw = request.form.get("password","")
        if pw == ADMIN_PASSWORD:
            session["is_admin"] = True
            return redirect(url_for("admin_index"))
        flash("Invalid admin password.", "danger")
        return redirect(url_for("admin_login"))
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("login"))
# ---------- Routes: Admin ----------

@app.route("/admin")
def admin_index():
    if not require_admin():
        return redirect(url_for("admin_login"))
    return redirect(url_for("admin_events"))

@app.route("/admin/events")
def admin_events():
    if not require_admin():
        return redirect(url_for("admin_login"))

    q = (request.args.get("q") or "").strip()
    try: per_page = int(request.args.get("n", "20"))
    except: per_page = 20
    if per_page not in (20, 50, 100): per_page = 20
    try: page = max(1, int(request.args.get("page", "1")))
    except: page = 1

    filt = {}
    if q:
        filt["$or"] = [
            {"title": {"$regex": re.escape(q), "$options": "i"}},
            {"venue": {"$regex": re.escape(q), "$options": "i"}},
            {"mode": {"$regex": re.escape(q), "$options": "i"}},
        ]

    total = events.count_documents(filt)
    skip = (page - 1) * per_page
    cur = events.find(filt).sort("date", DESCENDING).skip(skip).limit(per_page)

    rows = []
    for e in cur:
        rows.append({
            "id": str(e["_id"]),
            "title": e.get("title") or "",
            "slug": e.get("slug") or "",
            "date": e.get("date"),
            "published": bool(e.get("published")),
        })

    pages = (total + per_page - 1) // per_page
    return render_template("admin_events.html", events=rows, q=q, per_page=per_page, page=page, pages=pages, total=total)

@app.route("/admin/events/new", methods=["GET","POST"])
def admin_events_new():
    if not require_admin():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        description = request.form.get("description","").strip()
        date_str = request.form.get("date","").strip()
        venue = request.form.get("venue","").strip()
        mode = request.form.get("mode","").strip()
        join_url = safe_url(request.form.get("join_url","").strip())
        publish = bool(request.form.get("publish"))
        try:
            dt = datetime.fromisoformat(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        except:
            dt = utcnow()
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
        return redirect(url_for("admin_events"))
    return render_template("admin_event_new.html")

@app.post("/admin/event/<id>/toggle")
def admin_event_toggle(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    e = events.find_one({"_id": ObjectId(id)})
    if e:
        events.update_one({"_id": e["_id"]}, {"$set":{"published": not bool(e.get("published")),"updated_at": utcnow()}})
        flash("Event updated.", "success")
    return redirect(url_for("admin_events"))

@app.post("/admin/event/<id>/delete")
def admin_event_delete(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    events.delete_one({"_id": ObjectId(id)})
    flash("Event deleted.", "warning")
    return redirect(url_for("admin_events"))

@app.route("/admin/blogs")
def admin_blogs():
    if not require_admin():
        return redirect(url_for("admin_login"))

    q = (request.args.get("q") or "").strip()
    try: per_page = int(request.args.get("n", "20"))
    except: per_page = 20
    if per_page not in (20, 50, 100): per_page = 20
    try: page = max(1, int(request.args.get("page", "1")))
    except: page = 1

    filt = {}
    if q:
        filt["$or"] = [
            {"title": {"$regex": re.escape(q), "$options": "i"}},
            {"body": {"$regex": re.escape(q), "$options": "i"}},
        ]

    total = blogs.count_documents(filt)
    skip = (page - 1) * per_page
    cur = blogs.find(filt).sort("created_at", DESCENDING).skip(skip).limit(per_page)

    rows = []
    for b in cur:
        rows.append({
            "id": str(b["_id"]),
            "title": b.get("title") or "",
            "slug": b.get("slug") or "",
            "published": bool(b.get("published")),
            "created_at": b.get("created_at"),
        })

    pages = (total + per_page - 1) // per_page
    return render_template("admin_blogs.html", blogs=rows, q=q, per_page=per_page, page=page, pages=pages, total=total)

@app.route("/admin/blogs/new", methods=["GET","POST"])
def admin_blogs_new():
    if not require_admin():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        body = request.form.get("body","").strip()
        publish = bool(request.form.get("publish"))
        blogs.insert_one({
            "title": title,
            "body": body,
            "slug": slugify(title),
            "published": publish,
            "created_at": utcnow(),
            "updated_at": utcnow()
        })
        flash("Blog saved.", "success")
        return redirect(url_for("admin_blogs"))
    return render_template("admin_blog_new.html")

@app.post("/admin/blog/<id>/toggle")
def admin_blog_toggle(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    b = blogs.find_one({"_id": ObjectId(id)})
    if b:
        blogs.update_one({"_id": b["_id"]}, {"$set":{"published": not bool(b.get("published")),"updated_at": utcnow()}})
        flash("Blog updated.", "success")
    return redirect(url_for("admin_blogs"))

@app.post("/admin/blog/<id>/delete")
def admin_blog_delete(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    blogs.delete_one({"_id": ObjectId(id)})
    flash("Blog deleted.", "warning")
    return redirect(url_for("admin_blogs"))

@app.route("/admin/alumni")
def admin_alumni():
    if not require_admin():
        return redirect(url_for("admin_login"))

    q = (request.args.get("q") or "").strip()
    try: per_page = int(request.args.get("n", "25"))
    except: per_page = 25
    if per_page not in (25, 50, 100): per_page = 25
    try: page = max(1, int(request.args.get("page", "1")))
    except: page = 1

    filt = {}
    ors = []
    if q:
        if q.isdigit():
            ors.append({"graduation_year": int(q)})
        ors.extend([
            {"full_name": {"$regex": re.escape(q), "$options": "i"}},
            {"college_email": {"$regex": re.escape(q), "$options": "i"}},
            {"personal_email": {"$regex": re.escape(q), "$options": "i"}},
            {"branch": {"$regex": re.escape(q), "$options": "i"}},
            {"company": {"$regex": re.escape(q), "$options": "i"}},
        ])
    if ors: filt["$or"] = ors

    total = users.count_documents(filt)
    skip = (page - 1) * per_page
    cur = users.find(filt).sort("created_at", DESCENDING).skip(skip).limit(per_page)

    rows = []
    for u in cur:
        rows.append({
            "id": str(u["_id"]),
            "full_name": u.get("full_name") or "",
            "college_email": u.get("college_email") or "",
            "personal_email": u.get("personal_email") or "",
            "graduation_year": u.get("graduation_year") or "",
            "branch": u.get("branch") or "",
            "company": u.get("company") or "",
        })

    pages = (total + per_page - 1) // per_page
    return render_template("admin_alumni.html", rows=rows, q=q, per_page=per_page, page=page, pages=pages, total=total)

@app.post("/admin/alumni/<id>/delete")
def admin_alumni_delete(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    users.delete_one({"_id": ObjectId(id)})
    flash("Alumnus deleted.", "warning")
    return redirect(url_for("admin_alumni"))

# ---------- Run ----------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
