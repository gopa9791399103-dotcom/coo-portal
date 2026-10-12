COO PLANT PERFORMANCE BOARD  -  setup
=====================================

1. Install packages (once)
   Command Prompt:  pip install flask pymysql
   (or Thonny: Tools > Manage packages > flask, pymysql)

2. Check DB login at the top of app.py
   DB_USER = root, DB_PASS = Mokshita@123, DB_HOST = localhost
   The database "coo_portal" and all tables are created automatically.
   No SQL script to run.

3. Run app.py in Thonny  ->  open http://127.0.0.1:5011
   Other PCs on LAN: http://<this-PC-IP>:5011  (allow port 5011 in Windows Firewall)

4. Logins created on first run  (CHANGE PASSWORDS after first login)
     coo / Coo@123     COO - all plants, daily status, escalations, settings
     bu1 / Bu1@123     BU1 head - daily entry + own dashboard
     bu2 / Bu2@123     BU2 head
     bu3 / Bu3@123     BU3 head
     bu4 / Bu4@123     BU4 head

5. OPTIONAL sample data to test the dashboard:  run seed_sample.py once
   Remove it later in HeidiSQL:
     DELETE FROM coo_portal.daily_kpi WHERE entered_by='sample';

Rules
 - BU heads can enter / correct today and the previous 3 days (EDIT_DAYS in app.py).
 - One entry per plant per day; saving again updates it.
 - Monthly figures on the dashboard are calculated from daily entries:
     Achievement = sum actual / sum plan     OTD = on-time / due
     PPM = customer rej / actual x 1,000,000  Attendance = present / required
     OEE, 5S = average of entered days       Breakdown, safety = totals
     Open issues = latest entered count in the month
 - Plant names, targets, passwords: COO > Settings.

Tables (database coo_portal)
 plants, users, daily_kpi, kpi_targets, escalations


PUBLIC HOSTING ON RAILWAY  (same way as your other apps)
=========================================================
A. Put the code on GitHub
   cd D:\IOT\coo_portal
   git init
   git add .
   git commit -m "COO portal"
   (create an empty repo "coo-portal" on github.com, then)
   git remote add origin https://github.com/<you>/coo-portal.git
   git branch -M main
   git push -u origin main

B. Railway (railway.app)
   1. New Project > Deploy from GitHub repo > coo-portal
   2. In the same project: + New > Database > MySQL
   3. Click the coo-portal service > Variables > add these 6:
        MYSQLHOST      = ${{MySQL.MYSQLHOST}}
        MYSQLPORT      = ${{MySQL.MYSQLPORT}}
        MYSQLUSER      = ${{MySQL.MYSQLUSER}}
        MYSQLPASSWORD  = ${{MySQL.MYSQLPASSWORD}}
        MYSQLDATABASE  = ${{MySQL.MYSQLDATABASE}}
        SECRET_KEY     = any long random text, e.g. scavp-coo-8f3k29xq7m
   4. coo-portal service > Settings > Networking > Generate Domain
   5. Open the link > log in coo / Coo@123 > change all passwords
      (Settings page resets BU passwords)

   Tables and logins are created automatically on first start.
   Later changes:  git add . ; git commit -m "change" ; git push   -> Railway redeploys.

   The online database is separate from your PC database.
   Do NOT run seed_sample.py online.
