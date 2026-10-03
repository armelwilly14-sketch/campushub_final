import json, os, uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from flask import Flask, abort, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from database import get_db_connection

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def load_runtime_env():
    env_path = os.path.join(APP_DIR, ".env")
    for key in ("MISTRAL_API_KEY", "OPENAI_API_KEY", "AI_PROVIDER", "AI_MODEL", "AI_API_URL", "SECRET_KEY"):
        if os.getenv(key, "").strip() == "":
            os.environ.pop(key, None)
    load_dotenv(env_path, override=True)


load_runtime_env()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
ROOT = APP_DIR
UPLOAD = os.path.join(ROOT, "uploads")
PAST = {"pdf", "docx", "jpg", "jpeg", "png"}
IMAGE = {"jpg", "jpeg", "png", "gif", "webp"}
MSG_FILES = PAST


def ext(name):
    return name.rsplit(".", 1)[1].lower() if "." in name else ""


def save_file(f, folder, allowed):
    if not f or not f.filename or ext(f.filename) not in allowed:
        return None
    name = uuid.uuid4().hex + "_" + secure_filename(f.filename)
    os.makedirs(os.path.join(UPLOAD, folder), exist_ok=True)
    f.save(os.path.join(UPLOAD, folder, name))
    return name


def rows(sql, p=()):
    db = get_db_connection()
    c = db.cursor(dictionary=True)
    c.execute(sql, p)
    r = c.fetchall()
    c.close(); db.close()
    return r


def one(sql, p=()):
    r = rows(sql, p)
    return r[0] if r else None


def execute(sql, p=()):
    db = get_db_connection(); c = db.cursor()
    c.execute(sql, p); db.commit()
    last = c.lastrowid
    c.close(); db.close()
    return last


def effective_student_id():
    """Return the student represented by the current student or linked parent."""
    role = session.get("role")
    if role == "student":
        return session.get("user_id")
    if role == "parent":
        return session.get("child_student_id")
    return None


def required(role=None):
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if session.get("role") == "parent" and role is not None and role not in ("parent", "student_or_parent"):
                return redirect(url_for("parent_dashboard"))
            if role == "student_or_parent" and session.get("role") not in ("student", "parent"):
                return redirect(url_for("index"))
            if role and role != "student_or_parent" and session.get("role") != role:
                if session.get("role") == "student":
                    return redirect(url_for("student_dashboard"))
                return redirect(url_for("index"))
            return fn(*a, **k)
        return w
    return deco


def staff_only(fn):
    @wraps(fn)
    def w(*a, **k):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if session.get("role") not in ("admin", "teacher"):
            return redirect(url_for("student_dashboard"))
        return fn(*a, **k)
    return w


@app.context_processor
def common():
    site = one("SELECT * FROM site_settings WHERE id=1") or {"app_name": "CampusHub", "app_title": ""}
    language = session.get("language") or request.cookies.get("language") or "en"
    return {"site": site, "current_user": session.get("user_name"), "current_role": session.get("role"), "language": language}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    # Registration uses text fields with datalists so a student can select an existing
    # specialty/year OR type a new one. New values are automatically created.
    sp = rows("SELECT * FROM specialties ORDER BY name")
    ys = rows("SELECT * FROM years ORDER BY id")
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        matricule = request.form.get("matricule", "").strip().upper()
        password = request.form.get("password", "")
        specialty_name = request.form.get("specialty", "").strip()
        year_name = request.form.get("year", "").strip()
        if not all([full_name, email, matricule, password, specialty_name, year_name]):
            flash("Please complete all registration fields.")
            return render_template("register.html", specialties=sp, years=ys)
        # Keep the requested standard names, while still accepting custom values.
        aliases = {"year 1":"HND Year 1", "hnd 1":"HND Year 1", "hnd year1":"HND Year 1",
                   "year 2":"HND Year 2", "hnd 2":"HND Year 2", "hnd year2":"HND Year 2",
                   "year 3":"HND Year 3", "hnd 3":"HND Year 3", "hnd year3":"HND Year 3"}
        year_name = aliases.get(year_name.lower(), year_name)
        db = get_db_connection(); c = db.cursor(dictionary=True)
        try:
            c.execute("SELECT id FROM users WHERE email=%s", (email,))
            if c.fetchone():
                flash("This email is already registered.")
                return render_template("register.html", specialties=sp, years=ys)
            c.execute("SELECT id FROM users WHERE matricule=%s", (matricule,))
            if c.fetchone():
                flash("This matricule is already registered.")
                return render_template("register.html", specialties=sp, years=ys)
            c.execute("SELECT id FROM specialties WHERE LOWER(name)=LOWER(%s)", (specialty_name,))
            row = c.fetchone()
            if row:
                specialty_id = row["id"]
            else:
                c.execute("INSERT INTO specialties(name) VALUES(%s)", (specialty_name,))
                specialty_id = c.lastrowid
            c.execute("SELECT id FROM years WHERE LOWER(name)=LOWER(%s)", (year_name,))
            row = c.fetchone()
            if row:
                year_id = row["id"]
            else:
                c.execute("INSERT INTO years(name) VALUES(%s)", (year_name,))
                year_id = c.lastrowid
            c.execute("INSERT INTO users(full_name,email,password,role,matricule,specialty_id,year_id) VALUES(%s,%s,%s,'student',%s,%s,%s)",
                      (full_name, email, generate_password_hash(password), matricule, specialty_id, year_id))
            db.commit(); flash("Student account created successfully."); return redirect(url_for("login"))
        except Exception as e:
            db.rollback(); flash("Registration failed: " + str(e))
        finally:
            c.close(); db.close()
    return render_template("register.html", specialties=sp, years=ys)


@app.route("/parent/register", methods=["GET", "POST"])
def parent_register():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        matricule = request.form.get("matricule", "").strip().upper()
        if not full_name or not email or len(password) < 6 or not matricule:
            flash("Complete all fields. Password must contain at least 6 characters.")
            return render_template("parent/register.html")
        child = one("SELECT id FROM users WHERE role='student' AND matricule=%s", (matricule,))
        if not child:
            flash("No student was found with that matricule. Check it with your child or the school.")
            return render_template("parent/register.html")
        try:
            execute("INSERT INTO users(full_name,email,password,role,child_student_id) VALUES(%s,%s,%s,'parent',%s)",
                    (full_name, email, generate_password_hash(password), child["id"]))
            flash("Parent account created. Sign in with your child's matricule and your password.")
            return redirect(url_for("login"))
        except Exception:
            flash("Could not create parent account. The email may already be registered.")
    return render_template("parent/register.html")


