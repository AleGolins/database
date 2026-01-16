import os
from datetime import datetime, date
from functools import wraps

from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash


from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

# --------------------
# Config
# --------------------
app = Flask(__name__)


auth = HTTPBasicAuth()


BASIC_USERS = {
    "test": generate_password_hash("test123"),
    "collab": generate_password_hash("collab123"),
}


@auth.verify_password
def verify_password(username, password):
    print("DEBUG auth:", repr(username), repr(password), "known:", list(BASIC_USERS.keys()))
    if username in BASIC_USERS and check_password_hash(BASIC_USERS[username], password):
        return username
    return None


# SECRET_KEY: mettila come variabile ambiente in Railway
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# DATABASE_URL: Railway fornisce una DATABASE_URL Postgres
database_url = os.environ.get("DATABASE_URL", "sqlite:///local.db")

# Railway spesso usa postgres://, SQLAlchemy preferisce postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = "login"
login_manager.init_app(app)


# --------------------
# Models
# --------------------
class Practice(db.Model):
    __tablename__ = "pratiche"

    id = db.Column(db.Integer, primary_key=True)
    cliente = db.Column(db.String(200), nullable=False)
    oggetto = db.Column(db.String(300), nullable=False)
    stato = db.Column(db.String(20), nullable=False, default="NUOVA")  # NUOVA, ATTIVA, CHIUSA

    data_apertura = db.Column(db.Date, nullable=False, default=date.today)
    data_chiusura = db.Column(db.Date, nullable=True)

    note = db.Column(db.Text, nullable=True)

    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_by = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.String(120), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "cliente": self.cliente,
            "oggetto": self.oggetto,
            "stato": self.stato,
            "data_apertura": self.data_apertura.isoformat() if self.data_apertura else None,
            "data_chiusura": self.data_chiusura.isoformat() if self.data_chiusura else None,
            "note": self.note or "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "updated_by": self.updated_by or "",
        }


# --------------------
# Auth (semplice, 2 utenti via env)
# --------------------
class User(UserMixin):
    def __init__(self, user_id: str, username: str, password: str):
        self.id = user_id
        self.username = username
        self.password = password

# Imposti in Railway:
# USER1_USERNAME, USER1_PASSWORD, USER2_USERNAME, USER2_PASSWORD
def load_users():
    u1 = os.environ.get("USER1_USERNAME", "admin")
    p1 = os.environ.get("USER1_PASSWORD", "admin")
    u2 = os.environ.get("USER2_USERNAME", "collab")
    p2 = os.environ.get("USER2_PASSWORD", "collab")

    return {
        "1": User("1", u1, p1),
        "2": User("2", u2, p2),
    }

USERS = load_users()

@login_manager.user_loader
def load_user(user_id):
    return USERS.get(user_id)

def refresh_users():
    # utile in locale se cambi env e riavvii
    global USERS
    USERS = load_users()


def require_db_ready(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # crea tabelle (semplice, senza migrazioni)
        with app.app_context():
            db.create_all()
        return f(*args, **kwargs)
    return wrapper


# --------------------
# Routes
# --------------------
@app.get("/")
def home():
    return redirect(url_for("pratiche"))

@app.route("/login", methods=["GET", "POST"])
@auth.login_required
def login():
    refresh_users()

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        found = None
        for u in USERS.values():
            if u.username == username and u.password == password:
                found = u
                break

        if found:
            login_user(found)
            return redirect(url_for("pratiche"))
        flash("Credenziali non valide.", "error")

    return render_template("login.html")

@app.get("/logout")
@auth.login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.get("/pratiche")
@auth.login_required
def pratiche():
    stato = request.args.get("stato", "ATTIVA").upper()
    if stato not in ("NUOVA", "ATTIVA", "CHIUSA"):
        stato = "ATTIVA"
    return render_template("pratiche.html", stato=stato)

@app.get("/api/pratiche")
@auth.login_required
@require_db_ready
def api_pratiche():
    stato = request.args.get("stato", "ATTIVA").upper()
    if stato not in ("NUOVA", "ATTIVA", "CHIUSA"):
        stato = "ATTIVA"

    items = (Practice.query
             .filter_by(stato=stato)
             .order_by(Practice.updated_at.desc())
             .all())
    return jsonify([p.to_dict() for p in items])

@app.route("/pratiche/nuova", methods=["GET", "POST"])
@auth.login_required
@require_db_ready
def pratica_nuova():
    if request.method == "POST":
        cliente = (request.form.get("cliente") or "").strip()
        oggetto = (request.form.get("oggetto") or "").strip()
        stato = (request.form.get("stato") or "NUOVA").upper()
        note = (request.form.get("note") or "").strip()

        if stato not in ("NUOVA", "ATTIVA", "CHIUSA"):
            stato = "NUOVA"

        if not cliente or not oggetto:
            flash("Cliente e Oggetto sono obbligatori.", "error")
            return render_template("pratica_form.html", mode="new", pratica=None)

        p = Practice(
            cliente=cliente,
            oggetto=oggetto,
            stato=stato,
            data_apertura=date.today(),
            note=note,
            created_by=current_user.username,
            updated_by=current_user.username,
            updated_at=datetime.utcnow(),
        )
        db.session.add(p)
        db.session.commit()

        flash("Pratica creata.", "ok")
        return redirect(url_for("pratiche", stato=stato))

    return render_template("pratica_form.html", mode="new", pratica=None)

@app.route("/pratiche/<int:pid>/modifica", methods=["GET", "POST"])
@auth.login_required
@require_db_ready
def pratica_modifica(pid: int):
    p = Practice.query.get_or_404(pid)

    if request.method == "POST":
        cliente = (request.form.get("cliente") or "").strip()
        oggetto = (request.form.get("oggetto") or "").strip()
        stato = (request.form.get("stato") or p.stato).upper()
        note = (request.form.get("note") or "").strip()

        if stato not in ("NUOVA", "ATTIVA", "CHIUSA"):
            stato = p.stato

        if not cliente or not oggetto:
            flash("Cliente e Oggetto sono obbligatori.", "error")
            return render_template("pratica_form.html", mode="edit", pratica=p)

        p.cliente = cliente
        p.oggetto = oggetto
        p.stato = stato
        p.note = note

        # gestione data chiusura: se diventa CHIUSA metto oggi, se esce da CHIUSA la tolgo
        if stato == "CHIUSA" and p.data_chiusura is None:
            p.data_chiusura = date.today()
        if stato != "CHIUSA":
            p.data_chiusura = None

        p.updated_at = datetime.utcnow()
        p.updated_by = current_user.username

        db.session.commit()
        flash("Pratica aggiornata.", "ok")
        return redirect(url_for("pratiche", stato=stato))

    return render_template("pratica_form.html", mode="edit", pratica=p)

@app.post("/pratiche/<int:pid>/elimina")
@auth.login_required
@require_db_ready
def pratica_elimina(pid: int):
    p = Practice.query.get_or_404(pid)
    stato = p.stato
    db.session.delete(p)
    db.session.commit()
    flash("Pratica eliminata.", "ok")
    return redirect(url_for("pratiche", stato=stato))


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)
