import os, re, secrets, string, smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from pymongo import MongoClient, ASCENDING, DESCENDING
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# ---------- App & DB ----------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL not set in .env")
client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
client.admin.command("ping")

db = client["campus_circle"]
users = db["users"]
events = db["events"]
otps = db["otps"]
messages = db["messages"]

# ---------- Env / Email ----------
SMTP_HOST = os.getenv("BREVO_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
SMTP_USER = os.getenv("BREVO_SMTP_USER")
SMTP_PASS = os.getenv("BREVO_SMTP_PASS")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)
COLLEGE_EMAIL_DOMAIN = os.getenv("COLLEGE_EMAIL_DOMAIN", "@gmail.com").lower()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
ADMIN_NOTIFY_EMAIL = os.getenv("ADMIN_NOTIFY_EMAIL", EMAIL_FROM)

# ---------- Helpers ----------
UTC = timezone.utc
def now():
    return datetime.now(UTC)

def login_required(fn):
    from functools import wraps
    @wraps(fn)
    def _w(*a, **k):
        if not session.get("uid"):
            return redirect(url_for("login"))
        return fn(*a, **k)
    return _w

def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def _w(*a, **k):
        if not session.get("admin"):
            return redirect(url_for("admin_login"))
        return fn(*a, **k)
    return _w

def send_email(to, subject, text):
    if not (SMTP_HOST and SMTP_PORT and SMTP_USER and SMTP_PASS and EMAIL_FROM):
        print("[EMAIL] Missing SMTP config; skipping send.")
        return
    msg = EmailMessage()
    msg["From"] = EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)

def valid_phone(v):
    # 7–15 digits, optional +country
    return re.fullmatch(r"\+?\d{7,15}", v or "") is not None

def valid_name(v):
    # Letters, spaces, dots and hyphens, 2–80 chars
    return re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,79}", v or "") is not None

def clamp(n, lo, hi):
    try:
        n = int(n)
    except:
        n = lo
    return max(lo, min(hi, n))