@app.route("/admin/register", methods=["GET", "POST"])
def admin_register():
    if request.method == "POST":
        if request.form["issued_password"] != os.getenv("ADMIN_ISSUED_PASSWORD", "12345"):
            flash("Invalid issued administrator password."); return render_template("admin/register.html")
        try:
            execute("INSERT INTO users(full_name,email,password,role) VALUES(%s,%s,%s,'admin')",
                    (request.form["full_name"], request.form["email"], generate_password_hash(request.form["password"])))
            flash("Administrator created."); return redirect(url_for("login"))
        except Exception:
            flash("Could not create administrator. The email may already exist.")
    return render_template("admin/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        account_type = request.form.get("account_type", "student")
        identity = request.form.get("identity", "").strip()
        password = request.form.get("password", "")
        u = None
        if account_type == "parent":
            student = one("SELECT id FROM users WHERE role='student' AND matricule=%s", (identity.upper(),))
            if student:
                parents = rows("SELECT * FROM users WHERE role='parent' AND child_student_id=%s", (student["id"],))
                u = next((parent for parent in parents if check_password_hash(parent["password"], password)), None)
                if u:
                    u["student_id"] = student["id"]
        else:
            u = one("SELECT * FROM users WHERE email=%s AND role IN ('student','teacher','admin')", (identity.lower(),))
        if u and (u.get("is_banned") or u.get("is_suspended")):
            flash("This account is suspended. Contact an administrator.")
        elif u and check_password_hash(u["password"], password):
            session.update(user_id=u["id"], user_name=u["full_name"], role=u["role"],
                           specialty_id=u["specialty_id"], year_id=u["year_id"])
            if u["role"] == "admin": return redirect(url_for("admin_dashboard"))
            if u["role"] == "teacher": return redirect(url_for("teacher_dashboard"))
            if u["role"] == "parent":
                session["child_student_id"] = u["student_id"]
                return redirect(url_for("parent_dashboard"))
            return redirect(url_for("student_dashboard"))
        flash("Invalid login.")
    return render_template("login.html")


@app.route("/student")
@required("student")
def student_dashboard():
    return render_template("student/dashboard.html", **student_page_data(session["user_id"]))


def student_page_data(student_id):
    try:
        user = one("SELECT u.*,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.id=%s AND u.role='student'", (student_id,))
    except Exception:
        user = {}
    if not user:
        abort(404)
    sid, yid = user.get("specialty_id"), user.get("year_id")
    a = rows("SELECT a.*,u.full_name sender_name,u.role sender_role FROM announcements a LEFT JOIN users u ON a.created_by=u.id WHERE (a.specialty_id IS NULL OR a.specialty_id=%s) AND (a.year_id IS NULL OR a.year_id=%s) ORDER BY a.created_at DESC", (sid, yid))
    t = rows("SELECT t.*,s.name specialty,y.name year FROM timetables t JOIN specialties s ON t.specialty_id=s.id JOIN years y ON t.year_id=y.id WHERE t.specialty_id=%s AND t.year_id=%s ORDER BY t.created_at DESC", (sid, yid))
    p = rows("SELECT p.*,c.name course FROM past_papers p LEFT JOIN courses c ON p.course_id=c.id WHERE (p.specialty_id IS NULL OR p.specialty_id=%s) AND (p.year_id IS NULL OR p.year_id=%s) ORDER BY p.created_at DESC", (sid, yid))
    r = rows("SELECT r.*,c.name course FROM results r LEFT JOIN courses c ON r.course_id=c.id WHERE r.student_id=%s ORDER BY r.created_at DESC", (student_id,))
    m = rows("SELECT m.*,u.full_name sender_name,u.role sender_role FROM messages m LEFT JOIN users u ON m.sender_id=u.id WHERE m.student_id=%s ORDER BY m.created_at DESC", (student_id,))
    h = rows("SELECT h.*,c.name course FROM hall_distribution h LEFT JOIN courses c ON h.course_id=c.id WHERE (h.specialty_id IS NULL OR h.specialty_id=%s) AND (h.year_id IS NULL OR h.year_id=%s) ORDER BY h.id DESC", (sid, yid))
    return dict(user=user, announcements=a, timetables=t, past_papers=p, results=r, messages=m, halls=h)


@app.route("/parent")
@required("parent")
def parent_dashboard():
    child = one("SELECT id,full_name,matricule FROM users WHERE id=%s AND role='student'", (session.get("child_student_id"),))
    if not child:
        abort(404)
    return render_template("parent/dashboard.html", child=child)


@app.route("/parent/student")
@required("parent")
def parent_student_page():
    child_id = session.get("child_student_id")
    child = one("SELECT id FROM users WHERE id=%s AND role='student'", (child_id,))
    if not child:
        abort(404)
    return render_template("student/dashboard.html", **student_page_data(child_id), read_only=False, parent_proxy=True)


@app.route("/teacher-ratings", methods=["GET", "POST"])
@required("student")
def teacher_ratings():
    student_id = session["user_id"]
    if request.method == "POST":
        teacher_id = request.form.get("teacher_id", type=int)
        rating = request.form.get("rating", type=int)
        comment = request.form.get("comment", "").strip()
        if not teacher_id or not one("SELECT id FROM users WHERE id=%s AND role='teacher'", (teacher_id,)):
            flash("Select a valid teacher.")
        elif rating not in range(1, 6) or len(comment) > 2000:
            flash("Choose a rating from 1 to 5. Comments must be 2,000 characters or fewer.")
        else:
            execute("""INSERT INTO teacher_ratings(student_id,teacher_id,rating,comment)
                VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE rating=VALUES(rating),
                comment=VALUES(comment),updated_at=CURRENT_TIMESTAMP""",
                (student_id, teacher_id, rating, comment))
            flash("Your rating was submitted. Ratings are visible only to administrators.")
        return redirect(url_for("teacher_ratings"))
    teachers = rows("SELECT id,full_name FROM users WHERE role='teacher' ORDER BY full_name")
    return render_template("student/teacher_ratings.html", teachers=teachers)


@app.route("/admin/teacher-ratings")
@required("admin")
def admin_teacher_ratings():
    ratings = rows("""SELECT r.*,s.full_name student_name,s.matricule,t.full_name teacher_name
        FROM teacher_ratings r JOIN users s ON s.id=r.student_id
        JOIN users t ON t.id=r.teacher_id ORDER BY r.updated_at DESC""")
    summary = rows("""SELECT t.id,t.full_name,COUNT(r.id) rating_count,ROUND(AVG(r.rating),2) average_rating
        FROM users t LEFT JOIN teacher_ratings r ON r.teacher_id=t.id
        WHERE t.role='teacher' GROUP BY t.id,t.full_name ORDER BY t.full_name""")
    return render_template("admin/teacher_ratings.html", ratings=ratings, summary=summary)


@app.route("/assistant", methods=["GET", "POST"])
@required()
def assistant():
    role = session.get("role")
    if role not in ("parent", "teacher", "admin"):
        abort(403)
    answer = None
    question = ""
    error = None
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        if not question or len(question) > 4000:
            error = "Enter a question of up to 4,000 characters."
        else:
            provider = os.getenv("AI_PROVIDER", "").strip().lower()
            mistral_key = os.getenv("MISTRAL_API_KEY", "").strip()
            openai_key = os.getenv("OPENAI_API_KEY", "").strip()
            if provider == "mistral" or (not provider and mistral_key):
                api_key = mistral_key
                default_model = "mistral-small-latest"
                default_endpoint = "https://api.mistral.ai/v1/chat/completions"
            else:
                api_key = openai_key
                default_model = "gpt-4o-mini"
                default_endpoint = "https://api.openai.com/v1/chat/completions"
            if not api_key:
                error = "The AI assistant is not configured. Set MISTRAL_API_KEY or OPENAI_API_KEY in the app environment."
                return render_template("assistant.html", answer=answer, question=question, error=error)
            payload = json.dumps({
                "model": os.getenv("AI_MODEL", default_model),
                "messages": [
                    {"role": "system", "content": "You are CampusHub's helpful assistant. Assist with general academic, school administration, teaching, and parent-support questions. Do not claim to access private CampusHub records or reveal personal data. Be clear when users should contact school staff."},
                    {"role": "user", "content": question},
                ],
                "temperature": 0.4,
            }).encode("utf-8")
            endpoint = os.getenv("AI_API_URL", default_endpoint)
            req = Request(endpoint, data=payload, headers={
                "Authorization": "Bearer " + api_key,
                "Content-Type": "application/json",
            }, method="POST")
            try:
                with urlopen(req, timeout=30) as response:
                    result = json.loads(response.read().decode("utf-8"))
                answer = result["choices"][0]["message"]["content"].strip()
            except (HTTPError, URLError, TimeoutError, KeyError, IndexError, ValueError) as exc:
                app.logger.warning("CampusHub assistant request failed: %s", exc)
                error = "The assistant could not respond right now. Please try again later."
    return render_template("assistant.html", answer=answer, question=question, error=error)


@app.route("/parent/teacher-requests")
@required("parent")
def parent_teacher_requests():
    child_id = session.get("child_student_id")
    if not one("SELECT id FROM users WHERE id=%s AND role='student'", (child_id,)):
        abort(404)
    teachers = rows("SELECT id,full_name FROM users WHERE role='teacher' ORDER BY full_name")
    requests_ = rows("""SELECT r.*,t.full_name teacher_name,
        (r.status='approved' AND r.expires_at > NOW()) session_active
        FROM parent_teacher_requests r JOIN users t ON r.teacher_id=t.id
        WHERE r.parent_id=%s AND r.student_id=%s ORDER BY r.created_at DESC""",
        (session["user_id"], child_id))
    return render_template("parent/teacher_requests.html", teachers=teachers, requests=requests_)


@app.post("/parent/teacher-requests/send")
@required("parent")
def send_parent_teacher_request():
    child_id = session.get("child_student_id")
    teacher_id = request.form.get("teacher_id", type=int)
    if not one("SELECT id FROM users WHERE id=%s AND role='student'", (child_id,)):
        abort(404)
    if not teacher_id or not one("SELECT id FROM users WHERE id=%s AND role='teacher'", (teacher_id,)):
        flash("Select a valid teacher.")
        return redirect(url_for("parent_teacher_requests"))
    existing = one("""SELECT id FROM parent_teacher_requests
        WHERE parent_id=%s AND student_id=%s AND teacher_id=%s
        AND (status='pending' OR (status='approved' AND expires_at > NOW())) LIMIT 1""",
        (session["user_id"], child_id, teacher_id))
    if existing:
        flash("You already have a pending request or an active session with this teacher.")
        return redirect(url_for("parent_teacher_requests"))
    execute("INSERT INTO parent_teacher_requests(parent_id,student_id,teacher_id,status) VALUES(%s,%s,%s,'pending')",
            (session["user_id"], child_id, teacher_id))
    flash("Request sent. An administrator must approve it before chat is available.")
    return redirect(url_for("parent_teacher_requests"))


@app.route("/parent/teacher-chat/<int:request_id>", methods=["GET", "POST"])
@required("parent")
def parent_teacher_chat(request_id):
    chat = one("""SELECT r.id,r.expires_at,t.id teacher_id,t.full_name teacher_name
        FROM parent_teacher_requests r JOIN users t ON r.teacher_id=t.id
        WHERE r.id=%s AND r.parent_id=%s AND r.student_id=%s
        AND r.status='approved' AND r.expires_at > NOW()""",
        (request_id, session["user_id"], session.get("child_student_id")))
    if not chat:
        flash("This chat request is not approved or its 3-hour session has ended. Send a new request to chat again.")
        return redirect(url_for("parent_teacher_requests"))
    if request.method == "POST":
        msg = request.form.get("message", "").strip()
        if msg:
            execute("INSERT INTO parent_teacher_messages(request_id,sender_id,receiver_id,message) VALUES(%s,%s,%s,%s)",
                    (request_id, session["user_id"], chat["teacher_id"], msg))
        return redirect(url_for("parent_teacher_chat", request_id=request_id))
    messages = rows("""SELECT m.*,u.full_name sender_name,u.role sender_role
        FROM parent_teacher_messages m JOIN users u ON m.sender_id=u.id
        WHERE m.request_id=%s ORDER BY m.created_at ASC""", (request_id,))
    return render_template("parent/teacher_chat.html", chat=chat, messages=messages)


@app.route("/student/fees", methods=["GET", "POST"])
@required("student_or_parent")
def fee_payment():
    student_id = session["user_id"] if session["role"] == "student" else session.get("child_student_id")
    student = one("SELECT id,full_name,matricule FROM users WHERE id=%s AND role='student'", (student_id,))
    if not student:
        abort(404)
    schedules = rows("SELECT payment_period,total_amount FROM fee_schedules ORDER BY payment_period DESC")
    balances = rows("""SELECT fs.payment_period,fs.total_amount,
        COALESCE(SUM(CASE WHEN fp.status='confirmed' THEN fp.amount ELSE 0 END),0) paid,
        COALESCE(SUM(CASE WHEN fp.status='pending' THEN fp.amount ELSE 0 END),0) pending
        FROM fee_schedules fs LEFT JOIN fee_payments fp ON fp.payment_period=fs.payment_period AND fp.student_id=%s
        GROUP BY fs.payment_period,fs.total_amount ORDER BY fs.payment_period DESC""", (student_id,))
    if request.method == "POST":
        amount_text = request.form.get("amount", "").strip()
        payment_period = request.form.get("payment_period", "").strip()
        bank_reference = request.form.get("bank_reference", "").strip()
        try:
            amount = Decimal(amount_text).quantize(Decimal("0.01"))
            if not amount.is_finite() or amount <= 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            flash("Enter a valid payment amount greater than zero.")
            return redirect(url_for("fee_payment"))
        schedule = one("SELECT total_amount FROM fee_schedules WHERE payment_period=%s", (payment_period,))
        if not payment_period or len(payment_period) > 100 or not bank_reference or len(bank_reference) > 100:
            flash("Enter the academic period and bank transfer reference.")
            return redirect(url_for("fee_payment"))
        if not schedule:
            flash("The school has not set fees for that academic period yet.")
            return redirect(url_for("fee_payment"))
        reserved = one("SELECT COALESCE(SUM(amount),0) total FROM fee_payments WHERE student_id=%s AND payment_period=%s AND status IN ('pending','confirmed')",
                       (student_id, payment_period))["total"]
        available = Decimal(str(schedule["total_amount"])) - Decimal(str(reserved or 0))
        if amount > available:
            flash("The submitted amount is greater than the remaining amount available for this fee period.")
            return redirect(url_for("fee_payment"))

        receipt = request.files.get("receipt")
        if receipt and receipt.filename and ext(receipt.filename) not in {"pdf", "jpg", "jpeg", "png"}:
            flash("Receipt must be a PDF, JPG or PNG file.")
            return redirect(url_for("fee_payment"))
        if one("SELECT id FROM fee_payments WHERE bank_reference=%s", (bank_reference,)):
            flash("That bank transfer reference has already been submitted.")
            return redirect(url_for("fee_payment"))

        receipt_filename = save_file(receipt, "fee_receipts", {"pdf", "jpg", "jpeg", "png"})
        execute("INSERT INTO fee_payments(student_id,amount,payment_period,bank_reference,receipt_filename) VALUES(%s,%s,%s,%s,%s)",
            (student_id, amount, payment_period, bank_reference, receipt_filename))
        flash("Transfer details submitted. Your fee payment is pending finance-office verification.")
        return redirect(url_for("fee_payment"))

    payments = rows("SELECT * FROM fee_payments WHERE student_id=%s ORDER BY created_at DESC", (student_id,))
    saved_bank = one("SELECT bank_name,account_name,account_number,branch,currency FROM fee_payment_settings WHERE id=1")
    bank = {
        "name": (saved_bank["bank_name"] if saved_bank else os.getenv("FEE_BANK_NAME", "")).strip(),
        "account_name": (saved_bank["account_name"] if saved_bank else os.getenv("FEE_ACCOUNT_NAME", "")).strip(),
        "account_number": (saved_bank["account_number"] if saved_bank else os.getenv("FEE_ACCOUNT_NUMBER", "")).strip(),
        "branch": (saved_bank["branch"] if saved_bank else os.getenv("FEE_BANK_BRANCH", "")).strip(),
        "currency": (saved_bank["currency"] if saved_bank else os.getenv("FEE_CURRENCY", "")).strip(),
    }
    bank_configured = all(bank[key] for key in ("name", "account_name", "account_number"))
    return render_template("student/fees.html", payments=payments, schedules=schedules, balances=balances,
                           bank=bank, bank_configured=bank_configured, fee_student=student,
                           is_parent=session["role"] == "parent")


@app.route("/student/fees/receipt/<int:payment_id>")
def fee_receipt(payment_id):
    if not session.get("user_id"):
        return redirect(url_for("login"))
    if session.get("role") == "student":
        allowed_student_id = session["user_id"]
    elif session.get("role") == "parent":
        allowed_student_id = session.get("child_student_id")
    elif session.get("role") == "admin":
        allowed_student_id = None
    else:
        abort(403)
    payment = one("SELECT receipt_filename FROM fee_payments WHERE id=%s" +
                  ("" if allowed_student_id is None else " AND student_id=%s"),
                  (payment_id,) if allowed_student_id is None else (payment_id, allowed_student_id))
    if not payment or not payment.get("receipt_filename"):
        flash("Receipt not found.")
        return redirect(url_for("fee_payment"))
    return send_from_directory(os.path.join(UPLOAD, "fee_receipts"), payment["receipt_filename"], as_attachment=True)


@app.route("/community")
@required()
def community():
    student_id = effective_student_id() or session["user_id"]
    students = rows("SELECT u.id,u.full_name,u.avatar,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.role='student' AND u.id<>%s ORDER BY u.full_name", (student_id,))
    posts = rows("""SELECT p.*,u.full_name author_name,u.avatar author_avatar,s.name specialty,y.name year
        FROM community_posts p JOIN users u ON p.user_id=u.id
        LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id
        ORDER BY p.created_at DESC""")
    comments = rows("""SELECT c.*,u.full_name author_name,u.avatar author_avatar FROM community_comments c JOIN users u ON c.user_id=u.id ORDER BY c.created_at ASC""")
    inbox = rows("SELECT d.*,u.full_name sender_name FROM student_messages d JOIN users u ON d.sender_id=u.id WHERE d.receiver_id=%s ORDER BY d.created_at DESC", (student_id,))
    sent = rows("SELECT d.*,u.full_name receiver_name FROM student_messages d JOIN users u ON d.receiver_id=u.id WHERE d.sender_id=%s ORDER BY d.created_at DESC", (student_id,))
    return render_template("student/community.html", students=students, posts=posts, comments=comments, inbox=inbox, sent=sent)


@app.post("/community/post")
@required()
def community_post():
    text = request.form.get("content", "").strip()
    if text:
        execute("INSERT INTO community_posts(user_id,content) VALUES(%s,%s)", (session["user_id"], text))
    return redirect(url_for("community"))


@app.post("/community/comment/<int:post_id>")
@required()
def community_comment(post_id):
    text = request.form.get("content", "").strip()
    if text and one("SELECT id FROM community_posts WHERE id=%s", (post_id,)):
        execute("INSERT INTO community_comments(post_id,user_id,content) VALUES(%s,%s,%s)", (post_id, session["user_id"], text))
    return redirect(url_for("community"))


@app.route("/student-chat/<int:student_id>", methods=["GET", "POST"])
@required("student_or_parent")
def student_private_chat(student_id):
    own_student_id = effective_student_id()
    if student_id == own_student_id or not one("SELECT id FROM users WHERE id=%s AND role='student'", (student_id,)):
        flash("Student not found."); return redirect(url_for("community"))
    other = one("SELECT id,full_name FROM users WHERE id=%s AND role='student'", (student_id,))
    if request.method == "POST":
        text = request.form.get("message", "").strip()
        if text:
            execute("INSERT INTO student_messages(sender_id,receiver_id,message) VALUES(%s,%s,%s)", (own_student_id, student_id, text))
        return redirect(url_for("student_private_chat", student_id=student_id))
    messages = rows("""SELECT m.*,u.full_name sender_name FROM student_messages m JOIN users u ON m.sender_id=u.id
        WHERE (m.sender_id=%s AND m.receiver_id=%s) OR (m.sender_id=%s AND m.receiver_id=%s) ORDER BY m.created_at ASC""",
        (own_student_id, student_id, student_id, own_student_id))
    return render_template("student/private_chat.html", other=other, messages=messages,
                           chat_user_id=own_student_id, parent_proxy=session.get("role") == "parent")


@app.post("/community/send")
@required("student_or_parent")
def community_send():
    receiver = int(request.form["receiver_id"])
    own_student_id = effective_student_id()
    if receiver == own_student_id or not one("SELECT id FROM users WHERE id=%s AND role='student'", (receiver,)):
        flash("Student not found."); return redirect(url_for("community"))
    execute("INSERT INTO student_messages(sender_id,receiver_id,message) VALUES(%s,%s,%s)",
            (own_student_id, receiver, request.form["message"]))
    return redirect(url_for("student_private_chat", student_id=receiver))


@app.route("/teacher-requests")
@required("student_or_parent")
def teacher_requests():
    student_id = effective_student_id()
    teachers = rows("SELECT id,full_name FROM users WHERE role='teacher' ORDER BY full_name")
    requests_ = rows("""SELECT r.*,t.full_name teacher_name,a.full_name approved_by_name
        FROM teacher_requests r JOIN users t ON r.teacher_id=t.id
        LEFT JOIN users a ON r.approved_by=a.id
        WHERE r.student_id=%s ORDER BY r.created_at DESC""", (student_id,))
    approved = rows("""SELECT r.id,r.teacher_id,t.full_name teacher_name
        FROM teacher_requests r JOIN users t ON r.teacher_id=t.id
        WHERE r.student_id=%s AND r.status='approved' ORDER BY t.full_name""", (student_id,))
    return render_template("student/teacher_requests.html", teachers=teachers, requests=requests_, approved=approved,
                           parent_proxy=session.get("role") == "parent")


@app.post("/teacher-requests/send")
@required("student_or_parent")
def send_teacher_request():
    student_id = effective_student_id()
    teacher_id = int(request.form["teacher_id"])
    teacher = one("SELECT id FROM users WHERE id=%s AND role='teacher'", (teacher_id,))
    if not teacher:
        flash("Teacher not found.")
        return redirect(url_for("teacher_requests"))
    existing = one("SELECT id,status FROM teacher_requests WHERE student_id=%s AND teacher_id=%s AND status IN ('pending','approved')", (student_id, teacher_id))
    if existing:
        flash("You already have a pending or approved request for this teacher.")
        return redirect(url_for("teacher_requests"))
    execute("INSERT INTO teacher_requests(student_id,teacher_id,status) VALUES(%s,%s,'pending')", (student_id, teacher_id))
    flash("Request sent. An administrator must approve it before you can chat with the teacher.")
    return redirect(url_for("teacher_requests"))


@app.route("/teacher-chat/<int:teacher_id>", methods=["GET", "POST"])
@required("student_or_parent")
def student_teacher_chat(teacher_id):
    student_id = effective_student_id()
    teacher = one("SELECT id,full_name,email FROM users WHERE id=%s AND role='teacher'", (teacher_id,))
    approved = one("SELECT id FROM teacher_requests WHERE student_id=%s AND teacher_id=%s AND status='approved'", (student_id, teacher_id))
    if not teacher or not approved:
        flash("Teacher chat is available only after an administrator approves your request.")
        return redirect(url_for("teacher_requests"))
    if request.method == "POST":
        msg = request.form.get("message", "").strip()
        if msg:
            execute("INSERT INTO teacher_student_messages(request_id,sender_id,receiver_id,message) VALUES(%s,%s,%s,%s)",
                    (approved["id"], session["user_id"], teacher_id, msg))
        return redirect(url_for("student_teacher_chat", teacher_id=teacher_id))
    messages = rows("""SELECT m.*,u.full_name sender_name,u.role sender_role
        FROM teacher_student_messages m JOIN users u ON m.sender_id=u.id
        WHERE m.request_id=%s ORDER BY m.created_at ASC""", (approved["id"],))
    return render_template("student/teacher_chat.html", teacher=teacher, messages=messages,
                           parent_proxy=session.get("role") == "parent")


@app.route("/teacher/requests")
@required("teacher")
def teacher_requests_view():
    requests_ = rows("""SELECT r.*,s.full_name student_name,sp.name specialty,y.name year
        FROM teacher_requests r JOIN users s ON r.student_id=s.id
        LEFT JOIN specialties sp ON s.specialty_id=sp.id LEFT JOIN years y ON s.year_id=y.id
        WHERE r.teacher_id=%s ORDER BY r.created_at DESC""", (session["user_id"],))
    parent_requests = rows("""SELECT r.*,p.full_name parent_name,s.full_name student_name,
        (r.status='approved' AND r.expires_at > NOW()) session_active
        FROM parent_teacher_requests r JOIN users p ON r.parent_id=p.id
        JOIN users s ON r.student_id=s.id
        WHERE r.teacher_id=%s ORDER BY r.created_at DESC""", (session["user_id"],))
    return render_template("teacher/requests.html", requests=requests_, parent_requests=parent_requests)

@app.post("/teacher/request/<int:id>/respond")
@required("teacher")
def teacher_request_response(id):
    response = request.form.get("teacher_response", "").strip()
    if not response:
        flash("Write a response before sending it.")
    else:
        updated = execute("UPDATE teacher_requests SET teacher_response=%s WHERE id=%s AND teacher_id=%s",
                          (response, id, session["user_id"]))
        if updated is not None:
            flash("Response sent to the student and administrator.")
    return redirect(url_for("teacher_requests_view"))


@app.route("/teacher/chat/<int:student_id>", methods=["GET", "POST"])
@required("teacher")
def teacher_student_chat(student_id):
    approved = one("""SELECT r.id,s.full_name student_name FROM teacher_requests r JOIN users s ON r.student_id=s.id
        WHERE r.student_id=%s AND r.teacher_id=%s AND r.status='approved'""", (student_id, session["user_id"]))
    if not approved:
        flash("This student has not been approved for teacher chat.")
        return redirect(url_for("teacher_requests_view"))
    if request.method == "POST":
        msg = request.form.get("message", "").strip()
        if msg:
            execute("INSERT INTO teacher_student_messages(request_id,sender_id,receiver_id,message) VALUES(%s,%s,%s,%s)",
                    (approved["id"], session["user_id"], student_id, msg))
        return redirect(url_for("teacher_student_chat", student_id=student_id))
    messages = rows("""SELECT m.*,u.full_name sender_name,u.role sender_role
        FROM teacher_student_messages m JOIN users u ON m.sender_id=u.id
        WHERE m.request_id=%s ORDER BY m.created_at ASC""", (approved["id"],))
    return render_template("teacher/chat.html", student=approved, messages=messages)


@app.route("/teacher/parent-chat/<int:request_id>", methods=["GET", "POST"])
@required("teacher")
def teacher_parent_chat(request_id):
    chat = one("""SELECT r.id,r.parent_id,r.expires_at,p.full_name parent_name,s.full_name student_name
        FROM parent_teacher_requests r JOIN users p ON r.parent_id=p.id
        JOIN users s ON r.student_id=s.id
        WHERE r.id=%s AND r.teacher_id=%s AND r.status='approved' AND r.expires_at > NOW()""",
        (request_id, session["user_id"]))
    if not chat:
        flash("This parent chat is not approved or its 3-hour session has ended.")
        return redirect(url_for("teacher_requests_view"))
    if request.method == "POST":
        msg = request.form.get("message", "").strip()
        if msg:
            execute("INSERT INTO parent_teacher_messages(request_id,sender_id,receiver_id,message) VALUES(%s,%s,%s,%s)",
                    (request_id, session["user_id"], chat["parent_id"], msg))
        return redirect(url_for("teacher_parent_chat", request_id=request_id))
    messages = rows("""SELECT m.*,u.full_name sender_name,u.role sender_role
        FROM parent_teacher_messages m JOIN users u ON m.sender_id=u.id
        WHERE m.request_id=%s ORDER BY m.created_at ASC""", (request_id,))
    return render_template("teacher/parent_chat.html", chat=chat, messages=messages)


@app.route("/admin/teacher-requests")
@required("admin")
def admin_teacher_requests():
    requests_ = rows("""SELECT r.*,s.full_name student_name,t.full_name teacher_name,sp.name specialty,y.name year
        FROM teacher_requests r JOIN users s ON r.student_id=s.id JOIN users t ON r.teacher_id=t.id
        LEFT JOIN specialties sp ON s.specialty_id=sp.id LEFT JOIN years y ON s.year_id=y.id
        ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,r.created_at DESC""")
    parent_requests = rows("""SELECT r.*,p.full_name parent_name,s.full_name student_name,
        t.full_name teacher_name,(r.status='approved' AND r.expires_at > NOW()) session_active
        FROM parent_teacher_requests r JOIN users p ON r.parent_id=p.id
        JOIN users s ON r.student_id=s.id JOIN users t ON r.teacher_id=t.id
        ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,r.created_at DESC""")
    return render_template("admin/teacher_requests.html", requests=requests_, parent_requests=parent_requests)


@app.post("/admin/teacher-request/<int:id>/<action>")
@required("admin")
def admin_teacher_request_action(id, action):
    if action not in ("approve", "reject"):
        flash("Invalid request action.")
        return redirect(url_for("admin_teacher_requests"))
    status = "approved" if action == "approve" else "rejected"
    execute("UPDATE teacher_requests SET status=%s,approved_by=%s,decided_at=NOW() WHERE id=%s AND status='pending'",
            (status, session["user_id"], id))
    flash("Teacher chat request " + status + ".")
    return redirect(url_for("admin_teacher_requests"))


@app.post("/admin/parent-teacher-request/<int:id>/<action>")
@required("admin")
def admin_parent_teacher_request_action(id, action):
    if action not in ("approve", "reject"):
        flash("Invalid request action.")
        return redirect(url_for("admin_teacher_requests"))
    if action == "approve":
        execute("""UPDATE parent_teacher_requests SET status='approved',approved_by=%s,
            decided_at=NOW(),started_at=NOW(),expires_at=DATE_ADD(NOW(), INTERVAL 3 HOUR)
            WHERE id=%s AND status='pending'""", (session["user_id"], id))
        flash("Parent chat request approved. The three-hour session has started.")
    else:
        execute("UPDATE parent_teacher_requests SET status='rejected',approved_by=%s,decided_at=NOW() WHERE id=%s AND status='pending'",
                (session["user_id"], id))
        flash("Parent chat request rejected.")
    return redirect(url_for("admin_teacher_requests"))


def admin_data():
    return dict(
        students=rows("SELECT u.id,u.full_name,u.email,u.matricule,u.avatar,u.is_banned,u.is_suspended,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.role='student' ORDER BY s.name,y.id,u.full_name"),
        teachers=rows("SELECT id,full_name,email,avatar,is_suspended FROM users WHERE role='teacher' ORDER BY full_name"),
        admins=rows("SELECT id,full_name,email FROM users WHERE role='admin' ORDER BY full_name"),
        specialties=rows("SELECT * FROM specialties ORDER BY name"),
        years=rows("SELECT * FROM years ORDER BY id"),
        courses=rows("SELECT * FROM courses ORDER BY name"),
        announcements=rows("SELECT a.*,u.full_name creator FROM announcements a LEFT JOIN users u ON a.created_by=u.id ORDER BY a.created_at DESC"),
        timetables=rows("SELECT t.*,s.name specialty,y.name year FROM timetables t JOIN specialties s ON t.specialty_id=s.id JOIN years y ON t.year_id=y.id ORDER BY t.created_at DESC"),
        papers=rows("SELECT p.*,c.name course,s.name specialty,y.name year FROM past_papers p LEFT JOIN courses c ON p.course_id=c.id LEFT JOIN specialties s ON p.specialty_id=s.id LEFT JOIN years y ON p.year_id=y.id ORDER BY p.created_at DESC"),
        halls=rows("SELECT h.*,c.name course FROM hall_distribution h LEFT JOIN courses c ON h.course_id=c.id ORDER BY h.id DESC"))

@app.route("/admin")
@required("admin")
def admin_dashboard():
    return redirect(url_for("admin_overview"))

@app.route("/admin/overview")
@required("admin")
def admin_overview():
    return render_template("admin/overview.html", **admin_data())

@app.route("/admin/students")
@required("admin")
def admin_students():
    return render_template("admin/students.html", **admin_data())


@app.route("/admin/fees", methods=["GET", "POST"])
@required("admin")
def admin_fees():
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "save_bank_details":
            bank_name = request.form.get("bank_name", "").strip()
            account_name = request.form.get("account_name", "").strip()
            account_number = request.form.get("account_number", "").strip()
            branch = request.form.get("branch", "").strip()
            currency = request.form.get("currency", "").strip()
            if not all((bank_name, account_name, account_number)):
                flash("Bank, account name, and account number are required before parents can submit transfers.")
                return redirect(url_for("admin_fees"))
            if any(len(value) > limit for value, limit in ((bank_name, 150), (account_name, 150), (account_number, 80), (branch, 150), (currency, 12))):
                flash("One or more bank details exceed the allowed length.")
                return redirect(url_for("admin_fees"))
            execute("""INSERT INTO fee_payment_settings(id,bank_name,account_name,account_number,branch,currency)
                VALUES(1,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE bank_name=VALUES(bank_name),
                account_name=VALUES(account_name),account_number=VALUES(account_number),
                branch=VALUES(branch),currency=VALUES(currency)""",
                (bank_name, account_name, account_number, branch, currency))
            flash("Official fee payment bank details saved.")
        elif action == "set_schedule":
            period = request.form.get("payment_period", "").strip()
            try:
                amount = Decimal(request.form.get("total_amount", "").strip()).quantize(Decimal("0.01"))
                if not amount.is_finite() or amount <= 0:
                    raise InvalidOperation
            except (InvalidOperation, ValueError):
                flash("Enter a valid school-fee amount greater than zero.")
                return redirect(url_for("admin_fees"))
            if not period or len(period) > 100:
                flash("Enter a valid academic period (up to 100 characters).")
                return redirect(url_for("admin_fees"))
            execute("INSERT INTO fee_schedules(payment_period,total_amount) VALUES(%s,%s) ON DUPLICATE KEY UPDATE total_amount=VALUES(total_amount)",
                    (period, amount))
            flash("School fee amount saved for " + period + ".")
        elif action in ("confirm", "reject"):
            payment_id = request.form.get("payment_id", type=int)
            new_status = "confirmed" if action == "confirm" else "rejected"
            changed = execute("UPDATE fee_payments SET status=%s WHERE id=%s AND status='pending'",
                              (new_status, payment_id))
            flash("Transfer " + new_status + "." if changed is not None else "Transfer was already reviewed.")
        else:
            flash("Invalid fee action.")
        return redirect(url_for("admin_fees"))

    schedules = rows("SELECT payment_period,total_amount FROM fee_schedules ORDER BY payment_period DESC")
    balances = rows("""SELECT u.id student_id,u.full_name,u.matricule,fs.payment_period,fs.total_amount,
        COALESCE(p.paid,0) paid,COALESCE(p.pending,0) pending,
        GREATEST(fs.total_amount-COALESCE(p.paid,0),0) remaining
        FROM users u CROSS JOIN fee_schedules fs
        LEFT JOIN (SELECT student_id,payment_period,
          SUM(CASE WHEN status='confirmed' THEN amount ELSE 0 END) paid,
          SUM(CASE WHEN status='pending' THEN amount ELSE 0 END) pending
          FROM fee_payments GROUP BY student_id,payment_period) p
          ON p.student_id=u.id AND p.payment_period=fs.payment_period
        WHERE u.role='student' ORDER BY u.full_name,fs.payment_period DESC""")
    submissions = rows("""SELECT fp.*,u.full_name student_name,u.matricule
        FROM fee_payments fp JOIN users u ON u.id=fp.student_id
        ORDER BY CASE fp.status WHEN 'pending' THEN 0 ELSE 1 END,fp.created_at DESC""")
    saved_bank = one("SELECT bank_name,account_name,account_number,branch,currency FROM fee_payment_settings WHERE id=1")
    currency = (saved_bank["currency"] if saved_bank else os.getenv("FEE_CURRENCY", "")).strip()
    bank_settings = saved_bank or {
        "bank_name": os.getenv("FEE_BANK_NAME", "").strip(),
        "account_name": os.getenv("FEE_ACCOUNT_NAME", "").strip(),
        "account_number": os.getenv("FEE_ACCOUNT_NUMBER", "").strip(),
        "branch": os.getenv("FEE_BANK_BRANCH", "").strip(),
        "currency": currency,
    }
    return render_template("admin/fees.html", schedules=schedules, balances=balances,
                           submissions=submissions, currency=currency, bank_settings=bank_settings)

@app.route("/admin/teachers")
@required("admin")
def admin_teachers():
    return render_template("admin/teachers.html", **admin_data())

@app.route("/admin/content")
@required("admin")
def admin_content():
    return render_template("admin/content.html", **admin_data())


@app.route("/admin/timetables")
@required("admin")
def admin_timetables():
    return render_template("admin/timetables.html",
        timetables=rows("SELECT t.*,s.name specialty,y.name year FROM timetables t JOIN specialties s ON s.id=t.specialty_id JOIN years y ON y.id=t.year_id ORDER BY y.id,s.name,t.title"),
        specialties=rows("SELECT id,name FROM specialties ORDER BY name"),
        years=rows("SELECT id,name FROM years ORDER BY id"))


@app.route("/admin/halls")
@required("admin")
def admin_halls():
    return render_template("admin/halls.html",
        halls=rows("SELECT h.*,c.name course,s.name specialty,y.name year FROM hall_distribution h LEFT JOIN courses c ON c.id=h.course_id LEFT JOIN specialties s ON s.id=h.specialty_id LEFT JOIN years y ON y.id=h.year_id ORDER BY h.distribution_date DESC,h.start_time"),
        specialties=rows("SELECT id,name FROM specialties ORDER BY name"),
        years=rows("SELECT id,name FROM years ORDER BY id"),
        courses=rows("SELECT id,name FROM courses ORDER BY name"))

@app.route("/admin/communication")
@required("admin")
def admin_communication():
    return render_template("admin/communication.html", **admin_data())

@app.route("/admin/academic")
@required("admin")
def admin_academic():
    return render_template("admin/academic.html", **admin_data())

@app.route("/admin/settings-page")
@required("admin")
def admin_settings_page():
    return render_template("admin/settings.html",
        site=one("SELECT * FROM site_settings WHERE id=1"),
        about=one("SELECT * FROM about_us WHERE id=1"),
        contact=one("SELECT * FROM contact_us WHERE id=1"))


@app.post("/admin/teacher")
@required("admin")
def add_teacher():
    try:
        execute("INSERT INTO users(full_name,email,password,role) VALUES(%s,%s,%s,'teacher')",
                (request.form["full_name"], request.form["email"], generate_password_hash(request.form["password"])))
        flash("Teacher account created.")
    except Exception:
        flash("Could not create teacher account. The email may already exist.")
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/teacher/<int:id>/edit")
@required("admin")
def edit_teacher(id):
    teacher = one("SELECT id FROM users WHERE id=%s AND role='teacher'", (id,))
    if not teacher:
        flash("Teacher not found.")
        return redirect(url_for("admin_teachers"))
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not full_name or not email:
        flash("Teacher name and email are required.")
        return redirect(url_for("admin_teachers"))
    try:
        if password:
            execute("UPDATE users SET full_name=%s,email=%s,password=%s WHERE id=%s AND role='teacher'",
                    (full_name, email, generate_password_hash(password), id))
        else:
            execute("UPDATE users SET full_name=%s,email=%s WHERE id=%s AND role='teacher'",
                    (full_name, email, id))
        flash("Teacher account updated.")
    except Exception:
        flash("Could not update teacher account. The email may already exist.")
    return redirect(url_for("admin_teachers"))


@app.post("/admin/teacher/<int:id>/delete")
@required("admin")
def delete_teacher(id):
    deleted = execute("DELETE FROM users WHERE id=%s AND role='teacher'", (id,))
    flash("Teacher account deleted." if deleted is not None else "Teacher not found.")
    return redirect(url_for("admin_teachers"))


@app.post("/admin/student/<int:id>/ban")
@required("admin")
def toggle_student_ban(id):
    student = one("SELECT id,is_banned FROM users WHERE id=%s AND role='student'", (id,))
    if not student:
        flash("Student not found.")
    else:
        execute("UPDATE users SET is_banned=NOT is_banned WHERE id=%s AND role='student'", (id,))
        flash("Student account unbanned." if student["is_banned"] else "Student account banned.")
    return redirect(url_for("admin_students"))


@app.post("/admin/user/<int:id>/suspend")
@required("admin")
def toggle_user_suspension(id):
    user = one("SELECT id,role,is_suspended FROM users WHERE id=%s AND role IN ('student','teacher')", (id,))
    if not user:
        flash("User not found.")
    else:
        execute("UPDATE users SET is_suspended=NOT is_suspended WHERE id=%s AND role IN ('student','teacher')", (id,))
        flash(("Teacher" if user["role"] == "teacher" else "Student") +
              (" suspension lifted." if user["is_suspended"] else " account suspended."))
    return redirect(url_for("admin_teachers" if user and user["role"] == "teacher" else "admin_students"))


@app.post("/admin/announcement")
@required("admin")
def add_announcement():
    img = save_file(request.files.get("image"), "announcements", IMAGE)
    execute("INSERT INTO announcements(title,content,specialty_id,year_id,image_filename,created_by) VALUES(%s,%s,%s,%s,%s,%s)",
            (request.form["title"], request.form["content"], request.form.get("specialty_id") or None,
             request.form.get("year_id") or None, img, session["user_id"]))
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/announcement/delete/<int:id>")
@required("admin")
def delete_announcement(id):
    execute("DELETE FROM announcements WHERE id=%s", (id,)); return redirect(url_for("admin_dashboard"))


@app.post("/admin/timetable")
@required("admin")
def add_timetable():
    f = request.files.get("pdf")
    if not f or not f.filename or ext(f.filename) != "pdf":
        flash("Timetable must be PDF."); return redirect(url_for("admin_timetables"))
    n = save_file(f, "timetables", {"pdf"})
    execute("INSERT INTO timetables(title,specialty_id,year_id,pdf_filename) VALUES(%s,%s,%s,%s)",
            (request.form["title"], request.form["specialty_id"], request.form["year_id"], n))
    flash("Timetable uploaded.")
    return redirect(url_for("admin_timetables"))


@app.route("/admin/timetable/<int:id>/edit", methods=["POST"])
@required("admin")
def edit_timetable(id):
    current = one("SELECT id,pdf_filename FROM timetables WHERE id=%s", (id,))
    if not current:
        flash("Timetable not found.")
        return redirect(url_for("admin_timetables"))
    title = request.form.get("title", "").strip()
    specialty_id = request.form.get("specialty_id", type=int)
    year_id = request.form.get("year_id", type=int)
    if not title or not specialty_id or not year_id:
        flash("Title, specialty, and year are required.")
        return redirect(url_for("admin_timetables"))
    if not one("SELECT id FROM specialties WHERE id=%s", (specialty_id,)) or not one("SELECT id FROM years WHERE id=%s", (year_id,)):
        flash("Select a valid specialty and year.")
        return redirect(url_for("admin_timetables"))
    uploaded = request.files.get("pdf")
    filename = current["pdf_filename"]
    if uploaded and uploaded.filename:
        if ext(uploaded.filename) != "pdf":
            flash("Timetable must be PDF.")
            return redirect(url_for("admin_timetables"))
        filename = save_file(uploaded, "timetables", {"pdf"})
    execute("UPDATE timetables SET title=%s,specialty_id=%s,year_id=%s,pdf_filename=%s WHERE id=%s",
            (title, specialty_id, year_id, filename, id))
    flash("Timetable updated.")
    return redirect(url_for("admin_timetables"))


@app.post("/admin/timetable/delete/<int:id>")
@required("admin")
def delete_timetable(id):
    execute("DELETE FROM timetables WHERE id=%s", (id,)); return redirect(url_for("admin_timetables"))


@app.post("/admin/past-paper")
@required("admin")
def add_past_paper():
    f = request.files.get("file")
    if ext(f.filename) not in PAST: flash("Past papers: PDF, DOCX, JPG, JPEG or PNG only."); return redirect(url_for("admin_dashboard"))
    n = save_file(f, "past_papers", PAST)
    execute("INSERT INTO past_papers(title,course_id,specialty_id,year_id,academic_year,filename,file_type) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (request.form["title"], request.form.get("course_id") or None, request.form.get("specialty_id") or None,
             request.form.get("year_id") or None, request.form["academic_year"], n, ext(f.filename)))
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/past-paper/delete/<int:id>")
@required("admin")
def delete_past_paper(id):
    execute("DELETE FROM past_papers WHERE id=%s", (id,)); return redirect(url_for("admin_dashboard"))


