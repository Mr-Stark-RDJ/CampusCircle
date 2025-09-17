import os, smtplib, ssl, secrets, string, sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from pymongo import MongoClient, ASCENDING, DESCENDING
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    sys.exit("MONGO_URL not set.")
mongo = MongoClient(MONGO_URL)
db = mongo["campus_circle"]
users = db["users"]
events = db["events"]
pending = db["pending_registrations"]
messages = db["messages"]
resets = db["password_resets"]

SMTP_HOST = os.getenv("BREVO_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("BREVO_SMTP_PORT", "587"))
SMTP_USER = os.getenv("BREVO_SMTP_USER", "")
SMTP_PASS_RAW = os.getenv("BREVO_SMTP_PASS", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USER)
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
ADMIN_NOTIFY_EMAIL = os.getenv("ADMIN_NOTIFY_EMAIL", EMAIL_FROM or SMTP_USER)
COLLEGE_DOMAIN = os.getenv("COLLEGE_EMAIL_DOMAIN", "")

def _normalize_app_password(pw: str) -> str:
    return (pw or "").strip().strip('"').replace(" ", "")

def send_mail(to, subject, body):
    msg = EmailMessage()
    from_addr = EMAIL_FROM if EMAIL_FROM else SMTP_USER
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    pw = _normalize_app_password(SMTP_PASS_RAW)
    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.ehlo()
        s.login(SMTP_USER, pw)
        s.send_message(msg)

def require_login():
    return "user_id" in session

def current_user():
    uid = session.get("user_id")
    return users.find_one({"_id": ObjectId(uid)}) if uid else None

def require_admin():
    return session.get("admin") is True

@app.route("/")
def home():
    if not require_login():
        return redirect(url_for("login"))
    today = datetime.now(timezone.utc).date()
    start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    up = list(events.find({"published": True, "date": {"$gte": start}}).sort("date", ASCENDING).limit(6))
    latest = list(events.find({"published": True}).sort("created_at", DESCENDING).limit(6))
    return render_template("home.html", upcoming=up, latest=latest)

@app.route("/alumni")
def alumni():
    q = request.args.get("q", "").strip()
    year = request.args.get("year", "").strip()
    branch = request.args.get("branch", "").strip()
    filt = {"verified_at": {"$ne": None}}
    if q:
        filt["$or"] = [
            {"full_name": {"$regex": q, "$options": "i"}},
            {"company": {"$regex": q, "$options": "i"}},
            {"linkedin": {"$regex": q, "$options": "i"}}
        ]
    if year:
        try:
            filt["graduation_year"] = int(year)
        except:
            pass
    if branch:
        filt["branch"] = branch
    lst = list(users.find(filt, {"password_hash": 0, "role": 0}).sort("graduation_year", DESCENDING).limit(200))
    years = sorted({u.get("graduation_year") for u in users.find({"verified_at": {"$ne": None}}, {"graduation_year": 1}) if u.get("graduation_year")}, reverse=True)
    branches = sorted({(u.get("branch") or "").upper() for u in users.find({"verified_at": {"$ne": None}}, {"branch": 1}) if u.get("branch")})
    return render_template("alumni.html", items=lst, years=years, branches=branches, q=q, y=year, b=branch)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET","POST"])
def contact():
    if request.method == "POST":
        full_name = request.form.get("name","").strip()
        email = request.form.get("email","").strip()
        msg = request.form.get("message","").strip()
        if not full_name or not email or not msg:
            flash("All fields are required.", "danger")
            return redirect(url_for("contact"))
        doc = {"name": full_name, "email": email, "message": msg, "created_at": datetime.now(timezone.utc)}
        messages.insert_one(doc)
        try:
            send_mail(ADMIN_NOTIFY_EMAIL, "New Contact Message", f"From: {full_name} <{email}>\n\n{msg}")
        except:
            pass
        flash("Message sent.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        college_email = request.form.get("college_email","").strip().lower()
        personal_email = request.form.get("personal_email","").strip().lower()
        password = request.form.get("password","")
        if COLLEGE_DOMAIN and not college_email.endswith(COLLEGE_DOMAIN):
            flash("Use your college email.", "danger")
            return redirect(url_for("register"))
        if users.find_one({"$or":[{"college_email": college_email},{"personal_email": personal_email}]}):
            flash("Account already exists.", "danger")
            return redirect(url_for("register"))
        now = datetime.now(timezone.utc)
        doc = pending.find_one({"college_email": college_email})
        if doc and doc.get("locked_until") and now < doc["locked_until"]:
            flash("Too many attempts. Try again later.", "danger")
            return redirect(url_for("register"))
        if doc and doc.get("window_start") and now - doc["window_start"] > timedelta(hours=1):
            pending.update_one({"_id": doc["_id"]}, {"$set":{"window_start": now, "resend_count": 0}})
            doc["window_start"] = now
            doc["resend_count"] = 0
        if doc and doc.get("last_sent") and now - doc["last_sent"] < timedelta(seconds=60):
            flash("Wait 60 seconds before requesting another OTP.", "danger")
            session["pending_college_email"] = college_email
            return redirect(url_for("verify"))
        if doc and doc.get("resend_count",0) >= 5:
            flash("OTP request limit reached. Try after 1 hour.", "danger")
            session["pending_college_email"] = college_email
            return redirect(url_for("verify"))
        code = "".join(secrets.choice(string.digits) for _ in range(6))
        code_hash = generate_password_hash(code)
        pending.update_one(
            {"college_email": college_email},
            {"$set":{
                "college_email": college_email,
                "personal_email": personal_email,
                "password_hash": generate_password_hash(password),
                "otp_hash": code_hash,
                "expires_at": now + timedelta(minutes=10),
                "created_at": now,
                "last_sent": now
            },
             "$inc":{"resend_count":1},
             "$setOnInsert":{"attempts":0,"window_start": now}
            },
            upsert=True
        )
        try:
            send_mail(college_email, "Campus Circle OTP", f"Your OTP is {code}. It expires in 10 minutes.")
            flash("OTP sent to your college email.", "success")
        except:
            flash("Email sending failed. Check Gmail SMTP/app password.", "danger")
        session["pending_college_email"] = college_email
        return redirect(url_for("verify"))
    return render_template("auth_register.html")

@app.route("/verify", methods=["GET","POST"])
def verify():
    email = session.get("pending_college_email","")
    if request.method == "POST":
        code = request.form.get("otp","").strip()
        email_in = request.form.get("college_email","").strip().lower()
        if email_in:
            email = email_in
        doc = pending.find_one({"college_email": email})
        if not doc:
            flash("No pending registration found.", "danger")
            return redirect(url_for("register"))
        now = datetime.now(timezone.utc)
        if doc.get("locked_until") and now < doc["locked_until"]:
            flash("Too many attempts. Try again later.", "danger")
            return redirect(url_for("verify"))
        if now > doc["expires_at"]:
            pending.delete_one({"_id": doc["_id"]})
            flash("OTP expired.", "danger")
            return redirect(url_for("register"))
        if not check_password_hash(doc["otp_hash"], code):
            attempts = int(doc.get("attempts",0)) + 1
            upd = {"$set":{"attempts": attempts}}
            if attempts >= 3:
                upd["$set"]["locked_until"] = now + timedelta(minutes=15)
            pending.update_one({"_id": doc["_id"]}, upd)
            if attempts >= 3:
                flash("Too many wrong attempts. Locked for 15 minutes.", "danger")
            else:
                flash("Invalid OTP.", "danger")
            return redirect(url_for("verify"))
        u = {
            "college_email": doc["college_email"],
            "personal_email": doc["personal_email"],
            "password_hash": doc["password_hash"],
            "verified_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "role": "alumni",
            "full_name": "",
            "phone": "",
            "mobile": "",
            "company": "",
            "graduation_year": None,
            "linkedin": "",
            "branch": ""
        }
        res = users.insert_one(u)
        pending.delete_one({"_id": doc["_id"]})
        session.pop("pending_college_email", None)
        session["user_id"] = str(res.inserted_id)
        flash("Registration complete.", "success")
        return redirect(url_for("profile"))
    return render_template("auth_verify.html", email=email)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        u = users.find_one({"$or":[{"personal_email": email},{"college_email": email}]})
        if not u or not check_password_hash(u["password_hash"], password):
            flash("Invalid credentials.", "danger")
            return redirect(url_for("login"))
        session["user_id"] = str(u["_id"])
        flash("Logged in.", "success")
        return redirect(url_for("home"))
    return render_template("auth_login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))

@app.route("/forgot", methods=["GET","POST"])
def forgot():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        u = users.find_one({"$or":[{"personal_email": email},{"college_email": email}]})
        if not u:
            flash("If the email exists, an OTP has been sent.", "info")
            return redirect(url_for("forgot"))
        now = datetime.now(timezone.utc)
        doc = resets.find_one({"email": email})
        if doc and doc.get("last_sent") and now - doc["last_sent"] < timedelta(seconds=60):
            flash("Wait 60 seconds before requesting another OTP.", "danger")
            return redirect(url_for("forgot"))
        code = "".join(secrets.choice(string.digits) for _ in range(6))
        code_hash = generate_password_hash(code)
        resets.update_one(
            {"email": email},
            {"$set":{"otp_hash": code_hash, "expires_at": now + timedelta(minutes=10), "last_sent": now, "attempts":0}},
            upsert=True
        )
        try:
            send_mail(email, "Campus Circle Password Reset OTP", f"Your OTP is {code}. It expires in 10 minutes.")
        except:
            pass
        flash("If the email exists, an OTP has been sent.", "info")
        return redirect(url_for("reset"))
    return render_template("auth_forgot.html")

@app.route("/reset", methods=["GET","POST"])
def reset():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        otp = request.form.get("otp","").strip()
        newp = request.form.get("password","")
        doc = resets.find_one({"email": email})
        if not doc:
            flash("Request a new OTP.", "danger")
            return redirect(url_for("forgot"))
        now = datetime.now(timezone.utc)
        if now > doc["expires_at"]:
            resets.delete_one({"_id": doc["_id"]})
            flash("OTP expired.", "danger")
            return redirect(url_for("forgot"))
        if not check_password_hash(doc["otp_hash"], otp):
            att = int(doc.get("attempts",0)) + 1
            upd = {"$set":{"attempts": att}}
            if att >= 3:
                upd["$set"]["expires_at"] = now
            resets.update_one({"_id": doc["_id"]}, upd)
            flash("Invalid OTP.", "danger")
            return redirect(url_for("reset"))
        users.update_one(
            {"$or":[{"personal_email": email},{"college_email": email}]},
            {"$set":{"password_hash": generate_password_hash(newp)}}
        )
        resets.delete_one({"_id": doc["_id"]})
        flash("Password updated. Login now.", "success")
        return redirect(url_for("login"))
    return render_template("auth_reset.html")

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        pwd = request.form.get("password","")
        if pwd == ADMIN_PASSWORD and ADMIN_PASSWORD:
            session["admin"] = True
            flash("Admin logged in.", "success")
            return redirect(url_for("admin"))
        flash("Invalid admin password.", "danger")
        return redirect(url_for("admin_login"))
    return render_template("admin_login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("login"))

@app.route("/admin", methods=["GET","POST"])
def admin():
    if not require_admin():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        title = request.form.get("title","").strip()
        date = request.form.get("date","").strip()
        desc = request.form.get("description","").strip()
        pub = request.form.get("published") == "on"
        try:
            dt = datetime.fromisoformat(date)
            dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except:
            dt = datetime.now(timezone.utc)
        events.insert_one({
            "title": title,
            "description": desc,
            "date": dt,
            "published": pub,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        })
        flash("Event saved.", "success")
        return redirect(url_for("admin"))
    ev = list(events.find().sort("date", DESCENDING))
    total_alumni = users.count_documents({"verified_at": {"$ne": None}})
    return render_template("admin_dashboard.html", events=ev, total_alumni=total_alumni)

@app.route("/admin/event/<id>/toggle")
def admin_event_toggle(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    e = events.find_one({"_id": ObjectId(id)})
    if e:
        events.update_one({"_id": e["_id"]}, {"$set":{"published": not bool(e.get("published")), "updated_at": datetime.now(timezone.utc)}})
    return redirect(url_for("admin"))

@app.route("/admin/event/<id>/delete")
def admin_event_delete(id):
    if not require_admin():
        return redirect(url_for("admin_login"))
    events.delete_one({"_id": ObjectId(id)})
    return redirect(url_for("admin"))

@app.route("/admin/seed")
def admin_seed():
    if not require_admin():
        return redirect(url_for("admin_login"))
    from random import choice, randint
    branches = ["CSE","ECE","ME","CE","EEE","IT","BBA","MBA"]
    first = ["Aarav","Vivaan","Aditya","Ishaan","Vihaan","Arjun","Reyansh","Shaurya","Krish","Dhruv","Ananya","Diya","Aadhya","Anika","Ira","Myra","Sara","Kiara","Meera","Aarohi"]
    last = ["Sharma","Verma","Gupta","Singh","Patel","Reddy","Nair","Das","Khan","Chopra","Bose","Pillai"]
    companies = ["TCS","Infosys","Wipro","Accenture","HCL","Google","Microsoft","Amazon","Flipkart","Paytm","Zomato","Swiggy","PhonePe","Byju's","Ola"]
    for _ in range(60):
        fn = f"{choice(first)} {choice(last)}"
        yr = randint(2012, 2025)
        br = choice(branches)
        pe = f"{fn.lower().replace(' ','')}@mail.com"
        ce = f"{fn.lower().replace(' ','')}{yr}{br.lower()}@{COLLEGE_DOMAIN.replace('@','')}" if COLLEGE_DOMAIN else f"{fn.lower().replace(' ','')}{yr}{br.lower()}@college.edu"
        users.insert_one({
            "college_email": ce,
            "personal_email": pe,
            "password_hash": generate_password_hash("Pass@1234"),
            "verified_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "role": "alumni",
            "full_name": fn,
            "phone": "9" + "".join(secrets.choice(string.digits) for _ in range(9)),
            "mobile": "8" + "".join(secrets.choice(string.digits) for _ in range(9)),
            "company": choice(companies),
            "graduation_year": yr,
            "linkedin": "https://linkedin.com/in/" + fn.lower().replace(" ",""),
            "branch": br
        })
    base = datetime.now(timezone.utc)
    events.insert_many([
        {"title":"Annual Alumni Meet", "description":"Reunion and networking", "date": base + timedelta(days=14), "published": True, "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)},
        {"title":"Mentorship Drive", "description":"Alumni mentoring signups", "date": base + timedelta(days=30), "published": True, "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)},
        {"title":"Webinar: Careers in AI", "description":"Industry talk", "date": base + timedelta(days=45), "published": False, "created_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}
    ])
    flash("Dummy alumni and events added.", "success")
    return redirect(url_for("admin"))

@app.route("/api/chatbot", methods=["POST"])
def api_chatbot():
    data = request.get_json(silent=True) or {}
    q = (data.get("q") or "").lower()
    if not q:
        return jsonify({"answer":"Ask me about events, registration, alumni search, or contact."})
    if "register" in q or "sign up" in q:
        return jsonify({"answer":"Use Register with your college email and personal email, set a password, then enter the OTP sent to your college email. After login, complete your profile with name, branch, year, phone, company, and LinkedIn."})
    if "otp" in q:
        return jsonify({"answer":"An OTP is emailed to your college address and expires in 10 minutes. If it expires, re-register to get a new OTP."})
    if "login" in q:
        return jsonify({"answer":"Login with your email and password on the Login page. You can use either your college or personal email."})
    if "event" in q:
        today = datetime.now(timezone.utc).date()
        start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        up = list(events.find({"published": True, "date": {"$gte": start}}).sort("date", ASCENDING).limit(3))
        if not up:
            return jsonify({"answer":"There are no upcoming published events yet. Check back soon."})
        txt = "Upcoming events: " + "; ".join([f"{e['title']} on {e['date'].strftime('%d-%b-%Y')}" for e in up])
        return jsonify({"answer": txt})
    if "alumni" in q or "directory" in q:
        count = users.count_documents({"verified_at": {"$ne": None}})
        return jsonify({"answer": f"The directory has {count} verified alumni. Filter by year and branch on the Alumni page."})
    if "contact" in q or "admin" in q:
        return jsonify({"answer":"Use the Contact page to message the admins. Enter your name, email, and message, and you will receive a confirmation."})
    return jsonify({"answer":"I can help with registration, login, OTP, events, alumni directory, and contact. Ask me one of these."})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
