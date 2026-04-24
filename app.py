from datetime import datetime
from functools import wraps
import os
import secrets

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

# Секретный ключ нужен для сессий и flash-сообщений.
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
# Используем SQLite как просили в задании.
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///career_center.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # student, admin, curator
    full_name = db.Column(db.String(120), nullable=False)
    group_name = db.Column(db.String(50))
    about = db.Column(db.Text)
    contacts = db.Column(db.String(255))
    resume_public_token = db.Column(db.String(64), unique=True, index=True)
    curator_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    students = db.relationship("User", backref=db.backref("curator", remote_side=[id]), lazy=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class PortfolioEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    link = db.Column(db.String(255))
    status = db.Column(db.String(20), default="pending", nullable=False)  # pending, approved, rejected
    curator_comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    student = db.relationship("User", backref="portfolio_entries")


class Vacancy(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    company = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    contacts = db.Column(db.String(255))
    status = db.Column(db.String(20), default="active", nullable=False)  # active, hidden, archive
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    kind = db.Column(db.String(30), nullable=False)  # course, seminar, practice
    format_type = db.Column(db.String(20), nullable=False)  # online, offline
    places = db.Column(db.Integer)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="active", nullable=False)  # active, hidden, archive


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def role_required(*roles):
    # Простой декоратор для проверки роли пользователя на маршруте.
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                flash("У вас нет доступа к этой странице.", "error")
                return redirect(url_for("index"))
            return func(*args, **kwargs)

        return wrapper

    return decorator


def is_valid_status(value: str) -> bool:
    # Допустимые статусы для вакансий и учебных программ.
    return value in {"active", "hidden", "archive"}


STATUS_LABELS = {
    "active": "Активно",
    "hidden": "Скрыто",
    "archive": "Архив",
    "pending": "Ожидает проверки",
    "approved": "Подтверждено",
    "rejected": "Отклонено",
}


@app.context_processor
def inject_status_labels():
    return {"status_labels": STATUS_LABELS}


@app.route("/")
def index():
    if current_user.is_authenticated:
        if current_user.role == "admin":
            return redirect(url_for("admin_dashboard"))
        if current_user.role == "curator":
            return redirect(url_for("curator_students"))
        return redirect(url_for("student_dashboard"))
    return render_template("public/index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash("Вы успешно вошли в систему.", "success")
            return redirect(url_for("index"))

        flash("Неверный email или пароль.", "error")

    return render_template("auth/login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Вы вышли из аккаунта.", "success")
    return redirect(url_for("login"))


@app.route("/student")
@login_required
@role_required("student")
def student_dashboard():
    vacancies = Vacancy.query.filter_by(status="active").order_by(Vacancy.created_at.desc()).all()
    courses = Course.query.filter_by(status="active").order_by(Course.id.desc()).all()
    return render_template("student/dashboard.html", vacancies=vacancies, courses=courses)


@app.route("/student/profile", methods=["GET", "POST"])
@login_required
@role_required("student")
def student_profile():
    if request.method == "POST":
        current_user.full_name = request.form.get("full_name", "").strip()
        current_user.group_name = request.form.get("group_name", "").strip()
        current_user.about = request.form.get("about", "").strip()
        current_user.contacts = request.form.get("contacts", "").strip()
        db.session.commit()
        flash("Профиль обновлён.", "success")
        return redirect(url_for("student_profile"))

    return render_template("student/profile.html")


@app.route("/student/portfolio", methods=["GET", "POST"])
@login_required
@role_required("student")
def student_portfolio():
    if request.method == "POST":
        entry = PortfolioEntry(
            student_id=current_user.id,
            title=request.form.get("title", "").strip(),
            description=request.form.get("description", "").strip(),
            link=request.form.get("link", "").strip(),
            status="pending",
        )
        db.session.add(entry)
        db.session.commit()
        flash("Запись портфолио добавлена.", "success")
        return redirect(url_for("student_portfolio"))

    entries = PortfolioEntry.query.filter_by(student_id=current_user.id).order_by(PortfolioEntry.created_at.desc()).all()
    return render_template("student/portfolio.html", entries=entries, edit_entry=None)


@app.route("/student/portfolio/<int:entry_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("student")
def student_portfolio_edit(entry_id):
    # Студент может редактировать только свою запись.
    entry = PortfolioEntry.query.filter_by(id=entry_id, student_id=current_user.id).first_or_404()

    if request.method == "POST":
        entry.title = request.form.get("title", "").strip()
        entry.description = request.form.get("description", "").strip()
        entry.link = request.form.get("link", "").strip()
        # После редактирования запись снова уходит на проверку куратора.
        entry.status = "pending"
        db.session.commit()
        flash("Запись портфолио обновлена и отправлена на повторную проверку.", "success")
        return redirect(url_for("student_portfolio"))

    entries = PortfolioEntry.query.filter_by(student_id=current_user.id).order_by(PortfolioEntry.created_at.desc()).all()
    return render_template("student/portfolio.html", entries=entries, edit_entry=entry)


@app.route("/student/portfolio/<int:entry_id>/delete", methods=["POST"])
@login_required
@role_required("student")
def student_portfolio_delete(entry_id):
    # Студент может удалить только свою запись.
    entry = PortfolioEntry.query.filter_by(id=entry_id, student_id=current_user.id).first_or_404()
    db.session.delete(entry)
    db.session.commit()
    flash("Запись портфолио удалена.", "success")
    return redirect(url_for("student_portfolio"))

    return render_template("student/portfolio.html", entries=entries)

@app.route("/resume/<token>")
def public_resume(token):
    student = User.query.filter_by(resume_public_token=token, role="student").first_or_404()
    entries = PortfolioEntry.query.filter_by(student_id=student.id, status="approved").all()
    return render_template("public/resume.html", student=student, entries=entries)


@app.route("/curator/students")
@login_required
@role_required("curator")
def curator_students():
    students = User.query.filter_by(role="student", curator_id=current_user.id).order_by(User.full_name).all()
    return render_template("curator/students.html", students=students)


@app.route("/curator/student/<int:student_id>/portfolio", methods=["GET", "POST"])
@login_required
@role_required("curator")
def curator_student_portfolio(student_id):
    student = User.query.filter_by(id=student_id, role="student", curator_id=current_user.id).first_or_404()

    if request.method == "POST":
        entry_id = int(request.form.get("entry_id"))
        action = request.form.get("action")
        entry = PortfolioEntry.query.filter_by(id=entry_id, student_id=student.id).first_or_404()
        entry.status = "approved" if action == "approve" else "rejected"
        entry.curator_comment = request.form.get("curator_comment", "").strip()
        db.session.commit()
        flash("Статус записи обновлён.", "success")
        return redirect(url_for("curator_student_portfolio", student_id=student.id))

    review_filter = request.args.get("status", "all")
    entries_query = PortfolioEntry.query.filter_by(student_id=student.id).order_by(PortfolioEntry.created_at.desc())
    if review_filter in {"pending", "approved", "rejected"}:
        entries_query = entries_query.filter_by(status=review_filter)
    else:
        review_filter = "all"

    entries = entries_query.all()
    pending_entries = PortfolioEntry.query.filter_by(student_id=student.id, status="pending").order_by(
        PortfolioEntry.created_at.desc()
    ).all()
    return render_template(
        "curator/portfolio_review.html",
        student=student,
        entries=entries,
        pending_entries=pending_entries,
        review_filter=review_filter,
    )


@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    return render_template("admin/dashboard.html")


@app.route("/admin/students", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_students():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        full_name = request.form.get("full_name", "").strip()
        group_name = request.form.get("group_name", "").strip()
        curator_id = request.form.get("curator_id")

        if User.query.filter_by(email=email).first():
            flash("Пользователь с таким email уже есть.", "error")
            return redirect(url_for("admin_students"))

        student = User(
            email=email,
            role="student",
            full_name=full_name,
            group_name=group_name,
            curator_id=int(curator_id) if curator_id else None,
            resume_public_token=secrets.token_urlsafe(18),
        )
        student.set_password(password)
        db.session.add(student)
        db.session.commit()
        flash("Аккаунт студента создан.", "success")
        return redirect(url_for("admin_students"))

    students = User.query.filter_by(role="student").order_by(User.id.desc()).all()
    curators = User.query.filter_by(role="curator").order_by(User.full_name).all()
    return render_template("admin/students.html", students=students, curators=curators)


@app.route("/admin/vacancies", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_vacancies():
    if request.method == "POST":
        status = request.form.get("status", "active")
        if not is_valid_status(status):
            flash("Некорректный статус вакансии.", "error")
            return redirect(url_for("admin_vacancies"))

      
        vacancy = Vacancy(
            title=request.form.get("title", "").strip(),
            company=request.form.get("company", "").strip(),
            description=request.form.get("description", "").strip(),
            contacts=request.form.get("contacts", "").strip(),
            status=status,
        )
        db.session.add(vacancy)
        db.session.commit()
        flash("Вакансия сохранена.", "success")
        return redirect(url_for("admin_vacancies"))

    status_filter = request.args.get("status", "all")
    vacancies_query = Vacancy.query.order_by(Vacancy.created_at.desc())
    if status_filter in {"active", "hidden", "archive"}:
        vacancies_query = vacancies_query.filter_by(status=status_filter)
    else:
        status_filter = "all"

    vacancies = vacancies_query.all()
    return render_template("admin/vacancies.html", vacancies=vacancies, edit_vacancy=None, status_filter=status_filter)


@app.route("/admin/vacancies/<int:vacancy_id>/status", methods=["POST"])
@login_required
@role_required("admin")
def admin_vacancy_status(vacancy_id):
    vacancy = Vacancy.query.get_or_404(vacancy_id)
    status = request.form.get("status", "active")
    if not is_valid_status(status):
        flash("Некорректный статус вакансии.", "error")
        return redirect(url_for("admin_vacancies"))

    vacancy.status = status
    db.session.commit()
    flash("Статус вакансии изменён.", "success")
    return redirect(url_for("admin_vacancies"))


@app.route("/admin/vacancies/<int:vacancy_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_vacancy_edit(vacancy_id):
    vacancy = Vacancy.query.get_or_404(vacancy_id)

    if request.method == "POST":
        status = request.form.get("status", "active")
        if not is_valid_status(status):
            flash("Некорректный статус вакансии.", "error")
            return redirect(url_for("admin_vacancy_edit", vacancy_id=vacancy.id))

        vacancy.title = request.form.get("title", "").strip()
        vacancy.company = request.form.get("company", "").strip()
        vacancy.description = request.form.get("description", "").strip()
        vacancy.contacts = request.form.get("contacts", "").strip()
        vacancy.status = status
        db.session.commit()
        flash("Вакансия обновлена.", "success")
        return redirect(url_for("admin_vacancies"))

    vacancies = Vacancy.query.order_by(Vacancy.created_at.desc()).all()
    return render_template("admin/vacancies.html", vacancies=vacancies, edit_vacancy=vacancy)


@app.route("/admin/vacancies/<int:vacancy_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def admin_vacancy_delete(vacancy_id):
    vacancy = Vacancy.query.get_or_404(vacancy_id)
    db.session.delete(vacancy)
    db.session.commit()
    flash("Вакансия удалена.", "success")
    return redirect(url_for("admin_vacancies"))


@app.route("/admin/courses", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_courses():
    if request.method == "POST":
        format_type = request.form.get("format_type", "online")
        places = request.form.get("places")
        status = request.form.get("status", "active")

        if format_type not in {"online", "offline"}:
            flash("Некорректный формат программы.", "error")
            return redirect(url_for("admin_courses"))

        if not is_valid_status(status):
            flash("Некорректный статус программы.", "error")
            return redirect(url_for("admin_courses"))

        try:
            parsed_places = int(places) if format_type == "offline" and places else None
        except ValueError:
            flash("Количество мест должно быть числом.", "error")
            return redirect(url_for("admin_courses"))
        course = Course(
            title=request.form.get("title", "").strip(),
            kind=request.form.get("kind", "course"),
            format_type=format_type,
            places=parsed_places,
            description=request.form.get("description", "").strip(),
            status=status,
        )
        db.session.add(course)
        db.session.commit()
        flash("Курс/семинар/практика сохранены.", "success")
        return redirect(url_for("admin_courses"))

    status_filter = request.args.get("status", "all")
    courses_query = Course.query.order_by(Course.id.desc())
    if status_filter in {"active", "hidden", "archive"}:
        courses_query = courses_query.filter_by(status=status_filter)
    else:
        status_filter = "all"

    courses = courses_query.all()
    return render_template("admin/courses.html", courses=courses, edit_course=None, status_filter=status_filter)


@app.route("/admin/courses/<int:course_id>/status", methods=["POST"])
@login_required
@role_required("admin")
def admin_course_status(course_id):
    course = Course.query.get_or_404(course_id)
    status = request.form.get("status", "active")
    if not is_valid_status(status):
        flash("Некорректный статус программы.", "error")
        return redirect(url_for("admin_courses"))

    course.status = status
    db.session.commit()
    flash("Статус программы изменён.", "success")
    return redirect(url_for("admin_courses"))


@app.route("/admin/courses/<int:course_id>/edit", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_course_edit(course_id):
    course = Course.query.get_or_404(course_id)

    if request.method == "POST":
        format_type = request.form.get("format_type", "online")
        places = request.form.get("places")
        status = request.form.get("status", "active")

        if format_type not in {"online", "offline"}:
            flash("Некорректный формат программы.", "error")
            return redirect(url_for("admin_course_edit", course_id=course.id))

        if not is_valid_status(status):
            flash("Некорректный статус программы.", "error")
            return redirect(url_for("admin_course_edit", course_id=course.id))

        course.title = request.form.get("title", "").strip()
        course.kind = request.form.get("kind", "course")
        course.format_type = format_type
        try:
            course.places = int(places) if format_type == "offline" and places else None
        except ValueError:
            flash("Количество мест должно быть числом.", "error")
            return redirect(url_for("admin_course_edit", course_id=course.id))
        course.description = request.form.get("description", "").strip()
        course.status = status
        db.session.commit()
        flash("Программа обновлена.", "success")
        return redirect(url_for("admin_courses"))

    courses = Course.query.order_by(Course.id.desc()).all()
    return render_template("admin/courses.html", courses=courses, edit_course=course)


@app.route("/admin/courses/<int:course_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def admin_course_delete(course_id):
    course = Course.query.get_or_404(course_id)
    db.session.delete(course)
    db.session.commit()
    flash("Программа удалена.", "success")
    return redirect(url_for("admin_courses"))


@app.route("/vacancies")
@login_required
@role_required("student")
def student_vacancies():
    vacancies = Vacancy.query.filter_by(status="active").order_by(Vacancy.created_at.desc()).all()
    return render_template("student/vacancies.html", vacancies=vacancies)


@app.route("/courses")
@login_required
@role_required("student")
def student_courses():
    courses = Course.query.filter_by(status="active").order_by(Course.id.desc()).all()
    return render_template("student/courses.html", courses=courses)


def seed_if_empty():
    # Создаём стартовые аккаунты, чтобы можно было сразу проверить роли.
    if User.query.count() == 0:
        admin = User(email="admin@irkpo.ru", role="admin", full_name="Администратор")
        admin.set_password("admin123")

        curator = User(email="curator@irkpo.ru", role="curator", full_name="Куратор группы")
        curator.set_password("curator123")

        student = User(
            email="student@irkpo.ru",
            role="student",
            full_name="Студент ИРКПО",
            group_name="ИС-21",
            curator=curator,
            resume_public_token=secrets.token_urlsafe(18),
        )
        student.set_password("student123")

        db.session.add_all([admin, curator, student])
        db.session.commit()


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        seed_if_empty()
    app.run(debug=True)