@app.post("/admin/specialty")
@required("admin")
def add_specialty():
    execute("INSERT IGNORE INTO specialties(name) VALUES(%s)", (request.form["name"],)); return redirect(url_for("admin_dashboard"))


@app.post("/admin/year")
@required("admin")
def add_year():
    execute("INSERT IGNORE INTO years(name) VALUES(%s)", (request.form["name"],)); return redirect(url_for("admin_dashboard"))


@app.post("/admin/course")
@required("admin")
def add_course():
    execute("INSERT INTO courses(code,name) VALUES(%s,%s)", (request.form["code"], request.form["name"])); return redirect(url_for("admin_dashboard"))


@app.post("/admin/hall")
@required("admin")
def add_hall():
    values = hall_form_values()
    if values is None:
        return redirect(url_for("admin_halls"))
    execute("""INSERT INTO hall_distribution(title,specialty_id,year_id,course_id,hall,
        distribution_date,session,start_time,end_time) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""", values)
    flash("Hall distribution schedule added.")
    return redirect(url_for("admin_halls"))


def hall_form_values():
    title = request.form.get("title", "").strip()
    specialty_id = request.form.get("specialty_id", type=int)
    year_id = request.form.get("year_id", type=int)
    course_id = request.form.get("course_id", type=int)
    hall = request.form.get("hall", "").strip()
    distribution_date = request.form.get("distribution_date") or None
    session_name = request.form.get("session", "morning").strip().lower()
    start_time = request.form.get("start_time", "08:00").strip()
    end_time = request.form.get("end_time", "12:00").strip()
    try:
        start_value = datetime.strptime(start_time, "%H:%M")
        end_value = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        flash("Enter valid start and end times.")
        return None
    if (not title or len(title) > 200 or not hall or len(hall) > 100 or
            session_name not in ("morning", "evening") or start_value >= end_value):
        flash("Enter a title, hall, morning/evening session, and a valid start/end time.")
        return None
    if specialty_id and not one("SELECT id FROM specialties WHERE id=%s", (specialty_id,)):
        flash("Select a valid specialty.")
        return None
    if year_id and not one("SELECT id FROM years WHERE id=%s", (year_id,)):
        flash("Select a valid year.")
        return None
    if course_id and not one("SELECT id FROM courses WHERE id=%s", (course_id,)):
        flash("Select a valid course.")
        return None
    return (title, specialty_id, year_id, course_id, hall, distribution_date, session_name, start_time, end_time)


