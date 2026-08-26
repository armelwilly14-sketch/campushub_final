import os, uuid
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from database import get_db_connection

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-me")
ROOT = os.path.dirname(os.path.abspath(__file__))
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


def required(role=None):
    def deco(fn):
        @wraps(fn)
        def w(*a, **k):
            if not session.get("user_id"):
                return redirect(url_for("login"))
            if role and session.get("role") != role:
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
    language = request.cookies.get("language") or session.get("language", "en")
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
        password = request.form.get("password", "")
        specialty_name = request.form.get("specialty", "").strip()
        year_name = request.form.get("year", "").strip()
        if not all([full_name, email, password, specialty_name, year_name]):
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
            c.execute("INSERT INTO users(full_name,email,password,role,specialty_id,year_id) VALUES(%s,%s,%s,'student',%s,%s)",
                      (full_name, email, generate_password_hash(password), specialty_id, year_id))
            db.commit(); flash("Student account created successfully."); return redirect(url_for("login"))
        except Exception as e:
            db.rollback(); flash("Registration failed: " + str(e))
        finally:
            c.close(); db.close()
    return render_template("register.html", specialties=sp, years=ys)


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
        u = one("SELECT * FROM users WHERE email=%s", (request.form["email"],))
        if u and (u.get("is_banned") or u.get("is_suspended")):
            flash("This account is suspended. Contact an administrator.")
        elif u and check_password_hash(u["password"], request.form["password"]):
            session.update(user_id=u["id"], user_name=u["full_name"], role=u["role"],
                           specialty_id=u["specialty_id"], year_id=u["year_id"])
            if u["role"] == "admin": return redirect(url_for("admin_dashboard"))
            if u["role"] == "teacher": return redirect(url_for("teacher_dashboard"))
            return redirect(url_for("student_dashboard"))
        flash("Invalid login.")
    return render_template("login.html")


@app.route("/student")
@required("student")
def student_dashboard():
    sid, yid = session["specialty_id"], session["year_id"]
    try:
        user = one("SELECT u.*,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.id=%s", (session.get("user_id"),)) if session.get("user_id") else {}
    except Exception:
        user = {}
    a = rows("SELECT a.*,u.full_name sender_name,u.role sender_role FROM announcements a LEFT JOIN users u ON a.created_by=u.id WHERE (a.specialty_id IS NULL OR a.specialty_id=%s) AND (a.year_id IS NULL OR a.year_id=%s) ORDER BY a.created_at DESC", (sid, yid))
    t = rows("SELECT t.*,s.name specialty,y.name year FROM timetables t JOIN specialties s ON t.specialty_id=s.id JOIN years y ON t.year_id=y.id WHERE t.specialty_id=%s AND t.year_id=%s ORDER BY created_at DESC", (sid, yid))
    p = rows("SELECT p.*,c.name course FROM past_papers p LEFT JOIN courses c ON p.course_id=c.id WHERE (p.specialty_id IS NULL OR p.specialty_id=%s) AND (p.year_id IS NULL OR p.year_id=%s) ORDER BY p.created_at DESC", (sid, yid))
    r = rows("SELECT r.*,c.name course FROM results r LEFT JOIN courses c ON r.course_id=c.id WHERE r.student_id=%s ORDER BY r.created_at DESC", (session["user_id"],))
    m = rows("SELECT m.*,u.full_name sender_name,u.role sender_role FROM messages m LEFT JOIN users u ON m.sender_id=u.id WHERE m.student_id=%s ORDER BY m.created_at DESC", (session["user_id"],))
    h = rows("SELECT h.*,c.name course FROM hall_distribution h LEFT JOIN courses c ON h.course_id=c.id WHERE (h.specialty_id IS NULL OR h.specialty_id=%s) AND (h.year_id IS NULL OR h.year_id=%s) ORDER BY h.id DESC", (sid, yid))
    return render_template("student/dashboard.html", user=user, announcements=a, timetables=t, past_papers=p, results=r, messages=m, halls=h)