# ---------- Auth ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        u = users.find_one({"$or": [{"personal_email": email}, {"college_email": email}]})
        if u and check_password_hash(u.get("password_hash",""), pw):
            session["uid"] = str(u["_id"])
            session["name"] = u.get("name") or email
            flash("Logged in.", "success")
            return redirect(url_for("home"))
        flash("Invalid credentials.", "danger")
    return render_template("auth_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))

# (Your existing register / verify / forgot / reset routes can stay as-is.)

# ---------- Public pages ----------
@app.route("/")
def index():
    return redirect(url_for("home"))

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        messages.insert_one({
            "name": request.form.get("name","").strip(),
            "email": (request.form.get("email","").strip().lower()),
            "message": request.form.get("message","").strip(),
            "created_at": now()
        })
        flash("Message sent.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# Homescreen after login
@app.route("/home")
@login_required
def home():
    today = now().date()
    up = list(events.find(
        {"published": True, "date": {"$gte": datetime(today.year, today.month, today.day, tzinfo=UTC)}}
    ).sort("date", ASCENDING).limit(6))
    latest = list(events.find({"published": True}).sort("date", DESCENDING).limit(6))
    return render_template("home.html", upcoming=up, latest=latest)

# Public alumni directory with server-side pagination (no phones)
@app.route("/alumni")
def alumni():
    page = clamp(request.args.get("page", 1), 1, 1000000)
    per_page = clamp(request.args.get("per_page", 10), 10, 100)
    query = {"verified": {"$ne": False}}  # show if verified or default
    total = users.count_documents(query)
    cursor = users.find(
        query,
        projection={"name":1,"branch":1,"grad_year":1,"company":1,"linkedin":1,"_id":1}
    ).sort([("grad_year", DESCENDING), ("name", ASCENDING)]
    ).skip((page-1)*per_page).limit(per_page)
    rows = list(cursor)
    return render_template("alumni.html",
        rows=rows, page=page, per_page=per_page, total=total
    )

# ---------- Profile ----------
@app.route("/profile", methods=["GET","POST"])
@login_required
def profile():
    uid = ObjectId(session["uid"])
    u = users.find_one({"_id": uid})
    if request.method == "POST":
        name = request.form.get("name","").strip()
        phone = request.form.get("phone","").strip()
        mobile = request.form.get("mobile","").strip()
        linkedin = request.form.get("linkedin","").strip()
        company = request.form.get("company","").strip()
        branch = request.form.get("branch","").strip()
        grad_year = clamp(request.form.get("grad_year"), 1950, 2100)
        errs = []
        if name and not valid_name(name): errs.append("Invalid name.")
        if phone and not valid_phone(phone): errs.append("Invalid phone.")
        if mobile and not valid_phone(mobile): errs.append("Invalid mobile.")
        if errs:
            for e in errs: flash(e, "danger")
            return render_template("profile.html", u=u)
        users.update_one({"_id": uid},{
            "$set":{
                "name": name or u.get("name"),
                "phone": phone,
                "mobile": mobile,
                "linkedin": linkedin,
                "company": company,
                "branch": branch,
                "grad_year": grad_year,
                "updated_at": now()
            }
        })
        flash("Profile updated.", "success")
        return redirect(url_for("profile"))
    return render_template("profile.html", u=u)

# ---------- Events ----------
@app.route("/event/<id>")
def event_detail(id):
    try:
        ev = events.find_one({"_id": ObjectId(id), "published": True})
    except:
        ev = None
    if not ev:
        abort(404)
    return render_template("event_detail.html", ev=ev)

# ---------- Admin ----------
@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        pw = request.form.get("password") or ""
        if pw == ADMIN_PASSWORD:
            session["admin"] = True
            session["admin_email"] = email or "admin"
            flash("Admin logged in.", "success")
            return redirect(url_for("admin"))
        flash("Invalid admin password.", "danger")
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "info")
    return redirect(url_for("login"))

@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    # Create event
    if request.method == "POST":
        title = request.form.get("title","").strip()
        date_str = request.form.get("date","").strip()
        venue = request.form.get("venue","").strip()
        mode = request.form.get("mode","In-person")
        join_url = request.form.get("join_url","").strip()
        description = request.form.get("description","").strip()
        publish_now = bool(request.form.get("publish_now"))
        if not title or not date_str:
            flash("Title and date are required.", "danger")
        else:
            # Expect dd-mm-yyyy hh:mm
            try:
                dt = datetime.strptime(date_str, "%d-%m-%Y %H:%M").replace(tzinfo=UTC)
            except ValueError:
                flash("Invalid date format. Use dd-mm-yyyy hh:mm", "danger")
                return redirect(url_for("admin"))
            events.insert_one({
                "title": title,
                "date": dt,
                "venue": venue,
                "mode": mode,
                "join_url": join_url,
                "description": description,
                "published": publish_now,
                "created_at": now(),
                "updated_at": now()
            })
            flash("Event saved.", "success")
            return redirect(url_for("admin"))

    tab = request.args.get("tab","events")
    ev = list(events.find().sort("date", DESCENDING))
    # Alumni table data (no phones)
    alumni = list(users.find({}, {"name":1,"college_email":1,"personal_email":1,"grad_year":1,"branch":1}).sort([("grad_year", DESCENDING), ("name", ASCENDING)]).limit(200))
    total_alumni = users.count_documents({})
    return render_template("admin.html", tab=tab, events=ev, alumni=alumni, total_alumni=total_alumni)

@app.post("/admin/event/toggle/<id>")
@admin_required
def admin_event_toggle(id):
    try:
        ev = events.find_one({"_id": ObjectId(id)})
        if not ev: abort(404)
        events.update_one({"_id": ev["_id"]}, {"$set": {"published": not ev.get("published", False), "updated_at": now()}})
        flash("Event visibility toggled.", "success")
    except:
        flash("Invalid event id.", "danger")
    return redirect(url_for("admin", tab="events"))

@app.post("/admin/event/delete/<id>")
@admin_required
def admin_event_delete(id):
    try:
        events.delete_one({"_id": ObjectId(id)})
        flash("Event deleted.", "success")
    except:
        flash("Invalid event id.", "danger")
    return redirect(url_for("admin", tab="events"))

@app.post("/admin/alumni/delete/<id>")
@admin_required
def admin_alumni_delete(id):
    try:
        users.delete_one({"_id": ObjectId(id)})
        flash("Alumnus removed.", "success")
    except:
        flash("Invalid id.", "danger")
    return redirect(url_for("admin", tab="alumni"))

@app.post("/admin/seed")
@admin_required
def admin_seed():
    sample_alumni = [
        {"name":"Meera Singh","college_email":"meera@example.com","personal_email":"meera@gmail.com","grad_year":2021,"branch":"BBA","company":"Globex","linkedin":"https://linkedin.com/in/sample1"},
        {"name":"Vihaan Reddy","college_email":"vihaan@example.com","personal_email":"vihaan@gmail.com","grad_year":2019,"branch":"ME","company":"Initech","linkedin":"https://linkedin.com/in/sample2"},
    ]
    for a in sample_alumni:
        a["password_hash"] = generate_password_hash("Password@123")
        a["created_at"] = now(); a["verified"]=True
    if sample_alumni:
        users.insert_many(sample_alumni)
    sample_events = [
        {"title":"Annual Alumni Meet","date": now()+timedelta(days=14), "venue":"Main Auditorium", "mode":"In-person","join_url":"","description":"Reunion and networking", "published":True, "created_at":now(), "updated_at":now()},
        {"title":"Mentorship Drive","date": now()+timedelta(days=45), "venue":"Zoom","mode":"Online","join_url":"https://example.com","description":"Alumni mentoring signups", "published":True, "created_at":now(), "updated_at":now()},
    ]
    events.insert_many(sample_events)
    flash("Dummy data added.", "success")
    return redirect(url_for("admin", tab="events"))

@app.get("/register")
def register():
    # Renders a clean registration page (OTP logic can be in a POST route later)
    return render_template("auth_register.html")

# ---------- Error handlers ----------
@app.errorhandler(404)
def _404(e):
    return render_template("404.html"), 404

# ---------- Run ----------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