@app.post("/admin/hall/<int:id>/edit")
@required("admin")
def edit_hall(id):
    if not one("SELECT id FROM hall_distribution WHERE id=%s", (id,)):
        flash("Hall distribution not found.")
        return redirect(url_for("admin_halls"))
    values = hall_form_values()
    if values is not None:
        execute("""UPDATE hall_distribution SET title=%s,specialty_id=%s,year_id=%s,course_id=%s,
            hall=%s,distribution_date=%s,session=%s,start_time=%s,end_time=%s WHERE id=%s""", values + (id,))
        flash("Hall distribution updated.")
    return redirect(url_for("admin_halls"))


@app.post("/admin/hall/delete/<int:id>")
@required("admin")
def delete_hall(id):
    execute("DELETE FROM hall_distribution WHERE id=%s", (id,)); return redirect(url_for("admin_halls"))


@app.post("/admin/result")
@required("admin")
def add_result():
    f = request.files.get("pdf")
    n = save_file(f, "results", {"pdf"}) if f and f.filename else None
    execute("INSERT INTO results(student_id,course_id,score,grade,semester,academic_year,pdf_filename) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (request.form["student_id"], request.form.get("course_id") or None, request.form["score"], request.form["grade"],
             request.form["semester"], request.form["academic_year"], n))
    return redirect(url_for("admin_dashboard"))


