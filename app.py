"""
COO Plant Performance Board  —  BU daily entry + COO dashboard
---------------------------------------------------------------
Run :  python app.py      (or press Run in Thonny)
Open:  http://127.0.0.1:5011
Needs: pip install flask pymysql

On first start it creates the database `coo_portal`, all tables,
the 4 plants and these logins (change passwords after first login):
    coo / Coo@123        -> COO, sees all plants, settings
    bu1 / Bu1@123 ... bu4 / Bu4@123  -> BU heads, own plant only
"""
import os
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pymysql
    from pymysql.cursors import DictCursor
except ImportError:
    raise SystemExit("\n*** pymysql is not installed ***\n"
                     "Thonny: Tools > Manage packages > search 'pymysql' > Install\n"
                     "or Command Prompt: pip install pymysql\n")

# ------------------------------------------------------------------ config
# On Railway the MYSQL* variables are filled in automatically from the MySQL service.
# On your PC they are not set, so the local defaults below are used.
def env(*names, default=None):
    for n in names:
        v = os.getenv(n)
        if v:
            return v
    return default


DB_HOST = env("MYSQLHOST", "COO_DB_HOST", "FIVES_DB_HOST", default="localhost")
DB_PORT = int(env("MYSQLPORT", "COO_DB_PORT", "FIVES_DB_PORT", default="3306"))
DB_USER = env("MYSQLUSER", "COO_DB_USER", "FIVES_DB_USER", default="root")
DB_PASS = env("MYSQLPASSWORD", "COO_DB_PASS", "FIVES_DB_PASS", default="Mokshita@123")
DB_NAME = env("MYSQLDATABASE", "COO_DB_NAME", default="coo_portal")

IST = timezone(timedelta(hours=5, minutes=30))


def today():
    """Today's date in India, even when the server runs on UTC (Railway)."""
    return datetime.now(IST).date()

PORT = int(os.getenv("PORT", "5011"))
EDIT_DAYS = 3          # BU heads can enter / correct today and the previous 3 days

app = Flask(__name__)
app.secret_key = env("SECRET_KEY", "COO_SECRET_KEY", default="scavp-coo-board-change-this-key")
app.permanent_session_lifetime = timedelta(hours=12)

MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# ------------------------------------------------------------------ daily entry fields
# name: (label, type, min, max, nullable, help)
FIELDS = {
    "plan_qty":       ("Plan quantity", "int", 0, None, False, "units"),
    "actual_qty":     ("Actual quantity", "int", 0, None, False, "units"),
    "oee":            ("OEE", "dec", 0, 100, True, "%"),
    "orders_due":     ("Dispatch schedules due", "int", 0, None, False, "nos"),
    "orders_on_time": ("Dispatched on time", "int", 0, None, False, "nos"),
    "customer_rej":   ("Customer rejections", "int", 0, None, False, "qty"),
    "mp_required":    ("Manpower required", "int", 0, None, False, "nos"),
    "mp_present":     ("Manpower present", "int", 0, None, False, "nos"),
    "breakdown_hrs":  ("Breakdown time", "dec", 0, 1000, False, "hrs"),
    "near_miss":      ("Near-miss", "int", 0, None, False, "nos"),
    "first_aid":      ("First aid cases", "int", 0, None, False, "nos"),
    "lti":            ("Lost-time injury (LTI)", "int", 0, None, False, "nos"),
    "s5_score":       ("5S audit score", "dec", 0, 100, True, "only on audit day"),
    "open_issues":    ("Open issues", "int", 0, None, True, "count as of today"),
}
GROUPS = [
    ("Production", ["plan_qty", "actual_qty", "oee"]),
    ("Delivery", ["orders_due", "orders_on_time"]),
    ("Quality", ["customer_rej"]),
    ("Manpower", ["mp_required", "mp_present"]),
    ("Maintenance", ["breakdown_hrs"]),
    ("Safety", ["near_miss", "first_aid", "lti"]),
    ("5S & issues", ["s5_score", "open_issues"]),
]
TARGET_LABELS = {
    "ach": "Plan achievement % (min)", "oee": "OEE % (min)", "otd": "On-time delivery % (min)",
    "ppm": "Customer PPM (max)", "att": "Attendance % (min)", "s5": "5S score (min)",
    "bd": "Breakdown hrs per plant per month (max)", "issues": "Open issues per plant (max)",
}
DEFAULT_TARGETS = {"ach": 98, "oee": 75, "otd": 95, "ppm": 500, "att": 92, "s5": 80, "bd": 40, "issues": 10}
DEFAULT_PLANTS = [
    ("BU1", "BU1", "Plant 1 · Assembly", "BU1 Head"),
    ("BU2", "BU2", "Plant 2 · Machining", "BU2 Head"),
    ("BU3", "BU3", "Plant 3 · Paint & Finish", "BU3 Head"),
    ("BU4", "BU4", "Plant 4 · Moulding", "BU4 Head"),
]
AREAS = ["Safety", "Quality", "Delivery", "Production", "Maintenance", "Manpower", "Environment", "Other"]