@app.route("/community")
@required()
def community():
    students = rows("SELECT u.id,u.full_name,u.avatar,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.role='student' AND u.id<>%s ORDER BY u.full_name", (session["user_id"],))
    posts = rows("""SELECT p.*,u.full_name author_name,u.avatar author_avatar,s.name specialty,y.name year
        FROM community_posts p JOIN users u ON p.user_id=u.id
        LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id
        ORDER BY p.created_at DESC""")
    comments = rows("""SELECT c.*,u.full_name author_name,u.avatar author_avatar FROM community_comments c JOIN users u ON c.user_id=u.id ORDER BY c.created_at ASC""")
    inbox = rows("SELECT d.*,u.full_name sender_name FROM student_messages d JOIN users u ON d.sender_id=u.id WHERE d.receiver_id=%s ORDER BY d.created_at DESC", (session["user_id"],))
    sent = rows("SELECT d.*,u.full_name receiver_name FROM student_messages d JOIN users u ON d.receiver_id=u.id WHERE d.sender_id=%s ORDER BY d.created_at DESC", (session["user_id"],))
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
@required("student")
def student_private_chat(student_id):
    if student_id == session["user_id"] or not one("SELECT id FROM users WHERE id=%s AND role='student'", (student_id,)):
        flash("Student not found."); return redirect(url_for("community"))
    other = one("SELECT id,full_name FROM users WHERE id=%s AND role='student'", (student_id,))
    if request.method == "POST":
        text = request.form.get("message", "").strip()
        if text:
            execute("INSERT INTO student_messages(sender_id,receiver_id,message) VALUES(%s,%s,%s)", (session["user_id"], student_id, text))
        return redirect(url_for("student_private_chat", student_id=student_id))
    messages = rows("""SELECT m.*,u.full_name sender_name FROM student_messages m JOIN users u ON m.sender_id=u.id
        WHERE (m.sender_id=%s AND m.receiver_id=%s) OR (m.sender_id=%s AND m.receiver_id=%s) ORDER BY m.created_at ASC""",
        (session["user_id"], student_id, student_id, session["user_id"]))
    return render_template("student/private_chat.html", other=other, messages=messages)


@app.post("/community/send")
@required("student")
def community_send():
    receiver = int(request.form["receiver_id"])
    if receiver == session["user_id"] or not one("SELECT id FROM users WHERE id=%s AND role='student'", (receiver,)):
        flash("Student not found."); return redirect(url_for("community"))
    execute("INSERT INTO student_messages(sender_id,receiver_id,message) VALUES(%s,%s,%s)",
            (session["user_id"], receiver, request.form["message"]))
    return redirect(url_for("student_private_chat", student_id=receiver))


@app.route("/teacher-requests")
@required("student")
def teacher_requests():
    teachers = rows("SELECT id,full_name FROM users WHERE role='teacher' ORDER BY full_name")
    requests_ = rows("""SELECT r.*,t.full_name teacher_name,a.full_name approved_by_name
        FROM teacher_requests r JOIN users t ON r.teacher_id=t.id
        LEFT JOIN users a ON r.approved_by=a.id
        WHERE r.student_id=%s ORDER BY r.created_at DESC""", (session["user_id"],))
    approved = rows("""SELECT r.id,r.teacher_id,t.full_name teacher_name
        FROM teacher_requests r JOIN users t ON r.teacher_id=t.id
        WHERE r.student_id=%s AND r.status='approved' ORDER BY t.full_name""", (session["user_id"],))
    return render_template("student/teacher_requests.html", teachers=teachers, requests=requests_, approved=approved)


@app.post("/teacher-requests/send")
@required("student")
def send_teacher_request():
    teacher_id = int(request.form["teacher_id"])
    teacher = one("SELECT id FROM users WHERE id=%s AND role='teacher'", (teacher_id,))
    if not teacher:
        flash("Teacher not found.")
        return redirect(url_for("teacher_requests"))
    existing = one("SELECT id,status FROM teacher_requests WHERE student_id=%s AND teacher_id=%s AND status IN ('pending','approved')", (session["user_id"], teacher_id))
    if existing:
        flash("You already have a pending or approved request for this teacher.")
        return redirect(url_for("teacher_requests"))
    execute("INSERT INTO teacher_requests(student_id,teacher_id,status) VALUES(%s,%s,'pending')", (session["user_id"], teacher_id))
    flash("Request sent. An administrator must approve it before you can chat with the teacher.")
    return redirect(url_for("teacher_requests"))