def save_message_attachment():
    f = request.files.get("attachment")
    if not f or not f.filename: return None, None
    if ext(f.filename) not in MSG_FILES: return "", "invalid"
    return save_file(f, "messages", MSG_FILES), ext(f.filename)


@app.post("/admin/message")
@required("admin")
def send_message():
    n, typ = save_message_attachment()
    if typ == "invalid": flash("Attachment must be PDF, DOCX or image."); return redirect(url_for("admin_dashboard"))
    execute("INSERT INTO messages(sender_id,student_id,subject,message,attachment_filename,attachment_type) VALUES(%s,%s,%s,%s,%s,%s)",
            (session["user_id"], request.form["student_id"], request.form["subject"], request.form["message"], n, typ))
    return redirect(url_for("admin_dashboard"))


@app.route("/teacher")
@required("teacher")
def teacher_dashboard():
    students = rows("SELECT u.id,u.full_name,u.email,u.avatar,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.role='student' ORDER BY s.name,y.id,u.full_name")
    sent = rows("SELECT m.*,u.full_name student_name FROM messages m JOIN users u ON m.student_id=u.id WHERE m.sender_id=%s ORDER BY m.created_at DESC", (session["user_id"],))
    approved_students = rows("""SELECT r.student_id,s.full_name student_name,sp.name specialty,y.name year FROM teacher_requests r JOIN users s ON r.student_id=s.id LEFT JOIN specialties sp ON s.specialty_id=sp.id LEFT JOIN years y ON s.year_id=y.id WHERE r.teacher_id=%s AND r.status='approved' ORDER BY s.full_name""", (session["user_id"],))
    approved_parent_chats = rows("""SELECT r.id request_id,p.full_name parent_name,s.full_name student_name,r.expires_at
        FROM parent_teacher_requests r JOIN users p ON r.parent_id=p.id JOIN users s ON r.student_id=s.id
        WHERE r.teacher_id=%s AND r.status='approved' AND r.expires_at > NOW() ORDER BY p.full_name""",
        (session["user_id"],))
    notes = rows("SELECT n.*,u.full_name teacher_name FROM teacher_notes n JOIN users u ON n.created_by=u.id ORDER BY n.created_at DESC")
    announcements = rows("SELECT * FROM announcements ORDER BY created_at DESC")
    timetables = rows("SELECT t.*,s.name specialty,y.name year FROM timetables t JOIN specialties s ON t.specialty_id=s.id JOIN years y ON t.year_id=y.id ORDER BY t.created_at DESC")
    papers = rows("SELECT p.*,c.name course FROM past_papers p LEFT JOIN courses c ON p.course_id=c.id ORDER BY p.created_at DESC")
    results = rows("SELECT r.*,c.name course,s.full_name student_name FROM results r JOIN users s ON r.student_id=s.id LEFT JOIN courses c ON r.course_id=c.id ORDER BY r.created_at DESC")
    halls = rows("SELECT h.*,c.name course FROM hall_distribution h LEFT JOIN courses c ON h.course_id=c.id ORDER BY h.id DESC")
    admins = rows("SELECT id,full_name,email,avatar FROM users WHERE role='admin' ORDER BY full_name")
    admin_messages = rows("SELECT m.*,u.full_name sender_name FROM staff_messages m JOIN users u ON m.sender_id=u.id WHERE m.receiver_id=%s ORDER BY m.created_at DESC", (session["user_id"],))
    return render_template("teacher/dashboard.html", students=students, sent=sent, approved_students=approved_students,
                           approved_parent_chats=approved_parent_chats,
                           notes=notes, announcements=announcements, timetables=timetables, papers=papers,
                           results=results, halls=halls, admins=admins, admin_messages=admin_messages)


