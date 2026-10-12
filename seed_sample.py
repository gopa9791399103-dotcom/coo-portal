"""
OPTIONAL — fills daily_kpi with SAMPLE data (1 Apr to yesterday, Sundays off)
so you can see the dashboard working before BU heads start entering.

Run once in Thonny.  It does nothing if daily_kpi already has rows.
To remove sample data later, run in HeidiSQL:
    DELETE FROM coo_portal.daily_kpi WHERE entered_by='sample';
"""
import random
from datetime import date, timedelta

from app import get_db, init_db

PROFILE = {   # plan/day, OEE, OTD, PPM, attendance, breakdown h/day, 5S
    "BU1": (1750, 77, 96, 400, 93, 1.2, 85),
    "BU2": (1200, 69, 91, 620, 90, 2.0, 73),
    "BU3": (1020, 81, 98, 270, 95, 0.6, 90),
    "BU4": (1450, 74, 94, 500, 92, 1.5, 79),
}

init_db()
conn = get_db()
cur = conn.cursor()
cur.execute("SELECT COUNT(*) n FROM daily_kpi")
if cur.fetchone()["n"]:
    raise SystemExit("daily_kpi already has data — sample not loaded.")

today = date.today()
d = date(today.year if today.month >= 4 else today.year - 1, 4, 1)
rows = 0
random.seed(7)
while d < today:
    if d.weekday() != 6:
        for code, (plan, oee, otd, ppm, att, bd, s5) in PROFILE.items():
            act = int(plan * random.uniform(0.9, 1.04))
            due = random.randint(8, 14)
            mpr = random.randint(110, 140)
            cur.execute(
                """INSERT INTO daily_kpi (plant_code, entry_date, plan_qty, actual_qty, oee, orders_due,
                   orders_on_time, customer_rej, mp_required, mp_present, breakdown_hrs, near_miss, first_aid,
                   lti, s5_score, open_issues, remarks, entered_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'sample')""",
                (code, d, plan, act, round(oee + random.uniform(-4, 4), 1), due,
                 min(due, round(due * otd / 100 + random.uniform(-1, 1))),
                 round(act * ppm / 1e6 * random.uniform(0.3, 1.8)),
                 mpr, round(mpr * (att + random.uniform(-3, 3)) / 100),
                 round(max(0, bd + random.uniform(-1, 1.5)), 1),
                 random.choice([0, 0, 0, 1, 1, 2]), random.choice([0] * 12 + [1]),
                 1 if random.random() < 0.003 else 0,
                 round(s5 + random.uniform(-4, 4), 1) if d.weekday() == 4 else None,
                 random.randint(3, 16), "", ))
            rows += 1
    d += timedelta(days=1)
conn.commit()
conn.close()
print(f"Loaded {rows} sample daily rows.")