@app.route("/teacher-chat/<int:teacher_id>", methods=["GET", "POST"])
@required("student")
def student_teacher_chat(teacher_id):
    teacher = one("SELECT id,full_name,email FROM users WHERE id=%s AND role='teacher'", (teacher_id,))
    approved = one("SELECT id FROM teacher_requests WHERE student_id=%s AND teacher_id=%s AND status='approved'", (session["user_id"], teacher_id))
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
    return render_template("student/teacher_chat.html", teacher=teacher, messages=messages)


@app.route("/teacher/requests")
@required("teacher")
def teacher_requests_view():
    requests_ = rows("""SELECT r.*,s.full_name student_name,sp.name specialty,y.name year
        FROM teacher_requests r JOIN users s ON r.student_id=s.id
        LEFT JOIN specialties sp ON s.specialty_id=sp.id LEFT JOIN years y ON s.year_id=y.id
        WHERE r.teacher_id=%s ORDER BY r.created_at DESC""", (session["user_id"],))
    return render_template("teacher/requests.html", requests=requests_)

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


@app.route("/admin/teacher-requests")
@required("admin")
def admin_teacher_requests():
    requests_ = rows("""SELECT r.*,s.full_name student_name,t.full_name teacher_name,sp.name specialty,y.name year
        FROM teacher_requests r JOIN users s ON r.student_id=s.id JOIN users t ON r.teacher_id=t.id
        LEFT JOIN specialties sp ON s.specialty_id=sp.id LEFT JOIN years y ON s.year_id=y.id
        ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,r.created_at DESC""")
    return render_template("admin/teacher_requests.html", requests=requests_)


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