@app.route("/teacher/teachers")
@required("teacher")
def teacher_directory():
    teachers = rows("""SELECT u.id,u.full_name,u.email,u.avatar,s.name specialty,y.name year
        FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id
        WHERE u.role='teacher' AND u.id<>%s ORDER BY u.full_name""", (session["user_id"],))
    return render_template("teacher/teachers.html", teachers=teachers)


@app.post("/teacher/note")
@required("teacher")
def add_teacher_note():
    f = request.files.get("file")
    if not f or not f.filename or ext(f.filename) not in {"pdf", "jpg", "jpeg", "png", "gif", "webp"}:
        flash("Notes must be a PDF or image.")
        return redirect(url_for("teacher_dashboard"))
    filename = save_file(f, "teacher_notes", {"pdf", "jpg", "jpeg", "png", "gif", "webp"})
    execute("INSERT INTO teacher_notes(title,description,filename,file_type,created_by) VALUES(%s,%s,%s,%s,%s)",
            (request.form.get("title", "").strip(), request.form.get("description", "").strip(),
             filename, ext(f.filename), session["user_id"]))
    flash("Notes uploaded successfully.")
    return redirect(url_for("teacher_dashboard"))


@app.post("/teacher/admin-message")
@required("teacher")
def teacher_admin_message():
    admin_id = request.form.get("receiver_id")
    if not admin_id or not one("SELECT id FROM users WHERE id=%s AND role='admin'", (admin_id,)):
        flash("Select a valid administrator.")
    else:
        execute("INSERT INTO staff_messages(sender_id,receiver_id,message) VALUES(%s,%s,%s)",
                (session["user_id"], admin_id, request.form.get("message", "").strip()))
        flash("Message sent to the administrator.")
    return redirect(url_for("teacher_dashboard"))