# ------------------------------------------------------------------ database
def get_db(with_db=True):
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
                           database=DB_NAME if with_db else None, charset="utf8mb4",
                           cursorclass=DictCursor, autocommit=True,
                           init_command="SET time_zone = '+05:30'")


def q(sql, args=None, one=False):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            if cur.description is None:
                return cur.lastrowid
            return cur.fetchone() if one else cur.fetchall()
    finally:
        conn.close()


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS plants (
        code VARCHAR(10) PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        site VARCHAR(100),
        head VARCHAR(100),
        last_lti_date DATE NULL,
        sort_order INT DEFAULT 0
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY,
        username VARCHAR(50) NOT NULL UNIQUE,
        password_hash VARCHAR(255) NOT NULL,
        full_name VARCHAR(100),
        role ENUM('coo','bu') NOT NULL,
        plant_code VARCHAR(10) NULL,
        active TINYINT DEFAULT 1,
        last_login DATETIME NULL,
        FOREIGN KEY (plant_code) REFERENCES plants(code)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS daily_kpi (
        id INT AUTO_INCREMENT PRIMARY KEY,
        plant_code VARCHAR(10) NOT NULL,
        entry_date DATE NOT NULL,
        plan_qty INT DEFAULT 0,
        actual_qty INT DEFAULT 0,
        oee DECIMAL(5,2) NULL,
        orders_due INT DEFAULT 0,
        orders_on_time INT DEFAULT 0,
        customer_rej INT DEFAULT 0,
        mp_required INT DEFAULT 0,
        mp_present INT DEFAULT 0,
        breakdown_hrs DECIMAL(7,2) DEFAULT 0,
        near_miss INT DEFAULT 0,
        first_aid INT DEFAULT 0,
        lti INT DEFAULT 0,
        s5_score DECIMAL(5,2) NULL,
        open_issues INT NULL,
        remarks VARCHAR(500),
        entered_by VARCHAR(50),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uq_plant_day (plant_code, entry_date),
        FOREIGN KEY (plant_code) REFERENCES plants(code)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS kpi_targets (
        kpi VARCHAR(20) PRIMARY KEY,
        value DECIMAL(10,2) NOT NULL
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS escalations (
        id INT AUTO_INCREMENT PRIMARY KEY,
        plant_code VARCHAR(10) NOT NULL,
        area VARCHAR(50),
        issue VARCHAR(255) NOT NULL,
        owner VARCHAR(100),
        severity ENUM('Critical','High') DEFAULT 'High',
        status ENUM('Open','Closed') DEFAULT 'Open',
        raised_on DATE NOT NULL,
        raised_by VARCHAR(50),
        closed_on DATE NULL,
        closed_by VARCHAR(50),
        closure_note VARCHAR(255),
        FOREIGN KEY (plant_code) REFERENCES plants(code)
    ) CHARACTER SET utf8mb4""",
]


def init_db():
    print(f"Connecting to MySQL {DB_USER}@{DB_HOST}:{DB_PORT} ...")
    try:
        conn = get_db(with_db=False)
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.close()
    except pymysql.MySQLError:
        pass   # hosted MySQL: database already exists
    for sql in SCHEMA:
        q(sql)
    if not q("SELECT COUNT(*) n FROM plants", one=True)["n"]:
        for i, (code, name, site, head) in enumerate(DEFAULT_PLANTS):
            q("INSERT INTO plants (code,name,site,head,sort_order) VALUES (%s,%s,%s,%s,%s)",
              (code, name, site, head, i + 1))
    for k, v in DEFAULT_TARGETS.items():
        q("INSERT IGNORE INTO kpi_targets (kpi,value) VALUES (%s,%s)", (k, v))
    if not q("SELECT COUNT(*) n FROM users", one=True)["n"]:
        q("INSERT INTO users (username,password_hash,full_name,role) VALUES (%s,%s,%s,'coo')",
          ("coo", generate_password_hash("Coo@123"), "COO"))
        for code, _, _, head in DEFAULT_PLANTS:
            u = code.lower()
            q("INSERT INTO users (username,password_hash,full_name,role,plant_code) VALUES (%s,%s,%s,'bu',%s)",
              (u, generate_password_hash(f"Bu{code[-1]}@123"), head, code))
        print("Default logins created: coo/Coo@123, bu1/Bu1@123 ... bu4/Bu4@123  (change after first login)")
    print(f"Database `{DB_NAME}` ready.")


# ------------------------------------------------------------------ auth
def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return q("SELECT id,username,full_name,role,plant_code FROM users WHERE id=%s AND active=1", (uid,), one=True)


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            u = current_user()
            if not u:
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Session expired. Please log in again."}), 401
                return redirect(url_for("login", next=request.path))
            if role and u["role"] != role:
                abort(403)
            request.user = u
            return fn(*a, **kw)
        return wrapper
    return deco


@app.context_processor
def inject_user():
    return {"user": getattr(request, "user", None) or current_user()}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        un = request.form.get("username", "").strip().lower()
        u = q("SELECT * FROM users WHERE username=%s AND active=1", (un,), one=True)
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session.permanent = True
            session["uid"] = u["id"]
            q("UPDATE users SET last_login=NOW() WHERE id=%s", (u["id"],))
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") else url_for("home"))
        flash("Wrong username or password.", "bad")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required()
def home():
    return redirect(url_for("entry" if request.user["role"] == "bu" else "dashboard"))


@app.route("/password", methods=["GET", "POST"])
@login_required()
def password():
    if request.method == "POST":
        u = q("SELECT * FROM users WHERE id=%s", (request.user["id"],), one=True)
        new, conf = request.form.get("new", ""), request.form.get("confirm", "")
        if not check_password_hash(u["password_hash"], request.form.get("current", "")):
            flash("Current password is wrong.", "bad")
        elif len(new) < 6:
            flash("New password must be at least 6 characters.", "bad")
        elif new != conf:
            flash("New password and confirmation do not match.", "bad")
        else:
            q("UPDATE users SET password_hash=%s WHERE id=%s", (generate_password_hash(new), u["id"]))
            flash("Password changed.", "good")
            return redirect(url_for("home"))
    return render_template("password.html", active="pw")


# ------------------------------------------------------------------ helpers
def parse_date(s, default=None):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return default


def num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 2)


def pct(a, b):
    return round(a / b * 100, 1) if b else None


def targets():
    return {r["kpi"]: num(r["value"]) for r in q("SELECT kpi,value FROM kpi_targets")}


def visible_plants(user):
    if user["role"] == "coo":
        return q("SELECT * FROM plants ORDER BY sort_order, code")
    return q("SELECT * FROM plants WHERE code=%s", (user["plant_code"],))


def editable(d):
    t = today()
    return t - timedelta(days=EDIT_DAYS) <= d <= t


# ------------------------------------------------------------------ BU daily entry
@app.route("/entry", methods=["GET", "POST"])
@login_required("bu")
def entry():
    u = request.user
    plant = q("SELECT * FROM plants WHERE code=%s", (u["plant_code"],), one=True)
    tdy = today()
    d = parse_date(request.values.get("date"), tdy)
    errors, values = {}, {}

    if request.method == "POST":
        if not editable(d):
            flash(f"You can only enter data for tdy and the previous {EDIT_DAYS} days.", "bad")
            return redirect(url_for("entry"))
        for name, (label, typ, lo, hi, nullable, _) in FIELDS.items():
            raw = request.form.get(name, "").strip()
            values[name] = raw
            if raw == "":
                if name in ("plan_qty", "actual_qty"):
                    errors[name] = "Required"
                continue
            try:
                v = int(raw) if typ == "int" else round(float(raw), 2)
            except ValueError:
                errors[name] = "Enter a number" if typ == "dec" else "Enter a whole number"
                continue
            if v < lo or (hi is not None and v > hi):
                errors[name] = f"Must be between {lo} and {hi}" if hi is not None else f"Must be {lo} or more"
        remarks = request.form.get("remarks", "").strip()[:500]
        values["remarks"] = remarks

        def val(n):
            raw = values.get(n, "")
            if raw == "" or n in errors:
                return None if FIELDS[n][4] else 0
            return int(raw) if FIELDS[n][1] == "int" else round(float(raw), 2)

        if not errors:
            if val("orders_on_time") > val("orders_due"):
                errors["orders_on_time"] = "Cannot be more than schedules due"
            if val("lti") > 0 and not remarks:
                errors["remarks"] = "Describe the LTI in remarks"
        if errors:
            flash("Please correct the highlighted fields.", "bad")
        else:
            cols = list(FIELDS) + ["remarks", "entered_by"]
            data = [val(n) for n in FIELDS] + [remarks, u["username"]]
            q(f"""INSERT INTO daily_kpi (plant_code, entry_date, {', '.join(cols)})
                  VALUES (%s, %s, {', '.join(['%s'] * len(cols))})
                  ON DUPLICATE KEY UPDATE {', '.join(f'{c}=VALUES({c})' for c in cols)}""",
              [plant["code"], d] + data)
            flash(f"Saved {plant['name']} entry for {d.strftime('%d %b %Y')}.", "good")
            return redirect(url_for("entry", date=d.isoformat()))
    else:
        row = q("SELECT * FROM daily_kpi WHERE plant_code=%s AND entry_date=%s", (plant["code"], d), one=True)
        if row:
            values = {n: ("" if row[n] is None else num(row[n])) for n in FIELDS}
            values["remarks"] = row["remarks"] or ""
            values["_meta"] = f"Last saved by {row['entered_by']} at {row['updated_at'].strftime('%d %b, %H:%M')}"

    # last 7 days status strip + recent history
    since = tdy - timedelta(days=14)
    hist = q("""SELECT * FROM daily_kpi WHERE plant_code=%s AND entry_date>=%s
                ORDER BY entry_date DESC""", (plant["code"], since))
    have = {h["entry_date"] for h in hist}
    strip = [{"d": tdy - timedelta(days=i), "ok": (tdy - timedelta(days=i)) in have,
              "edit": i <= EDIT_DAYS} for i in range(6, -1, -1)]
    for h in hist:
        h["ach"] = pct(h["actual_qty"], h["plan_qty"])
        h["can_edit"] = editable(h["entry_date"])
    return render_template("entry.html", active="entry", plant=plant, d=d, today=tdy,
                           can_edit=editable(d), fields=FIELDS, groups=GROUPS, values=values,
                           errors=errors, strip=strip, hist=hist, edit_days=EDIT_DAYS,
                           min_date=(tdy - timedelta(days=EDIT_DAYS)).isoformat())


# ------------------------------------------------------------------ dashboard
@app.route("/dashboard")
@login_required()
def dashboard():
    return render_template("dashboard.html", active="dash")


def fy_months(today):
    m = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
    out = []
    while m <= today:
        out.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    return out


SERIES_KEYS = ["plan", "act", "ach", "oee", "otd", "ppm", "att", "s5", "bd", "nm", "fa", "lti", "issues", "days"]


def derive(r):
    if not r:
        return {k: None for k in SERIES_KEYS}
    act = r["act"]
    return {
        "plan": r["plan"], "act": act, "ach": pct(act, r["plan"]),
        "oee": None if r["oee"] is None else round(r["oee"], 1),
        "otd": pct(r["ontime"], r["due"]),
        "ppm": round(r["rej"] / act * 1e6) if act else None,
        "att": pct(r["mpp"], r["mpr"]),
        "s5": None if r["s5"] is None else round(r["s5"], 1),
        "bd": round(r["bd"], 1), "nm": r["nm"], "fa": r["fa"], "lti": r["lti"],
        "issues": r["issues"], "days": r["days"],
    }


def combine(raws):
    """Combine raw monthly sums of several plants into one (for 'All plants')."""
    raws = [r for r in raws if r]
    if not raws:
        return None
    out = {k: sum(r[k] for r in raws) for k in ["plan", "act", "due", "ontime", "rej", "mpr", "mpp", "bd", "nm", "fa", "lti", "days"]}
    w = [(r["oee"], r["act"]) for r in raws if r["oee"] is not None]
    out["oee"] = (sum(o * a for o, a in w) / sum(a for _, a in w)) if w and sum(a for _, a in w) else (
        sum(o for o, _ in w) / len(w) if w else None)
    s5 = [r["s5"] for r in raws if r["s5"] is not None]
    out["s5"] = sum(s5) / len(s5) if s5 else None
    iss = [r["issues"] for r in raws if r["issues"] is not None]
    out["issues"] = sum(iss) if iss else None
    return out


@app.route("/api/dashboard")
@login_required()
def api_dashboard():
    u = request.user
    tdy = today()
    months = fy_months(tdy)
    start, end = months[0], tdy
    plants = visible_plants(u)
    codes = [p["code"] for p in plants]
    idx = {(m.year, m.month): i for i, m in enumerate(months)}

    rows = q("""SELECT plant_code, YEAR(entry_date) y, MONTH(entry_date) m,
                   SUM(plan_qty) plan, SUM(actual_qty) act, AVG(oee) oee,
                   SUM(orders_due) due, SUM(orders_on_time) ontime, SUM(customer_rej) rej,
                   SUM(mp_required) mpr, SUM(mp_present) mpp, SUM(breakdown_hrs) bd,
                   SUM(near_miss) nm, SUM(first_aid) fa, SUM(lti) lti, AVG(s5_score) s5, COUNT(*) days
                FROM daily_kpi WHERE entry_date BETWEEN %s AND %s
                GROUP BY plant_code, YEAR(entry_date), MONTH(entry_date)""", (start, end))
    issues = q("""SELECT d.plant_code, YEAR(d.entry_date) y, MONTH(d.entry_date) m, d.open_issues
                  FROM daily_kpi d JOIN (
                      SELECT plant_code, MAX(entry_date) md FROM daily_kpi
                      WHERE open_issues IS NOT NULL AND entry_date BETWEEN %s AND %s
                      GROUP BY plant_code, YEAR(entry_date), MONTH(entry_date)) x
                  ON x.plant_code=d.plant_code AND x.md=d.entry_date""", (start, end))
    iss_map = {(r["plant_code"], r["y"], r["m"]): r["open_issues"] for r in issues}

    raw = {c: [None] * len(months) for c in codes}
    for r in rows:
        if r["plant_code"] not in raw:
            continue
        rr = {k: (float(r[k]) if r[k] is not None else None) for k in
              ["plan", "act", "oee", "due", "ontime", "rej", "mpr", "mpp", "bd", "nm", "fa", "lti", "s5", "days"]}
        for k in ["plan", "act", "due", "ontime", "rej", "mpr", "mpp", "nm", "fa", "lti", "days"]:
            rr[k] = int(rr[k] or 0)
        rr["bd"] = rr["bd"] or 0
        rr["issues"] = iss_map.get((r["plant_code"], r["y"], r["m"]))
        raw[r["plant_code"]][idx[(r["y"], r["m"])]] = rr

    def series(raw_list):
        ds = [derive(r) for r in raw_list]
        return {k: [d[k] for d in ds] for k in SERIES_KEYS}

    last_lti = {r["plant_code"]: r["d"] for r in
                q("SELECT plant_code, MAX(entry_date) d FROM daily_kpi WHERE lti>0 GROUP BY plant_code")}
    out_plants = {}
    for p in plants:
        dates = [x for x in (p["last_lti_date"], last_lti.get(p["code"])) if x]
        out_plants[p["code"]] = {"name": p["name"], "site": p["site"] or "", "head": p["head"] or "",
                                 "lastLti": max(dates).isoformat() if dates else None,
                                 **series(raw[p["code"]])}
    all_series = series([combine([raw[c][i] for c in codes]) for i in range(len(months))])

    if u["role"] == "coo":
        esc = q("""SELECT * FROM escalations WHERE status='Open'""")
    else:
        esc = q("""SELECT * FROM escalations WHERE status='Open' AND plant_code=%s""", (u["plant_code"],))
    fy = months[0].year
    return jsonify({
        "role": u["role"], "plant": u["plant_code"],
        "fy": f"FY {fy}-{str(fy + 1)[2:]}",
        "months": [f"{MON[m.month - 1]} {m.year}" for m in months],
        "targets": targets(), "plants": out_plants, "all": all_series,
        "escalations": [{"bu": e["plant_code"], "area": e["area"] or "", "issue": e["issue"],
                         "owner": e["owner"] or "", "days": (tdy - e["raised_on"]).days,
                         "sev": "r" if e["severity"] == "Critical" else "a"} for e in esc],
        "today": tdy.isoformat(),
    })


@app.route("/api/daily")
@login_required()
def api_daily():
    d = parse_date(request.args.get("date"), today())
    plants = visible_plants(request.user)
    rows = {r["plant_code"]: r for r in q("SELECT * FROM daily_kpi WHERE entry_date=%s", (d,))}
    out = []
    for p in plants:
        r = rows.get(p["code"])
        if not r:
            out.append({"bu": p["code"], "name": p["name"], "submitted": False})
            continue
        out.append({
            "bu": p["code"], "name": p["name"], "submitted": True,
            "plan": r["plan_qty"], "act": r["actual_qty"], "ach": pct(r["actual_qty"], r["plan_qty"]),
            "oee": num(r["oee"]), "otd": pct(r["orders_on_time"], r["orders_due"]),
            "rej": r["customer_rej"], "att": pct(r["mp_present"], r["mp_required"]),
            "bd": num(r["breakdown_hrs"]), "nm": r["near_miss"], "fa": r["first_aid"], "lti": r["lti"],
            "remarks": r["remarks"] or "", "by": r["entered_by"],
            "at": r["updated_at"].strftime("%d %b %H:%M"),
        })
    return jsonify({"date": d.isoformat(), "rows": out})


# ------------------------------------------------------------------ escalations
@app.route("/escalations", methods=["GET", "POST"])
@login_required()
def escalations():
    u = request.user
    plants = visible_plants(u)
    codes = [p["code"] for p in plants]
    if request.method == "POST":
        action = request.form.get("action")
        if action == "raise":
            plant = request.form.get("plant_code") if u["role"] == "coo" else u["plant_code"]
            issue = request.form.get("issue", "").strip()[:255]
            if plant not in codes or not issue:
                flash("Choose a plant and describe the issue.", "bad")
            else:
                q("""INSERT INTO escalations (plant_code,area,issue,owner,severity,raised_on,raised_by)
                     VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                  (plant, request.form.get("area"), issue, request.form.get("owner", "").strip()[:100],
                   "Critical" if request.form.get("severity") == "Critical" else "High",
                   today(), u["username"]))
                flash("Escalation raised.", "good")
        elif action == "close":
            e = q("SELECT * FROM escalations WHERE id=%s", (request.form.get("id"),), one=True)
            if e and e["plant_code"] in codes and e["status"] == "Open":
                q("""UPDATE escalations SET status='Closed', closed_on=%s, closed_by=%s, closure_note=%s
                     WHERE id=%s""", (today(), u["username"],
                                      request.form.get("note", "").strip()[:255], e["id"]))
                flash("Escalation closed.", "good")
        return redirect(url_for("escalations"))

    ph = ",".join(["%s"] * len(codes))
    open_rows = q(f"""SELECT * FROM escalations WHERE status='Open' AND plant_code IN ({ph})
                      ORDER BY severity='Critical' DESC, raised_on""", codes)
    closed = q(f"""SELECT * FROM escalations WHERE status='Closed' AND plant_code IN ({ph})
                   ORDER BY closed_on DESC, id DESC LIMIT 20""", codes)
    for e in open_rows:
        e["days"] = (today() - e["raised_on"]).days
    return render_template("escalations.html", active="esc", plants=plants, open_rows=open_rows,
                           closed=closed, areas=AREAS)


# ------------------------------------------------------------------ COO settings
@app.route("/settings", methods=["GET", "POST"])
@login_required("coo")
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "targets":
            for k in TARGET_LABELS:
                try:
                    q("UPDATE kpi_targets SET value=%s WHERE kpi=%s", (float(request.form[k]), k))
                except (KeyError, ValueError):
                    pass
            flash("Targets saved.", "good")
        elif action == "plants":
            for p in q("SELECT code FROM plants"):
                c = p["code"]
                q("UPDATE plants SET name=%s, site=%s, head=%s, last_lti_date=%s WHERE code=%s",
                  (request.form.get(f"name_{c}", c).strip() or c, request.form.get(f"site_{c}", "").strip(),
                   request.form.get(f"head_{c}", "").strip(), parse_date(request.form.get(f"lti_{c}")), c))
            flash("Plant details saved.", "good")
        elif action == "reset_pw":
            new = request.form.get("new", "")
            if len(new) < 6:
                flash("New password must be at least 6 characters.", "bad")
            else:
                q("UPDATE users SET password_hash=%s WHERE id=%s",
                  (generate_password_hash(new), request.form.get("id")))
                flash("Password reset.", "good")
        elif action == "toggle":
            uid = int(request.form.get("id", 0))
            if uid != request.user["id"]:
                q("UPDATE users SET active=1-active WHERE id=%s", (uid,))
                flash("User status changed.", "good")
        return redirect(url_for("settings"))
    t = targets()
    return render_template("settings.html", active="set", targets=t, labels=TARGET_LABELS,
                           plants=q("SELECT * FROM plants ORDER BY sort_order, code"),
                           users=q("SELECT * FROM users ORDER BY role DESC, username"))


@app.errorhandler(403)
def forbidden(_):
    return render_template("message.html", title="Not allowed",
                           msg="Your login does not have access to this page."), 403


@app.errorhandler(pymysql.MySQLError)
def db_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Database error: {e}"}), 500
    return render_template("message.html", title="Database error", msg=str(e)), 500


if __name__ == "__main__":
    try:
        init_db()
    except pymysql.MySQLError as e:
        raise SystemExit(f"\n*** Could not connect to MySQL ***\n{e}\n"
                         f"Check MySQL is running and the user/password in app.py (DB_USER / DB_PASS).\n")
    print(f"Open http://127.0.0.1:{PORT}")
    # use_reloader=False keeps it stable when started from Thonny
    app.run(host="0.0.0.0", port=PORT, debug=True, use_reloader=False)