def admin_data():
    return dict(
        students=rows("SELECT u.id,u.full_name,u.email,u.avatar,u.is_banned,u.is_suspended,s.name specialty,y.name year FROM users u LEFT JOIN specialties s ON u.specialty_id=s.id LEFT JOIN years y ON u.year_id=y.id WHERE u.role='student' ORDER BY s.name,y.id,u.full_name"),
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

@app.route("/admin/teachers")
@required("admin")
def admin_teachers():
    return render_template("admin/teachers.html", **admin_data())

@app.route("/admin/content")
@required("admin")
def admin_content():
    return render_template("admin/content.html", **admin_data())

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
    if ext(f.filename) != "pdf": flash("Timetable must be PDF."); return redirect(url_for("admin_dashboard"))
    n = save_file(f, "timetables", {"pdf"})
    execute("INSERT INTO timetables(title,specialty_id,year_id,pdf_filename) VALUES(%s,%s,%s,%s)",
            (request.form["title"], request.form["specialty_id"], request.form["year_id"], n))
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/timetable/delete/<int:id>")
@required("admin")
def delete_timetable(id):
    execute("DELETE FROM timetables WHERE id=%s", (id,)); return redirect(url_for("admin_dashboard"))


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
    execute("INSERT INTO hall_distribution(title,specialty_id,year_id,course_id,hall,distribution_date) VALUES(%s,%s,%s,%s,%s,%s)",
            (request.form["title"], request.form.get("specialty_id") or None, request.form.get("year_id") or None,
             request.form.get("course_id") or None, request.form["hall"], request.form.get("distribution_date") or None))
    return redirect(url_for("admin_dashboard"))


@app.post("/admin/hall/delete/<int:id>")
@required("admin")
def delete_hall(id):
    execute("DELETE FROM hall_distribution WHERE id=%s", (id,)); return redirect(url_for("admin_dashboard"))


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
    notes = rows("SELECT n.*,u.full_name teacher_name FROM teacher_notes n JOIN users u ON n.created_by=u.id ORDER BY n.created_at DESC")
    announcements = rows("SELECT * FROM announcements ORDER BY created_at DESC")
    timetables = rows("SELECT t.*,s.name specialty,y.name year FROM timetables t JOIN specialties s ON t.specialty_id=s.id JOIN years y ON t.year_id=y.id ORDER BY t.created_at DESC")
    papers = rows("SELECT p.*,c.name course FROM past_papers p LEFT JOIN courses c ON p.course_id=c.id ORDER BY p.created_at DESC")
    results = rows("SELECT r.*,c.name course,s.full_name student_name FROM results r JOIN users s ON r.student_id=s.id LEFT JOIN courses c ON r.course_id=c.id ORDER BY r.created_at DESC")
    halls = rows("SELECT h.*,c.name course FROM hall_distribution h LEFT JOIN courses c ON h.course_id=c.id ORDER BY h.id DESC")
    admins = rows("SELECT id,full_name,email,avatar FROM users WHERE role='admin' ORDER BY full_name")
    admin_messages = rows("SELECT m.*,u.full_name sender_name FROM staff_messages m JOIN users u ON m.sender_id=u.id WHERE m.receiver_id=%s ORDER BY m.created_at DESC", (session["user_id"],))
    return render_template("teacher/dashboard.html", students=students, sent=sent, approved_students=approved_students,
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
def uploaded_file(folder, filename): return send_from_directory(os.path.join(UPLOAD, folder), filename)
@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("index"))


@app.route("/set-language/<lang>")
def set_language(lang):
    response = redirect(request.referrer or url_for("index"))
    if lang in ("en", "fr"):
        session["language"] = lang
        response.set_cookie("language", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
    return response



def ensure_runtime_schema():
    """Create feature tables needed by the enhanced build on an existing database."""
    db = get_db_connection(); c = db.cursor()
    statements = [
        "ALTER TABLE users MODIFY role ENUM('student','teacher','admin') NOT NULL DEFAULT 'student'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar VARCHAR(255) NULL",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_banned BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE",
        "CREATE TABLE IF NOT EXISTS staff_messages(id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS student_messages(id INT AUTO_INCREMENT PRIMARY KEY,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS teacher_requests(id INT AUTO_INCREMENT PRIMARY KEY,student_id INT NOT NULL,teacher_id INT NOT NULL,status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',approved_by INT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,decided_at TIMESTAMP NULL,FOREIGN KEY(student_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(teacher_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(approved_by) REFERENCES users(id) ON DELETE SET NULL)",
        "CREATE TABLE IF NOT EXISTS teacher_notes(id INT AUTO_INCREMENT PRIMARY KEY,title VARCHAR(200) NOT NULL,description TEXT,filename VARCHAR(255) NOT NULL,file_type VARCHAR(20) NOT NULL,created_by INT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS issue_reports(id INT AUTO_INCREMENT PRIMARY KEY,reporter_id INT NOT NULL,subject VARCHAR(200) NOT NULL,message TEXT NOT NULL,status ENUM('open','resolved') NOT NULL DEFAULT 'open',admin_reply TEXT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,resolved_at TIMESTAMP NULL,FOREIGN KEY(reporter_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS teacher_student_messages(id INT AUTO_INCREMENT PRIMARY KEY,request_id INT NOT NULL,sender_id INT NOT NULL,receiver_id INT NOT NULL,message TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(request_id) REFERENCES teacher_requests(id) ON DELETE CASCADE,FOREIGN KEY(sender_id) REFERENCES users(id) ON DELETE CASCADE,FOREIGN KEY(receiver_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS community_posts(id INT AUTO_INCREMENT PRIMARY KEY,user_id INT NOT NULL,content TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)",
        "CREATE TABLE IF NOT EXISTS community_comments(id INT AUTO_INCREMENT PRIMARY KEY,post_id INT NOT NULL,user_id INT NOT NULL,content TEXT NOT NULL,created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,FOREIGN KEY(post_id) REFERENCES community_posts(id) ON DELETE CASCADE,FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)"
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