@app.post("/teacher/message")
@required("teacher")
def teacher_message():
    student_id = int(request.form["student_id"])
    student = one("SELECT id FROM users WHERE id=%s AND role='student'", (student_id,))
    if not student:
        flash("Student not found.")
        return redirect(url_for("teacher_dashboard"))
    n, typ = save_message_attachment()
    if typ == "invalid": flash("Attachment must be PDF, DOCX or image."); return redirect(url_for("teacher_dashboard"))
    execute("INSERT INTO messages(sender_id,student_id,subject,message,attachment_filename,attachment_type) VALUES(%s,%s,%s,%s,%s,%s)",
            (session["user_id"], student_id, request.form["subject"], request.form["message"], n, typ))
    flash("Message sent. The student must request approval before replying.")
    return redirect(url_for("teacher_dashboard"))


@app.route("/reports", methods=["GET", "POST"])
@required()
def reports():
    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not subject or not message:
            flash("Add a subject and describe the problem.")
        else:
            execute("INSERT INTO issue_reports(reporter_id,subject,message) VALUES(%s,%s,%s)",
                    (session["user_id"], subject, message))
            flash("Your private report was sent to the administrators.")
            return redirect(url_for("reports"))
    reports_ = rows("""SELECT r.*,u.full_name reporter_name FROM issue_reports r
        JOIN users u ON u.id=r.reporter_id WHERE r.reporter_id=%s ORDER BY r.created_at DESC""", (session["user_id"],))
    return render_template("reports.html", reports=reports_)


@app.route("/admin/reports", methods=["GET", "POST"])
@required("admin")
def admin_reports():
    if request.method == "POST":
        report_id = request.form.get("report_id")
        reply = request.form.get("admin_reply", "").strip()
        if reply:
            execute("UPDATE issue_reports SET admin_reply=%s,status='resolved',resolved_at=NOW() WHERE id=%s",
                    (reply, report_id))
            flash("Report reply sent privately to the reporter.")
        return redirect(url_for("admin_reports"))
    reports_ = rows("""SELECT r.*,u.full_name reporter_name,u.email reporter_email,u.role reporter_role
        FROM issue_reports r JOIN users u ON u.id=r.reporter_id ORDER BY r.created_at DESC""")
    return render_template("admin/reports.html", reports=reports_)


@app.route("/admin/chat", methods=["GET", "POST"])
@required("admin")
def admin_chat():
    admins = rows("SELECT id,full_name,email FROM users WHERE role='admin' AND id<>%s ORDER BY full_name", (session["user_id"],))
    inbox = rows("SELECT s.*,u.full_name sender_name FROM staff_messages s JOIN users u ON s.sender_id=u.id WHERE s.receiver_id=%s ORDER BY s.created_at DESC", (session["user_id"],))
    sent = rows("SELECT s.*,u.full_name receiver_name FROM staff_messages s JOIN users u ON s.receiver_id=u.id WHERE s.sender_id=%s ORDER BY s.created_at DESC", (session["user_id"],))
    if request.method == "POST":
        receiver = int(request.form["receiver_id"])
        if receiver == session["user_id"] or not one("SELECT id FROM users WHERE id=%s AND role='admin'", (receiver,)):
            flash("Invalid administrator selected.")
        else:
            execute("INSERT INTO staff_messages(sender_id,receiver_id,message) VALUES(%s,%s,%s)",
                    (session["user_id"], receiver, request.form["message"]))
            return redirect(url_for("admin_chat"))
    return render_template("admin/chat.html", admins=admins, inbox=inbox, sent=sent)


@app.post("/admin/staff-message/delete/<int:id>")
@required("admin")
def delete_staff_message(id):
    execute("DELETE FROM staff_messages WHERE id=%s AND sender_id=%s", (id, session["user_id"]))
    return redirect(url_for("admin_chat"))


@app.post("/admin/settings")
@required("admin")
def update_settings():
    db = get_db_connection(); c = db.cursor()
    c.execute("UPDATE site_settings SET app_name=%s,app_title=%s WHERE id=1", (request.form["app_name"], request.form["app_title"]))
    c.execute("UPDATE about_us SET title=%s,content=%s WHERE id=1", (request.form["about_title"], request.form["about_content"]))
    c.execute("UPDATE contact_us SET email=%s,phone=%s,address=%s,content=%s WHERE id=1", (request.form["contact_email"], request.form["contact_phone"], request.form["contact_address"], request.form["contact_content"]))
    db.commit(); c.close(); db.close(); return redirect(url_for("admin_dashboard"))


@app.route("/profile", methods=["GET", "POST"])
@required()
def profile():
    uid = session["user_id"]
    user = one("SELECT u.*,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.id=%s", (uid,))
    specialties = rows("SELECT * FROM specialties ORDER BY name")
    years = rows("SELECT * FROM years ORDER BY id")
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        specialty_name = request.form.get("specialty", "").strip()
        year_name = request.form.get("year", "").strip()
        new_password = request.form.get("new_password", "")
        current_password = request.form.get("current_password", "")
        if not full_name or not email:
            flash("Name and email are required.")
            return render_template("profile.html", user=user, specialties=specialties, years=years)
        conflict = one("SELECT id FROM users WHERE email=%s AND id<>%s", (email, uid))
        if conflict:
            flash("That email is already used by another account.")
            return render_template("profile.html", user=user, specialties=specialties, years=years)
        db=get_db_connection(); c=db.cursor(dictionary=True)
        try:
            sid=user.get("specialty_id"); yid=user.get("year_id")
            if user["role"] == "student":
                if specialty_name:
                    c.execute("SELECT id FROM specialties WHERE LOWER(name)=LOWER(%s)", (specialty_name,)); r=c.fetchone()
                    if r: sid=r["id"]
                    else:
                        c.execute("INSERT INTO specialties(name) VALUES(%s)", (specialty_name,)); sid=c.lastrowid
                if year_name:
                    c.execute("SELECT id FROM years WHERE LOWER(name)=LOWER(%s)", (year_name,)); r=c.fetchone()
                    if r: yid=r["id"]
                    else:
                        c.execute("INSERT INTO years(name) VALUES(%s)", (year_name,)); yid=c.lastrowid
            avatar = save_file(request.files.get("profile_picture"), "profiles", IMAGE)
            if avatar:
                c.execute("UPDATE users SET avatar=%s WHERE id=%s", (avatar, uid))
            c.execute("UPDATE users SET full_name=%s,email=%s,specialty_id=%s,year_id=%s,last_seen=NOW() WHERE id=%s", (full_name,email,sid,yid,uid))
            if new_password:
                if not current_password or not check_password_hash(user["password"], current_password):
                    db.rollback(); flash("Enter your current password to change the password.")
                    return render_template("profile.html", user=user, specialties=specialties, years=years)
                if len(new_password) < 6:
                    db.rollback(); flash("New password must contain at least 6 characters.")
                    return render_template("profile.html", user=user, specialties=specialties, years=years)
                c.execute("UPDATE users SET password=%s WHERE id=%s", (generate_password_hash(new_password),uid))
            db.commit()
            session["user_name"] = full_name
            session["specialty_id"] = sid
            session["year_id"] = yid
            flash("Profile updated successfully.")
            return redirect(url_for("profile"))
        except Exception as e:
            db.rollback(); flash("Could not update profile: " + str(e))
        finally:
            c.close(); db.close()
    return render_template("profile.html", user=user, specialties=specialties, years=years)

@app.route("/about")
def about(): return render_template("public/about.html", about=one("SELECT * FROM about_us WHERE id=1"))
@app.route("/contact")
def contact(): return render_template("public/contact.html", contact=one("SELECT * FROM contact_us WHERE id=1"))
@app.route("/uploads/<folder>/<filename>")
def uploaded_file(folder, filename):
    if folder == "fee_receipts":
        abort(404)
    if folder == "results":
        if not session.get("user_id"):
            return redirect(url_for("login"))
        result = one("SELECT student_id FROM results WHERE pdf_filename=%s", (filename,))
        if not result:
            abort(404)
        role = session.get("role")
        if role == "student" and result["student_id"] != session["user_id"]:
            abort(403)
        if role == "parent" and result["student_id"] != session.get("child_student_id"):
            abort(403)
        if role not in ("student", "parent", "teacher", "admin"):
            abort(403)
    return send_from_directory(os.path.join(UPLOAD, folder), filename)
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("index"))


@app.route("/set-language/<lang>")
def set_language(lang):
    target = request.args.get("next", "")
    if not target.startswith("/") or target.startswith("//") or "\\" in target:
        target = request.referrer or url_for("index")
    response = redirect(target)
    if lang in ("en", "fr"):
        session["language"] = lang
        response.set_cookie("language", lang, max_age=60 * 60 * 24 * 365, samesite="Lax", path="/")
    return response



def ensure_runtime_schema():
    """Create feature tables needed by the enhanced build on an existing database."""
    db = get_db_connection(); c = db.cursor()
    statements = [
        "ALTER TABLE users MODIFY role ENUM('student','teacher','admin','parent') NOT NULL DEFAULT 'student'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS matricule VARCHAR(50) NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS child_student_id INT NULL",
        "CREATE UNIQUE INDEX uq_users_matricule ON users(matricule)",
        "ALTER TABLE users ADD CONSTRAINT fk_users_child_student FOREIGN KEY(child_student_id) REFERENCES users(id) ON DELETE CASCADE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar VARCHAR(255) NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE teacher_requests ADD COLUMN IF NOT EXISTS teacher_response TEXT NULL",
        "CREATE TABLE IF NOT EXISTS staff_messages(id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS student_messages(id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS teacher_requests(id INT AUTO_INCREMENT PRIMARY KEY,student_id INT NOT NULL,teacher_id INT NOT NULL,status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',approved_by INT NULL,teacher_response TEXT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,decided_at TIMESTAMP NULL,FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL)",
        "CREATE TABLE IF NOT EXISTS teacher_notes(id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,description TEXT,filename VARCHAR(255) NOT NULL,file_type VARCHAR(20) NOT NULL,created_by INT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS issue_reports(id INT AUTO_INCREMENT PRIMARY KEY,reporter_id INT NOT NULL,subject VARCHAR(200) NOT NULL,message TEXT NOT NULL,status ENUM('open','resolved') NOT NULL DEFAULT 'open',admin_reply TEXT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,resolved_at TIMESTAMP NULL,FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS teacher_student_messages(id INT AUTO_INCREMENT PRIMARY KEY,request_id INT NOT NULL,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(request_id) REFERENCES teacher_requests(id) ON DELETE CASCADE,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS parent_teacher_requests(id INT AUTO_INCREMENT PRIMARY KEY,parent_id INT NOT NULL,student_id INT NOT NULL,teacher_id INT NOT NULL,status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',approved_by INT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,decided_at TIMESTAMP NULL,started_at DATETIME NULL,expires_at DATETIME NULL,INDEX idx_parent_teacher_request(parent_id,student_id,teacher_id,status),FOREIGN KEY(parent_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL)",
        "CREATE TABLE IF NOT EXISTS parent_teacher_messages(id INT AUTO_INCREMENT PRIMARY KEY,request_id INT NOT NULL,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(request_id) REFERENCES parent_teacher_requests(id) ON DELETE CASCADE,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS community_posts(id INT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,content TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS community_comments(id INT AUTO_INCREMENT PRIMARY KEY,post_id INT NOT NULL,user_id INT NOT NULL,content TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(post_id) REFERENCES community_posts(id) ON DELETE CASCADE,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS fee_payments(id INT AUTO_INCREMENT PRIMARY KEY,student_id INT NOT NULL,amount DECIMAL(12,2) NOT NULL,payment_period VARCHAR(100) NOT NULL,bank_reference VARCHAR(100) NOT NULL,receipt_filename VARCHAR(255) NULL,status ENUM('pending','confirmed','rejected') NOT NULL DEFAULT 'pending',created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,INDEX idx_fee_payments_student_created(student_id,created_at),FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS fee_schedules(id INT AUTO_INCREMENT PRIMARY KEY,payment_period VARCHAR(100) NOT NULL UNIQUE,total_amount DECIMAL(12,2) NOT NULL,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS fee_payment_settings(id TINYINT PRIMARY KEY,bank_name VARCHAR(150) NOT NULL,account_name VARCHAR(150) NOT NULL,account_number VARCHAR(80) NOT NULL,branch VARCHAR(150) NULL,currency VARCHAR(12) NULL,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS teacher_ratings(id INT AUTO_INCREMENT PRIMARY KEY,student_id INT NOT NULL,teacher_id INT NOT NULL,rating TINYINT NOT NULL,comment TEXT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,UNIQUE KEY uq_teacher_rating_student_teacher(student_id,teacher_id),FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE)",
        "ALTER TABLE hall_distribution ADD COLUMN IF NOT EXISTS session ENUM('morning','evening') NOT NULL DEFAULT 'morning'",
        "ALTER TABLE hall_distribution ADD COLUMN IF NOT EXISTS start_time TIME NULL",
        "ALTER TABLE hall_distribution ADD COLUMN IF NOT EXISTS end_time TIME NULL"
    ]
    try:
        for q in statements:
            try: c.execute(q)
            except Exception: pass
        for y in ("HND Year 1","HND Year 2","HND Year 3"):
            try: c.execute("INSERT IGNORE INTO years(name) VALUES(%s)",(y,))
            except Exception: pass
        db.commit()
    finally:
        c.close(); db.close()


if __name__ == "__main__":
    try: ensure_runtime_schema()
    except Exception as e: print("Schema check skipped:", e)
    app.run(debug=True)
