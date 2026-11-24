==============================================================================
 OFFICE RECORD PORTAL  -  PROJECT GUIDE
 Flask + SQLite, running in Docker on an Ubuntu server
==============================================================================

 CONTENTS
   1.  What this portal does
   2.  Quick start on Ubuntu with Docker
   3.  Which file does what (file map)
   4.  How the files are connected
   5.  The most important files
   6.  How to change the logo and the company name
   7.  Where the data is stored
   8.  Daily administration (users, departments, columns, sharing)
   9.  Backup, export to another machine, restore, and cron
  10.  Changing code and updating the portal
  11.  Common errors and how to troubleshoot them
  12.  Security notes and limits
  13.  New in this version: features guide (roles, public QR, language ...)
  14.  HTTPS (secure connection)
  15.  Virus scanning of attachments
  16.  Idle timeout, sessions and login protection


==============================================================================
 1. WHAT THIS PORTAL DOES
==============================================================================
 Employees open  http://SERVER-IP:PORT  in a browser, log in with username,
 password and department, and keep their records in one central database.

   - Login with department. The admin creates all accounts (or imports a CSV).
   - Roles: Admin (sees and manages everything) and User.
   - Departments, each with its own record columns defined by the admin.
     Suggested starter columns exist for IT, HR & Admin, Billing & Revenue,
     Sales & Marketing, Technical, Accounts and Management.
   - Column types: text, long text, number, date, dropdown list, yes/no.
   - "Protect from accidental delete" on each column. A protected column cannot
     be removed until the admin clicks "Remove protection".
   - Removing a column hides it and keeps its data. It can be restored, or
     erased for good (an automatic backup is made first).
   - Sharing: the owner shares a record with a whole department OR with one chosen
     person, and picks "Can edit" or "View only" for each (section 18). Only the
     owner and the admin can delete or change sharing.
   - Edit history on every record: who changed what, when, old and new value.
   - Two people editing at once: the second save is refused with a clear
     message, so nothing is silently overwritten.
   - Recycle bin: deleted records can be restored for 30 days.
   - Reminders: any number of date columns per department (for example Warranty end
     date, Meeting) drive the reminder list, the dashboard and the bell messages
     (see section 17).
   - Repair log per record, only in departments where the admin switched it on.
   - Public QR codes with a unique random code under each (HRC-#####, for example HRC-48392), see sections 19 and 20.
   - Invoices: dept-admin invoice templates, employee invoices, PDF/print, public QR, see section 20.
   - Optional file attachments, switched on per department with a size limit.
   - CSV download (users: their own records; admin: everything, filterable).
   - Admin dashboard, activity log (with IP addresses), settings (company name, logo).
   - NEW in this version (see section 13): public QR codes, change of owner by
     admins, comments and suggestions, notifications, bulk actions,
     Excel and PDF exports and reports, filters and sorting,
     light/dark mode, department admins, view-only access to other departments,
     HTTPS, password re-entry, login protection, idle timeout, virus scanning,
     and a mobile-friendly layout.


==============================================================================
 2. QUICK START ON UBUNTU WITH DOCKER
==============================================================================
 Step 1  Install Docker (once)
         curl -fsSL https://get.docker.com | sudo sh
         sudo systemctl enable --now docker
         sudo usermod -aG docker $USER      (log out and log in again)
         docker compose version             (must print a version)

 Step 2  Copy the project to the server and open the folder
         unzip inventory-portal-docker.zip
         cd inventory-portal

 Step 3  Set the port and time zone
         nano .env
            PORTAL_PORT=8000          port employees type in the browser
            TZ=Asia/Dhaka             your time zone

 Step 4  Start the portal
         docker compose up -d --build
         docker compose ps             (STATUS should become "healthy")

 Step 5  Open the port in the firewall (use your port number)
         sudo ufw allow 8000/tcp
         sudo ufw status

 Step 6  First login (from any PC on the network)
         http://SERVER-IP:8000
            Username:   admin
            Password:   ChangeMe@123
            Department: All departments (admin only)
         The portal forces a new password immediately.

 Step 7  Set up (as admin)
         Departments  -> create each department (pick its starter template)
         Users        -> add users, or "Import users" with a CSV (200 at once)
         Settings     -> company name and logo

 The data survives restarts: Docker starts at boot and the container has
 "restart: unless-stopped". Test it once with:  sudo reboot


==============================================================================
 3. WHICH FILE DOES WHAT  (file map)
==============================================================================
 Format:  FILE - purpose.  [Uses: files it needs]  [Used by: files that need it]

 --- Python program files (project folder) -----------------------------------

 app.py            Starts the portal. Creates the Flask app, upgrades/creates the
                   database, registers all page files, checks the login and the
                   security token on every request, adds the logo and company
                   name to every page, hourly clean-up of the recycle bin.
                   [Uses: every .py file below]  [Used by: Dockerfile (waitress)]

 config.py         All settings: data folders, default admin, session time,
                   login lock, recycle bin days, attachment limits.
                   [Used by: almost every .py file]

 models.py         The database: table definitions (schema), connection with safe
                   settings (WAL), automatic upgrade of older databases, import
                   of old "equipment" data, activity log helper.
                   [Uses: config.py, core.py]  [Used by: app.py, core.py, routes]

 core.py           The business rules: columns, permission checks (owner / shared
                   / admin), reading and saving record values, edit history,
                   conflict check for simultaneous edits, recycle bin, department
                   creation, reminders, CSV building.
                   [Uses: models.py, templates_data.py, utils.py, config.py]
                   [Used by: routes_records.py, routes_admin.py, import_users.py]

 auth.py           Login with department, logout, change password, wrong-password
                   lock, and the login_required / admin_required guards.
                   [Uses: models.py, config.py]  [Used by: app.py, route files]

 routes_records.py Pages every user sees: record list, add/edit, detail page,
                   sharing, repair log, attachments, recycle bin, reminders,
                   change of owner, own CSV download.
                   [Uses: core.py, auth.py, models.py, utils.py]
                   [Templates: records_list, record_form, record_detail, bin,
                    reminders, qr_label]

 routes_admin.py   Admin-only pages: dashboard, all records, users, departments,
                   record columns (add, edit, order, protect, remove, restore,
                   erase), attachment settings, user import, activity log,
                   settings (company name, logo).
                   [Uses: core.py, auth.py, backup.py, branding.py,
                    import_users.py, routes_records.py (QR codes)]
                   [Templates: all admin_*.html]

 branding.py       Serves the logo and the browser-tab icon. Picks the logo that
                   was uploaded in Settings, otherwise static/logo.png.
                   [Used by: app.py, routes_admin.py, base.html]

 templates_data.py The suggested starter columns of the 7 departments.
                   [Used by: core.py, import_users.py, routes_admin.py]
                   Edit this file to change the suggested columns.

 utils.py          Small helpers: CSV download (safe for Excel), random password,
                   search escaping, paging.
                   [Used by: core.py, routes, import_users.py]

 import_users.py   Creates many users from a CSV file (also usable from the
                   command line).
                   [Uses: core.py, templates_data.py]  [Used by: routes_admin.py]

 backup.py         Makes a safe database backup (works while the portal runs,
                   keeps the newest 30). Also used for the automatic backup
                   before a column is erased for good.
                   [Used by: backup.sh, routes_admin.py]

 reset_admin.py    Emergency tool: new temporary password for the admin.
                   docker compose exec portal python reset_admin.py

 --- NEW program files in this version ---------------------------------------

 routes_workflow.py  Notifications, comments/suggestions, reminder-days setting.
                   [Uses: core.py, routes_records.py]  [Templates: notifications]
 routes_deptdb.py  The DEPARTMENT DATABASE (section 19): columns, rows, access,
                   export. [Uses: core.py]  [Templates: deptdb, deptdb_form,
                    deptdb_row, deptdb_columns, deptdb_column_edit, deptdb_people]
 routes_public.py  Public QR links: the public page /p/<token>, the code search
                   page /code/HRC-n (+ PDF), the switch on a record, group QR for
                   many records, the QR print page.
 routes_invoices.py Invoices (section 20): dept-admin templates, employee invoices,
                   invoice PDF, public QR with HRC-##### code, template sharing and
                   department invoice sharing. [Templates: invoice_*.html]
                   [Uses: core.py, routes_records.py]  [Templates: public_view,
                    public_message, public_links, public_link_form]
 routes_bulk.py    Bulk actions on ticked records, Excel/PDF exports, reports,
                   the clean record PDF.
                   [Uses: core.py, exports.py, routes_records.py, routes_admin.py]
 security.py       Login attempt locks (username and IP address), sessions with the
                   30-minute idle timeout, password rules, password re-entry.
                   [Used by: auth.py, app.py, routes_admin.py, import_users.py]
 scanner.py        Talks to the ClamAV container to scan uploaded files.
                   [Used by: routes_records.py]
 exports.py        Builds the formatted Excel (.xlsx) and PDF files.
                   [Uses: openpyxl, reportlab, static/fonts]  [Used by: routes_bulk.py]
 Caddyfile         Settings of the HTTPS front door.   certs/  your own certificate.

 CHANGED program files: app.py (sessions, idle timeout, language/theme, HTTPS proxy
 headers), models.py (new tables), core.py (department admin and view-only access,
 notifications, sorting, public links), auth.py (login protection),
 routes_records.py (new access levels, comments, public QR panel, virus scan),
 routes_admin.py (roles, password re-entry, sessions page, IP in the log),
 import_users.py and utils.py (password rules), style.css (mobile, dark mode).

 --- Scripts and Docker files -------------------------------------------------

 backup.sh         Backup of database and attachments to ./backups-copy and,
                   if configured, to another machine. Run by hand or by cron.
                   [Uses: backup.py (inside the container), backup.conf]

 backup.conf       Optional settings for backup.sh (remote machine address).

 Dockerfile        How the container image is built (Python, packages, waitress).
 docker-compose.yml How the container runs: port, time zone, the data volume
                   "portal_data", automatic restart.  [Reads: .env]
 .env              Port, time zone, HTTPS flag - the settings you change most.
 .dockerignore     Files that must not be copied into the image.
 requirements.txt  Python packages: Flask, waitress, segno (QR codes).
 README.txt        This guide.

 --- Pages (folder templates/) -----------------------------------------------
 base.html            Frame of every page: logo, menu, messages, print header.
 _macros.html         Reusable pieces: record tables, paging, history lines.
 login.html           Login page.            change_password.html  Password page.
 error.html           Error page (403, 404 ...).
 records_list.html    My records / shared tabs.   record_form.html  Add / edit.
 record_detail.html   One record: details, repairs (if on), files, sharing, history, public QR.
 bin.html             Recycle bin.           reminders.html   Reminder lists.
 qr_label.html        Printable public QR codes (with the HRC code).
 admin_dashboard.html, admin_records.html, admin_users.html,
 admin_user_form.html, admin_departments.html, admin_columns.html,
 admin_column_edit.html, admin_removed_columns.html, admin_import.html,
 admin_import_result.html, admin_activity.html, admin_settings.html

 --- Look and files (folder static/) -----------------------------------------
 style.css            All colours, fonts, layout, animations and print styles.
 logo.png             DEFAULT logo (login page, menu, printouts, QR codes).
 favicon.png          DEFAULT browser-tab icon.
 users_template.csv   Sample file for "Import users".
 fonts/               The bundled font (works without internet).

 --- Data (NOT in the project folder: inside the Docker volume "portal_data") --
 portal.db            The database (users, departments, columns, records ...).
 portal.db-wal / -shm Recent saves not yet merged into portal.db. Normal.
 secret.key           Keeps login sessions valid. Do not share it.
 uploads/             Attachment files, one folder per record.
 branding/            Logo uploaded in Settings.
 backups/             Database backups made by backup.py.


==============================================================================
 4. HOW THE FILES ARE CONNECTED
==============================================================================

   Employee browser
         |  http://SERVER-IP:PORT
         v
   docker-compose.yml (port from .env)  -->  Dockerfile starts waitress
         v
   app.py  -------------------------------------------------------------+
     |  registers                                                        |
     +--> auth.py ............ login, logout, password                   |
     +--> routes_records.py .. user pages                                |
     +--> routes_admin.py .... admin pages                               |
     +--> branding.py ........ logo, icon                                |
     |                                                                   |
     |   routes_*.py  --> core.py (rules) --> models.py --> portal.db    |
     |   routes_*.py  --> templates/*.html --> static/style.css          |
     |   core.py      --> templates_data.py (starter columns)            |
     +--> config.py (settings used by all) <-----------------------------+

 Example: an employee saves a record.
   record_form.html -> routes_records.py (edit_record) -> core.parse_form
   (checks values) -> core.update_record (version check, writes values and
   history) -> models.py connection -> portal.db -> back to the detail page.


==============================================================================
 5. THE MOST IMPORTANT FILES
==============================================================================
 1. The data volume "portal_data" (especially portal.db). It holds all your
    data. Back it up (section 9). Never run "docker compose down -v".
 2. app.py       - connects everything. If it has an error, nothing starts.
 3. core.py      - all rules about records, columns, sharing and permissions.
 4. models.py    - the database structure. Be careful when editing the tables.
 5. .env and docker-compose.yml - port, time zone, data volume, auto restart.
 6. backup.sh    - your protection against disk failure.
 Everything else (templates, style.css, logo) is appearance and is safe to
 change.


==============================================================================
 6. HOW TO CHANGE THE LOGO AND THE COMPANY NAME
==============================================================================
 METHOD A - from the portal (no restart, no rebuild)   <- recommended
   1. Log in as admin, open  Settings.
   2. Under "Logo" choose a PNG, JPG or WEBP file (max 2 MB) and click
      "Upload logo".  A wide picture with a transparent background works best.
   3. Press Ctrl+F5 in the browser if the old logo still shows.
   The new logo appears on the login page, every page, the browser tab, QR
   labels and printouts. "Use the default logo" brings the original back.
   The company name is changed on the same page.

 METHOD B - replace the default logo files (needs a rebuild)
   1. Replace static/logo.png (the main logo, about 900 px wide) and
      static/favicon.png (small square icon, 128 x 128 px). Keep the names.
   2. Rebuild:  docker compose up -d --build
   A logo uploaded in Settings (Method A) overrides these files.

 CHANGE THE COLOURS: open static/style.css; the colours are at the top
   (--accent, --cyan, --ink). Then rebuild (section 10).


==============================================================================
 7. WHERE THE DATA IS STORED
==============================================================================
 All data is in the Docker volume "portal_data", mounted at /data inside the
 container. On Ubuntu it normally lives here (needs sudo to open):
      /var/lib/docker/volumes/inventory-portal_portal_data/_data
 Find the exact path:
      docker volume inspect inventory-portal_portal_data
 Look inside:
      docker compose exec portal ls -lh /data

 Do not copy or edit portal.db by hand while the portal runs. Use backup.sh.
 Read a database safely: take a backup (section 9) and open the copy in
 "DB Browser for SQLite" on your own PC.

 Space needed (200 users): database about 100-150 MB after 1 year. Attachments
 are the only thing that can grow large (about 2-10 GB per year depending on
 use). Keep 100 GB free to be comfortable.


==============================================================================
 8. DAILY ADMINISTRATION
==============================================================================
 ADD A DEPARTMENT   Admin > Departments > pick a template (or "Start blank"),
                    untick the suggested columns you do not need, create.
 RECORD COLUMNS     Admin > Departments > Columns.
                    Add: name, type, dropdown options, required, protect,
                    reminder date. Use the arrows to change the order.
                    Remove: click Remove, type the column name to confirm. Data
                    is kept in "Removed columns" (restore, or erase for good).
                    Protected column: no Remove button. Click "Remove
                    protection" first, then remove it.
 ATTACHMENTS        Admin > Departments > Columns > "File attachments": switch
                    on for that department and set the max size per file.
 USERS              Admin > Users: add, edit department/role, disable, reset
                    password. Import 200 users: Admin > Import users.
 MOVING A USER      Changing a user's department does not move old records;
                    they stay in the department where they were created.
 REMINDERS          Mark any number of date columns per department as "Reminder date"
                    (section 17 explains the bell messages and the time field).
 RECYCLE BIN        Owner or admin can restore, or "Delete forever". Items are
                    erased automatically after 30 days (config.py: BIN_DAYS).
 ACTIVITY LOG       Admin > Activity (last 300 actions; kept for 2 years).


==============================================================================
 9. BACKUP, EXPORT TO ANOTHER MACHINE, RESTORE, AND CRON
==============================================================================
 A Docker volume protects you from crashes and restarts, NOT from a failed
 disk or a deleted volume. Keep backups, and keep a copy on another machine.

 9.1  TAKE A BACKUP BY HAND
      cd inventory-portal
      chmod +x backup.sh                (first time only)
      ./backup.sh
      Result:  ./backups-copy/db/portal_YYYYMMDD_HHMMSS.db   (database)
               ./backups-copy/uploads/                        (attachments)
      The database backup is safe while employees are working and contains
      every entry saved up to that moment. Check:  ls -lh backups-copy/db

 9.2  AUTOMATIC BACKUP WITH CRON
      Use the root crontab so cron can use Docker.
        sudo crontab -e
      Add these lines at the end (replace the path with the output of "pwd"
      inside the project folder):

        PATH=/usr/local/bin:/usr/bin:/bin
        # every night at 02:00
        0 2 * * * /home/ubuntu/inventory-portal/backup.sh >> /var/log/portal-backup.log 2>&1

      More often (every hour, on the hour):
        0 * * * * /home/ubuntu/inventory-portal/backup.sh >> /var/log/portal-backup.log 2>&1

      Check that cron has it:   sudo crontab -l
      Check the result:         tail -n 20 /var/log/portal-backup.log
      (The .log file only holds the messages of the job. The real backups are
       the .db files in backups-copy/db.)

 9.3  EXPORT BACKUPS TO ANOTHER MACHINE AUTOMATICALLY
      Needs an SSH login to the other machine ("backup server").
      On BOTH machines:   sudo apt install -y rsync
      On the backup server, create the folder:
        mkdir -p /srv/backups/inventory-portal
      On the portal server (as root, because cron runs as root):
        sudo ssh-keygen -t ed25519 -f /root/.ssh/portal_backup_key -N ""
        sudo ssh-copy-id -i /root/.ssh/portal_backup_key.pub backupuser@192.168.1.50
        sudo ssh -i /root/.ssh/portal_backup_key backupuser@192.168.1.50 exit
            (the last command accepts the host key once; it must not ask for a
             password)
      Edit backup.conf in the project folder:
        REMOTE_TARGET=backupuser@192.168.1.50:/srv/backups/inventory-portal
        SSH_OPTIONS="-i /root/.ssh/portal_backup_key"
      Test:  sudo ./backup.sh     (last line must say "backup finished")
      From now on every run of backup.sh (and the cron job) also copies
      everything to the other machine. Old files are never deleted there.

      One-time manual copy instead (from the portal server):
        scp -r backups-copy backupuser@192.168.1.50:/srv/backups/inventory-portal/
      Or pull it to your own PC:
        scp -r user@SERVER-IP:/home/ubuntu/inventory-portal/backups-copy .

 9.4  RESTORE A BACKUP (same server, or a new server)
      On a new server first do section 2 (steps 1-4) so the container exists.
      Then, in the project folder (replace the file name):

        docker compose stop portal
        docker compose cp backups-copy/db/portal_20261027_020000.db portal:/data/portal.db
        docker compose cp backups-copy/uploads/. portal:/data/uploads/
        docker compose run --rm -u root --entrypoint sh portal -c \
          "chown -R portal /data/portal.db /data/uploads; rm -f /data/portal.db-wal /data/portal.db-shm"
        docker compose up -d

      The chown line matters: without it you get "attempt to write a readonly
      database". Restoring REPLACES all current data with the backup.

 9.5  MOVE THE PORTAL TO ANOTHER SERVER
      1. On the old server:  ./backup.sh
      2. Copy the project folder (with .env) and backups-copy to the new server.
      3. On the new server follow section 2 steps 1-4, then section 9.4.
      4. Employees use the new IP (or move the old IP to the new server).


==============================================================================
 10. CHANGING CODE AND UPDATING THE PORTAL
==============================================================================
 The code and templates are copied INTO the image when it is built. So:

   Changed .py, .html, .css, logo files, requirements.txt, Dockerfile:
        docker compose up -d --build
   Changed only .env:
        docker compose up -d
   Plain "docker compose up -d" after a code change keeps running the OLD code.

 Your data is not touched by a rebuild (it lives in the volume). Before any
 update run ./backup.sh. The database upgrades itself on start: missing tables
 and columns are added and old data is kept. Press Ctrl+F5 in the browser to
 load a new style.css.

 Read what the portal is saying:   docker compose logs --tail 100
 Follow live:                      docker compose logs -f
 Start / stop / restart:           docker compose up -d | down | restart
 Status:                           docker compose ps
 NEVER:                            docker compose down -v   (deletes the data)

 Run without Docker (testing only):
     pip install -r requirements.txt  &&  python app.py   (http://127.0.0.1:8000)


==============================================================================
 11. COMMON ERRORS AND HOW TO TROUBLESHOOT THEM
==============================================================================
 First look at:  docker compose ps   and   docker compose logs --tail 100

 PROBLEM : Other PCs cannot open http://SERVER-IP:8000
 CAUSE   : Firewall, wrong IP/port, or container not running.
 FIX     : docker compose ps (running and healthy?). sudo ufw allow 8000/tcp.
           Use the port from .env. Test on the server: curl -I http://localhost:8000/login
           Check the PC is in the same network (ping SERVER-IP).

 PROBLEM : "permission denied while trying to connect to the Docker daemon"
 CAUSE   : Your user is not allowed to use Docker.
 FIX     : sudo usermod -aG docker $USER, log out and in again (or use sudo).

 PROBLEM : "port is already allocated" / "address already in use"
 CAUSE   : Another program uses that port.
 FIX     : Change PORTAL_PORT in .env, then docker compose up -d.
           Who uses it:  sudo ss -ltnp | grep 8000

 PROBLEM : Container keeps restarting or shows "unhealthy"
 CAUSE   : An error at start (often a typo after a code change).
 FIX     : docker compose logs --tail 100 and read the last lines. Fix the file,
           then docker compose up -d --build. If it started working before, restore
           the previous file.

 PROBLEM : I changed a file but nothing changed
 CAUSE   : The image was not rebuilt, or the browser cached the page.
 FIX     : docker compose up -d --build, then Ctrl+F5.

 PROBLEM : "This page has expired" (error 400) after pressing Save or Login
 CAUSE   : The page stayed open too long, cookies are blocked, or PORTAL_HTTPS=1
           while the portal is opened over plain http.
 FIX     : Refresh the page and try again. Set PORTAL_HTTPS=0 in .env (unless you
           really use HTTPS) and run docker compose up -d.

 PROBLEM : "Too many wrong attempts"
 CAUSE   : 5 wrong passwords for that username (lock for 5 minutes). The lock is saved
           in the database, so restarting the container does not remove it.
 FIX     : Wait 5 minutes.

 PROBLEM : The admin forgot the password
 FIX     : docker compose exec portal python reset_admin.py
           (prints a temporary password; to reset another user add the username)

 PROBLEM : A user cannot log in although the password is right
 CAUSE   : Wrong department chosen (normal users must pick their own), or the
           account is disabled.
 FIX     : Admin > Users: check the department and that the account is active.

 PROBLEM : A user cannot see a colleague's record
 CAUSE   : Records are private to their owner. Others see them only when the
           owner shares them with their department or with that person.
 FIX     : The owner opens the record and shares it under "Shared with" (a whole
           department, or "Add a person").

 PROBLEM : "Your changes were NOT saved" while editing
 CAUSE   : Someone else saved the same record first (protection against
           overwriting).
 FIX     : The page shows the latest values and your own entries. Apply your
           change again and save.

 PROBLEM : A column has no Remove button
 CAUSE   : It is protected against accidental delete.
 FIX     : Click "Remove protection" on that column, then Remove.

 PROBLEM : Times are wrong (hours off)
 FIX     : Set TZ in .env (for example Asia/Dhaka), docker compose up -d.

 PROBLEM : Upload fails or "file type is not allowed"
 CAUSE   : Attachments are off for the department, the file is bigger than the
           department limit (server maximum 25 MB), or the type is blocked
           (programs and scripts are always blocked).
 FIX     : Admin > Departments > Columns > File attachments.
           Allowed: pdf, jpg, png, gif, webp, txt, csv, doc(x), xls(x), ppt(x).

 PROBLEM : The new logo does not show
 FIX     : Ctrl+F5. The file must be PNG, JPG or WEBP and under 2 MB.

 PROBLEM : "attempt to write a readonly database"
 CAUSE   : Restored file belongs to root instead of the portal user.
 FIX     : Run the chown command of section 9.4, then docker compose up -d.

 PROBLEM : "database is locked"
 CAUSE   : Rare. Another program has the database open, or the disk is full/slow.
 FIX     : Do not open portal.db by hand. df -h to check space. docker compose restart.

 PROBLEM : Disk is full
 FIX     : df -h and docker system df. Remove old copies in backups-copy, run
           docker image prune, check the size of attachments. Add disk space.

 PROBLEM : Cron backup does not run
 FIX     : sudo crontab -l (is the line there?). Use the FULL path to backup.sh.
           chmod +x backup.sh. Put "PATH=/usr/local/bin:/usr/bin:/bin" above the
           line (cron has a short PATH and may not find docker). Read
           /var/log/portal-backup.log. Test by hand with: sudo ./backup.sh

 PROBLEM : Copy to the other machine fails
 CAUSE/FIX: "rsync: command not found"  -> sudo apt install rsync on both machines.
           "Permission denied (publickey)" -> repeat ssh-copy-id (section 9.3).
           "Host key verification failed" -> run the ssh test command once by hand.
           "No such file or directory" -> create the folder on the backup server.

 PROBLEM : docker compose up --build fails while downloading packages
 CAUSE   : The server has no internet access during the build.
 FIX     : Allow internet for the build, or build the image on another machine
           (docker save / docker load).

 PROBLEM : "container name /inventory-portal is already in use"
 FIX     : docker compose down (keeps the data), then docker compose up -d.


==============================================================================
 12. SECURITY NOTES AND LIMITS
==============================================================================
 - Passwords are stored hashed. Admin-created temporary passwords must be
   changed at first login. Five wrong attempts lock a user for five minutes.
 - Every form has a security token (CSRF). Uploaded files get random names, only
   safe types are accepted, and files are always downloaded, never executed.
 - By default the portal uses plain HTTP (fine inside a trusted office network).
   Turn on HTTPS as described in section 14. Never open the port to the internet.
 - SQLite is enough for about 200 users (WAL mode, 8 server threads). If
   the company grows to many hundreds of users saving constantly, move to
   MySQL or PostgreSQL later (the data can be migrated).
 - Keep the volume on a local SSD, not on a network share.
 - Keep backups on another machine. A backup you never tested is not a backup:
   try a restore on a spare machine once.


==============================================================================
 13. NEW IN THIS VERSION: FEATURES GUIDE
==============================================================================
 PUBLIC QR (anyone can scan, no login)
   One record: open the record > "Public QR" box > tick the fields to show >
   "Create public QR". Print the QR from the same box.
   Many records, one QR: in the list tick the records > "Public QR" > give a title,
   tick the fields > create.
   Safety: the link contains a long random code that cannot be guessed; only the
   ticked fields are shown (never history, files, costs unless ticked, or owner
   names); "Turn off" stops it at once; "New code" makes old printed QR codes useless;
   one computer may open at most 60 public pages per minute; search engines are
   told not to index it. Manage all links: More > Public QR links.
   A logged-in person who may open the record is taken to the full record instead.
   The old login-only "QR label" no longer exists: only public QR codes remain.

 ROLES AND PERMISSIONS
   Admin               everything.
   User                own records, records shared with them or with their department.
   Department admin    (set per user: Admin > Users > Edit) sees EVERY record of
                       their department in the tab "My department", can write
                       suggestions, can run reports of the department, can CHANGE THE
                       OWNER of the department's records and is the manager of the
                       department database. Cannot edit others' records.
   View other          (set per user: "Can also view these departments") sees the
   departments         records of those departments in the tab "Other departments"
                       and can write suggestions. Cannot edit.
   Every user can always add and edit their OWN records.
   Suggestions appear on the record with a "Suggestion" label; the owner gets a
   notification. They are separate from the edit history.

 CHANGE OF OWNER   Record page > "Change owner" (only the portal admin and the department
   admin of the record's department see it). The admin may choose anybody; a department
   admin a member of the same department. It takes effect at once, is written in the edit
   history, and the old and new owner get a bell message. (Hand over and Requests were removed.)

 NOTIFICATIONS   The bell in the top bar: shares, comments, suggestions,
   replaced files, owner changes, blocked viruses (admin) and the reminder messages (section 17).

 BULK ACTIONS   Tick records in a list. A bar appears: Share with, Public QR,
   Excel, PDF, CSV, Delete (recycle bin). Actions that change records work only on
   records you own (or all, as admin).

 EXCEL AND PDF   Lists: "Export" button. One record: "PDF" button, then tick the fields
   you want (only fields, never history or repair log). Reports page (admin and department admins): all records, reminders,
   open repairs, summary, and activity log (admin). Excel files have a styled header,
   filters, frozen header, real numbers; PDF files have the logo and page numbers.
   PDF prints English and European letters; other letters print as ? in PDF, Excel keeps them.

 SORTING AND FILTERS   In a list: search, "Filter by column", "Sort" and direction.

 LOOK   Click your name (top right) > Appearance: Auto / Light / Dark. Saved per
   user. The login page has the same switch.

 PHONES   On a phone the menu becomes a button, tables become cards, forms use one
   column. The Windows and Android apps show the same pages.

 DANGEROUS ACTIONS NEED YOUR PASSWORD   Reset a user's password, change a role or
   disable an account, remove/erase a column, remove protection, remove a department.
   The admin types the own password once; for the next 5 minutes it is not asked again.

 PASSWORD RULES   At least 8 characters with letters and numbers, not equal to the
   username. Temporary passwords made by the portal follow the same rule.

 ACTIVITY LOG WITH IP ADDRESS   Admin > Activity shows the IP address of each action,
   including failed logins. Search by IP is possible.


==============================================================================
 14. HTTPS (SECURE CONNECTION)
==============================================================================
 Why: with plain http, passwords can be read by someone on the network.
 How it works: a "caddy" container accepts https and passes the request to the portal.

 STEP 1  Choose how the certificate is made (edit .env):
   A) Built-in (easy):          TLS_ARGS=internal
      Browsers will show a warning until the PCs trust Caddy's own certificate
      authority. Install it once on each PC (or by Group Policy: Trusted Root
      Certification Authorities):
         docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./portal-root.crt
   B) Your own certificate (best, for example from your Windows CA):
         copy portal.crt and portal.key into the folder  certs/
         TLS_ARGS=/certs/portal.crt /certs/portal.key
      The certificate must be issued for the name in PORTAL_HOST.
 STEP 2  Edit .env:
         COMPOSE_PROFILES=https
         PORTAL_HTTPS=1
         PORTAL_BEHIND_PROXY=1
         PORTAL_BIND=127.0.0.1
         PORTAL_HOST=portal.hrctech.net       (the name people type)
         HTTPS_PORT=443
 STEP 3  Start:   docker compose up -d --build
 STEP 4  Open the firewall for the https port and CLOSE the old http port:
         sudo ufw allow 443/tcp
         sudo ufw delete allow 8000/tcp
 STEP 5  Employees open  https://portal.hrctech.net   (the old http address stops working).
 The portal then also sends the HSTS header and marks the login cookie Secure, and it
 sees each computer's real IP address in the activity log.
 Going back to http: set COMPOSE_PROFILES= and the 3 values to 0 / 0 / 0.0.0.0.
 Windows app: works with a certificate trusted by Windows. Android app: phones must
 trust the certificate (install the CA on the phone, or use a public certificate).


==============================================================================
 15. VIRUS SCANNING OF ATTACHMENTS
==============================================================================
 Every uploaded file can be checked by ClamAV before it is stored. A file with a virus
 is refused, the admin gets a notification and the activity log shows "virus_blocked".
 If the scanner is switched on but not reachable, uploads are refused (safe default).
 Needs about 2 GB of RAM for the scanner. The first start downloads the virus database
 (a few minutes, internet needed). The database updates itself every day.
   Edit .env:   COMPOSE_PROFILES=scan          (or  https,scan  for both)
                CLAMAV_HOST=clamav
   Start:       docker compose up -d --build
   Check:       docker compose ps      (clamav must say "healthy")
                docker compose logs clamav --tail 20
   Test (harmless test file): save the 68-character EICAR test string from
   eicar.org as a .txt file and upload it; it must be refused.
 Turn it off: leave CLAMAV_HOST empty and remove "scan" from COMPOSE_PROFILES.


==============================================================================
 16. IDLE TIMEOUT, SESSIONS AND LOGIN PROTECTION
==============================================================================
 - A login ends after 30 minutes without activity (config.py: IDLE_MINUTES) and
   after 8 hours at most (SESSION_HOURS). The person sees a message at the next login.
 - Admin > More > Sessions lists everybody logged in with IP address and browser. The
   admin can end a session. Disabling a user or resetting a password ends their sessions.
   Changing your own password ends your other sessions.
 - 5 wrong passwords for one username lock that username for 5 minutes. 20 wrong
   passwords from one computer block that computer for 10 minutes. Every attempt is
   saved with its IP address (Admin > Activity, actions login_failed / login_blocked).
 - The numbers can be changed in config.py (MAX_FAILED, LOCK_MINUTES, IP_MAX_FAILED ...).
   After a change run: docker compose up -d --build


==============================================================================
 MORE COMMON ERRORS (new features)
==============================================================================
 PROBLEM : "You were logged out because of inactivity"
 FIX     : Normal after 30 minutes without clicking. Log in again.

 PROBLEM : Everybody gets logged out after an update
 CAUSE   : Normal if secret.key was lost, or sessions were ended on purpose.
 FIX     : Log in again. Keep the data volume so secret.key stays.

 PROBLEM : "Too many failed logins from this computer"
 CAUSE   : 20 wrong passwords from one IP address. Behind HTTPS all users look like
           one computer if PORTAL_BEHIND_PROXY is 0.
 FIX     : Wait 10 minutes, or docker compose restart portal is NOT enough (the lock is
           saved). Admin can wait or delete rows: docker compose exec portal python -c
           "import models;c=models.connect();c.execute('DELETE FROM login_attempts');c.commit()"
           For HTTPS make sure PORTAL_BEHIND_PROXY=1.

 PROBLEM : Public QR shows "no longer active" or "not valid"
 CAUSE   : The owner turned it off or made a new code.
 FIX     : Record page > Public QR > turn on / print the new QR.

 PROBLEM : Attachment refused: "could not be scanned"
 CAUSE   : The virus scanner is switched on but not running yet (the first start
           takes minutes) or is out of memory.
 FIX     : docker compose ps and docker compose logs clamav --tail 30. Wait until healthy.
           Give the server more RAM, or switch scanning off (section 15).

 PROBLEM : HTTPS page shows a certificate warning
 FIX     : Install the certificate authority on the PC (section 14, option A) or use
           your own certificate (option B).

 PROBLEM : HTTPS opens but login says "This page has expired"
 CAUSE   : PORTAL_HTTPS=1 but the page is opened over http.
 FIX     : Always use the https address, or set PORTAL_HTTPS=0.

 PROBLEM : PDF shows ? instead of some letters
 CAUSE   : The PDF font only has English and European letters.
 FIX     : Use the Excel export for other alphabets.

 PROBLEM : "Type your password to confirm this action"
 CAUSE   : Dangerous actions need the admin's own password (once per 5 minutes).
 FIX     : Type your own password in the box that appears in the form.

==============================================================================
 END OF GUIDE
==============================================================================


==============================================================================
 17. MEETING REMINDERS (TIME FIELD, SEVERAL REMINDER COLUMNS, BELL MESSAGES)
==============================================================================
 WHAT IT DOES
   The portal now warns the OWNER of a record before a date or meeting. Example message
   in the bell:   Meeting: Acme Ltd is tomorrow at 3:00 PM

 1. SEVERAL REMINDER COLUMNS PER DEPARTMENT
    Admin > Departments > Columns. Tick "Send reminders for this date" on every Date
    column that should warn people (Warranty end, Contract end, Meeting ...). There is
    no longer a limit of one per department. Existing settings are kept.

 2. TIME NEXT TO THE DATE
    Tick "Also keep a time, for meetings" on a Date column (when adding it, or later with
    Edit). The record form then shows a date box and a time box side by side. The time is
    optional: a meeting without a time is announced without "at ...".
    Old records and normal date columns are not changed.
    The "Sales & Marketing" starter list now has a "Meeting" column (reminder + time) for
    NEW departments. For a department that already exists, add the column by hand.

 3. WHEN THE BELL MESSAGE IS SENT (owner only)
    For every reminder date the owner gets:
      - one message 1 day before,
      - one message on the day itself,
      - one message at the number of days he/she chose (1, 3 or 7, default 3).
    Messages are sent in the MORNING: not before REMINDER_HOUR in .env (default 7 = 07:00).
    A record created later in the day is announced at the next check (every 5 minutes).
    If the time of today's meeting has already passed, it is not announced.
    Each message is sent once. If the date or time is changed, new messages are sent.
    Messages are only in the bell for now (no e-mail).

 4. EACH PERSON CHOOSES HOW MANY DAYS AHEAD
    Bell > Notifications > "Warn me before a reminder date": 1, 3 or 7 days.

 TIME ZONE IS IMPORTANT
    Set TZ in .env (for example TZ=Asia/Dhaka), then:  docker compose up -d
    Meeting times and the morning hour follow this time zone.

 UPGRADE
    ./backup.sh  ->  unzip over the old folder (keep your own PORTAL_PORT and TZ in .env)
    ->  docker compose up -d --build.   The database upgrades itself; nothing is lost.
    Old reminder columns keep working. Never run  docker compose down -v.

 FILES CHANGED:  core.py (reminder engine, time values), models.py (new columns/table),
    app.py (checks every 5 minutes), config.py, routes_admin.py, routes_records.py,
    routes_bulk.py, routes_workflow.py, templates_data.py, style.css, docker-compose.yml,
    .env, and the templates: admin_columns, admin_column_edit, record_form, _macros,
    reminders, admin_dashboard, notifications.


==============================================================================
 18. SHARING WITH ONE PERSON, EDIT / VIEW ONLY, REPLACING ATTACHMENTS
==============================================================================
 SHARING (record page > "Shared with" - only the owner and the admin see it)
   Whole departments : tick the departments. EVERY member gets the access you choose
                       in the box next to the department name.
   Specific people   : "Add a person", choose the access, "Share with this person".
                       The person can be in ANY department. Choosing a person who is
                       already in the list changes his/her access. "Remove" stops it.
   Access            : CAN EDIT  = change every field, upload, REPLACE and remove files.
                       VIEW ONLY = read the record, download files, write suggestions.
   If somebody gets two shares (personal and through the department) the stronger
   one counts: one "Can edit" is enough.
   Only the owner and the admin can change sharing or delete the record.
   Everything is written in the Edit history (who shared with whom, access changes,
   stopped sharing) and the people concerned get a bell message.
   Lists: "Shared with me" and "Shared by me" include personal shares; the
   "Shared with" column shows e.g.  Sales (view only)  /  Rahim (person, view only).
   Bulk bar (tick records > Share with): choose the access, then departments and/or
   one person. They get ONE bell message for the whole batch.
   Change of owner: if the new owner already had a personal share, it is removed.
   Old shares from before this update stay "Can edit" exactly as they were.

 REPLACING AN ATTACHMENT
   Record page > Attachments > "Replace" next to a file > choose the new file.
   Everybody with "can edit" access can do it (owner, admin, edit-shared people).
   The new file goes through the same checks as an upload (type, size limit, virus
   scan). The entry keeps its place in the list, shows the new name, uploader and
   time, and the OLD FILE IS DELETED from the server. The Edit history shows:
   "Bina replaced the file quote_v1.pdf with quote_v2.pdf" and the owner gets a
   bell message. View-only people cannot replace, remove or upload files.

 UPGRADE: ./backup.sh, unzip over the old folder (keep your own .env values),
   docker compose up -d --build. The database upgrades itself; nothing is lost.
 FILES CHANGED: core.py, models.py, routes_records.py, routes_bulk.py,
   routes_workflow.py, app.py, and templates record_detail, _macros.


==============================================================================
 19. DEPARTMENT DATABASE, PUBLIC QR CODES (HRC-n), REPAIR LOG SWITCH, PDF AND PRINT
==============================================================================
 DEPARTMENT DATABASE (menu: Department database)
   One shared table per department (a staff list, vendor list, stock sheet ...).
   Columns: the department admin (or a Manager) adds, edits, reorders, hides and removes
     them under "Columns". Removing keeps the data and can be restored. Types: text, long
     text, number, date (optionally with time), dropdown, yes/no.
   Access: "People and access" sets for every person of the department:
     View only                 read all rows
     Add and manage own rows   (the default) add rows, change or delete only their own
     Edit every row            change any row (deleting only their own)
     Manager                   works as the department admin: columns, access, any row
     The portal admin and the department admin are always Managers.
   Rows: everybody sees all rows of the department. Tabs: All rows / My rows / Deleted
     (managers; deleted rows can be restored for 30 days). Each row has an edit history and
     the same "two people saved at once" protection as records. Search, filter by a column,
     sort (numbers sort as numbers), export to Excel, PDF and CSV.
   Copy: on a personal record the button "Copy to department database" opens a new row
     pre-filled from the columns with the same name. Check it, then save.
   The portal admin can open any department's database with the Department box.

 PUBLIC QR WITH A UNIQUE CODE
   Record page > Public QR: tick the fields to share, or "Share the full record", then
   "Generate public QR". The QR gets the next code HRC-0, HRC-1, HRC-2 ... printed under it
   (record page, print page, public page). Numbers are never reused, even if a QR is deleted.
   "New scan link" changes the link inside the QR but KEEPS the code.
   Any logged-in person can type the code (HRC-12, hrc 12) in a search bar: the page of
   that code opens and "Download PDF" gives a clean PDF of the shared information only.
   If the owner switched the QR off, the search says so. Existing public QRs got numbers in
   the order they were created. The old login-only "QR label" was removed.

 REPAIR LOG ONLY WHERE NEEDED
   Admin > Departments > Columns > "Repair log". Off = the card, reports and dashboard
   figure are hidden. Departments that already had repair entries (and IT) stay ON,
   new departments start OFF (except the IT starter). Entries are never deleted by switching.

 PDF
   The "PDF" button on a record lets you tick the fields to include. The PDF contains only
   those fields' values: no edit history, no repair log, empty fields are left out.

 PRINT
   Printing a record shows only its title, owner, the details and the attachment names.
   Buttons, hints, tabs, side panels, comments, history and helper texts are hidden.
   In the browser's print window untick "Headers and footers" to remove the web address.

 REMINDER DAYS: the Reminders page can look 1, 3, 7, 15, 30, 60, 90, 180 or 365 days ahead.
 SAVED FILTERS were removed (filtering and sorting stay).

 UPGRADE: ./backup.sh, unzip over the old folder (keep your .env values),
   docker compose up -d --build. The database upgrades itself; old handover, request and
   saved-view data stay in the database but are no longer shown.

==============================================================================
 20. INVOICES, RANDOM PUBLIC QR CODES (HRC-#####), WATERMARK, TWO LOGOS
==============================================================================
 INVOICES (menu: Invoices)
   Dept admin (not the portal admin) creates invoice templates for their OWN
   department: Invoice templates > New template, or "Create starter templates"
   (Billing Invoice, Admin Expense Voucher, Conveyance Bill, Purchase Request).
   A template sets: heading (title / subtitle), number format (for example
   BIL-{0000}), top fields, item columns, totals, VAT %, amount in words,
   notes / terms, signatures (how many authorized, with title, person name
   and designation, plus the employee signature), currency, and the watermark
   (see below). Draft templates stay hidden from employees until Active.
   Changes to a template apply to NEW invoices only; issued invoices keep
   the format they were made with (the format is frozen on the invoice).
   Employees: Invoices tab > Create on a format card. Live totals update as
   you type. Save as Draft (still editable), then "Finalize and number" -
   the number (for example BIL-0007) is given once, never reused, and the
   invoice is locked. After that it can be marked Paid, or Voided with a
   reason (number kept, never reused). Draft and Void invoices never get a
   live public QR.
   Dept admin sees every invoice in their own department: Invoices > "All
   invoices in my department". Other departments stay hidden unless shared.
   Currency: one currency per invoice (BDT, USD, EUR, GBP, INR). The currency
   is shown beside EVERY amount in the form and in the PDF - Rate, Amount,
   Subtotal, VAT, Grand Total - and in the amount in words. No conversion.

 INVOICE PDF (layout)
   Top row: left HRC logo + company name + single-line address, right second
   logo in the top right corner (optional, uploaded in the template; if none,
   that corner stays empty). Below the coloured rule: invoice number, date,
   reference, bill-to. Then the invoice type (INVOICE / CONVEYANCE BILL /
   EXPENSE VOUCHER / PURCHASE REQUEST) centred ON TOP OF THE TABLE, and the
   table below it (moved lower than before). Then totals, amount in words,
   terms, horizontal signature blocks, and at the bottom the QR + its code.

 WATERMARK
   OFF by default. In the template, tick "Show watermark" and type what it
   will be (for example ISSUED, PAID, DRAFT, VOID, or your own word). If OFF,
   the PDF shows no watermark at all, even on Issued / Paid invoices.

 PUBLIC QR FOR INVOICES - AND FOR ALL PUBLIC QRs
   Every public QR now uses HRC- + a random 5-digit code, for example
   HRC-48392, HRC-72914. This applies to record QRs and invoice QRs alike.
   New QRs get a random code. Existing record QRs were given a random code
   on upgrade (their old sequential number is kept internally only).
   Invoice: detail page > Public QR. Tick what a stranger may see (amounts,
   customer name, item lines), set an expiry date if wanted, then "Turn on".
   The public PDF respects those ticks. "New scan link" gives a NEW random
   code, so the old printed QR stops working. "Turn off" stops it.
   SEARCHING A CODE NEEDS A LOGIN: type the code in the Invoices search box
   or in Search QR. Without login there is no view and no PDF download.
   Draft / Void / switched-off / expired codes show nothing to download.

 SHARING (dept admin only)
   1. Share a template: Invoice templates > Share > choose another department.
      That dept admin sees it under "Shared with you" and presses "Use in my
      department" - they get their own copy to use and edit. Your original
      is unchanged. The share can be revoked. Sharing a template does NOT
      share invoices or user data.
   2. Share department data: Invoice templates > "Share department data" >
      choose another department. That dept admin can view (and download) your
      department's invoices, view-only: they cannot edit, void or mark paid.
      This share can also be revoked, and can have an expiry date.

 UPGRADE: ./backup.sh, unzip over the old folder (keep your .env values),
   docker compose up -d --build. The database upgrades itself. No other
   behaviour was changed in this update.

==============================================================================
 21. DEPARTMENT DATABASE MEETINGS + ATTACHMENT COLUMNS
==============================================================================
 MEETING NOTIFICATIONS (Department database)
   A date column with "Also keep a time" ticked is a meeting schedule.
   When a user adds (or changes) a row with a date + time in such a column,
   the portal sends a bell notification to:
     - the user who added the row: "You have a meeting at 05 Nov 2026 3:00 PM"
     - every dept admin of that department: "Rahim Uddin has a meeting at
       05 Nov 2026 3:00 PM"  (the owner's name, then the date and time)
   When: the day before the meeting, and again on the morning of the meeting
   (after REMINDER_HOUR in .env, default 7 in the morning, checked every
   5 minutes and on each page load, like record reminders). Each person gets
   each message only once; changing the date/time sends a new set for the
   new time. If the meeting time has already passed today, no "today"
   message is sent. Clicking the bell message opens the department-database
   row. Portal admin is not notified unless they are also a dept admin of
   that department.

 ATTACHMENT COLUMNS (Department database)
   New column type: "Attachment (file)". A user adds a file to a row in the
   row form (file input, with the current file shown and a Remove tick on
   edit). The row detail and list show the file name with a Download link;
   only people who may open that department's database can download it.
   Files are stored with a random name in uploads/ddb_attachments, with the
   same allowed file types and size limit as record attachments, and the
   same ClamAV scan when scanning is on (refused if it cannot be scanned).
   Export shows the original file name, not the stored name. Files of rows
   purged for good (after 30 days in the bin) are deleted with the row.
   WHO CAN CREATE SUCH A COLUMN: the portal admin, always. A dept admin
   only if the portal admin gave them access: Admin > DeptDB attachment
   access (tick the dept admin), or Users > Edit user > "Can create
   attachment columns in the Department Database". A dept admin without
   that access gets a clear message and cannot create an attachment column,
   but can still create all other column types. Old databases upgrade
   automatically: the department-database column table is recreated with
   the wider type list, keeping all columns and rows.

 UPGRADE: ./backup.sh, unzip over the old folder (keep your .env values),
   docker compose up -d --build. The database upgrades itself.

==============================================================================
 22. DEPARTMENT DATABASE TABS (replaces the old single DeptDB table)
==============================================================================
 There is no longer one shared table per department. Under "Department
 database" the department admin (or a delegate, see below) creates
 different tabs, and users switch between those tabs on the page.
 Filter and sorting sit ON TOP of the tabs and apply to the tab that is
 open (search text, filter by a column, sort by last changed / created /
 any column, ascending or descending).

 TEMPLATE TABS (starter columns, which the admin can then customise):
   - Client Info: Client name, Contact person, Phone number, Email,
     Address, Notes. This is only a record of clients.
   - Meetings: Client name, Address, Contact number, Date (with time),
     Purpose, Notes. This is a meeting schedule; it is NOT connected to
     the Client Info tab — the meeting row carries its own client name,
     address and contact number, typed in again.
   - Employee Info: Employee name, Employee ID, Designation, Phone
     number, Email, Joining date, Address.
   - Billing: Client name, Bill number, Amount, Date, Status
     (Paid / Unpaid / Partially paid), Notes.
   - Accounts: Account / Head, Type (Income / Expense), Amount, Date,
     Reference, Notes.
   - Custom tab (blank): no starter columns; the admin adds them.
 Customising a tab: Tabs > Columns for that tab — add, rename, reorder,
 remove (restorable) columns, exactly as columns worked before, but per
 tab. Attachment columns keep the previous rule (portal admin grants
 which dept admins may create them, Admin > DeptDB attachment access).

 WHO CAN SEE / EDIT A ROW:
   - Every user in the same department can see every row in a tab.
   - Only the row's owner can edit it.
   - The owner may share a row with another department or with a
     specific user, and sets the permission when sharing: View only or
     Can edit. A shared user/department can only do what was allowed.
   - Every change is shown in the row's edit history on the row page
     (who changed what, when, plus shares and unshares).
   - Department admins, their delegates and the portal admin may manage
     tabs and columns and edit every row in their department.

 DELEGATE (a user who can do what a dept admin can do):
   Department database > Delegates: the dept admin chooses a user in the
   department and gives them permission to do everything a department
   admin can do in the Department Database — create tabs, customise
   columns, edit every row, and grant/remove delegates. Delegates are
   also notified about meetings like dept admins (below).

 MEETING NOTIFICATIONS (now in meeting tabs, at 7 / 3 / 1 days + same day):
   A tab with meeting notifications on (the Meetings template turns this
   on; any tab can be ticked on the Tabs page) works like this: a date
   column with "Also keep a time" in such a tab is a meeting schedule.
   The row owner gets "You have a meeting at <date time>" and every dept
   admin (and delegate) of that department gets "<USER> has a meeting at
   <date time>", at 7 days before, 3 days before, 1 day before, and on
   the morning of the meeting (after REMINDER_HOUR in .env, default 7 AM).
   Each message once per person per meeting date/time; changing the
   date/time sends a new set; no "today" message if the time has passed.
   This replaces the old day-before + morning-of timing in section 21.
   Meeting notifications do NOT fire for date columns in other tabs.

 UPGRADE FROM THE OLD DEPARTMENT DATABASE:
   Old columns and rows are NOT lost: on first start they are moved into
   a first tab called "General" for their department. If the old table had
   a date+time column, that General tab keeps meeting notifications on.
   The old "People and access" levels (view / own / edit / manager) are
   replaced by the see-all / owner-only-edit / share rules above.

 UPGRADE: ./backup.sh, unzip over the old folder (keep your .env values),
   docker compose up -d --build. The database upgrades itself.

==============================================================================
 23. INVOICES AS A DEFAULT TAB INSIDE THE DEPARTMENT DATABASE
==============================================================================
 The invoice page is no longer a separate top-menu page. It is a DEFAULT
 tab inside "Department database", next to Client Info, Meetings and the
 other tabs. It is always there — the dept admin does not create it, and
 it cannot be deleted or customised like the other tabs. Old /invoices
 links and bookmarks redirect to it.

 INSIDE THE INVOICES TAB — SUB-TABS:
   - All: every kind of invoice, from every user in the department.
   - One sub-tab per invoice type: Billing Invoice, Admin Expense
     Voucher, Conveyance Bill, Purchase Request, and every custom type.
     A sub-tab shows only invoices of that type, from every user.
   - When a dept admin creates a NEW invoice type (on the templates
     page), its sub-tab appears here AUTOMATICALLY — no extra step, no
     Department Database tab to create. The sub-tabs are built from the
     department's templates and from templates that already have invoices,
     so a type that already has invoices keeps its sub-tab even if its
     template is later drafted.

 FILTERS (on top of the Invoices tab, and they carry across sub-tabs):
   Search (customer, number or HRC code), Filter by user (All users /
   My invoices / one specific user), Filter by status (Draft / Issued /
   Paid / Void), and Sort (newest, oldest, invoice date, amount).

 SEE / EDIT (unchanged invoice rules, plus department-wide viewing):
   - Every user in the department can SEE every invoice in the tab,
     including its detail page and PDF. A same-department viewer sees no
     Finalize / Mark Paid / Void / public-QR buttons.
   - Editing is unchanged: only the owner can edit a Draft; only the
     owner or a dept admin can mark an invoice Paid or Void; only the
     owner or a dept admin can change its public QR settings.
   - Creating an invoice still works from the format cards at the top of
     the tab (Create on a template), and every other invoice feature is
     unchanged: Draft → Issued (numbered, locked) → Paid / Void, PDF and
     print, public QR with HRC code, code search (login required),
     template sharing, department invoice sharing, watermark option and
     currency beside every amount.
   - Dept-admin invoice sharing still works: a dept admin who receives a
     shared department's invoices sees those invoices in this tab too,
     marked with their department name.

 INVOICE TEMPLATES STAY OUTSIDE:
   Invoice templates remain a separate, dept-admin-only page (Invoice
   templates in the menu), exactly as before. They do not become a
   Department Database tab or an Invoices sub-tab.

 UPGRADE: ./backup.sh, unzip over the old folder (keep your .env values),
   docker compose up -d --build. No database change is needed for this
   feature; the tab is built from the existing invoice tables.

==============================================================================
 24. PORTAL ADMINISTRATIVE PERMISSION, DEPARTMENT-ADMIN USERS PAGE,
     LOCKED / DELETED USER NAMES, AND RECYCLE BIN USERS TAB
==============================================================================
 PORTAL ADMIN ALL USERS PAGE — FILTERS:
   The Users page (portal admin) keeps its search box and adds filters
   that can all be combined: Department (All departments / one
   department), User (All users / one specific user), Role (Admin /
   Department admin / User) and Status (Active / Locked / Pending
   approval). Deleted users are NOT on this page; they are in the
   Recycle Bin, Users tab (below).

 PORTAL ADMINISTRATIVE PERMISSION:
   The portal admin can give a user portal administrative permission:
   Users > Edit user > "Portal administrative permission" (only the
   original portal admin sees this tick box). That user can then do
   every task the portal admin can do: Users, Departments, columns,
   All records, Reports, Activity, Sessions, Settings, Department DB
   attachment access, and the Recycle Bin tabs below.
   Limits, enforced in the code, not just in the page:
   - A permission user cannot give portal administrative permission to
     anyone else, and cannot create a true admin account.
   - A permission user cannot edit, disable, reset or delete a true
     portal admin account, and cannot delete his own account.
   - Only the original portal admin can give or remove the permission,
     and can disable or remove the permission user.
   - The portal admin can restore everything a permission user deleted
     (records and users, from the Recycle Bin), because a permission
     user cannot erase for good his own deletions or the portal admin's
     deletions from the Recycle Bin (Records tab, below).

 DEPARTMENT ADMIN USERS PAGE:
   Department admins get a Users page in the menu (Users). On it they
   can VIEW the accounts of their own department only, and CREATE an
   account for their own department only (as a regular user; the
   department is fixed to theirs).
   - An account created by a department admin is NOT functional until
     it is approved: it shows as "Pending approval" on the portal admin
     Users page, cannot log in, and is approved (Approve button) or
     rejected (Reject button, removes the pending account outright) by
     the portal admin or a permission user. A portal admin creating an
     account on the main Add user page is approved at once, as before.
   - A department admin CANNOT reset a password, lock, disable, edit or
     delete any user. His Users page has no Reset, Lock, Disable, Edit
     or Delete buttons at all, and those routes refuse a department
     admin even if the address is typed directly.
   - Only the portal admin and a permission user can delete a user
     account at all. No other user can delete any account.

 LOCKED, DELETED AND RESTORED NAMES (colours, with words too):
   A person's name is coloured wherever it appears with his work
   (Users lists, record lists and detail pages, Department Database
   rows, invoice lists, Recycle Bin):
   - Green = active. A restored user is green again.
   - Yellow = locked (disabled, "Locked" in the Status column). A locked
     user cannot log in, but all his records and work stay in the
     portal, visible only to the people who normally had access to
     them (same department, shared access, and so on).
   - Red = deleted (soft-deleted, see below). His work stays visible
     for 30 days, only to the people who normally had access, with his
     name in red.
   The colour is never the only signal: the Status column also says
   Active / Locked / Pending approval, and a deleted user is listed in
   the Recycle Bin Users tab.

 DELETING A USER (soft delete, 30 days):
   Users > Delete account (portal admin or permission user only, with
   the admin's password to confirm) does NOT erase the account at once.
   The account goes to the Recycle Bin, Users tab: it cannot log in,
   its work stays in the portal for 30 days (name in red), and it can
   be restored from the Users tab (Restore button, portal admin or
   permission user) — then it works as before, name green again.
   After 30 days the account AND all his work vanish from the portal
   automatically (records, Department Database rows, invoices and
   public QR links). This hourly clean-up also erases old records in
   the Records tab, as before.

 RECYCLE BIN — TWO TABS (portal admin and permission user only):
   Recycle bin now has two tabs at the top:
   - Records: deleted records, as before (owner, deleted by, erase date).
   - Users: deleted user accounts, with deleted date, deleted by and
     erase date. Other users do not see the Users tab at all; their
     Recycle Bin shows only their own deleted records, as before.
   In the Records tab, a permission user can restore any deletion and
   can erase for good other users' deletions, but cannot erase for
   good his own deletions or the portal admin's deletions — only the
   portal admin can erase those.
   In the Users tab, a permission user can restore any deleted user,
   and can erase for good other users' deleted accounts, but cannot
   erase a true portal admin's account or his own account.

   ERASING A DELETED USER FOR GOOD — THE POPUP:
   "Delete forever" on a user in the Users tab shows a popup:
     "You want to delete this user all work from the portal too?"
   - Yes: the user's work is deleted from the portal immediately, then
     the account is deleted for good.
   - No: the account leaves the Recycle Bin list, but his work stays in
     the portal (name in red) until the 30 days end, when it vanishes
     with the account, as above.

 RENAMED BUTTON:
   The button on the Users page (and the page it opens, and the menu
   link under More) now reads "Department DB attachment access" in
   full, instead of the "DeptDB" abbreviation. The access rule itself
   is unchanged.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in the
   zip), unzip over the old folder, compare and restore your live .env
   if it differs, then docker compose up -d --build. The database
   upgrades itself: new user fields (portal permission, soft-delete,
   pending approval) are added to existing accounts without losing data.
   Apply only this latest zip, not the older ones in order.


==============================================================================
 25. SECURITY AND BUG FIXES (SCAN OF 2026-11-04, .env UNTOUCHED)
==============================================================================
 This build fixes the errors found in the scan of the users-admin
 build, except one: the .env file is left exactly as it was in that
 zip, untouched, as instructed. Nothing else in this list changes
 .env, and the upgrade step above (back up your live .env first)
 still applies.

 1. SEQUENTIAL PUBLIC CODES NO LONGER OPEN A LINK. Only the random
    HRC-##### code printed under a QR is accepted in code search,
    /code/<code>, and search bars. Old sequential numbers (HRC-0,
    HRC-1, ...) no longer open anything, and they are no longer shown
    anywhere. Every existing link already has a random code; the
    database upgrade gives one to any link missing it, so no link is
    left without a working code. The token link (/p/<token>) is
    unchanged.
 2. REGENERATING A RECORD QR NOW ROTATES THE CODE TOO. "New scan
    link" on a record and "New code" on the Public QR links page now
    give a new random HRC-##### code as well as a new token, so the
    old code typed in search stops working, exactly like invoices
    already did. Print the new QR after regenerating.
 3. EXCEL FORMULA INJECTION FIXED. A text cell starting with =, +,
    -, @, tab or carriage return is now written to Excel as plain
    text, not as a formula, so a value like =2+2 stays =2+2 instead of
    calculating to 4. CSV export already did the same with a leading
    apostrophe; Excel now uses a text cell instead, so the visible
    value is unchanged. Number cells are untouched.
 4. RECORD PDF, UNTICK ALL. The PDF form on a record page now sends
    a marker, so submitting it with every box unticked gives an empty
    PDF ("No information to show") instead of the full record. A
    direct PDF link with no form marker still gives all columns, as
    before.
 5. .env: LEFT AS IT IS. No change was made to .env in this build.
 6. DEPENDENCIES PINNED. requirements.txt now pins the exact versions
    this build was tested with (Flask 3.1.3, waitress 3.0.2,
    segno 1.6.6, openpyxl 3.1.5, reportlab 5.1.0), so a rebuild cannot
    silently pull newer versions.
 7. NOTIFICATIONS READ STATE. Opening the Notifications page no
    longer marks everything read. Use the new "Mark all as read"
    button on that page; until then the "New" badges and the bell
    count stay.
 8. SORTING BY A COLUMN NAME IS NOW PER-DEPARTMENT. Sorting a list
    by a column now checks the column type in each record's own
    department, so a number column with the same name in another
    department no longer makes this department's text values sort as
    numbers.
 9. LEGACY TABLES, LEFT ALONE. The old handovers (transfers),
    requests and saved views tables are still in the database, with
    no pages for them, exactly as before. They were deliberately NOT
    deleted (that would lose old data) and NOT rebuilt (that would be
    a new feature, not a bug fix). They are documented here as legacy
    only; purging a user's work still clears his entries in them, as
    before.
 10. SMALLER FIXES. Code search and /code/<code> now give one
     generic "not available" answer whether a code does not exist or
     its owner switched it off, so existence cannot be probed. The
     Attachments card on a record page no longer prints. A permission
     user can now edit his own name and department on the Users page
     (he still cannot make himself a true admin, remove his own
     permission, or disable himself).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in the
   zip), unzip over the old folder, compare and restore your live .env
   if it differs, then docker compose up -d --build. The database
   upgrades itself; no new database change is needed for these fixes.
   Apply only this latest zip, not the older ones in order.

 26. INVOICE HRC CODE LABELLED "SHARE CODE" (2026-11-05, LABELS ONLY)
    The invoice number and the public QR code are two different
    numbers, and they are now labelled so they cannot be mixed up.
    The invoice number (for example BIL-0001) is the official
    number: quote it for payment and accounts. The HRC-##### code
    is now called the "Share code" everywhere an invoice shows it:
    it is only for scanning the QR and searching for the invoice,
    it is not the invoice number, and it changes when a new scan
    link is generated. No number, code, permission or behaviour
    was changed except for this one correction found while testing
    the labelled search (below).
    - Department Database > Invoices tab: the table columns are
      now "Share code" and "Invoice number", and the search box
      says "Search customer, invoice number or share code".
    - Invoice detail page, Public QR panel: "Share code:
      HRC-##### (not the invoice number)", with the note that
      the invoice number is the one to quote for payment.
    - Invoice code page: heading "Share code HRC-##### ...
      Invoice No. BIL-0001", with the same not-the-invoice-number
      note.
    - Invoice PDF footer: under the QR it now reads "Share code:
      HRC-#####", and the footer text says the share code is only
      for scanning and searching, and to quote the invoice number
      above for payment. The PDF meta still shows "INVOICE NO.".
      A draft PDF (no QR yet) now just says "Generated by HRC
      Portal" in the footer instead of referring to a share code
      that does not exist yet.
    - Printed QR label: the code under the QR now reads
      "Share code: HRC-#####" (this label template is shared, so
      record QR labels get the same clearer label).
    - CORRECTION FOUND IN TESTING: searching the Invoices tab by
      a share code used to be hijacked by the Department Database
      record-code redirect and land on a 404 record code page.
      The Invoices tab is now exempt from that redirect, so its
      own search filters by share code as labelled. Searching a
      code from any other Department Database tab still redirects
      to the record code page, as before.
    No separate invoice-only QR search button was added, as
    requested for now; the existing routes are the Invoices tab
    search (invoices only) and top-menu Search QR (records and
    invoices together).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 1. DASHBOARD SETTINGS BUTTON. Top right of the Dashboard, next to
    Reports / Export Excel / + Add record, there is now a "Dashboard
    settings" button. It opens a panel with a tick box for each
    dashboard section: KPI cards, Records by department, Department
    database, Records by status, Recent activity, Logged in now,
    Reminders coming up and Quick actions. Unticking a section hides
    it from YOUR dashboard. The setting is saved per admin (each
    admin's own login): hiding a section on your login does not hide
    it for anyone else. Tick everything back on to bring a section
    back. Nothing is deleted — a hidden section is only hidden.
 2. DEPARTMENT DATABASE WIDGET. A new section on the Dashboard,
    "Department database", right after "Records by department". For
    each department it shows the total Department Database rows, and
    underneath, each tab's row count (Client Info 3, Meetings 1,
    Invoices 2, and so on). The Invoices tab is counted too: the
    total is all the department's DeptDB rows plus its invoices.
    Only tabs that have rows are listed; a department with no rows
    shows nothing in the breakdown. The numbers come from the live
    Department Database, so the widget always matches it.
 3. EACH DEPARTMENT HAS ITS OWN COLOUR. In both department charts
    the bars/slices are coloured per department, from the portal's
    chart colours (teal, green, amber, red, purple, grey-blue). A
    department keeps the same colour in both charts and every time
    you look, even when the counts change. The "Records by status"
    chart keeps its existing colours (by status, not by department).
 4. BAR / PIE CHART SWITCH. In the Dashboard settings panel, under
    "Records by department" and under "Department database", there
    is a Bar | Pie chart switch for each chart, set independently.
    Bar shows the vertical bars (as before, now in each
    department's colour). Pie chart shows a big filled pie: each
    slice is its department's colour, and the count is written on
    the slice in white (white is the ink that reads on every slice
    colour — the department's own colour on its own slice would
    disappear into it). Under the pie, the legend shows each
    department with its count in that department's colour, and the
    Total at the end. "Records by status" is now the same filled
    pie, the same size, so all three charts match.
 5. NOTHING ELSE CHANGED. The login page is unchanged. Every other
    page, tab, filter, button and permission is exactly as it was.
    The dashboard still has its "See all" links, Select / Select
    all and the print guard are untouched, and the password eye is
    still on every password box. The KPI row and the rail are still
    hidden when printing.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   The upgrade creates one new table (dashboard_settings) for the
   per-admin settings; your data and the live .env are not touched.
   Apply only this latest zip, not the older ones in order.

 27. INVOICE PDF SHARE CODE IN THE BOTTOM RIGHT CORNER (2026-11-05)
    In the invoice PDF only, the share code is now flush-right in
    the bottom right corner: the QR is flush-right in its column
    and the "Share code: HRC-#####" text under it is right-aligned
    (it was centred under the QR before), as the last line of the
    footer. The footer text on the left now reads "Share code at
    the bottom right is only for scanning and searching — it is
    not the invoice number. Quote the invoice number above for
    payment." Nothing else in the PDF layout changed: top row,
    INVOICE NO., table position, totals and signatures are as in
    layout v4. The detail page, code page, Invoices tab and printed
    QR label are unchanged by this update.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 28. INVOICE PDF SHARE CODE AT THE BOTTOM LEFT CORNER OF THE PAGE
    (2026-11-05, CORRECTION TO SECTION 27)
    The previous bottom-right change put the share code under the
    QR inside the footer block, which on a short invoice sits in
    the middle of the page, not at the bottom. That was wrong.
    Now, in the invoice PDF only, the share code is drawn in the
    page footer itself, at the bottom left corner of the page
    (left margin, same baseline as "Page 1" on the right), on
    every page of the invoice. It no longer appears under the QR:
    there is exactly one "Share code: HRC-#####" in the PDF, at
    the bottom left. The QR stays in the footer block, on the
    right. The footer text on the left now reads "Share code at
    the bottom left of this page is only for scanning and
    searching — it is not the invoice number. Quote the invoice
    number above for payment." A draft invoice with no QR yet
    shows no share code at the bottom. Nothing else in the PDF
    layout changed, and the detail page, code page, Invoices tab
    and printed QR label are unchanged by this update.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 29. INVOICE PDF: SMALLER QR AT BOTTOM LEFT ABOVE SHARE CODE, SAME
    SIGN GAP FOR ALL INVOICE TYPES (2026-11-05, APPROVED LOOK)
    Built exactly as approved in the JPG preview of 2026-11-05
    (sign-lower-2). In the invoice PDF, for every invoice type
    and every custom format, because they all use the one shared
    invoice_pdf builder:
    - The QR is no longer in the footer block on the right. It is
      drawn in the page footer, at the bottom left corner, at
      1.9 cm (was 2.8 cm), directly on top of the share code.
    - Under it, at the very bottom left, is "Share code:
      HRC-#####", with "Page 1" still at the bottom right. The
      QR and code appear on every page of the invoice.
    - The signature gap is the same for all types: the space
      after the Terms line before the signature blocks is now
      64 points (was 16), so Prepared / Authorized / Approved
      sit the same amount lower in Billing, Admin Expense
      Voucher, Conveyance Bill, Purchase Request and custom
      formats. No other PDF layout changed.
    A draft invoice with no QR yet shows no QR and no share
    code at the bottom. The detail page, code page, Invoices
    tab and printed QR label are unchanged by this update.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 30. FOUR FIXES: TAX TICK, SMALL INVOICE QR, GENERAL TAB DELETED,
    MY RECORDS FOR ALL ADMINS (2026-11-05)
    1. Tax tick in the template builder. In Invoice templates >
    New / Edit template, section 5 Totals, there is now a "Tax"
    tick box on the left of the "VAT / tax %" box. It is per
    template and set by the dept admin. Ticked: the employee
    making an invoice gets the tax option as before (VAT % and
    VAT amount on the form, the invoice detail and the PDF).
    Unticked: the employee gets no tax option at all - no VAT
    field on the form and no VAT line on the invoice detail or
    the PDF, and the total is just the subtotal. The % typed in
    the box is kept when the tick is off, so ticking it again
    brings tax back with the same %. Existing templates were
    set from their VAT % on upgrade (Billing, 5%, ticked; the
    0% starters, unticked), and the upgrade never overwrites
    the tick afterwards. A new template starts ticked. An
    invoice already issued keeps the VAT it was issued with
    even if the template is unticked later; only new invoices
    follow the new tick. A template shared with another
    department copies its tick with it.
    2. Small invoice QR. The Public QR on the invoice detail
    page was full-width because it had no size limit. It now
    uses the same small 150 px box as the Public QR on a
    record detail page, with the share code under it. The PDF
    QR, the code page and the printed QR label are unchanged.
    3. General tab deleted for all users. The "General" tab in
    Department Database was created by the upgrade for old
    single-table data, never by a dept admin, but it was shown
    to every user. On upgrade every tab named "General" is now
    deleted (soft-deleted, the same as pressing Delete on a
    tab) in every department, for normal users, dept admins,
    delegates and the portal admin alike. Its rows stay in the
    database, they are only hidden. A dept admin can no longer
    create a tab called "General", rename a tab to "General",
    or restore a deleted "General" tab. Old single-table rows
    from a database that has never had tabs are moved into the
    department's first admin-created tab when one exists; if
    the department has no tab yet they stay in the database
    with no tab (not shown) instead of getting a system-made
    tab. The Invoices default tab is not affected.
    4. My records for all admins. The top menu showed "My
    records" only to regular users: a portal admin got
    Dashboard / All records / Users / Departments and a dept
    admin got only Users, so neither had a way back to their
    own records page. Both now get a "My records" link in the
    top menu (portal admin: after All records; dept admin:
    before Users), and so does a portal administrative
    permission user. It opens the same My records page regular
    users see. Nothing else about the menu changed.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (the new
   invoice_templates.show_tax column is added automatically on
   first start, and the General tab is deleted automatically on
   first start). Apply only this latest zip, not the older ones
   in order.

 31. MY DEPARTMENT TAB: OWN DEPARTMENT DATABASE WORK ONLY, WITH
    LOCATE (2026-11-05)
    The "My department" tab on the My records page used to be a
    dept-admin-only list of every personal record in the
    department. It now works differently, for every user:
    - The tab is on every user's My records page (regular user,
      dept admin, portal admin and portal administrative
      permission user), next to Mine, Shared by me and Shared
      with me. Those three tabs are unchanged.
    - It shows only that user's own rows in the Department
      Database: the rows they created in the department's
      tabs (Client Info, Meetings, and so on), grouped under
      the tab they belong to. No other user's rows, no personal
      records, and no rows shared with them by someone else.
      Invoices are not listed here; they stay in the
      Department Database Invoices tab. The count beside the
      tab is the number of that user's own Department Database
      rows. A search box on the tab searches the values of
      those rows, and Download CSV downloads them.
    - Nothing can be edited from this tab. There are no edit,
      delete or share buttons on it.
    - Each row has a Locate button on its right side. Locate
      is a plain link in the same browser tab (it does not open
      a new tab or window). It opens the Department Database
      page on the tab the row belongs to, on the page that row
      sits on, scrolled to that row and highlighting it, so
      the row can be seen in place and edited there if the user
      is allowed to (owner, dept admin or delegate, as before).
    - Because the tab no longer lists personal records, a dept
      admin no longer sees other users' personal records on
      the My records page at all. Department-wide viewing
      happens in the Department Database page itself, where
      every user in the department already sees every row.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 32. USER APPROVAL NOTIFICATIONS, MY INVOICES TAB, PRINT WITHOUT
    EDIT HISTORY, PROFESSIONAL ROW HIGHLIGHT, NOTIFICATION LINKS
    (2026-11-05)
    1. User creation approval notifications. Until now, when a dept
    admin created an account, it only sat as "Pending approval"
    on the Users page and nobody was told. Now the moment a dept
    admin creates an account, every portal admin and every user
    with portal administrative permission gets a bell
    notification with the new person's name and department.
    Tapping it opens the Users page filtered to pending accounts,
    at that exact person's row, with Approve and Reject right
    there. When the admin approves the account, the dept admin
    who created it gets a notification saying it was approved
    and can now log in; when it is rejected, they get a
    notification saying it was rejected, so they are not left
    waiting. Tapping that notification opens the dept admin's
    own Users page at the account. The account now records who
    created it (users.created_by, added automatically on
    upgrade); accounts created before this update notify the
    dept admins of their department instead.
    2. My invoices sub-tab. The Invoices tab had sub-tabs for
    All and for each invoice type, and "My invoices" only as an
    option in the user dropdown. There is now a "My invoices"
    sub-tab next to All, listing only the current user's
    invoices across all types, with its own count beside it.
    The dropdown is unchanged, and search, status and sort
    still carry across the sub-tabs.
    3. Print without Edit history. The printed Department
    Database row page (and the printed record page) showed the
    Edit history section even though it is marked not to print:
    a later print rule that lays the page out for printing
    (.stack) overrode the do-not-print mark on the same element.
    That rule now leaves do-not-print elements alone, so the
    printed page has no Edit history. The screen page is
    unchanged, and Edit history is still shown there.
    4. Professional row highlight. The row opened by Locate (or
    from a notification) used to get yellow cells with a hard
    orange outline. It now gets a soft blue tint that fades
    away on its own after 1.5 seconds, with no outline.
    5. Notification links. Every notification that points at
    something now opens that exact place when tapped, in the
    same tab. A Department Database row (meeting reminders and
    row shares) opens the Department Database page on the row's
    own tab and page, with the same soft 1.5-second highlight
    on the row. A user approval opens the Users page at that
    pending account. A record opens its detail page, and a bulk
    share opens the Shared with me tab. Notifications with
    nothing to open (for example a blocked upload) stay as
    plain text.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (the new
   users.created_by column is added automatically on first
   start). Apply only this latest zip, not the older ones in
   order.

==============================================================================
 33. PER-TEMPLATE INVOICE HEADER, LOWER SIGNATURES, RECYCLE BIN PURGE RULE,
     MY SUB-TABS, USERNAME CHANGE (2026-11-05)
==============================================================================
 1. Per-template invoice header. When a dept admin creates or edits an
    invoice template, section 2 Heading has two new boxes: Company name
    and Address. Whatever is typed there appears at the top of invoices
    made from that template, next to the logo, in place of the fixed
    address line. There is no email box and no email is ever shown in
    the header (accounts@hrctech.net is gone from invoice PDFs). The
    phone number is part of the address line the admin types. New
    templates start filled with the portal's company name and address,
    and so do existing templates when the admin opens them; until then
    their invoices look as before, minus the email. The "Show company
    address and contact" tick box now actually hides or shows the
    address line (it was saved before but the PDF ignored it). A
    template shared with another department carries its header with
    it. An invoice keeps the header it was made with, even if the
    template is changed later; on invoices made before this update,
    only the email disappears if the PDF is downloaded again.
 2. Signatures lower. The space above the signature line is now the
    same on every invoice, 88 points, whether the invoice has Terms
    or not. Before, the gap only existed when Terms were written, so
    invoices without Terms had almost no room to sign. The gap is the
    same for every invoice type and custom format.
 3. Recycle Bin purge rule. A permission user can no longer erase
    from the Recycle Bin a deletion made by a permission user -- only
    the true portal admin can. That covers user accounts (a permission
    user can no longer erase any user account at all, since accounts
    are only ever deleted by the portal admin or a permission user)
    and records (including erasing a user's work with "Yes, delete
    all their work too" when purging their account). A permission
    user can still erase records a regular user deleted himself, and
    can still restore any deletion.
 4. "My" sub-tabs in the Department Database. The portal admin no
    longer gets a "My rows" or "My invoices" sub-tab on any
    Department Database tab, in any department. A permission user
    gets them only in his own department, not in other departments.
    Dept admins and regular users are unchanged. A bookmarked link
    with the "my" filter now simply shows All.
 5. Username change. The portal admin and a permission user can now
    change another user's username on the Edit user page. The new
    name must not already be used by someone else, and the user logs
    in with the new name afterwards.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (the new
   invoice_templates.company_name and company_address columns are
   added automatically on first start). Apply only this latest zip,
   not the older ones in order.

==============================================================================
 34. WATCHER NOTIFICATIONS, NOTIFICATION MULTI-SELECT (2026-11-05)
==============================================================================
 1. Watcher notifications. Each level now watches the level below it,
    so the right people hear about the work done underneath them:
      - Nobody is told about the portal admin's tasks. When the true
        portal admin does something, no notification goes to anyone.
      - The portal admin is told about two levels below him: what a
        permission user does, and what a dept admin does.
      - A permission user is told about what the dept admins do.
      - A dept admin is told about what the users in his department
        do in the Department Database.
    What counts as a task at each level:
      - Permission user (the portal admin is told): the Admin-area
        work -- create, edit, reset the password of, or delete a user;
        approve or reject a pending account; end someone's session;
        import users; restore or erase something from the Recycle
        Bin; add or delete a department, change its repair-log or
        attachment settings; add, edit, move, remove, restore, or
        erase a record column; change the attachment-access list;
        change the portal settings (company name or logo).
      - Dept admin (the portal admin and the permission users are
        told): create a user in his department; manage the Department
        Database tabs, columns, and delegates; share, create, or copy
        an invoice template; share the department's invoices with
        another department; mark an invoice Paid or Void; add, edit,
        share, delete, or restore a row in his department.
      - A user in the Department Database (that department's dept
        admin is told): add, edit, share, or delete a row. When the
        owner marks his own invoice Paid or Void, the dept admin is
        told too. A dept admin adding or editing a row himself counts
        as a dept-admin task, so the portal admin and the permission
        users are told instead; a delegate's Department Database
        actions count the same way. Creating or editing an invoice
        draft, finalising it, or changing its public QR does not send
        a notification.
    Each notification says who did what, for example "Perm User
    created a new user: New Hire (newhire), Sales & Marketing", and
    tapping it opens the page where it happened, such as the Users
    page or the Department Database tab.
 2. Notification multi-select. A "Select" button now sits on the
    left of "Mark all as read" on the Notifications page. Tapping it
    shows a tick box on the left of every notification. Tick the ones
    wanted, then tap "Mark as read" to mark only the ticked ones read,
    or "Clear" to clear only the ticked ones. Tapping "Select" again
    hides the tick boxes. "Mark all as read" and "Clear all" are
    unchanged and still act on everything.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (notifications use
   the existing notifications table). Apply only this latest zip,
   not the older ones in order.

==============================================================================
 35. DASHBOARD "LOGGED IN NOW" CARD LINKS TO SESSIONS (2026-11-05)
==============================================================================
 The "Logged in now" card on the dashboard now has a "See all" link
 under the number, in the same place and style as the "See all" link
 on the Reminders card. Clicking it opens the Sessions page
 (Admin > Sessions), which lists the users who are currently active,
 with their IP address, browser, login time, and last activity, and
 lets the admin log someone out. The Sessions page itself is
 unchanged. The dashboard and the Sessions page are both open to the
 portal admin and to a portal-administrative-permission user, so both
 see the link and can open the page; a dept admin cannot open the
 dashboard, as before.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (only one template
   line changed). Apply only this latest zip, not the older ones
   in order.

==============================================================================
 36. SELECT / SELECT ALL + PRINT GUARD + LANDSCAPE PRINT WITH ALL COLUMNS
     (2026-11-06)
==============================================================================
 1. SELECT AND SELECT ALL. On every Department Database record tab
    (Client Info, Meetings, custom tabs) and on the My records page
    (Mine, Shared by me, Shared with me, My department), two buttons
    now sit on the right of the sub-tabs row: "Select" and "Select
    all". Tapping Select shows a tick box on the left of every row on
    the page; tapping it again hides the boxes and clears the
    selection (it reads "Cancel" while the boxes are shown). "Select
    all" shows the boxes and ticks every row on the page. A line under
    the table says how many rows are selected. On My records the same
    tick boxes already used for bulk actions are used, so the bulk bar
    (Share, Public QR, Excel, PDF, CSV, Delete) still works on the
    ticked rows. The Invoices tab has no Select buttons, as before.
 2. EXPORT AND PRINT USE ONLY THE SELECTED ROWS. With rows ticked,
    Export (Excel / PDF / CSV) and the Download CSV on the My
    department tab export only those rows; Print prints only those
    rows. With nothing ticked, Export still exports everything the
    current filters match, as before.
 3. PRINT GUARD. On the Department Database page and the My records
    page, pressing Print with no row selected shows the red message
    "Please select the data row first." and nothing prints. After
    selecting a row (Select or Select all), Print works and prints
    only the selected rows. The Invoices tab has no Select, so its
    Print button is unchanged and prints the whole list. Detail
    pages' Print is unchanged.
 4. PRINT FORMAT. The Open / Edit / Restore / Locate buttons no
    longer print (the print rule that forced the actions column back
    on is fixed). The browser's own header and footer (the page
    address at the top right, the date) no longer print; the portal's
    own header (HRC logo, company name, "Printed ... by ...") stays.
    The print table fits the page width, the header row repeats on
    every page, and long text wraps inside its own cell, so the row
    grows taller and every cell stays lined up at the top. Nothing is
    cut off.
 5. LANDSCAPE, ALL COLUMNS. The Department Database and My records
    list pages now print in landscape, and the print table shows ALL
    columns of the tab, not only the first 7 shown on screen (the
    extra columns stay hidden on screen and only appear in print),
    one row per record, with "Added by" always last. The printout
    says "Selected rows · N of M" under the title. Other pages
    (record detail, row detail, Invoices tab) still print in
    portrait. A selection covers only the rows on the page shown, not
    other pages of the list.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

==============================================================================
 37. PASSWORD EYE: SHOW WHAT YOU TYPED (2026-11-06)
==============================================================================
 1. EYE BUTTON ON EVERY PASSWORD BOX. Every box where you type a
    password now has a small eye button at its right end: the login
    page (Password), the Change password page (Current password, New
    password, New password again), and the "Your password to confirm"
    box that appears on admin actions (reset a password, delete an
    account, remove a department or a column, and the same box on the
    Edit user page).
 2. TAP TO SHOW, TAP AGAIN TO HIDE. Tapping the eye shows the
    password as plain text and the eye changes to an eye with a slash
    across it. Tapping it again hides the password back to dots. The
    password starts hidden every time the page opens, and showing it
    changes nothing else: the password is only shown on your own
    screen, it is not saved or sent any differently, and the eye
    button never submits the form.
 3. TEMPORARY PASSWORD BOXES UNCHANGED. When an admin creates a user,
    the "Temporary password" box already shows the password as plain
    text (so the admin can read it back to the user), so it has no
    eye button. The eye follows the portal's light and dark themes.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

==============================================================================
 38. DESIGN 6: NEW PAGE LAYOUT — KPI CARDS, CHART AND RIGHT RAIL (2026-11-06)
==============================================================================
 1. EVERY PAGE EXCEPT LOGIN HAS THE NEW LAYOUT. This is the Design 6
    layout you approved from the 32 JPG concepts (Command Center +
    Activity Rail combined): a row of KPI cards at the top, the page's
    main content on the left, and a 330px rail on the right. The
    colours are the portal's own (deep teal-blue, cyan, pale blue-grey
    background, Manrope font) — nothing was re-coloured. The LOGIN
    PAGE IS UNCHANGED, exactly as it is now.
 2. NOTHING WAS REMOVED. Every tab, filter, button, form field, table
    column, link and permission is exactly where it was, only the
    layout around it changed. The Department Database still has Select
    / Select all, the print guard and the landscape print; the
    Invoices tab still has its sub-tabs, share codes and Create cards;
    My records still has Mine / Shared by me / Shared with me / My
    department with Locate; the dashboard still has its "See all"
    link to the Sessions page; the password eye is still on every
    password box.
 3. KPI CARDS. The top row shows the counts that matter on that page:
    Department Database shows Total rows, My rows, Follow-ups due and
    Deleted; the Invoices tab shows All invoices, My invoices, Issued
    and Paid; the Dashboard shows Total records, Active users, Open
    repairs, Reminders and Logged in now; Users shows Users, Pending
    approval, Locked and Admins; and so on. Each card's number comes
    from data the page already had.
 4. THE CHART. The Department Database has a "Rows added this week"
    bar chart (rows created each day for the last 7 days, tallest day
    highlighted). The Dashboard's "Records by department" is now the
    same vertical bar chart instead of horizontal bars. Both use the
    portal's own colours.
 5. THE RIGHT RAIL. On list and detail pages the rail shows:
    - Follow-ups due: meetings in this department in the next 7 days
      (a date+time column in a meeting-notify tab), with the date and
      time, linking to the row.
    - Recent activity: the most recently changed rows in this
      department, with who changed them and when, linking to the row.
    - Quick actions: the page's main actions (Add row, Export to
      Excel, Print this tab, and so on).
    Everything in the rail is data that user is already allowed to
    see — a regular user only ever sees their own department's rows
    and meetings, never another department's.
    Detail pages keep their own side cards in the rail: the record
    detail keeps its Public QR, Shared with and Admin cards; the
    invoice detail keeps its Public QR card and a Details card. Form
    pages have a short explainer card in the rail instead.
 6. PRINTING IS UNCHANGED. The KPI row and the rail are hidden when
    printing, so a printout still shows only the table (and the
    Select/print guard still works: Print with nothing selected shows
    "Please select the data row first."). On a narrow screen (phone
    or tablet) the rail stacks below the main content, as the
    portal's other two-column pages already do.
 7. A LATENT CRASH WAS FIXED ALONG THE WAY. The portal admin's
    Dashboard would crash (500) whenever any record reminder was due,
    because routes_admin.py used datetime.strptime without importing
    datetime. It never fired before because no reminder date had come
    due in testing. The import is fixed (one word); nothing else
    about reminders changed.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 39. DASHBOARD SETTINGS + DEPARTMENT DATABASE WIDGET + FILLED PIE CHARTS (2026-11-06)
==============================================================================
 1. DASHBOARD SETTINGS BUTTON. Top right of the Dashboard, next to
    Reports / Export Excel / + Add record, there is now a "Dashboard
    settings" button. It opens a panel with a tick box for each
    dashboard section: KPI cards, Records by department, Department
    database, Records by status, Recent activity, Logged in now,
    Reminders coming up and Quick actions. Unticking a section hides
    it from YOUR dashboard. The setting is saved per admin (each
    admin's own login): hiding a section on your login does not hide
    it for anyone else. Tick everything back on to bring a section
    back. Nothing is deleted — a hidden section is only hidden.
 2. DEPARTMENT DATABASE WIDGET. A new section on the Dashboard,
    "Department database", right after "Records by department". For
    each department it shows the total Department Database rows, and
    underneath, each tab's row count (Client Info 3, Meetings 1,
    Invoices 2, and so on). The Invoices tab is counted too: the
    total is all the department's DeptDB rows plus its invoices.
    Only tabs that have rows are listed; a department with no rows
    shows nothing in the breakdown. The numbers come from the live
    Department Database, so the widget always matches it.
 3. EACH DEPARTMENT HAS ITS OWN COLOUR. In both department charts
    the bars/slices are coloured per department, from the portal's
    chart colours (teal, green, amber, red, purple, grey-blue). A
    department keeps the same colour in both charts and every time
    you look, even when the counts change. The "Records by status"
    chart keeps its existing colours (by status, not by department).
 4. BAR / PIE CHART SWITCH. In the Dashboard settings panel, under
    "Records by department" and under "Department database", there
    is a Bar | Pie chart switch for each chart, set independently.
    Bar shows the vertical bars (as before, now in each
    department's colour). Pie chart shows a big filled pie: each
    slice is its department's colour, and the count is written on
    the slice in white (white is the ink that reads on every slice
    colour — the department's own colour on its own slice would
    disappear into it). Under the pie, the legend shows each
    department with its count in that department's colour, and the
    Total at the end. "Records by status" is now the same filled
    pie, the same size, so all three charts match.
 5. NOTHING ELSE CHANGED. The login page is unchanged. Every other
    page, tab, filter, button and permission is exactly as it was.
    The dashboard still has its "See all" links, Select / Select
    all and the print guard are untouched, and the password eye is
    still on every password box. The KPI row and the rail are still
    hidden when printing.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   The upgrade creates one new table (dashboard_settings) for the
   per-admin settings; your data and the live .env are not touched.
   Apply only this latest zip, not the older ones in order.

 40. NOTIFICATION MESSAGES BIGGER (2026-11-07)
==============================================================================
 1. The message text on the Notifications page is now bigger
    (1.05rem, with more space between the lines) so it is easy to
    read at a glance. The date in the "When" column, the "New"
    badge, the KPI cards and everything else on the page are
    unchanged. This is the same for every user: the Notifications
    page is one page, and the bigger message text applies to
    everyone who opens it.
 2. NOTHING ELSE CHANGED. No other page, table or permission was
    touched.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 41. LOGIN PAGE REDESIGNED — FROST 6 (2026-11-07)
==============================================================================
 1. The login page has a new look, Frost 6, the frosted-glass design
    you picked from the JPG: the whole page is the teal gradient
    with soft round shapes behind it, the sign-in form sits in a
    frosted-glass card on the left, and your own words sit on the
    right — "Every asset, one clear place." with the description
    and the three points (Department workspaces, Secure sharing,
    Full edit history) as small pills.
 2. NOTHING ABOUT SIGNING IN CHANGED. The same username, password
    and department boxes, the same department list (including
    "All departments (admin only)"), the same Sign in button, the
    same password eye, the same "Forgot your password?" line and
    the same Appearance selector below the card. Wrong passwords,
    wrong departments, locked accounts and forced password changes
    all behave exactly as before.
 3. The frosted card always looks the same — light glass on the
    teal gradient — whichever Appearance (Auto / Light / Dark) you
    use, so the login page looks identical for everyone.
 4. On a narrow screen (phone or narrow window) the text on the
    right hides and the frosted card takes the whole width, as
    the old login page did.
 5. NOTHING ELSE CHANGED. No other page, table or permission was
    touched.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 42. CSS CLEANUP — MUTED TEXT FIX + DEAD RULES REMOVED (2026-11-07)
==============================================================================
 1. The tab breakdown in the Dashboard's "Department database"
    widget (the "— Client Info 12 · Meetings 3" part after each
    department name) is now muted grey, as it was meant to be. It
    was showing in the same dark colour as the department name
    because the "mut" style it uses had no rule in the stylesheet.
    A new .mut rule (the portal's muted text colour) fixes it.
    Nothing else on the Dashboard changed.
 2. Five rules that nothing uses were removed from the stylesheet:
    the old bar-chart row, the old donut chart and its legend, an
    old two-column grid, and a print-hide entry for a class no
    element carries. The old "grow" animation went with the bar
    chart, since nothing else used it. This only makes the
    stylesheet smaller; no page looks or behaves differently.
 3. NOTHING ELSE CHANGED. No page, table or permission was touched,
    and the login page is exactly as it was.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 43. DASHBOARD VALUES + SETTINGS SAVE FIX + NOTIFICATIONS LINES & SELECT
     + MY RECORDS RAIL + PRINT FIX + PORTAL-ADMIN DEPT SWITCH (2026-11-08)
==============================================================================
 1. Dashboard charts now show the value. In "Records by department"
    and in "Department database", the count is printed in bold above
    each bar (0 shows as 0), so you can read how many records each
    department added without guessing from the bar height. The pie
    view is unchanged (it already showed the counts in its legend).
    Nothing else on the Dashboard changed.
 2. Dashboard settings Save works again. Saving any dashboard
    setting used to fail with the "400 — This page has expired"
    error. The settings form was the only form in the portal that
    sent the security token's name instead of the token itself, so
    the server rejected every save. That one line is fixed; changing
    a tick box or a Bar/Pie switch and clicking Save now applies it
    and returns to the Dashboard. No other form was touched.
 3. Notifications table has no visible lines any more. The Message /
    When table on the Notifications page (the same page every user
    sees) no longer shows the lines between the rows. Other tables
    in the portal keep their lines; only this table changed.
 4. Notifications Select now shows the tick boxes. Clicking Select
    (it becomes Cancel, and Mark as read / Clear appear) now really
    shows a tick box on the left of every notification, so you can
    tick just the ones you want and then Mark as read or Clear only
    those. The boxes were in the page but a stylesheet rule kept
    hiding them after the script ran; the script now sets them to
    show properly. Clicking Cancel hides them again. Mark all as
    read and Clear all are unchanged.
 5. My records is simpler. The "Follow-ups due" and the "Recent
    activity" cards are removed from the My records page (both the
    main view and the "My department" tab), for all users. Quick
    actions stays. Follow-ups due and Recent activity are
    Department Database activity, and they stay on the Department
    Database page, the Dashboard and the Notifications page.
 6. Printing the Department Database is fixed. (a) The right-hand
    cards (Follow-ups due, Recent activity, Quick actions) no
    longer print — they were slipping through because a print rule
    that lays the page out was overriding the rule that hides them.
    (b) The print table's headings and data now line up: long
    headings wrap instead of spilling into the next column, and
    the cells have tighter padding so there is room. (c) All
    columns print and fit: the table keeps its fixed layout with
    the per-column widths, text wraps inside its cell, and the
    table no longer clips at the side. The "Selected rows" line,
    the print header and the landscape page are unchanged.
 7. The portal admin can switch departments again. The Department
    dropdown on the Department Database page is back and is always
    visible for the portal admin (and for a permission user), even
    when the admin's own department has no tabs yet — before, it
    was hidden inside the "this department has a tab" block, so an
    admin whose own department had no tabs had no way to switch
    and could not open another department's database at all. The
    dropdown sits under the page heading; picking a department
    shows that department's tabs, rows and invoices, and it stays
    on that department when paging or changing tabs. Regular users
    and dept admins never see the dropdown, as before.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 44. BIG BOX FIX + PRINT ALIGNMENT + NOTIFICATION LINES + FOLLOW-UPS /
     RECENT ACTIVITY ONLY ON DEPARTMENT DATABASE (2026-11-08)
==============================================================================
 1. The big empty box on the Sessions page and the Users page is
    gone. It was the small blue pill ("This is you" on Sessions;
    "Admin" and "Department admin" on Users) blown up to 380 by
    380 pixels. The login page's three decorative circles were
    named .b1, .b2 and .b3 in the stylesheet, and that bare .b2
    name also matched the pill, so every pill got the circle's
    size. The circles are now named .blob.b1, .blob.b2 and .blob.b3,
    so they only apply to the login page. The login page keeps its
    circles, and the pills are their normal small size again on
    every page that uses them (Sessions, Users, record details,
    public view, departments, columns).
 2. Printing the Department Database lines the headings up with
    their data. The table now has a column guide, so every
    column's width is set once for the whole table and the heading
    and the data under it share it, instead of the width coming
    only from the heading row. The print headings are now the same
    size as the data (8.5 pt), so short headings fit on one line
    more often instead of breaking onto two lines. The right-hand
    cards still do not print, all columns still print, and the
    "Selected rows" line and landscape page are unchanged.
 3. The Notifications table is now completely flat. Taking the
    border off was not enough: the table also shaded every second
    row, and the edge between a white row and a shaded row still
    showed as a line. The shading (and the shading on hover) is
    now off for this table only, so the messages sit on one plain
    background with nothing between them. Other tables keep their
    lines and shading.
 4. "Follow-ups due" and "Recent activity" are now only on the
    Department Database page. They were in the side panel of
    almost every page (Sessions, Users, Notifications, record
    pages, invoice pages, settings and more). Both cards are
    removed from all of those pages and stay only on the
    Department Database page (and its Invoices tab), where they
    belong. The Dashboard's own "Recent activity" section is a
    dashboard overview, not one of these cards, so it stays and
    can still be hidden from the Dashboard settings.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 45. NOTIFICATION LINES REALLY GONE + STYLESHEET CACHE FIX (2026-11-08)
==============================================================================
 1. Why the lines were still there after the last build. The last
    build only took the top border off the cells
    (.tb.notif td{border-top:0}), but the lines were not coming
    from that border at all. The message cell in the table carries
    class="msg" (added so the message text is bigger), and the
    stylesheet also uses .msg for the flash-message box, which has
    border:1px solid (a full border on all four sides, in the dark
    text colour). So every message cell was drawn inside its own
    dark box: the left and right edges and the bottom edge came
    from that flash-message border, and in a collapsed table the
    bottom edge of one cell shows as the line under it. Taking
    only the top border off could never remove those edges.
    That is also why the lines looked dark instead of the pale
    table-line colour.
 2. The fix is to take the whole border off the notification
    table cells: .tb.notif td{border:0} in the stylesheet, which
    removes the flash-message border and the table's own top
    border together. The bigger message text is untouched (it
    comes from a separate .tb td.msg font-size rule, not from the
    border). The messages now sit on one plain background with
    no lines between them. Other tables keep their lines and
    shading, and the flash-message box keeps its border.
 3. As a guarantee, the Notifications page now also carries the
    flat-table style inside the page itself (a small <style> block
    in templates/notifications.html, using the {% block head %}
    slot). It sets the same three rules as the stylesheet: no
    border on the cells, no shading on alternate rows, no shading
    on hover. Because it is part of the page, it applies even if
    the browser is still holding an old copy of style.css.
 4. The stylesheet now also has the same cache protection as the
    logo, so a future stylesheet fix cannot sit unseen behind a
    saved copy. The page loads style.css with a version number
    taken from the file's own change time (app.py inject_common
    computes css_v from the modification time of
    static/style.css, and base.html loads
    /static/style.css?v=<that number>). Whenever style.css
    changes, the address changes too, so the browser fetches a
    fresh copy instead of reusing the saved one. This applies to
    every page, so any future stylesheet fix takes effect right
    after the build is applied, with no cache clearing needed.
 5. NOTHING ELSE CHANGED.

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 46. DASHBOARD "RECENT ACTIVITY" REMOVED — IT LIVES ONLY ON DEPARTMENT DATABASE (2026-11-08)
==============================================================================
 1. Follow-ups due and Recent activity now live only on the
    Department Database page, with no exception. The Dashboard's
    own "Recent activity" overview section is gone: it showed the
    latest activity-log entries on the Dashboard, which is not
    the Department Database page, so it did not belong there
    under the rule that these two belong only on Department
    Database. The section is removed from the Dashboard
    (templates/admin_dashboard.html), and its tick box is removed
    from the Dashboard settings panel, so there is no way to turn
    it back on. The setting itself is removed too: "recent" is
    out of core.DASHBOARD_SECTIONS (so it leaves the defaults),
    and the settings save route no longer writes a show_recent
    value. A previously saved show_recent value is simply
    ignored, never an error, and no database change is needed.
 2. What stays: the Recent activity card in the Department
    Database page's right rail (templates/_design6.html
    recent_card, called only from deptdb.html and
    deptdb_invoices.html), and Follow-ups due in the same rail.
    The Dashboard keeps everything else: KPI cards, Records by
    department, Department database, Records by status, Logged
    in now, Reminders coming up and Quick actions, with the same
    settings, colours and Bar/Pie switches. The Activity page
    (/admin/activity) is untouched — it is a full page of its own,
    not the Dashboard section.
 3. NOTHING ELSE CHANGED. This build also carries the whole of
    build 26 (notification lines really gone, stylesheet
    cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 47. NOTIFICATION LINES GONE AT THE SOURCE — MESSAGE CELL NO LONGER SHARES THE FLASH-MESSAGE CLASS (2026-11-08)
==============================================================================
 1. Why the lines were still showing. Build 26 took the whole
    border off the notification table cells (.tb.notif
    td{border:0}), which removes the border in the stylesheet.
    But the message cell itself still carried class="msg", the
    same class the flash-message box uses, so the cell still
    matched the .msg rule (border:1px solid) and a saved or
    slow-loading stylesheet could still draw the box around
    every message. Overriding the border was not enough; the
    cell should never have shared that class at all.
 2. The cell no longer shares the class. The message cell in
    templates/notifications.html is now <td class="nmsg">, and
    the bigger-text rule in the stylesheet is now
    .tb td.nmsg{font-size:1.05rem;line-height:1.5}, so the
    message text is exactly as big as before. The .msg rule
    itself is untouched and still gives the flash-message box
    (and the "Public QR is ON/OFF" and "Please select the data
    row first" messages) its border. The .tb.notif td{border:0}
    rule and the inline flat-table style on the Notifications
    page stay in place as a safety net, and the stylesheet
    version (css_v) stays too. The messages now sit on one plain
    background with no lines between them, in every browser, with
    no dependence on which copy of the stylesheet loads first.
 3. NOTHING ELSE CHANGED. This build also carries the whole of
    build 27 (Dashboard Recent activity removed) and build 26
    (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 48. LOGIN HEADING: "WELCOME BACK" BECOMES "WELCOME" (2026-11-08)
==============================================================================
 1. The heading inside the frosted card on the login page now
    reads "Welcome" instead of "Welcome back"
    (templates/login.html). One word changed, nothing else: the
    sign-in hint, Username, Password, Department select, Sign in
    button, Appearance selector, hero text and pills on the right,
    and the login behaviour (CSRF, errors, department validation,
    lockout, forced password change) are all unchanged.
 2. NOTHING ELSE CHANGED. This build also carries the whole of
    build 28 (notification lines gone at the source), build 27
    (Dashboard Recent activity removed) and build 26 (stylesheet
    cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 49. REQUEST ITEMS — DEFAULT TAB IN DEPARTMENT DATABASE (2026-11-08)
==============================================================================
 1. A new default tab "Request items" inside Department Database, always
    there for every department (like Invoices), cannot be deleted or
    customised. Sub-tabs: My request, All request, Other's request.
 2. Item Request kind (new file routes_requests.py, templates
    request_kinds.html / request_kind_form.html): the dept admin makes the
    format for request items, just like invoice templates (dept-admin-only
    page). Fields: kind name, number prefix (REQ), default currency,
    company name / address, show address, two logos, notes, signatures,
    status (active / draft). The dept admin can add as many signature
    blocks as he wants ("+ Add signature" adds a row). A "Create starter
    kind" button makes an "Office Supplies Request" kind (REQ, BDT,
    Requested by / Received by / Approved by). The kind appears as a
    Create card in the Request items tab, so a user can make a request
    from there. New tables: item_request_kinds, item_requests,
    item_request_lines (models.py).
 3. Creating and sending a request (templates/request_form.html): a user
    picks a kind, adds items (Description / Qty / Rate / Amount, live
    totals, amount in words, one currency, no tax), and sends it to ONE
    specific user. The recipient can ONLY be a user in the HR & Admin
    Department (the dropdown lists only active, approved HR & Admin
    users; any other recipient is refused). Sending gives the request a
    number (REQ-0001, sequential per kind, never reused) and the status
    Pending, and notifies the recipient. The request then appears in the
    recipient's "Other's request" sub-tab.
 4. The recipient can print the request and download its PDF, and can
    change its status: Pending, Issued, Paid, Handovered (detail page,
    recipient only — POST /requests/<id>/status). When the status
    changes, the creator is notified and can see the new status in "My
    request". The creator can also print and download the PDF.
 5. All request visibility: the portal admin, administrative permission
    users and HR & Admin Department users see ALL departments' requests;
    users of other departments see only their own department's requests.
    Filter is BOTH department and status, with a search bar — anyone can
    search by name (creator, recipient, kind) or Department, and only
    matching records appear. The department filter is shown only to
    users who see all departments.
 6. Request document (exports.request_pdf, format approved in
    item-request-format-v3.jpg): two logos on the two top corners (HRC
    logo top-left with company + address, second logo top-right — the
    portal logo fills the right corner when the kind has no right logo),
    "Item Request" centred at the top with the kind name under it,
    coloured rule, Request No. / Date / Status and Requested by /
    Department / Requested to, kind name on top of the table, Qty / Rate
    / Amount with the currency beside every amount, Subtotal and Grand
    Total, amount in words, signatures lower on the page (a bigger gap
    than on an invoice) with as many blocks as the dept admin set, QR
    (1.9 cm) and "Share code: HRC-#####" at the very bottom left of
    every page and "Page 1" at the bottom right.
 7. Public QR (like invoices): a request can get a public QR — random
    HRC-##### code, turn on / off / new scan link (regenerating kills
    the old code). Searching the code, viewing it and downloading its
    PDF all need a login (routes /requests/code/<code> and
    /requests/code/<code>/pdf). The Request items tab is exempt from
    the DeptDB share-code redirect, like the Invoices tab.
 8. NOTHING ELSE CHANGED. This build also carries the whole of build 29
    (login heading "Welcome"), build 28 (notification lines gone at the
    source), build 27 (Dashboard Recent activity removed) and build 26
    (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (new tables are
   created automatically on first start). Apply only this
   latest zip, not the older ones in order.

 50. REQUEST ITEMS — KIND NAME OFF THE DOCUMENT (2026-11-08)
==============================================================================
 1. The Item Request document (PDF) no longer shows the kind name at
    all — neither as the small line under "Item Request" at the top, nor
    as the heading above the table. The document is just "Item Request",
    then the request number, the table, and the rest (exports.request_pdf
    and routes_requests._build_pdf). The kind name still appears in the
    Request items tab, on the Create card, so a user can pick which kind
    to make a request from — it is only the printed document that no
    longer carries it.
 2. The Request items tab's top heading cards (All requests, My
    requests, Pending, Handovered) already use the exact same code as
    the Invoices tab, so in a real browser they sit side by side in one
    row, like the Invoices tab. No code change was needed there — the
    stacked look in the build-30 proof JPG was a fault of the picture
    tool (WeasyPrint cannot do the auto-fit grid, so it stacks the
    cards in the picture only).
 3. NOTHING ELSE CHANGED. This build also carries the whole of build 30
    (Request Items) and build 29 (login heading "Welcome"), build 28
    (notification lines gone at the source), build 27 (Dashboard Recent
    activity removed) and build 26 (stylesheet cache-busting, inline
    flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (the request tables
   are created automatically on first start). Apply only this
   latest zip, not the older ones in order.

 51. REQUEST ITEMS — EDIT, EDIT LOG AND UPDATES (2026-11-08)
==============================================================================
 1. The owner (the user who made the request) AND the recipient (the
    HR & Admin user it was sent to) can now both edit the request.
    An "Edit" button sits on the request detail page for both of them.
    Only the items (description, qty, rate — add, remove or change
    lines) and the notes can be changed. The request number, the date,
    the kind and the recipient stay the same and are not editable.
    Saving recalculates the totals and the amount in words, and the
    PDF shows the updated values. Nobody else can edit — not the portal
    admin, not other users in the department (they get a 403).
 2. The status is still changed only by the recipient (Pending, Issued,
    Paid, Handovered), as before. The owner cannot change the status.
 3. Updates on the notification page: when the recipient edits the
    request or changes its status, the owner is notified; when the
    owner edits the request, the recipient is notified. Each
    notification links to the request.
 4. Edit log in activities: every edit is written to a new
    item_request_history table — who edited it, when, and what changed,
    line by line (old value struck through, new value beside it), plus
    the creation of the request as the first entry. The log shows as an
    "Edit history" section on the request detail page, in the same style
    as the record edit history, and every edit is also written to the
    portal Activity log (action "request_edit"), so the portal admin
    can see it on the Activity page.
 5. NOTHING ELSE CHANGED. This build also carries the whole of build 31
    (kind name off the request document), build 30 (Request Items),
    build 29 (login heading "Welcome"), build 28 (notification lines
    gone at the source), build 27 (Dashboard Recent activity removed)
    and build 26 (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (the edit-log table
   is created automatically on first start). Apply only this
   latest zip, not the older ones in order.

==============================================================================
 52. SEARCH QR LOOKS ALL OVER, PUBLIC QR FOR EVERY DEPARTMENT DATABASE ROW,
     REQUEST ITEM NAME, OTHER'S REQUEST ONLY FOR HR & ADMIN, DEPARTMENT
     DATABASE PRINT FIXED (2026-11-09)
==============================================================================
 1. Search QR looks all over for the entered code. Typing a code in the
    Search QR page now searches everywhere a public code can live — a
    record link, an invoice, an item request, or a Department Database
    row — and opens whichever one matches. Before this, a request's
    public code (for example HRC-96531) was never found and the page
    said "This QR code is not available", because the search only looked
    at record links and invoices. A code typed in a Department Database
    tab's search box now also goes to the Search QR page (it used to go
    straight to the record-only code page and miss invoice, request and
    row codes).
 2. Public QR generation for every Department Database tab's rows. Until
    now only the Invoices tab and the Request items tab had a public QR.
    Now every row in every tab (Client Info, Meetings, Employee Info,
    Billing, Accounts and any custom tab) can generate a public QR:
      - a "Public QR" panel on the row detail page, in the same style as
        the invoice and request panels: Turn on / Save, Turn off, and
        New scan link (which kills the old printed QR's code), with the
        QR image, the share code (HRC-#####) and the view count;
      - the row's owner, or a department admin / delegate / portal
        admin, can change it; anyone else sees the panel but no buttons
        (a non-manager who posts to it gets a 403);
      - scanning the QR or searching the code opens the row's public
        page (login-only), with a Download PDF button, and the Search QR
        page finds the row's code too;
      - new columns on ddb_rows: public_code, public_enabled and
        public_views (added automatically on first start, existing rows
        are untouched).
    All public codes are now unique across records, invoices, requests
    and rows: the code generators check all four places, so a code can
    never belong to two things at once.
 3. Request items are now Item name, Description, Quantity, Rate (BDT).
    Each item line has four fields: Item name, Description, Quantity and
    Rate (BDT). The Amount is still worked out from Quantity x Rate and
    shown beside the Rate. The Item name is saved per line (new column
    item_request_lines.item_name), and shows on the create form, the
    edit form (pre-filled), the request detail page, the request code
    page and the request PDF (the PDF table is now #, Item name,
    Description, Qty, Rate, Amount, with Item name and Description
    given the most room). The edit log uses the item name as the field
    name (falling back to the description when a line has no item
    name). Old requests without an item name still open and print
    normally, with the Item name column empty.
 4. The "Other's request" sub-tab is only for HR & Admin users. Only an
    HR & Admin user can ever receive a request, so for everyone else the
    sub-tab was always empty. It now appears only when the current user
    is in the HR & Admin department. "My request" and "All request" are
    unchanged, and a bookmarked Other's request link just shows All
    request for a user who may not see it.
 5. Department Database print is fixed. The printed table (the one from
    the Print button on a tab) now uses reliable fixed column widths:
    the widths are written directly on the table's columns instead of
    through a CSS variable that Chrome print did not apply, the
    tick-box and actions columns take no width in print, and long
    values (emails, addresses) wrap inside their own column instead of
    pushing the other columns over. Every field fits on the landscape
    page, and each heading lines up with its own column's content.
    The screen table is unchanged — the print widths are neutralised on
    screen, so the on-screen columns still size by their content.
 6. NOTHING ELSE CHANGED. This build also carries the whole of build 32
    (request editing and edit log), build 31 (kind name off the request
    document), build 30 (Request Items), build 29 (login heading
    "Welcome"), build 28 (notification lines gone at the source),
    build 27 (Dashboard Recent activity removed) and build 26
    (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update (the new columns
   are created automatically on first start). Apply only this
   latest zip, not the older ones in order.

 53. DEPARTMENT ADMIN NOTIFICATIONS FOR INVOICES AND REQUESTS, PRINT
     ALIGNMENT FIXED, DEPARTMENT FILTER REMOVED FROM REQUEST ITEMS TAB
     (2026-11-09)
==============================================================================
 1. The department admin is now told about everything the users in
    their department do in the Department Database. Before this, a user
    could create an invoice or send an Item Request and their
    department admin heard nothing. Now the dept admin is notified when
    a user in their department creates an invoice draft, finalises
    (issues) an invoice, sends an Item Request, or edits a request —
    and when a request from their department has its status changed.
    Marking an invoice Paid or Void already told the dept admin, and
    that is unchanged. The notifications the recipient and the creator
    already got (recipient on send, creator on status change and edit)
    are unchanged. A dept admin is never told about their own action,
    and a true portal admin's own actions still tell nobody. The
    "Who gets told what" help card on the Notifications page is updated
    to say the same, so it no longer says creating a draft or
    finalising tells nobody.
 2. Department Database print alignment is fixed at the real cause.
    Build 33 fixed the column widths, and the columns do size correctly
    in Chrome — but the values still sat to the right of their headings.
    The cause was the mobile card-view rule, which right-aligns table
    values on a small screen; it was leaking into print because the
    print style never set a text alignment, so the data printed
    right-aligned while the headings stayed left-aligned. The print
    style now sets the table cells left-aligned, so every heading
    lines up with its own column's content. Judge the print in real
    Chrome — the render pictures cannot show this.
 3. The extra Department dropdown is gone from the Request items tab.
    The tab had two department controls: the Department dropdown at
    the top and the "All departments" filter in the filter row. The
    top dropdown is removed; the "All departments" filter stays, so
    requests can still be filtered by department. The Invoices tab
    and the other Department Database tabs keep their Department
    dropdown.
 4. NOTHING ELSE CHANGED. This build also carries the whole of build 33
    (Search QR looks all over, public QR for every row, request Item
    name, Other's request only for HR & Admin, print column widths),
    build 32 (request editing and edit log), build 31 (kind name off
    the request document), build 30 (Request Items), build 29 (login
    heading "Welcome"), build 28 (notification lines gone at the
    source), build 27 (Dashboard Recent activity removed) and build 26
    (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order.

 54. APPROVED WATERMARK SEAL, QR SCAN FIX, THIRD SIGNATURE, NEW INVOICE
     AND REQUEST FORMAT, AND APPROVED INVOICE STATUS (2026-11-09)
 1. The watermark is now a grey APPROVED seal, not the big diagonal
    green "Approved" text. When the watermark text is Approved, the
    seal (a new file, static/approved-seal-grey.png) is drawn at the
    bottom right of the invoice PDF, in the empty space below the
    signatures, 55 mm across. Any other watermark text still draws
    the old diagonal green text.
 2. Scanning a public QR now works. The printed QRs used to encode
    the address https://portal, which no phone can open — that was
    the error after scanning. The QR now encodes the portal's real
    address. A new setting, Portal settings -> "Public portal
    address", holds that address (for example
    http://192.168.1.116:8100); set it once after upgrading, or the
    QR falls back to the address the portal is reached on. The QR
    on screen and the QR printed on a PDF both use it.
 3. The code pages no longer need a login. Anyone who scans a QR can
    now see the record, invoice, Item Request or Department Database
    row behind it, and download its PDF, without signing in. The
    Search QR page is public too. (A record's code page still shows
    only the fields the owner made public; the "View full record"
    button appears only for a signed-in user who may see it.)
 4. Every signature on an invoice template now prints. Only the
    first two used to print; the third (for example Authorized By)
    was dropped. All of them print now, the owner's own signature
    first as Prepared By.
 5. The invoice and Item Request PDFs have the new format. The
    company name and address are centred at the top. On the left,
    stacked, are Invoice No. (or Request No.), Reference / PO (only
    when the user filled it in — it is hidden everywhere when it is
    empty), and Bill to (or Requested by / Department / Requested
    to). The Date is on the right (with the Status on a request).
    The title (INVOICE / Item Request) sits above the table.
 6. There is no text at the bottom between the QR code and the page
    number any more. The bottom has only the QR with "Share code:
    HRC-#####" on the left and "Page N" on the right, on every page.
 7. The amount in words now reads the currency before Only, for
    example "One Hundred Eighty Taka Only" (not "Taka One Hundred
    Eighty Only"). The same change is in Item Requests.
 8. Signatures have the new layout on both documents. The title
    (Prepared By / Checked By / Approved / Authorized By) is on top,
    then a gap to sign in, then the line, then the name centred
    under the line, then the designation centred under the name.
    The title, the name and the designation are all centred in
    respect to the name. The designation is the one typed in the
    template's Designation box.
 9. NEW — the owner can set an invoice's status to Approved, and
    the grey APPROVED seal then appears on its PDF. Two ways:
    while editing a draft, the Status field on the invoice form can
    be set to Approved; on an issued invoice, the "Mark as
    approved" button on the invoice detail page sets it. An
    approved draft can still be finalised, and it keeps its
    Approved status (and its seal) when it gets its number. An
    approved invoice can be marked Paid or Void, and it can also
    get a public QR. The department admin is told when an invoice
    is approved, the same as when it is finalised or marked Paid.
    The Invoices tab has an Approved status filter and an Approved
    count, and Approved shows as a green pill.
 10. One fix found while checking the request PDF: its Date and
    Status were drawn past the right edge of the page and were cut
    off. They now sit inside the page, on the right, as intended.
 11. NOTHING ELSE CHANGED. This build also carries the whole of
    build 34 (dept-admin notifications for invoices and requests,
    print alignment, Department dropdown removed from the Request
    items tab), build 33 (Search QR looks all over, public QR for
    every row, request Item name, Other's request only for HR &
    Admin, print column widths), build 32 (request editing and edit
    log), build 31 (kind name off the request document), build 30
    (Request Items), build 29 (login heading "Welcome"), build 28
    (notification lines gone at the source), build 27 (Dashboard
    Recent activity removed) and build 26 (stylesheet
    cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   phones can reach. QR links work for anyone on the office Wi-Fi
   or LAN; a phone on mobile data cannot reach a 192.168 address.

 55. SINGLE-LINE META, SIGNATURE ALIGNMENT BY COUNT, MARK APPROVED /
     MARK PENDING AND PENDING SEAL (2026-11-09)
 1. The invoice and Item Request meta is now one field per line, not
    label above value. On an invoice: "Invoice No. - JOY-0001" on one
    line, then "Reference - HRC/PO/" under it (only when filled in),
    then "Bill to - HRC Technologies Limited" under that; on the
    right, "Date - 2026-11-09" on one line. On a request: "Request
    No. - REQ-0003", then "Requested by", "Department" and "Requested
    to" under it; on the right, "Date" and "Status" on one line each.
    Nothing else in the header changed.
 2. Signatures are now aligned by how many there are, on invoices and
    on Item Requests. One signature sits at the left of the page, not
    in the middle. Two sit one at the left and one at the right.
    Three sit at the left, the centre and the right. Four spread
    evenly across the page. (More than four wrap in groups of four.)
    Inside each block the title, the name and the designation stay
    centred in respect to the name, as before.
 3. NEW — the owner marks an invoice Approved or Pending, and a seal
    shows on its PDF. The "Mark Paid" button is gone: in its place
    the invoice detail page has "Mark approved" and "Mark pending".
    Mark approved sets the status to Approved and the grey APPROVED
    seal appears on the PDF. Mark pending sets the status to Pending
    and a new grey PENDING seal (static/pending-seal-grey.png, same
    place and size as the APPROVED seal) appears instead. A pending
    invoice can be marked approved again, and an approved one can be
    marked pending. The Status field while editing a draft now has
    Draft, Approved and Pending. A pending draft can still be
    finalised and keeps Pending (and its seal) when it gets its
    number. A pending invoice can be voided and can get a public QR.
    The department admin is told when an invoice is approved or
    marked Pending, the same as when it is finalised. The Invoices
    tab has a Pending status filter and a Pending count, and Pending
    shows as an amber pill. Invoices that were already marked Paid
    keep that status and still show in the Paid filter and count, but
    no invoice can newly be marked Paid.
 4. The template watermark works the same way for Pending: if the
    template's watermark text is "Pending", the grey PENDING seal is
    drawn instead of the diagonal text.
 5. NOTHING ELSE CHANGED. This build also carries the whole of build
    35 (APPROVED seal, QR scan fix, third signature, new invoice and
    request format, Approved invoice status), build 34 (dept-admin
    notifications for invoices and requests, print alignment,
    Department dropdown removed from the Request items tab), build
    33 (Search QR looks all over, public QR for every row, request
    Item name, Other's request only for HR & Admin, print column
    widths), build 32 (request editing and edit log), build 31
    (kind name off the request document), build 30 (Request Items),
    build 29 (login heading "Welcome"), build 28 (notification lines
    gone at the source), build 27 (Dashboard Recent activity removed)
    and build 26 (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   phones can reach. QR links work for anyone on the office Wi-Fi
   or LAN; a phone on mobile data cannot reach a 192.168 address.

 56. PENDING WATERMARK USES THE USER'S GREEN STAMP (2026-11-09)
 1. The Pending watermark is now the green rectangular PENDING stamp
    the user supplied (static/pending-stamp.png), drawn at the bottom
    right of the invoice PDF, 7.5 cm wide, in the empty space below
    the signatures. It replaces the grey circular PENDING seal from
    build 36 (static/pending-seal-grey.png is removed). The stamp's
    black background was removed so only the green stamp shows.
    Nothing else changed: the stamp still appears when the owner
    marks an invoice Pending (or when the template's watermark text
    is Pending), and the grey APPROVED seal is unchanged.
 2. NOTHING ELSE CHANGED. This build also carries the whole of build
    36 (single-line meta, signature alignment by count, Mark
    approved / Mark pending, PENDING status), build 35 (APPROVED
    seal, QR scan fix, third signature, new invoice and request
    format, Approved invoice status), build 34 (dept-admin
    notifications for invoices and requests, print alignment,
    Department dropdown removed from the Request items tab), build
    33 (Search QR looks all over, public QR for every row, request
    Item name, Other's request only for HR & Admin, print column
    widths), build 32 (request editing and edit log), build 31
    (kind name off the request document), build 30 (Request Items),
    build 29 (login heading "Welcome"), build 28 (notification lines
    gone at the source), build 27 (Dashboard Recent activity removed)
    and build 26 (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   phones can reach. QR links work for anyone on the office Wi-Fi
   or LAN; a phone on mobile data cannot reach a 192.168 address.

 57. PENDING STAMP IS GREY (2026-11-09)
 1. The Pending watermark (static/pending-stamp.png, the user's
    rectangular PENDING stamp) is now grey, the same tone as the
    grey APPROVED seal, instead of green. The stamp's shape,
    size (7.5 cm wide), place (bottom right of the invoice PDF
    below the signatures) and transparent background are unchanged.
    Nothing else changed.
 2. NOTHING ELSE CHANGED. This build also carries the whole of
    build 37 (the user's PENDING stamp replaces the grey circular
    seal), build 36 (single-line meta, signature alignment by
    count, Mark approved / Mark pending, PENDING status), build 35
    (APPROVED seal, QR scan fix, third signature, new invoice and
    request format, Approved invoice status), build 34 (dept-admin
    notifications for invoices and requests, print alignment,
    Department dropdown removed from the Request items tab), build
    33 (Search QR looks all over, public QR for every row, request
    Item name, Other's request only for HR & Admin, print column
    widths), build 32 (request editing and edit log), build 31
    (kind name off the request document), build 30 (Request Items),
    build 29 (login heading "Welcome"), build 28 (notification
    lines gone at the source), build 27 (Dashboard Recent activity
    removed) and build 26 (stylesheet cache-busting, inline
    flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   phones can reach. QR links work for anyone on the office Wi-Fi
   or LAN; a phone on mobile data cannot reach a 192.168 address.

 59. VOID INVOICE DELETE, SIGNATURE LINE CENTRED, ROUND REQUEST
    FIGURES, HR & ADMIN CAN OPEN ANY REQUEST (2026-11-09)
 1. Delete invoice also on void invoices. The Delete invoice button
    now appears on a void invoice too, so the owner, the portal
    admin and a permission user can delete it (with the password
    pop-up, as before). A department admin still cannot delete
    someone else's invoice. Invoices already marked Void keep that
    status and the Void filter.
 2. Signature line centred. In the invoice and request PDFs, the
    line under each signature was left-aligned while the title, the
    name and the designation were centred, so the line sat about 14
    points to the left of the name and the name looked out of line.
    The line is now centred as well, so the title, the line, the
    name and the designation all sit on one central axis in every
    signature block.
 3. Request figures are round. When an Item Request is saved or
    edited, the rate is rounded to the nearest whole number, so the
    amount, the subtotal and the grand total are whole numbers too
    (for example a rate of 49,999.99 becomes 50,000, and 7 x 50,000
    is 350,000). The amount in words follows the rounded total.
    Invoices are unchanged.
 4. HR & Admin users can open any request. Any HR & Admin user can
    now open and see every request in the All request section,
    whatever department it came from (before, only the recipient
    could open one from another department). Only the recipient —
    the HR & Admin user the request was sent to — can edit it, and
    only the recipient can change its status, as before. The owner
    can still edit their own request.
 5. NOTHING ELSE CHANGED. This build also carries the whole of
    build 39 (no watermark by default, new status notification,
    Delete invoice), build 38 (the PENDING stamp is grey), build 37
    (the user's PENDING stamp replaces the grey circular seal),
    build 36 (single-line meta, signature alignment by count, Mark
    approved / Mark pending, PENDING status), build 35 (APPROVED
    seal, QR scan fix, third signature, new invoice and request
    format, Approved invoice status), build 34 (dept-admin
    notifications for invoices and requests, print alignment,
    Department dropdown removed from the Request items tab),
    build 33 (Search QR looks all over, public QR for every row,
    request Item name, Other's request only for HR & Admin, print
    column widths), build 32 (request editing and edit log),
    build 31 (kind name off the request document), build 30
    (Request Items), build 29 (login heading "Welcome"), build 28
    (notification lines gone at the source), build 27 (Dashboard
    Recent activity removed) and build 26 (stylesheet
    cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   office can open. The "Public portal address" setting is already
   set on the live portal and is kept.

58. NO WATERMARK BY DEFAULT, NEW STATUS NOTIFICATION, DELETE INVOICE (2026-11-09)
 1. No watermark by default. The APPROVED seal and the PENDING stamp
    now come ONLY from the invoice's status. A newly created invoice
    shows no watermark at all, even when its template has a watermark
    turned on with the text "Approved" or "Pending" — that was the
    error: the template's watermark text used to make the seal appear
    on every new invoice. The seal appears when the owner marks the
    invoice Approved and the stamp when the owner marks it Pending.
    A template watermark with any other text (for example
    "Confidential") still shows as the old diagonal text.
 2. Status-change notification. When the owner changes an invoice's
    status, the department admin is now told: "[User] changed the
    status for [invoice number] to Approved." or "[User] changed the
    status for [invoice number] to Pending." This applies to the
    Mark approved / Mark pending buttons and to setting Approved or
    Pending in the edit form.
 3. Delete invoice replaces Void. The Void button on the invoice
    detail page is gone. In its place (on the right, next to Mark
    pending) is a Delete invoice button, shown for draft, issued,
    paid, approved and pending invoices. Only the owner of the
    invoice and a portal admin can delete it; a department admin
    cannot delete someone else's invoice. Clicking it opens a
    warning pop-up where the owner or portal admin must type their
    own password to delete it — a wrong password deletes nothing.
    Deleting removes the invoice and its lines for good; its number
    is never reused. If the owner deletes it, the department admin
    is told "[User] deleted invoice [number]." (A portal admin
    deleting it tells nobody, following the portal's rule that
    nobody is told about a portal admin's own actions.) Invoices
    already marked Void keep that status and the Void filter.
 4. NOTHING ELSE CHANGED. This build also carries the whole of
    build 38 (the PENDING stamp is grey), build 37 (the user's
    PENDING stamp replaces the grey circular seal), build 36
    (single-line meta, signature alignment by count, Mark approved
    / Mark pending, PENDING status), build 35 (APPROVED seal, QR
    scan fix, third signature, new invoice and request format,
    Approved invoice status), build 34 (dept-admin notifications
    for invoices and requests, print alignment, Department dropdown
    removed from the Request items tab), build 33 (Search QR looks
    all over, public QR for every row, request Item name, Other's
    request only for HR & Admin, print column widths), build 32
    (request editing and edit log), build 31 (kind name off the
    request document), build 30 (Request Items), build 29 (login
    heading "Welcome"), build 28 (notification lines gone at the
    source), build 27 (Dashboard Recent activity removed) and
    build 26 (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   No database change is needed for this update. Apply only this
   latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   phones can reach. QR links work for anyone on the office Wi-Fi
   or LAN; a phone on mobile data cannot reach a 192.168 address.

 60. APPLICATION LETTERS, DESIGNATION ON USER ACCOUNTS AND MY SETTINGS (2026-11-10)
 1. Application Letters — a new page inside More, for every user
    except the portal admin. A department admin makes Application
    Letter kinds for their own department (like an invoice template
    or an Item Request kind). The starter kinds are Annual Leave
    (AL), Sick Leave (SL) and Casual Leave (CL); change the prefix
    on the kind if you want another one. Each kind appears on the
    page as a Create card. A user picks a kind, fills in the leave
    (from date, to date, reason, letter) and sends the application
    to ONE specific user in the HR & Admin Department. The recipient
    is notified and sees it in "Received". A new application starts
    as Pending and gets a number like AL-0001 (sequential per kind,
    never reused).
 2. Who can do what. The specific HR & Admin user the application
    was sent to AND the HR & Admin department admin can edit it,
    set a note, upload their signature to it and change the status
    (Pending, Approved, Rejected). The owner can edit their own
    application only while it is still Pending. Other HR & Admin
    users can open and see every application in All applications,
    but cannot change it. The applicant is notified of every status
    change, and the other party is notified of every edit. Every
    edit is written to the edit log on the application detail page
    and to the portal Activity log.
 3. The document is a FORMAL application letter, not an invoice. A
    plain centred letterhead (company name and address, one thin
    rule, no logos, no teal), Ref on the left and the date on the
    right, then To, Subject, the body, "Thanking you. Yours
    faithfully," and the applicant's signature (name, designation,
    department, company). Then a FOR OFFICE USE section with the HR
    note and the approver's uploaded signature image above their
    name and designation, and the status with the date. The body is
    set in a serif typeface, like a typed formal letter. The QR
    (1.9 cm) and share code stay at the bottom left of every page,
    with the page number at the bottom right, the same as the other
    portal documents.
 4. Public QR. Applications have the same public QR as invoices and
    item requests: HRC- + random 5-digit code, unique across
    records, invoices, requests, applications and Department
    Database rows. Search QR looks all over for a code, so an
    application code opens the application. Anyone who scans the QR
    sees the letter and can download its PDF — no login needed.
 5. Designation. A user account now has a Designation (job title).
    The admin types it on the Add user and Edit user forms. Every
    user can also change their own name, username and designation
    on a new "My settings" page, reached from the user menu next to
    Password. The username change takes effect at once and must be
    unique. The designation is filled in AUTOMATICALLY under the
    owner's name in the owner signature: invoice "Prepared By",
    Item Request "Requested By", and the applicant on an
    application letter. If a user has no designation set, that line
    is simply left out, as before. Changing the designation in My
    settings updates every new invoice, request and application
    that user creates.
 6. NOTHING ELSE CHANGED. This build also carries the whole of
    build 40 (void invoice delete, signature line centred, round
    request figures, HR & Admin can open any request), build 39
    (no watermark by default, new status notification, Delete
    invoice), build 38 (the PENDING stamp is grey), build 37 (the
    user's PENDING stamp replaces the grey circular seal), build 36
    (single-line meta, signature alignment by count, Mark approved
    / Mark pending, PENDING status), build 35 (APPROVED seal, QR
    scan fix, third signature, new invoice and request format,
    Approved invoice status), build 34 (dept-admin notifications
    for invoices and requests, print alignment, Department
    dropdown removed from the Request items tab), build 33 (Search
    QR looks all over, public QR for every row, request Item name,
    Other's request only for HR & Admin, print column widths),
    build 32 (request editing and edit log), build 31 (kind name
    off the request document), build 30 (Request Items), build 29
    (login heading "Welcome"), build 28 (notification lines gone
    at the source), build 27 (Dashboard Recent activity removed)
    and build 26 (stylesheet cache-busting, inline flat-table
    style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   The database upgrades itself: the new tables (application_kinds,
   applications, application_history) are created and the
   designation column is added to users. No data is lost. Apply only
   this latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   office can open. The "Public portal address" setting is already
   set on the live portal and is kept.

 61. RECYCLE BIN NOW SHOWS DELETED DEPARTMENT ROWS AND APPLICATION LETTERS (2026-11-10)
 1. The bug. The Recycle Bin only ever listed personal records. A row
    deleted from the Department Database was soft-deleted (it stayed in
    the database for 30 days and was only erased for good after that),
    but it never appeared in the Recycle Bin at all — whoever deleted
    it, the owner, a permission user or the portal admin. So there was
    no way to see it or restore it from the bin. The bin showed 0
    deleted records even after rows had been deleted.
 2. Deleted Department Database rows now appear in the Recycle Bin.
    The Records tab lists them next to deleted personal records, with
    the row's first value, its department and tab, who deleted it and
    when, and the date it will be erased. Each row has Restore and
    Delete forever. The owner or a department admin of that department
    can restore it; restoring puts it back in its tab. The 30-day rule
    is unchanged: a row that stays deleted for 30 days is erased for
    good, exactly as before.
 3. Application letters can now be deleted, and go to the Recycle Bin
    too. There was no Delete on an application before. The detail page
    has a Delete button for the owner, the recipient, the HR & Admin
    department admin and the portal admin. Deleting is a soft delete:
    the application goes to the Recycle Bin for 30 days, where it can
    be restored, and is only erased for good from there. Its number
    (for example AL-0001) is never reused. A deleted application no
    longer appears in the Application Letters list, its detail page,
    its public QR code page or Search QR.
 4. Who sees what in the bin. A portal admin or permission user sees
    every deleted record, row and application. Any other user sees only
    their own deleted records and rows, and application letters they
    applied for or were sent. The same purge rule as for personal
    records applies to rows and applications: a permission user can
    restore anything, but only the portal admin can erase for good a
    row or application that a permission user, the portal admin or he
    himself deleted.
 5. Invoices are unchanged. Delete invoice still erases the invoice
    and its lines for good at once, as in build 39, so a deleted
    invoice does not appear in the Recycle Bin. That is by design: the
    number is never reused and there is nothing to restore.
 6. NOTHING ELSE CHANGED. This build also carries the whole of
    build 41 (Application Letters, designation on user accounts and
    My settings), build 40 (void invoice delete, signature line
    centred, round request figures, HR & Admin can open any request),
    build 39 (no watermark by default, new status notification,
    Delete invoice), build 38 (the PENDING stamp is grey), build 37
    (the user's PENDING stamp replaces the grey circular seal),
    build 36 (single-line meta, signature alignment by count, Mark
    approved / Mark pending, PENDING status), build 35 (APPROVED seal,
    QR scan fix, third signature, new invoice and request format,
    Approved invoice status), build 34 (dept-admin notifications for
    invoices and requests, print alignment, Department dropdown
    removed from the Request items tab), build 33 (Search QR looks all
    over, public QR for every row, request Item name, Other's request
    only for HR & Admin, print column widths), build 32 (request
    editing and edit log), build 31 (kind name off the request
    document), build 30 (Request Items), build 29 (login heading
    "Welcome"), build 28 (notification lines gone at the source),
    build 27 (Dashboard Recent activity removed) and build 26
    (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   The database upgrades itself: the deleted_by column is added to
   Department Database rows and the deleted_at / deleted_by columns
   are added to application letters. No data is lost. Apply only
   this latest zip, not the older ones in order. After upgrading, set
   Portal settings -> "Public portal address" once, for example
   http://192.168.1.116:8100, so new QRs point at the address your
   office can open. The "Public portal address" setting is already
   set on the live portal and is kept.

62. TWO-STAGE APPLICATION APPROVAL, KIND LETTERHEAD, PASSWORD IN MY
    SETTINGS, NARROWED APPLICATION DELETE, AND THE LETTER PDF FIXES
    (2026-11-10)
 1. Two-stage approval replaces sending straight to HR. A user now
    sends their application to a user in their OWN department — a
    department user or the person with Department admin permission
    of that department. That person is the checker. The checker
    checks it, uploads their signature under Checked By, then
    forwards it to ONE specific HR & Admin user. HR approves or
    rejects it and uploads their signature under Approved By. The
    statuses are now Pending (with the checker) -> Checked (checker
    signed and forwarded, waiting on HR) -> Approved / Rejected.
    The checker cannot forward until their signature is uploaded.
    The letter's "To," is the checker, with the applicant's
    department and the company — not HR & Admin. The Received
    sub-tab shows an application to whoever it was sent to: the
    checker while it is Pending, the HR approver once it is Checked.
 2. The letter and the PDF show two signature blocks side by side
    under FOR OFFICE USE — Checked By (the checker's signature image
    on top, then Checked By, then the checker's name, then the
    checker's designation) and Approved By (the HR approver's
    signature image on top, then Approved By, then the approver's
    name, then the approver's designation). The blocks are laid out
    by count the same way as the invoice and item request
    signatures: two sit left and right, three would sit left,
    centre and right, four would spread across the page. Every
    signature image is drawn at the same height, so the line under
    each signature sits on the same level, and every image is
    CENTRED above its own title, name and designation — the image
    used to sit at the left edge of its block while the text was
    centred, so the line under it did not line up with the name
    below. The spacing between the title, the name and the
    designation is tight, like the applicant's own signature block.
 3. The PDF watermark comes from the status only. An approved
    application shows the grey APPROVED seal already in the project
    (the same seal as on an approved invoice). A rejected
    application shows the grey REJECTED stamp (the image you
    uploaded, converted to grey), drawn at the same size and place
    as the seal (5.5 cm, bottom right) so it never reaches as far
    left as the approver's signature block. A pending or checked
    application shows no watermark. There is no separate Status or
    Date line at the bottom of the letter or the PDF any more — the
    status is shown by the seal or the stamp, and the date is
    already at the top of the letter (Ref / date line).
 4. The application kind carries its own company name and address.
    The department admin sets them when making or editing a kind;
    they print on the letterhead of applications made from that
    kind. Leave them blank and the portal company name and default
    address are used instead. The kinds list shows the company for
    each kind.
 5. Change password is now inside My settings. The My settings
    page has a Change password box (current password, new password,
    new password again) with the same rules as the standalone
    Change password page: the current password must be right, the
    two new ones must match, and the new one must differ from the
    old one. Changing it ends the user's other logins. The
    standalone Change password page still works.
 6. Application delete is narrowed and asks for a password. The
    Delete button sits to the right of Print on the detail page
    (Edit / Download PDF / Print / Delete, all the same height in
    one row). Clicking it opens a password box, like Delete invoice.
    Only the owner, an administrative permission user and the
    portal admin can delete an application — the checker, the HR
    approver and the HR & Admin department admin cannot. A wrong
    password deletes nothing. A deleted application goes to the
    Recycle Bin for 30 days, as in build 42, and its number is
    never reused. The portal admin may open an application and
    delete it (and download its PDF), while the Application Letters
    list stays hidden from them.
 7. The letter preview is centred in its card on the detail page
    and on the public code page, not shifted to the left. The
    header buttons and the user-menu buttons are aligned: a form
    inside a button row is now a flex item, so its button sits on
    the same baseline as the links and buttons beside it.
 8. The detail page shows the checker and the approver in the
    status line and in the Details rail (Sent to, Checked by,
    Approved by). While the application is Pending, the checker
    sees a "Check and forward" card: upload their signature, then
    pick an HR & Admin user and forward it. Once it is Checked,
    the HR approver (and the HR & Admin department admin) see the
    status, note and signature forms. The owner is told when the
    checker forwards it and when HR approves or rejects it; the
    checker is told when HR approves or rejects it. The
    notifications page "Who gets told what" card says so.
 9. NOTHING ELSE CHANGED. This build also carries the whole of
    build 42 (Recycle Bin shows deleted Department Database rows
    and application letters), build 41 (Application Letters,
    designation on user accounts and My settings), build 40 (void
    invoice delete, signature line centred, round request figures,
    HR & Admin can open any request), build 39 (no watermark by
    default, new status notification, Delete invoice), build 38
    (the PENDING stamp is grey), build 37 (the user's PENDING
    stamp replaces the grey circular seal), build 36 (single-line
    meta, signature alignment by count, Mark approved / Mark
    pending, PENDING status), build 35 (APPROVED seal, QR scan fix,
    third signature, new invoice and request format, Approved
    invoice status), build 34 (dept-admin notifications for
    invoices and requests, print alignment, Department dropdown
    removed from the Request items tab), build 33 (Search QR looks
    all over, public QR for every row, request Item name, Other's
    request only for HR & Admin, print column widths), build 32
    (request editing and edit log), build 31 (kind name off the
    request document), build 30 (Request Items), build 29 (login
    heading "Welcome"), build 28 (notification lines gone at the
    source), build 27 (Dashboard Recent activity removed) and
    build 26 (stylesheet cache-busting, inline flat-table style).

 UPGRADE: ./backup.sh, then copy your live .env OUTSIDE the portal
   folder first (unzipping overwrites .env with the older copy in
   the zip), unzip over the old folder, compare and restore your
   live .env if it differs, then docker compose up -d --build.
   The database upgrades itself: the checker and approver columns
   are added to application letters (checker_id,
   checker_signature_path, checker_signature_at, approver_id) and
   the company name and address columns are added to application
   kinds. Existing applications keep working: applications sent
   before this build keep their HR recipient as the person they
   are with, and their "To," still shows that recipient. No data
   is lost. Apply only this latest zip, not the older ones in
   order. After upgrading, set Portal settings -> "Public portal
   address" once, for example http://192.168.1.116:8100, so new
   QRs point at the address your office can open. The "Public
   portal address" setting is already set on the live portal and
   is kept.

==============================================================================
63. APPLICATION LETTER SUBJECT, WATERMARK POSITION AND SIGNATURE TRIMMING
    (2026-11-11)
==============================================================================
 1. The subject line no longer repeats "Application". It used to read
    "Application for Leave Application for 2 days ..." when the kind
    itself was called "Leave Application". The subject is now the kind
    name on its own: "Leave Application for 2 days (11 November 2026
    – 12 November 2026).". The same change is made on the letter
    preview on the detail page and on the public code page, so the
    subject reads the same everywhere. Other kinds read the same way:
    "Annual Leave for 2 days ...", "Sick Leave for 2 days ...".
 2. The watermark (the grey APPROVED seal, or the grey REJECTED stamp)
    on the application letter PDF has moved up, from 6.2 cm above the
    bottom of the page to 10 cm above the bottom. It now sits in the
    blank space on the right side of the page, beside the applicant's
    signature and above FOR OFFICE USE, clear of both signature
    blocks. It is still drawn at the same size (5.5 cm) and in the
    same place for approved and rejected letters, and it still sits
    behind the letter content. The invoice seal and stamp have NOT
    moved — only the application letter watermark.
 3. An uploaded signature picture is now trimmed when it is saved.
    A signature photo or scan often has more blank space on one side
    than the other, so the picture was centred in its block but the
    writing (and any line under it) sat left of the title below it.
    Saving now crops the picture to the ink, with the same small
    margin on every side, so the ink — and any line under it — is
    centred above its title, name and designation. This applies to
    both the checker's and the approver's signature, and to the
    signature as shown on the detail page, the public code page and
    the PDF, because all three show the same saved picture. Pictures
    that are already tight are left alone. Signatures uploaded before
    this build are not changed; they are trimmed the next time that
    person uploads a signature.
    Upgrade: nothing to back up beyond the usual. Apply only this
    latest zip, not the older ones in order. After upgrading, set
    Portal settings -> "Public portal address" once, for example
    http://192.168.1.116:8100, so new QRs point at the address your
    office can open. The "Public portal address" setting is already
    set on the live portal and is kept.

==============================================================================
64. FIX: CONTAINER RESTARTING AFTER UPGRADE FROM BUILD 41/42 (2026-11-12)
==============================================================================
 1. What went wrong. After applying build 44 over a portal that was
    still on build 41 or 42, the container kept restarting and the
    portal never came up. The log showed:
    "sqlite3.OperationalError: no such column: checker_id" in
    models.init_db(), at conn.executescript(SCHEMA).
 2. Why. Build 43 added the checker_id and approver_id columns to
    the applications table, plus two indexes on them (idx_app_checker,
    idx_app_approver), and put those indexes inside the SCHEMA text.
    On startup init_db() runs the SCHEMA first and only afterwards
    adds missing columns to tables that already exist
    (_ensure_column). On a database made before build 43, the
    applications table has no checker_id yet, so creating the index
    on it crashed the whole startup — before the column could be
    added. A fresh database never hit this, because its applications
    table is created with all columns at once; that is why the tests
    (which always use a fresh database) never caught it.
 3. The fix. The two indexes are no longer in the SCHEMA text. They
    are now created in init_db() AFTER the _ensure_column calls that
    add checker_id and approver_id, so the columns always exist
    before the indexes are built. Fresh databases and upgraded
    databases both work, and a second startup is a no-op. No data is
    lost and nothing else changes: build 44's subject, watermark and
    signature-trimming work is all still in here.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). If the container is currently
    restarting, this build fixes it — the database is upgraded on
    the first startup and the portal comes up. Back up first and
    keep your live .env untouched, as before. Apply only this
    latest zip, not the older ones in order.

==============================================================================
 65. APPLICATION LETTERS FOR THE PORTAL ADMIN, CLICK-TO-READ NOTIFICATIONS,
     DELETE NOTIFICATIONS, BIGGER SIGNATURES, USER MENU, NOTIFICATION
     WORDING AND TWO KIND LOGOS (2026-11-14)
==============================================================================
 1. The portal admin now has the Application Letters page. "Application
    Letters" is in the More menu for the portal admin too, and the list
    opens for them (it used to give a 403). The portal admin and the
    administrative permission users can see every application in the
    All tab, whatever department it came from, and can delete any of
    them. They still cannot create an application, check one, forward
    one, approve one or manage the kinds — those stay with the
    department users, the checker and HR.
 2. Clicking a notification now marks just that one read. The
    notification opens the page it points at, and its "New" badge and
    the bell count go away — nobody has to press "Mark all as read"
    separately any more. "Mark all as read", "Select" and "Clear all"
    are unchanged, and opening the notifications list itself still
    marks nothing read.
 3. When the portal admin or an administrative permission user deletes
    an application, only the owner is told ("Portal Admin deleted the
    application LV-0001. It is in the Recycle Bin for 30 days.").
    Nobody else is told — not the checker, not the HR approver, not
    the department admins. When the owner deletes their own
    application, the checker / approver is told, as before.
 4. The checker and approver signatures on the application detail
    page and on the public code page are a bit larger — 68px instead
    of 52px. The signature size on the PDF letter is unchanged.
 5. The user menu (top right) now has only "My settings" and
    "Log out". The "Password" button is gone; changing the password
    is inside My settings, where it has been since build 43. The
    standalone /change-password page itself is unchanged.
 6. An application being sent no longer produces two near-identical
    notifications for the same person. The checker gets one ("X sent
    you a Leave Application LV-0004 to check.") and the department
    admins get the watcher one ("X sent a Leave Application LV-0004
    to [checker] to check."). If the checker is also a department
    admin, they get only the checker one — the watcher one skips
    them, but the other department admins still get it. The wording
    also no longer repeats "application": it reads "Leave Application
    LV-0004", not "Leave Application application LV-0004". The same
    wording fix applies to the "updated the ..." notifications when
    an application is edited. The notification chain itself is
    unchanged: the portal admin and the permission users are told
    about every task a department admin does, the portal admin is
    told about every task a permission user or department admin does,
    and a department admin is told about every task done by a user
    in their department in the Department Database and on the
    Application Letters page.
 7. The application delete box now has an eye button on the password
    field, the same as the login page, so the user can see the
    password they typed.
 8. An application kind can now carry two logos: one for the top left
    corner of the letter and one for the top right corner. The
    department admin sets them on the New kind and Edit kind forms
    ("Logo — top left corner" and "Logo — top right corner"). The
    logos print at the top corners of the letter on the detail page,
    the public code page and the PDF, with the company name and
    address staying centred between them. If a kind has no logo for
    a corner, that corner is left blank — no placeholder and no
    default logo. The logos belong to the kind, like its company
    name and address, so they appear on every letter made from that
    kind, including ones already sent. Uploading a new logo replaces
    the old one; ticking "Remove it" on the edit form clears that
    corner again. The logos are stored per kind (application_kinds
    logo_left / logo_right); kinds made before this build have no
    logos until the department admin adds them.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The two new kind columns are
    added to an existing database on the first startup, so no data
    is lost. Back up first and keep your live .env untouched, as
    before. Apply only this latest zip, not the older ones in order.

==============================================================================
 66. BIGGER PDF SIGNATURES, NO PRINT BUTTON ON THE APPLICATION DETAIL PAGE,
     AND THE PORTAL ADMIN / PERMISSION USERS TOLD ABOUT DEPARTMENT ADMIN
     APPLICATION ACTIVITY (2026-11-14)
==============================================================================
 1. The checker and approver signatures on the application letter PDF
    are bigger — 1.4 cm tall instead of 0.9 cm — so they are easy to
    read on the printed letter. Both are still drawn at the same
    fixed height, so the line under each signature still lines up
    across the two blocks, and the ink and the line stay centred
    above the title, name and designation. The signature size on the
    detail and code pages (68px, from build 46) is unchanged.
 2. The Print button is gone from the application detail page. There
    is no Print button in the top action row any more, and no Print
    button in the Quick actions card on the right either. Only Edit
    and Download PDF are left there (and Delete, for the owner, the
    portal admin and the administrative permission users, who can
    still delete an application). The page can still be printed from
    the browser itself (Ctrl+P), and the "Print this QR" link in the
    Public QR panel is unchanged. The Print button on the public
    code page is unchanged.
 3. The portal admin and the administrative permission users are now
    told about department admin activity on applications, which they
    were not told about before:
    (a) When a regular user sends an application to a department
    admin, the portal admin and the permission users are told
    ("X sent a Leave Application LV-0004 to Sales Admin to
    check."). Before, only the checker and that department's
    department admins were told. A department admin or permission
    user sending it already told them through the watcher chain,
    so they are not told twice.
    (b) When a department admin (as checker) checks and forwards
    an application to HR, the portal admin and the permission
    users are told ("X checked the application LV-0004 and
    forwarded it to HR User."). The watcher notification is
    routed by whoever the checker is: a department admin
    checker tells the portal admin and the permission users, a
    regular-user checker tells that department's department
    admins, a permission-user checker tells the true portal
    admins.
    (c) When a department admin edits an application, the portal
    admin and the permission users are told ("X updated the
    application LV-0004."). This tells a different set from the
    department-admin notification that was already sent on an
    edit, so nobody is told twice.
    The notification chain itself is unchanged: a department
    user's task tells that department's department admins, a
    department admin's task tells the portal admin and the
    permission users, a permission user's task tells the true
    portal admins, and nobody is told about a true portal
    admin's task. The delete rule from build 46 is unchanged:
    when the portal admin or a permission user deletes an
    application, only the owner is told.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). No database change in this
    build. Back up first and keep your live .env untouched, as
    before. Apply only this latest zip, not the older ones in order.

==============================================================================
 67. NO DOUBLE APPLICATION NOTIFICATIONS, AND THE PORTAL ADMIN /
     PERMISSION USERS TOLD ABOUT THE HR DEPARTMENT ADMIN'S APPROVAL
     (2026-11-14)
==============================================================================
 1. A department admin who is also the checker no longer gets the same
    application news twice. When HR approves or rejects, the checker
    used to get two notifications — "hr admin changed the application
    LV-0009 to Approved." (as a department admin) and "hr admin
    changed the application LV-0009 you checked to Approved." (as
    the checker). Now they get only the checker one. The same fix
    applies when an application is edited: a department admin who is
    the recipient or the checker gets only the direct "updated ..."
    notification, not the department-admin one as well. The helper
    that tells the department admins now skips the owner, the checker
    and the recipient, who were already told directly in the same
    action.
 2. When a regular user forwards an application, the owner (if they
    are a department admin) no longer gets the watcher notification
    as well as the direct "checked your application ... and
    forwarded it ..." one. The forward's watcher notification now
    skips the owner, who was just told directly.
 3. When the HR department admin approves or rejects an application,
    the portal admin and the administrative permission users are now
    told ("hr admin changed the application LV-0009 to Approved.").
    Before, nobody above the department was told about it, because
    the approval route never sent a watcher notification. A regular
    HR user approving still tells only the department admins, as
    before — they are already told by the department-admin
    notification, so they are not told twice. The "Who gets told
    what" help card on the Notifications page now says this plainly,
    and that nobody is told twice about the same application event.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). No database change in this
    build. Back up first and keep your live .env untouched, as
    before. Apply only this latest zip, not the older ones in order.

==============================================================================
 68. THE LETTER'S "TO" SECTION IS NOW WHAT THE USER WRITES (2026-11-14)
==============================================================================
 1. There is a new "To" box on the application creating page, right
    after "Send to". The user writes the lines that appear under
    "To," in the letter, one per row. The letter's "To" section now
    shows ONLY those lines — the checker's name, their department and
    the company are no longer filled in automatically. By default,
    if the box is left blank, nothing appears under "To," at all,
    just "To," and then the Subject. The "Send to" dropdown is
    unchanged: it still picks who the application is sent to for
    checking. Only the letter's "To" block changed.
 2. The typed lines appear on the detail page, the public code page
    and the PDF, all three. The user can also change them later on
    the Edit form, which shows the same "To" box pre-filled; changing
    them writes an edit-log entry ("To") and notifies the other party,
    like the other editable fields.
 3. Applications that already exist keep their letters looking as
    they did: on the first startup after applying this build, each
    one is filled in from the three lines its letter used to show
    (checker name, department, company). A new application left
    blank stays blank — it is not filled in.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The database gains one new column
    (applications.to_lines) and the one-time fill above; nothing else
    changes. Back up first and keep your live .env untouched, as
    before. Apply only this latest zip, not the older ones in order.

==============================================================================
 69. SIGNATURE UPLOADED ONCE IN MY SETTINGS, USED WITH A TICK BOX (2026-11-14)
==============================================================================
 1. Every user now uploads their signature once, in My settings. A new
    "My signature" box sits under the name, username and designation,
    and says: "Upload your signature once. Please scan your signature
    and upload as png or jpg here." The saved signature is shown there,
    with an upload to replace it and a tick box to remove it.
 2. Whatever the user uploads — a png or a jpg — is always converted
    to PNG and trimmed to the ink before it is stored, so the signature
    kept for future use is always a PNG. A webp is refused. The stored
    PNG is what the "Use my signature" tick box uses.
 3. There is no longer a signature upload box in application letters.
    In its place, both the checker (under Checked By) and the HR
    approver (under Approved By) get a tick box "Use my signature".
    Ticking it copies the saved signature onto the application, so it
    stays as it was even if the user later changes their signature in
    My settings. Applications that already have a signature uploaded
    keep showing it, unchanged.
 4. A user who has not uploaded a signature in My settings yet sees a
    message with a link to My settings instead of a working tick box,
    and cannot sign until they have one. The checker still cannot
    forward until their signature is on file.
 5. NEW: the HR approver cannot save the status (Approve or Reject)
    until their signature is on file for that application. The "Save
    status" button stays disabled, and the page refuses the change,
    until the approver has ticked "Use my signature". The HR note can
    still be saved without a signature. This is the same rule the
    checker already has for forwarding.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The database gains one new column
    (users.signature_path); nothing else changes. Back up first and
    keep your live .env untouched, as before. Apply only this latest
    zip, not the older ones in order.

==============================================================================
 70. MORNING REMINDER TO UPLOAD YOUR SIGNATURE (2026-11-14)
==============================================================================
 1. Every morning, from 07:00 (REMINDER_HOUR, the same morning hour as
    the other reminders), every user who has not uploaded a signature
    in My settings yet gets one notification in their Notifications
    page: "Please upload your signature from my settings". Clicking
    it opens My settings, where the "My signature" box is.
 2. The portal admin and the administrative permission users never
    get this reminder, even if they have no signature uploaded. Every
    other user does — department admins, HR users and regular users.
    Inactive, deleted and not-yet-approved accounts never get it.
 3. It comes once a day, and again the next morning, until the user
    uploads a signature — then it stops. If they later remove their
    signature, it starts again the next morning. Yesterday's
    notification does not stop today's: each morning brings a new one
    while the signature is still missing.
 4. It is sent by the same morning check that sends the other
    reminders: the background check every 5 minutes, and again when
    somebody opens a page. So the bell shows it even before the user
    has opened a page that morning, as long as the portal is running.
    The "Who gets told what" card on the Notifications page now says
    this too.
 5. A small fix that this needed: the background check used to stop
    after the first reminder sender that sent something, so a later
    sender could be skipped on that check. It now calls every sender,
    every time.
    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The database gains one new table
    (signature_reminder_sent, one row per user per day, so nobody is
    told twice on the same day); nothing else changes. Back up first
    and keep your live .env untouched, as before. Apply only this
    latest zip, not the older ones in order.


==============================================================================
 71. THREE-STEP APPROVAL FOR APPLICATION LETTERS (2026-11-14)
==============================================================================
 1. The application creating page no longer has one "Send to" box.
    It has three steps — "Who approves it — 3 steps, in order". Every
    step has a role and a person:
      - role: None, Checked By, Approved By or Authorised By
      - person: a user from the applicant's own department, HR & Admin
        or Management
    A step set to None is skipped: use two steps and two signature
    blocks appear at the bottom of the letter; use three and three
    appear; use one and one appears.
 2. The steps run strictly in order. The second person cannot approve
    until the first has approved, and the third cannot approve until
    the second has. While they are waiting, the person sees
    "Waiting for (name)'s approval" on the application page, and the
    application appears in their Received tab only when their turn
    comes. The first person is told when the application is sent; the
    next person is told when the person before them has approved.
 3. Every person in the chain must tick "Use my signature" (the
    signature they saved in My settings) before they can approve or
    reject. The "Save status" button stays disabled until they have
    ticked it. Each decision is only Approved or Rejected.
 4. The grey APPROVED seal appears on the letter's PDF only after
    the LAST used step has approved. An approval by an earlier step
    shows no seal. (The REJECTED stamp rule changed in build 53,
    section 72: any rejection stamps the PDF at once.)
 5. Old applications keep working: an application sent before this
    update keeps its old two-step flow — the checker checks it, signs
    under Checked By and forwards it to one HR & Admin user, who
    approves or rejects it under Approved By. Its detail page shows
    the same chain as its steps.
 6. The detail page shows the whole chain in the "Currently with"
    row and one row per step, each with its state (waiting / approved
    / rejected) and date. The edit history names the step that
    decided: "Step 2 (Approved By) from Pending to Approved". The
    "Who gets told what" card on the Notifications page now says
    this too.

    THREE QUESTIONS STILL OPEN (the defaults built for now — please
    say if you want them changed):
      a. All three steps set to None: the application is refused —
         "Choose at least one step — who approves this application?".
      b. The same person in two steps: refused — "Choose a different
         person for each step."
      c. Step 1 or Step 2 rejects: ANSWERED in build 53
         (section 72) — the application is Rejected at once, the
         chain ends, and the REJECTED stamp DOES appear on the PDF
         straight away. Only the APPROVED seal waits for the last
         person.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The database gains one new table
    (application_steps — one row per step of each application) and one
    new column on applications (chain_legacy). Existing applications
    are moved into the new table on first start: a pending one gets
    its checker as step 1 (and still keeps the old forward), a
    checked one gets checker + approver, an approved or rejected one
    gets both steps marked decided. Nothing else changes. Back up
    first and keep your live .env untouched, as before. Apply only
    this latest zip, not the older ones in order.


==============================================================================
 72. "REJECTED BY" AND THE STAMP ON ANY REJECTION (2026-11-14)
==============================================================================
 1. When a person in the chain chooses Reject instead of Approve,
    the label above their name in the signature block changes from
    their role to "Rejected By" — so the checker rejecting shows
    "Rejected By" over the checker's name, the approver rejecting
    shows it over the approver's name, and the authoriser rejecting
    shows it over the authoriser's name. It shows in the same place
    everywhere the block appears: the detail page, the public code
    page and the PDF. Approving keeps the role label, and a step
    that has not decided yet keeps its role label.
 2. The watermark rule is now split in two. The REJECTED stamp
    appears on the PDF as soon as ANY person in the chain rejects,
    and the request goes no further. The APPROVED seal still
    appears only when the LAST person in the chain approves — an
    approval by an earlier person shows no seal and no stamp.
 3. "The request goes no further" is now true on screen as well as
    in the rules: once an application is approved or rejected, the
    detail page shows "Currently with —" (nobody has it), a step
    that never got its turn says "not reached" instead of
    "waiting", and the application never appears in the next
    person's Received tab. The person the application ended with
    (the one who rejected it, or the last approver) is the one
    shown as "Applied to" in the list.
 4. The edit history names the step for an approval in the middle
    of the chain: "Step 2 (Approved By) from Pending to Approved"
    (before, it read "changed the status from Checked to Checked",
    which said nothing). A final decision still reads "changed the
    status from Checked to Approved/Rejected".

    TWO QUESTIONS STILL OPEN (the defaults built for now — please
    say if you want them changed):
      a. All three steps set to None: the application is refused —
         "Choose at least one step — who approves this application?".
      b. The same person in two steps: refused — "Choose a different
         person for each step."

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). No database change in this
    build — the tables and columns from build 52 are unchanged.
    Back up first and keep your live .env untouched, as before.
    Apply only this latest zip, not the older ones in order.

73. WHO CAN SEE APPLICATIONS IN APPLICATION LETTERS (2026-11-14)
    Who sees what on the Application Letters list page changed:

    1. The portal admin and the administrative permission users see
       every user's application from every department in the All
       applications tab, as before. The department filter (All
       departments) is only shown to them.
    2. Every department admin has an All applications tab showing
       his own department's users' applications.
    3. The HR & Admin department admin sees more in All: every
       request sent to one of his department's users — any
       application where any person in the approval chain is an
       HR & Admin user, even when the application came from another
       department — as well as his own department's applications.
       This wider "sent to" view is only for the HR & Admin
       department admin; other department admins see only their
       own department's applications in All.
    4. A normal user has no All applications tab at all — only "My
       applications" and "Received" (the applications requested to
       them). There are no Approved or Rejected tabs.
    5. A normal user can no longer open another user's application,
       even one from their own department: opening it directly
       (from a link or a notification) is refused. The old rule
       that "every user in the same department can open an
       application" is gone. Who CAN open an application: the
       portal admin, the applicant, the person it is currently
       with, anyone in the approval chain, the department admin of
       the applicant's department, and the HR & Admin department
       admin for a request sent to one of his users. The "How
       approval works" text on the list page now says this.
    6. What changed for regular HR & Admin users: until now every
       HR user could see all departments in the All tab (a rule
       shared with Request Items). They no longer can — only their
       own applications and the ones requested to them, like any
       other normal user. Request Items is unchanged: HR users
       still see every department's requests there.
    7. A bookmarked ?apptab=all for a user with no All tab now
       opens My applications instead of showing other users'
       applications; a Received tab that does not apply now also
       falls back to My instead of All.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). No database change in this
    build — the tables and columns from build 52 are unchanged.
    Back up first and keep your live .env untouched, as before.
    Apply only this latest zip, not the older ones in order.

74. DEPARTMENT NAME UNDER THE DESIGNATION IN EVERY SIGNATURE
    (2026-11-14)
    Every signature block in Application Letters now shows the
    signer's department name directly under their designation:

    1. The FOR OFFICE USE blocks — one per step in the approval
       chain — show the department under the designation, on the
       application detail page, on the public code page, and in
       the PDF letter. The department is the full department name
       of the person who signed (for example Sales & Marketing,
       HR & Admin, Management), centred under the designation
       like the rest of the block, in the same grey style as the
       designation in the PDF.
    2. The applicant's own block already showed the department
       (name, designation, department, company) on all three
       places — nothing changed there.
    3. A step whose user was deleted and has no department shows
       no department line, the same as a missing designation.
    4. The "Use my signature" hint on the detail page now says
       "with your name, designation and department under it."
    5. The "Step 1 / Step 2 / Step 3" rows in the Details rail
       are not signature blocks (no signature image there), so
       they are unchanged.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). No database change in this
    build — the tables and columns from build 52 are unchanged.
    Back up first and keep your live .env untouched, as before.
    Apply only this latest zip, not the older ones in order.

75. CUSTOM APPLICATION + CLOSING IN THE BODY (2026-11-14)
    1. A new "Custom Application" kind exists by default in every
       department — nobody has to create it. It appears as its own
       card on the Application Letters page ("Write your own
       subject and body"). A department made after this build gets
       its Custom Application kind at once, and the startup backfill
       gives one to every older department too. Its number prefix
       is CA (CA-0001, CA-0002...). The department admin can edit
       its company header and logos like any other kind.
    2. The Custom Application form has only the 3 approval steps,
       the To box, a Subject box and the application body. There is
       no From date, no To date, no Days and no Reason — a custom
       application stores none of them, its From/To/Days cells in
       the list are blank, and the detail page shows no Days card
       and no From/To/Reason rows. The letter is exactly what the
       user wrote: the typed subject and the typed body, including
       "Respected Sir," and "Thanking you. Yours faithfully," if
       the user wrote them. The letter adds no opening or closing
       of its own for a custom application. The subject can be
       changed from the edit form (one edit-log entry, "Subject").
    3. For EVERY application format, "Thanking you. Yours
       faithfully," is now part of the application body, so the
       user can change it if they want. The letter (PDF, detail
       page and code page) no longer adds its own closing. For
       leave kinds the body is still filled in from the dates and
       the reason — and the filled-in body now ends with the
       closing, so the user sees it in the letter box and can
       change it before sending. "Respected Sir," is still added
       by the letter for leave kinds. Applications made before
       this build keep looking exactly as they did: on startup
       their bodies gain the closing (only rows whose body does
       not already end with it are touched, and running it again
       never doubles it).

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The database changes are
    additive (a subject column on applications, an is_custom flag
    on application kinds, both with backfills that run on
    startup). Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

76. INVOICE + REQUEST APPROVAL CHAINS, WATERMARK CHOICE, TEMPLATE/KIND DELETE (2026-11-14)
    1. The department admin no longer has a signature option when
       creating an invoice format or a request item format: the
       Signatures section is gone from both forms. Instead, the
       user creating the invoice or the item request picks the
       signatures, exactly like Application Letters — up to 3 steps
       in order, each with a role and a person, and each person
       must tick "Use my signature" before they can approve or
       reject. The approve/reject mechanism is the same as
       Application Letters.
    2. Invoices. The owner no longer has "Mark approved" or "Mark
       pending" — both are gone. Clicking Finalise gives the
       invoice its number and starts it forwarding through the
       steps; after Finalise the status is Pending. The step people
       can be chosen from any department, with the roles None,
       Checked By, Approved By, Authorised By. If anyone rejects,
       forwarding stops there and the grey REJECTED stamp appears
       on the PDF. If the final person approves, the grey APPROVED
       seal appears. The invoice PDF shows the owner's Prepared By
       block plus one signature block per step (signature, role —
       "Rejected By" for a step that rejected — name, designation
       and department). A draft's steps can be changed while it is
       a draft; at least one step is needed and no person can be
       picked twice.
    3. Item requests. The roles are None, Checked By, Send/Request
       To, Approved By, Authorised By, and the step people are
       chosen from the owner's own department, HR & Admin or
       Management. Exactly one step must be Send/Request To — that
       person is the one who receives the request. After the last
       person approves, the APPROVED seal appears and the
       Send/Request To user can change the status to Pending,
       Issued, Paid or Handover. If anyone rejects, the process
       stops there and the REJECTED stamp appears. The request PDF
       shows the owner's Requested By block plus one signature
       block per step, as for invoices.
    4. Two PDF download options. On the invoice and the request
       detail pages there are now two buttons: "Download PDF"
       (with the watermark — the APPROVED seal, the REJECTED stamp
       or the PENDING stamp, and any diagonal template watermark)
       and "Download PDF without watermark" (no seal, stamp or
       diagonal watermark at all; the signatures and everything
       else stay). Both are available to the owner and to other
       users who can view the invoice or request.
    5. Deleting templates and kinds. On the Invoice templates page
       and the Item Request kinds page there is now a tick box on
       every row (and one in the header to select all) plus a
       "Delete selected" button, with a confirmation step. A
       department admin can delete templates and kinds from his own
       department; the portal admin and administrative permission
       users can delete them from any department (with a department
       switcher on those pages). A deleted template or kind
       disappears at once and does NOT go to the Recycle Bin — but
       the invoices and item requests already made from it stay
       exactly as they are, and still open and download their PDF.
       The starter templates can be made again afterwards.
    6. Old signatures stay exactly as they were. Templates and
       kinds made before this build keep their stored signature
       blocks, and invoices and requests made from them keep
       showing them — only new invoices and requests use the
       chain. An old draft with no chain cannot be finalised until
       the owner picks at least one step on the edit page.
    7. Note: a rejected invoice does not get a live public QR
       (draft, void and rejected invoices have none; issued, paid,
       approved and pending do). This was not spelled out in the
       request, so it is flagged here rather than decided silently.
    8. Also fixed while touching those two list pages: the
       Signatures column used to show the length of the stored
       JSON text (a template with no signatures showed "2
       authorized + employee"). It now shows the real count of
       stored signature blocks (0 for a new template or kind).

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). The database changes are
    additive (two new tables, invoice_steps and
    item_request_steps, created on startup; no column is changed
    on any existing table). Back up first and keep your live .env
    untouched, as before. Apply only this latest zip, not the
    older ones in order.

77. STEP PEOPLE CAN OPEN WHAT WAS SENT TO THEM, OTHER'S SUB-TABS, REQUEST DELETE (2026-11-14)

    1. A step person can now open an invoice or an item request that
       was sent to them — and download its PDF — whatever department
       they are in. Before this build, the detail page and the PDF
       only let in the portal admin, the owner, people from the
       invoice or request's own department, and departments it was
       shared with, so an approver from another department (for
       example an HR & Admin user picked as Approved By on a Sales
       invoice, or a Management user picked as a step on a request)
       got "You do not have permission to open this page" (403).
       That is fixed: anyone picked as a step can open it, view
       only. They can still only approve or reject when their turn
       comes (strict order is unchanged), and they cannot edit it,
       change its status or manage its public QR. Application
       Letters already worked this way and are unchanged.
    2. The label above the approve/reject dropdown is now just
       "Status", on the invoice detail page and on the request
       detail page. The other dropdown on the request page — the
       one the Send/Request To user uses to change the status to
       Pending, Issued, Paid or Handover — keeps its own label.
    3. The Invoices tab has a new "Other's invoices" sub-tab. It
       shows every invoice sent to you as an approval step, and it
       only appears for a user who has at least one. The Request
       items tab's "Other's request" sub-tab is widened the same
       way: it used to show only HR & Admin users the requests
       where they were the single recipient; it now shows every
       step person (Checked By, Send/Request To, Approved By,
       Authorised By) the requests sent to them, whatever
       department they are in. Both sub-tabs show an approval as
       soon as it is sent to you — even before your turn — and it
       stays there after you have decided. A bookmarked Other's
       tab for a user with nothing sent to them just shows All.
       The Other's lists are NOT limited to the department being
       viewed: a department admin can only open his own
       department's page, so a department-scoped list would never
       have shown him an approval sent from another department.
       The hint on the Request items tab is updated to match the
       new flow.
    4. Item requests can now be deleted. On the request detail
       page there is a "Delete request" button, next to Print,
       for the owner, the portal admin and administrative
       permission users (a department admin who is not the owner
       cannot delete, and sees no button). It follows the invoice
       delete exactly: a password box, hard delete (the request,
       its lines, its edit history and its chain steps are
       removed, and any step signature files with them), and its
       number is never reused. If the owner deletes it, the
       department admin is told; if the portal admin or a
       permission user deletes it, nobody is told. A deleted
       request does not go to the Recycle Bin, like a deleted
       invoice.
    5. Three details of the request delete were not answered when
       this build was confirmed, so they follow the invoice delete
       as the model and are flagged here rather than decided
       silently: (a) it asks for the password, like the invoice
       delete; (b) it is a hard delete, not into the Recycle Bin;
       (c) only the department admin is told when the owner
       deletes (the other party is not told separately). Say the
       word if any of the three should work differently.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is no database change in
    this build — no new table or column — so the upgrade is code
    and templates only. Back up first and keep your live .env
    untouched, as before. Apply only this latest zip, not the
    older ones in order.

78. OWNER'S SIGNATURE IN THE PREPARED BY / REQUESTED BY BLOCK, NO EMPTY "BILL TO" LINE (2026-11-14)

    1. The Prepared By signature is back on invoice PDFs, and the
       Requested By signature on item request PDFs. The owner's
       block was built as text only (title, a blank line, name,
       designation), while the approval steps were built as image
       blocks — so even though the owner had uploaded a signature
       in My settings, it never appeared on the PDF, and the
       invoice showed an empty line under Prepared By next to the
       approvers' signatures. The owner's block now shows the
       signature they saved in My settings, above the name, exactly
       like the steps show theirs. The PDF is built fresh on every
       download, so it reads the signature the owner has saved now
       — an invoice that was already issued, like CON-0006, shows
       it as soon as this build is applied, without being made
       again. An owner who has not uploaded a signature keeps the
       old text block with its line. Nothing else about the block
       changes: no department line is added under Prepared By, and
       the step blocks are untouched.
    2. The "Bill to -" line no longer prints on an invoice that
       has no customer. A Conveyance invoice (and an Admin Expense
       or Purchase Request invoice) has no customer field on its
       form, so its PDF used to print "Bill to -" with nothing
       after it — and the public copy printed "Bill to - —". The
       line now appears only when the invoice actually has a
       customer. A Billing invoice still shows "Bill to" with the
       customer name, and a billing invoice whose customer is
       hidden from strangers still shows the "—" in its place.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is no database change in
    this build — no new table or column — so the upgrade is code
    only. Back up first and keep your live .env untouched, as
    before. Apply only this latest zip, not the older ones in
    order.

79. MY RECORDS COLUMNS PER USER, USERS' RECORDS PAGE, INVOICES + REQUESTS IN THE RECYCLE BIN (2026-11-14)

    1. The columns on a user's Mine tab are now that user's own
       choice. Until now the columns on a My records page were the
       department's columns, set by the portal admin / permission
       user, and every user in the same department saw the same
       columns. The Mine tab now has a "Columns" picker: tick a
       column to show it, untick it to hide it. The choice is
       personal — it changes only that user's own Mine tab, not
       anyone else's — and a new column appears for everyone until
       they hide it. The department admin still makes the
       department's columns themselves (adding a field, and so
       on); what the admin no longer decides is which of them
       appear on a user's Mine tab. The Shared by me, Shared with
       me and My department tabs are unchanged.
    2. Users' records: a new page for the portal admin and
       administrative permission users, in the top menu next to
       All records. It lists every user's name; clicking a name
       opens that user's whole My records page (Mine, Shared by
       me, Shared with me, My department, and Other departments
       where it applies), with the user's own Mine-tab columns.
       It is view and delete only — there is no Add, Edit,
       Export or Print there. Deleting a record from it moves the
       record to the Recycle Bin, and the owner is told ("Portal
       Admin deleted your record ..."), with a link to the Bin
       where they can restore it. The same rule applies anywhere
       else a record is deleted by someone other than its owner;
       the owner deleting their own record tells nobody.
    3. Invoice and item request deletes now go to the Recycle
       Bin. They used to be deleted for good at once; now the
       invoice or request, its lines and its approval chain stay
       in the Bin for 30 days and can be restored, with the same
       number and status it had. While it is in the Bin it is
       gone from the Invoices / Request items tab, from its
       detail page, from its PDF, from its public code page and
       from Search QR, exactly like a deleted application letter.
       A draft invoice (no number yet) shows in the Bin as
       "Draft invoice". After 30 days it is erased for good. The
       number is never reused, and the password box, the delete
       button and the notifications are unchanged (the owner
       deleting tells the department admin; the portal admin
       deleting tells nobody).
    4. The Recycle Bin clear rules are UNCHANGED, because they
       already worked the way they were asked for: a permission
       user cannot erase for good a deletion he made himself, one
       the portal admin made, or one another permission user
       made — only the portal admin can erase those. A permission
       user can still erase a deletion a regular user made, and
       can restore anything. The same rule now covers invoices
       and item requests in the Bin. Deleted users still appear
       in the Bin's Users tab and everything else in its Records
       tab.
    5. Small things done while this was built: when a deleted
       user's work is erased for good, their item requests are
       now erased too (until now only their invoices were), and
       their invoices' chain signature files are removed instead
       of being left behind.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There IS a database change in
    this build: a new table for each user's Mine-tab column
    choice, and two new columns (deleted_at, deleted_by) on the
    invoices and item_requests tables. They are added
    automatically when the portal starts — there is nothing to
    run by hand, and an older database upgrades cleanly (this
    was tested by starting the new code on a build-59
    database). Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

80. USERS ADD THEIR OWN MINE-TAB COLUMNS; USER ATTACHMENT ACCESS (2026-11-15)

    1. A user can now add a column of their own to their Mine tab.
       Inside the "Columns" box on the Mine tab there is an "Add a
       column" section: column name, type (Text, Long text, Number,
       Date, Dropdown list, Yes / No, plus Attachment (file) when
       the user has attachment access), dropdown options one per
       line when the type is a dropdown, and a Required tick.
       Required means the field must be filled when a record is
       added or edited. The new column appears on the Mine tab
       straight away, ticked in the picker, and in the Add record
       form; existing records show it blank.
    2. A column a user adds shows ONLY on that user's own Mine tab
       — never on another user's page, and it never becomes a
       department column. It also shows in the portal admin /
       permission user's Users' records view of that user, and in
       that user's own record exports and record PDF. The user's
       columns do not appear on the Shared with me tab, the Other
       departments tab, or the All records page, which keep showing
       department columns only.
    3. The user can rename, move and remove the columns they added
       themselves, from the "Your columns" part of the same Columns
       box. The type never changes. They cannot change the
       department's columns — those stay the admin's, and the
       Departments -> record columns page never lists a user's own
       columns. Removing a column hides it from the Mine tab and
       the Add form; its values stay in the database, like a
       removed department column.
    4. "Department DB attachment access" is now "User Attachment
       Access" (Admin menu, and the Users page). It lists every
       user, not just dept admins, and the portal admin and
       administrative permission users tick which users may upload
       attachments on their own My records page. A user without the
       tick is not offered the Attachment type. The same tick
       still lets a dept admin create attachment columns in the
       Department Database — that rule is unchanged — and the old
       page address redirects to the new one. An attachment file
       on a record is shown by its file name (never as stored
       text) on the Mine tab, the record page, in exports and in
       the record PDF, and it downloads from the record page. A
       file is scanned and size-checked the same way as a
       Department Database attachment, and it is erased for good
       when the record is erased from the Recycle Bin.
    5. Small safety fix found while this was built: the table
       upgrade that adds the new column type commits first and
       only then turns foreign keys off, because turning them off
       inside an open transaction does nothing — without the
       commit, rebuilding the columns table would have deleted
       every record value and Mine-tab column choice through the
       cascade. The same commit was added to the older Department
       Database attachment upgrade, which had the same latent
       risk. No data was lost anywhere: the upgrade was tested by
       starting the new code on a build-60 database holding
       records, values and hidden-column choices, and they all
       survived.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There IS a database change in
    this build: the columns table gains a user_id column, accepts
    the 'attachment' type, and gets a per-user unique index.
    It is added automatically when the portal starts — there is
    nothing to run by hand, and an older database upgrades
    cleanly (tested by starting the new code on a build-60
    database). Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

81. YOUR COLUMNS AS THE ADMIN'S TABLE; MY DEPARTMENT TAB SHOWS INVOICES AND REQUESTS TOO (2026-11-15)

    1. "Your columns" in the Mine tab's Columns box is now a table,
       exactly like the portal admin's Departments -> record columns
       page: one row per column you added, with Column (name, and the
       dropdown options underneath when it is a dropdown), Type,
       Required, Shown and Filled in, and the actions in the last
       cell. The tick-box picker above it and the "Add a column" form
       below it are unchanged.
    2. The up and down arrows are now shown on EVERY row, like the
       admin's page. Until now the up arrow was hidden on the first
       column and the down arrow on the last one, so with only one
       column of your own there was no arrow at all and it looked as
       if the feature did not exist. Pressing up on the top column
       or down on the bottom one does nothing, like the admin's.
    3. Edit and Remove now open in the row itself, the way the
       admin's Remove opens: Edit shows the name, the dropdown
       options and the Required tick; Remove asks you to confirm in
       the row and says the data is kept. The browser's own popup
       is gone.
    4. Shown says Yes when the column is ticked in the picker and
       Hidden when it is unticked; Filled in counts how many of
       your records have a value in the column.
    5. The My department tab on the My records page now shows all
       of a user's own work in the Department Database, grouped
       under the tab each item belongs to — not just the rows in the
       custom tabs. Your own invoices appear under "Invoices" and
       your own requests under "Request items", showing the same
       details the Department Database shows for them. The invoices
       and requests sent to you as an approval step appear under
       "Invoices sent to you" and "Item requests sent to you". Rows
       shared with you are still not shown. The two counts at the
       top count everything on the tab, and the search box searches
       invoices and requests too (number, share code, customer,
       kind, people). Nothing can be edited from the tab. Locate
       on a row opens it in the Department Database, on the exact
       page it sits on, as before; Locate on an invoice or a
       request opens the document itself, because the Department
       Database lists for those are filtered to whoever is looking,
       so a page link would land on the wrong person's list when
       the portal admin looks at a user's records. The admin's
       Users' records view of a user shows the same groups. The
       invoice and request groups are not part of Select, Export
       or Print on this tab — those still work on the Department
       Database rows, as before; use the document's own page for
       its PDF. Download CSV on this tab still downloads the
       Department Database rows only.
    6. What is deliberately NOT in this build: rows shared with
       you stay out of the My department tab — they belong to
       someone else, and this tab is your own work. Say the word
       if you want them in too.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is NO database change in
    this build. Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

82. "MY COLUMNS" IS A PAGE OF ITS OWN, LIKE THE ADMIN'S COLUMNS PAGE; PROTECT KEPT (2026-11-15)

    1. Your columns now have a page of their own — "My columns" —
       laid out exactly like the portal admin's Departments -> record
       columns page: KPI cards on top (Columns, Removed, Protected),
       the table on the left, and the "Add column" card in the right
       rail. Open it from the Mine tab: the "Manage my columns"
       button under the Columns picker, or the "My columns" action in
       the Quick actions on the right. The Mine tab's Columns box
       keeps only the tick-box picker for showing and hiding columns.
    2. The table has the same columns as the admin's: Column (name,
       and the dropdown options underneath), Type, Required, Shown,
       Filled in, with up, down, Edit and Remove on every row. The up
       and down arrows are shown on every row, as before.
    3. Edit opens its own page, like the admin's Edit column page:
       the name box shows the column's name — delete it and type a
       new one to rename the column — plus the dropdown options, the
       Required tick, the Shown tick and the Protect tick. The type
       cannot be changed; add a new column instead. Shown is the
       picker's tick, so unticking it hides the column on the Mine
       tab without removing it.
    4. The Protect tick is kept, on the Add column form and on the
       Edit page, exactly like the admin's. A protected column shows
       a lock beside its name and has no Remove button until you
       click "Remove protection". Protection can be switched on in
       the Add form or on the Edit page; switching it off needs the
       separate "Remove protection" button, so it cannot happen by
       accident. Reminders and "keep a time" are still admin-column
       features only, and there is no Repair log or File attachments
       card on this page — those are department settings.
    5. Remove now asks you to type the column name to confirm, like
       the admin's — a missing or wrong name removes nothing. No
       password is asked, because it is your own column; the admin's
       password is there because a department column affects the
       whole department. A protected column cannot be removed until
       its protection is removed.
    6. A removed column is no longer gone for good. It goes to a
       "Removed columns" page (the "Removed columns · N" button at
       the top of the page and in the Quick actions), where it can be
       restored with all its data, or erased for good — erasing
       first saves an automatic backup, and also asks for the column
       name typed out. Restoring is refused if you already have a
       live column with the same name.
    7. What is NOT in this build: the department's default columns
       are still the department's — this page lists only the columns
       you added yourself, and nothing here touches anyone else's
       columns or the department's columns. One thing in your last
       message I could not read with certainty — "users now can
       delete the default column name" — I built it as the Edit page
       letting you delete the name in the box and type a new one
       (rename). If you meant users should be able to remove the
       department's default columns from their own Mine tab, say so
       in a word and I will add that next; I have not built it,
       because deleting a department column for everyone would be
       wrong and I did not want to guess.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is NO database change in
    this build. Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

83. NO DEPARTMENT COLUMNS ON A USER'S PERSONAL RECORDS; THE PAGE IS NOW CALLED "MANAGE COLUMNS" (2026-11-15)

    This build answers the question left open at the end of §82, in
    your words: "There wont be any deparment wise predefine column
    for users.. From now on user can create their own column and
    manage them in my records page's mine tab". The plan from your
    11:00 message (delete a predefined column from your own Mine tab
    and reorder predefined + own columns together) is replaced by
    this one — there are no predefined columns on the Mine tab at
    all, so there is nothing there to delete or reorder.

    1. The Mine tab shows only the columns you added yourself. The
       department's columns (on your live Sales tab: Client or lead,
       Contact person, Phone, Email, Campaign, Deal stage, Expected
       value, Follow-up date, Meeting, Assigned to, Marketing
       material, Remarks) no longer appear anywhere on your personal
       records — not in the Columns picker, not in the table, not in
       the Add record form, not on the record page, not in the CSV /
       Excel / PDF exports, and not in the record PDF. The same goes
       for the field picker on the record page (the "Choose the
       fields to put in the PDF" boxes) and for the fields you can
       put in a public QR link: only your own columns are offered.
       A value stored in a department column would stay hidden
       everywhere, even if one ever existed — you said there are no
       existing records in them, so nothing is lost.
    2. The button, the page and the Quick actions link are renamed
       from "Manage my columns" / "My columns" to "Manage columns".
       The page heading, the browser title, and the "Back to Manage
       columns" links on the Edit and Removed columns pages all say
       "Manage columns". The address stays /records/my-columns, so
       bookmarks keep working. The picker no longer marks every
       column "· yours" — every column it lists is yours now, so the
       tag added nothing.
    3. A user who has added no columns yet sees an empty Mine tab
       with a prompt — "You have no columns yet. Add your first
       column on the Manage columns page." — and clicking "+ Add
       record" sends them to the Manage columns page instead of a
       form with no fields. There is no starter set: each user starts
       with no columns and adds the ones they want.
    4. The department's columns are untouched for the Department
       Database. The Client Info, Meeting and other DeptDB tabs, and
       the admin's Departments -> record columns page, are exactly
       as before — the department admin still makes those columns,
       and they still work there. Copying a personal record into the
       Department Database still works too: it now matches the
       record's own columns by name instead of the department's.
    5. What does NOT change: the admin's All records page still
       shows department columns only (so it does not show a user's
       own columns, as before); Shared with me / Viewing still show
       department columns only; the admin's Users' records view shows
       the viewed user's own columns, as before. Your own columns
       still have no reminder tick and no "keep a time" — those are
       still admin-column features only. That also means the
       personal-record reminders, which were driven by the
       department's date columns, will no longer fire — your own
       columns cannot be a reminder column. The Department Database
       meeting reminders are unchanged. If you want a reminder tick
       on your own columns, say so and I will add it.
    6. The columns themselves are only removed from the users' view,
       not deleted from the database. The department's columns stay
       in the database for the Department Database, and any value
       ever entered in one on a personal record stays stored (it is
       just never shown). Nothing was deleted in this build.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is NO database change in
    this build. Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

84. DASHBOARD SETTINGS PANEL FIXED (2026-11-15)
    What was wrong: on the Dashboard (portal admin and administrative
    permission users), opening "Dashboard settings" showed a broken
    panel — the heading, the "Choose what shows on your dashboard"
    text and every tick-box row were squeezed side by side in one
    horizontal row, and the panel ran off the right edge of the
    screen. The Bar / Pie chart toggles were cut off.
    The cause: the stylesheet had one rule, ".acts form{display:flex}",
    meant for a form that IS a button in the header button row (for
    example a Delete form, so its button sits on the same baseline as
    the links beside it). But that rule also caught the Dashboard
    settings form, which sits inside the settings panel nested under
    the button row — so the form's heading, hint, tick-box rows and
    Save / Cancel buttons were all laid out in a row, like buttons.
    The fix: the rule is now scoped to a form that is a direct child
    of the button row (".acts>form"). The settings form is nested
    three levels down, so it is no longer caught, and it stays a
    normal block form: its heading on top, the hint under it, then
    one tick-box row per line (KPI cards, Records by department with
    its Bar / Pie chart toggle, Department database with its Bar /
    Pie chart toggle, Records by status, Logged in now, Reminders
    coming up, Quick actions), and Save / Cancel side by side at the
    bottom, all inside the panel.
    Nothing else changes: the button-row forms that must stay a flex
    row — the Delete forms and the notifications "Mark all as read" /
    "Clear all" forms — are direct children of the button row, so
    they still get the rule and still line up and still submit. The
    Log out form in the user menu has its own rule and is untouched.
    Saving settings works exactly as before, for the portal admin
    and for administrative permission users, and the settings stay
    per user (one admin's choices do not change another's). A regular
    user still gets 403 on the Dashboard.
    Tests: 825/825 checks pass (813 from builds up to 64 + 12 new).
    The new checks cover the scoped stylesheet rule, the panel
    opening for both roles with all seven rows, both chart toggles
    and Save / Cancel, saving settings for both roles, the per-user
    separation, the 403 for a regular user, and a button-row form
    still submitting.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is NO database change in
    this build. Back up first and keep your live .env untouched,
    as before. Apply only this latest zip, not the older ones in
    order.

85. SALES PIPELINE TAB AND REPORT FROM SELECTED RECORDS (2026-11-15)
    What this is: a new default tab in the Department Database for
    the Sales & Marketing department, called "Sales Pipeline", and a
    Report button on it that makes the "Client follow-up & sales
    pipeline report" — the report you showed me in the four photos —
    from the rows you select, and downloads it as a PDF. It is built
    from the data in the tab, not from a fixed list.
    The tab: Sales & Marketing gets the tab automatically, on the
    first start after you apply this build (and on any later start
    if the tab was removed). A department that is created later with
    "Sales" and "Marketing" in its name gets it too. Any department
    admin can also add the tab from the Tabs page — it is offered
    there as the "Sales Pipeline" template. The tab has 12 columns,
    in this order: Client name (text, required — the only required
    one), Contact person (text), Phone number (text), Email (text),
    Assigned to (dropdown: Mohaiminul, Syful, Shanjid, Prince,
    Imtiaz), Follow-up method (dropdown: Physical visit, Phone
    call), Follow-up date (date), Deal stage (dropdown: Open, Done,
    Terminated), MRC (BDT) (number), Referred by (text), Phone
    reason (dropdown: Outside Dhaka, Busy), Notes (long text). The
    tab works like any other Department Database tab: add, edit,
    share and delete rows, and the usual Export / Print.
    The Report button: on the Department Database page, to the right
    of "Select all", there is now a Report button. Tick the rows you
    want in the report (Select all ticks them all), then click
    Report — the PDF downloads. The report is made from the selected
    rows only; untick a row and it leaves the report. If you click
    Report with nothing ticked, it says "Please select the data row
    first." and nothing downloads.
    The button only appears where the report can be made: on a
    Department Database tab that has all four columns the report
    needs (Assigned to, Follow-up method, Deal stage, MRC (BDT)).
    The Sales Pipeline tab has them, so it always shows the button.
    Another tab shows it too if it has those four columns. It does
    NOT appear on the Invoices tab or the Request items tab — those
    are separate pages, not Department Database tabs, and they never
    show it.
    What the report contains (one landscape A4 page, in the style of
    your photos): a dark-blue title band — "CLIENT FOLLOW-UP &
    SALES PIPELINE REPORT", "Prepared for: Managing Director",
    today's date, "Amounts in BDT", and which tab and department it
    came from and how many rows were selected. Then two sections
    side by side. (1) EXISTING CLIENT FOLLOW-UP: how many were
    reached by physical visit and how many by phone call, with the
    share of the selected rows; a stacked bar per Account Manager
    (blue = physical visit, orange = phone call) and the share
    reached; and, when any client was reached by phone, a box
    "Why some clients were contacted by phone" listing how many
    were outside Dhaka and how many were busy. (2) SALES PIPELINE:
    how many prospects (Open + Done), the potential MRC, how many
    are Done and how many are Open, with their MRC; the top
    referrer in an orange box (how many prospects, how much MRC,
    what share of the pipeline MRC, and by which Account Managers);
    a bar per Account Manager of pipeline MRC (purple = Open, blue
    = Done); and the Top 5 open prospects by MRC. At the bottom, a
    KEY MESSAGE band with two sentences summing up the visits and
    the pipeline.
    How the numbers are worked out: the follow-up counts use every
    selected row. The pipeline counts use only rows whose Deal stage
    is Open or Done. A row marked Terminated counts in the follow-up
    (it was visited or phoned) but NOT in the pipeline, and the
    report says how many were terminated. A row with no stage or a
    stage other than Open / Done / Terminated counts in the
    follow-up only. "Reached" means visited or phoned, so the
    reached share is (visits + phone calls) out of the selected
    rows. The referred-by box shows the person who referred the
    most pipeline MRC; it is left out when no selected row has a
    Referred by value. The Top 5 list shows only Open prospects.
    The report is logged in the Activity log as an export ("sales
    pipeline report <department> / <tab>: N rows"). Who can download
    it follows the usual Department Database rules: a regular user
    only for their own department, a portal admin or an
    administrative permission user for any department; a user from
    another department gets 404.
    Still open (not built in this build): your photos also had two
    annexes — Annex A, the Head of Sales 3-month performance report,
    and Annex B, the termination customer list. You did not say
    whether you want them in the same PDF, so they are NOT in this
    build; the report is the main page only. Say the word and I will
    add them. The tab is named "Sales Pipeline"; say if you want a
    different name.
    Tests: 869/869 checks pass (825 from builds up to 65 + 44 new).
    The new checks cover the tab being created on startup and on
    department creation (and not duplicated, and not created for a
    plain Marketing department or for HR & Admin), the 12 columns
    in order with only Client name required, the Report button
    showing on the pipeline tab and on a tab with the four columns
    but not on Client Info, Invoices or Request items, the guard
    when nothing is ticked, the report's numbers for eight rows
    (visits, phone calls, prospects, MRC, Done / Open, the referred
    box, per-KAM bars and the Top 5), the one-page PDF, a
    Terminated row counting in the follow-up but not the pipeline,
    and the access rules for another department's user.

    Upgrade: apply this zip the usual way (extract, then
    docker compose up -d --build). There is NO database change in
    this build. The Sales Pipeline tab and its 12 columns are
    created by the startup backfill the first time the new code
    runs, so your existing Department Database rows are untouched.
    Back up first and keep your live .env untouched, as before.
    Apply only this latest zip, not the older ones in order.

86. THE WHOLE PROJECT MOVES TO MYSQL (2026-11-15)
    What this is: the portal's database changes from SQLite (one
    file, portal.db) to MySQL 8.0 (a separate database container).
    Nothing about the portal's screens, features or data changes —
    this is the same portal, on a different database engine.
    Why: you asked for the whole project to be migrated to MySQL,
    with no errors, with a step-by-step backup guide, and with the
    data persistent.
    How it works: a new file, dbapi.py, keeps the exact interface
    the portal's code was written against (the ? placeholders, the
    Row that answers both row["name"] and row[0], the date functions)
    and runs it on MySQL through PyMySQL, so the rest of the portal
    does not change. The schema is the same 50 tables, rewritten
    for MySQL: INT AUTO_INCREMENT primary keys, DATETIME defaults,
    TEXT columns with no default (MySQL forbids defaults on TEXT —
    the code already reads them with an "or []" / "or ''" guard),
    the settings key renamed to setting_key (KEY is a MySQL
    reserved word), and the partial unique indexes (a column name
    may be reused only after the old one is removed) rebuilt as
    generated columns, because MySQL has no partial indexes.
    What is new in this build:
      * docker-compose.yml gains a db service (mysql:8.0) with a
        named volume mysql_data for /var/lib/mysql. The MySQL port
        is NOT published to the host — only the portal container
        can reach the database, over the internal Docker network.
      * backup.py now runs mysqldump (the portal image installs
        default-mysql-client) and writes portal_YYYYMMDD_HHMMSS.sql
        into backups/ (the portal_data volume), keeping the newest
        30. backup.sh copies the newest backup to ./backups-copy/db/.
      * migrate_sqlite_to_mysql.py moves your existing data: it
        copies every row of every table from the old portal.db into
        MySQL, keeping the same IDs, so invoice numbers, record
        links, public QR codes and approval chains all keep working.
        It refuses to run if the MySQL database already has rows
        (pass --replace to empty it first), and it checks every
        table's row count against the SQLite file before finishing.
      * MYSQL_BACKUP_GUIDE.txt — the step-by-step guide you asked
        for: how to take a MySQL backup, where backups are stored,
        where the current database stores its data, how to restore,
        and how to make sure the data is persistent.
    The .env file is UNCHANGED in this build — no MySQL variables
    were added to it, as you required. The MySQL password is set by
    docker-compose (MYSQL_PASSWORD, default "portal-change-me").
    If you want a different password, add MYSQL_PASSWORD=... to
    your live .env file BEFORE the first start of the MySQL
    container; changing it afterwards does not change the password
    inside MySQL.
    How to apply this build (read this before you start):
      1. Back up the live portal the old way first (copy
         /data/portal.db out of the portal container, and copy the
         portal_data volume's files). Keep that portal.db copy.
      2. Stop the portal: docker compose stop portal
      3. Copy the live SQLite file out:
         docker compose cp portal:/data/portal.db /tmp/portal.db
      4. Extract this zip over the project folder (the live .env
         stays untouched — do NOT overwrite it).
      5. Start the database: docker compose up -d db
         (wait about 30 seconds for it to become healthy)
      6. Run the migration:
         docker compose run --rm portal python migrate_sqlite_to_mysql.py /tmp/portal.db
         It prints one line per table and ends with "OK: N rows
         copied into 50 tables, counts match." If it prints an
         error instead, stop — do not start the portal on MySQL.
      7. Start the portal: docker compose up -d
         Open it and check your records, invoices and requests.
         The old portal.db is NOT deleted; keep it as an extra
         backup until you are sure the MySQL portal is working.
    Data persistence: the MySQL data lives in the named volume
    mysql_data (/var/lib/mysql) and the portal's files in
    portal_data (/data). Both survive docker compose stop, down
    (without -v), up -d --build, and a server restart. NEVER run
    docker compose down -v — it deletes both volumes and the data
    is gone for good.
    Bugs found by the MySQL test run and fixed in this build:
      * CREATE INDEX IF NOT EXISTS is accepted by MariaDB but NOT
        by MySQL 8.0 — the two checker/approver index creations now
        check information_schema first.
      * INSERT OR REPLACE was translated to "REPLACE INTO INTO"
        (a double INTO) — now translated to REPLACE.
      * ESCAPE '\' (one backslash, SQLite's form) is a syntax
        error in MySQL — the translator now writes ESCAPE '\\'.
        Without this, every LIKE search on the My department tab
        and the Department Database search failed with a 500.
      * The Tabs page aliased a count as "rows" — ROWS is a
        reserved word in MySQL 8.0, so the page failed with a 500.
        The alias is now row_count.
    Tests: 892/892 checks pass on the work copy and on a fresh
    extract (869 from builds up to 66 + 23 new). The new checks
    cover the 50-table MySQL schema, the setting_key rename, the
    generated-column unique indexes (a removed column name can be
    reused, two live ones are refused), the Row and datetime
    behaviour, the ESCAPE fix, the Tabs page, the shipped files
    (migration script, backup guide, dbapi.py, compose, PyMySQL),
    and backup.py writing a .sql dump. Separately, the migration
    was tested end to end (21/21: a build-66 SQLite database with
    departments, users, a record, a DeptDB row, an invoice, a
    request and an application migrated, counts matched, the
    portal booted and the sales user logged in and saw their
    data), and backup/restore/persistence was tested (14/14: a
    mysqldump restored into a fresh database with matching row
    counts, and the data survived a MariaDB restart).
    Apply only this latest zip, not the older ones in order.
    Back up first and keep your live .env untouched, as before.

87. MYSQL USER AND PASSWORD NOW COME FROM THE .ENV FILE (2026-11-15)
    What this is: in build 67 the database user name "portal" was
    written directly in docker-compose.yml, in two places (the
    database service and the portal service), and only the password
    was read from the .env file. Now both the user and the password
    live only in the .env file, and docker-compose.yml reads them
    from there.
    What changed:
      * docker-compose.yml: the database service now uses
        MYSQL_USER: ${MYSQL_USER:-portal} and
        MYSQL_PASSWORD: ${MYSQL_PASSWORD:-portal-change-me};
        the portal service now uses the same two values for
        DB_USER and DB_PASSWORD, so the portal always logs in
        with the user MySQL actually created. The root password
        already came from .env (MYSQL_ROOT_PASSWORD) and is
        unchanged.
      * config.py: only the comment above the database settings
        changed, to say the user and password are set in .env.
      * MYSQL_BACKUP_GUIDE.txt: the mysqldump command now uses
        your MYSQL_USER from .env, and the guide notes that the
        user and password come from .env since build 68.
    How to use it: add these two lines to your live .env file on
    the server (the same file that already has PORTAL_PORT), before
    the first start of the database:
        MYSQL_USER=portal
        MYSQL_PASSWORD=your-own-password
    If you leave them out, the defaults portal / portal-change-me
    are used, so a fresh install still starts. The .env file inside
    this zip is UNCHANGED, as before — you add the lines to your
    live .env on the server.
    Keep in mind: MySQL creates the user only the first time the
    database starts. Changing MYSQL_USER or MYSQL_PASSWORD in .env
    after the database already exists does NOT change the user or
    password inside MySQL.
    Tests: 895/895 checks pass on the work copy and on a fresh
    extract (892 from builds up to 67 + 3 new). The new checks
    cover the compose file reading the user and password from .env
    (no hardcoded user name left in it), the portal service using
    the same two values, and the zip's .env still containing no
    MYSQL bytes. No database change in this build, and no screen
    or feature change. Apply only this latest zip, not the older
    ones in order. Back up first and keep your live .env
    untouched, as before.

88. THE MYSQL USER AND PASSWORDS ARE NOW IN THE .ENV FILE (2026-11-15)
    What this is: builds 67 and 68 kept the .env file inside the
    zip byte-identical and asked you to add the MySQL lines to your
    live .env by hand. Now the three lines are written in the .env
    file itself, with a comment above them, so you change the
    values there:
        # --- MySQL database. The database container and the portal
        # both read the user and passwords from these three lines —
        # change the values here, and nowhere else. Change them
        # BEFORE the first start of the database: MySQL creates the
        # user only on first start, so changing them later does not
        # change the user or password inside MySQL.
        MYSQL_USER=portal
        MYSQL_PASSWORD=portal-change-me
        MYSQL_ROOT_PASSWORD=portal-change-me-root
    The values are the same defaults docker-compose.yml used to
    fall back to, and no other .env line changed — PORTAL_PORT, TZ
    and all the rest are exactly as they were.
    The root password is in .env too: docker-compose.yml no longer
    holds any password of its own. It reads MYSQL_USER,
    MYSQL_PASSWORD and MYSQL_ROOT_PASSWORD from .env with no
    fallback value left in the file — so the three lines MUST be
    in your live .env, or the database and the portal will not
    start. If your live .env does not have them yet, copy the
    three lines (and the comment) into it by hand from the .env
    in this zip.
    WARNING — read this before you apply the zip: the .env inside
    this zip now carries the DEFAULT user and passwords. Do NOT
    let it overwrite your live .env on the server. If you already
    set your own values in your live .env, keep your live .env as
    it is. Overwriting your live .env would also reset PORTAL_PORT
    to 8000 and lose any values you already set — and the portal
    would then try to log in with the default password while
    MySQL holds yours.
    Tests: 898/898 checks pass on the work copy and on a fresh
    extract (895 from builds up to 68 + 3 new). The new checks
    cover the three lines being in .env with the defaults, the
    comment above them, and the original .env settings being
    unchanged; the updated build-68 checks cover the compose file
    holding no password value and no fallback. No database change
    in this build, and no screen or feature change. Apply only
    this latest zip, not the older ones in order. Back up first
    and keep your live .env untouched, as before.

89. THE PORTAL WOULD NOT START ON REAL MYSQL 8.0 — MISSING cryptography
    PACKAGE (2026-11-15)
    What happened: after applying the MySQL build, the live portal
    kept restarting. The log showed two errors, and only the second
    one is the bug.
      * The first error (Connection refused on 'db') was the portal
        trying while the database was still starting up. The db
        healthcheck tested MySQL over its local socket, so it could
        report healthy a moment before the network port was ready.
        Those errors stopped on their own once the database was up.
      * The error that kept the portal restarting was this one:
        RuntimeError: 'cryptography' package is required for
        sha256_password or caching_sha2_password auth methods.
        MySQL 8.0 logs users in with caching_sha2_password by
        default, and PyMySQL needs the `cryptography` package to
        do that login. requirements.txt did not list it, so the
        portal image had no cryptography and every connection
        failed. This is my bug: the MariaDB test server logs users
        in with mysql_native_password instead, so the 898 checks
        never took the caching_sha2_password path and never caught
        it — the same MariaDB-vs-MySQL trap as the CREATE INDEX IF
        NOT EXISTS bug in build 67.
    The fix:
      * requirements.txt now pins cryptography==44.0.0. The
        Dockerfile installs requirements.txt, so a rebuild of the
        image picks it up.
      * The db healthcheck now pings 127.0.0.1 (the TCP port) instead
        of localhost (the local socket), so "healthy" means the port
        the portal connects to is accepting connections.
    How to apply: extract this zip, then run
        docker compose up -d --build
    The --build is REQUIRED — the image must be rebuilt to pick up
    the new package; `up -d` on its own will not install it, and
    the portal will keep crashing the same way. After the rebuild
    the portal starts. If it comes up with no data (only the seed
    admin account), the migration from section 86 has not run yet:
    stop the portal, run the migration script, and start again.
    If the migration refuses because the portal already created
    its tables, run it with --replace (it empties the tables
    first, then copies your old data in).
    Tests: 901/901 checks pass on the work copy and on a fresh
    extract (898 from builds up to 69 + 3 new). The new checks
    cover requirements.txt pinning cryptography, the exact login
    call that crashed live (sha2_rsa_encrypt with a real RSA key)
    now working, and the healthcheck using 127.0.0.1. The live
    error was also reproduced here first (the same RuntimeError
    with cryptography missing) and then shown fixed with it
    installed. No database change in this build, and no screen or
    feature change. Apply only this latest zip, not the older
    ones in order. Back up first and keep your live .env
    untouched, as before.

90. THE PORTAL STILL WOULD NOT START ON REAL MYSQL 8.0 — FOREIGN KEY
    ERROR 1215, PLUS A SECOND MYSQL 8.0 QUERY ERROR (2026-11-16)
    What happened: build 70 fixed the login (cryptography), and the
    next error in the log was this one, while the portal created its
    tables:
        pymysql.err.IntegrityError: (1215, 'Cannot add foreign key constraint')
    at models.init_db() -> conn.executescript(SCHEMA), at the
    `columns` table. It passed all 901 checks here because the test
    server is MariaDB, and MariaDB allows what MySQL 8.0 refuses.
    Root cause, reproduced on real MySQL 8.0 (8.0.46) and bisected
    statement by statement: MySQL 8.0 refuses a FOREIGN KEY on a
    column that a generated column's expression refers to. The
    `columns` table had both — FOREIGN KEY (user_id) REFERENCES
    users(id), and the generated columns name_dept / name_user whose
    CASE expressions refer to user_id (they implement the partial
    unique indexes: a live department column's name is unique per
    department, a live user column's name unique per user and
    department). Adding the key afterwards fails the same way, in
    both directions. This is the third MariaDB-vs-MySQL gap in this
    migration, after CREATE INDEX IF NOT EXISTS (build 67) and the
    cryptography login (build 70). From now on the test suite runs
    against real MySQL 8.0, not MariaDB, so this class of bug is
    caught here instead of on your server.
    The fix (the smallest one that keeps both the foreign key on
    department_id and the database-level name uniqueness): the
    foreign key on columns.user_id is gone. A user's own columns
    are deleted explicitly in core.purge_user_work instead, when
    the user is erased for good; their values and hidden-column
    rows still go with them through the ON DELETE CASCADE keys on
    column_id. No other table was affected — columns was the only
    table where a generated column referred to a foreign-key
    column (checked). The upgrade helper that used to add that key
    no longer does.
    A second MySQL 8.0 error was found while testing the fix: the
    record detail page crashed with error 3065, because
    core.names_for_records ordered a DISTINCT query by columns
    (position, id) that were not in its SELECT list. MariaDB
    allowed that; MySQL 8.0 refuses it. The query now selects
    position and id too, keeping the same rows in the same order,
    and the detail page works. Every other DISTINCT and GROUP BY
    query in the project was checked against the same rule — this
    was the only one.
    How to apply: extract this zip, then run
        docker compose up -d --build
    (the --build is still required — the image must include
    cryptography from build 70). The portal then starts and
    creates its tables. Your live database already holds the
    first three tables (departments, users, user_view_departments)
    from the earlier failed starts; the new code skips those and
    creates the rest, so no cleanup is needed. If the portal
    comes up with no data (only the seed admin account), the
    migration from section 86 has not run yet: stop the portal,
    run the migration script, and start again. If the migration
    refuses because the portal already created its tables, run it
    with --replace.
    Tests: 909/909 checks pass on the work copy and on a fresh
    extract (901 from builds up to 70 + 8 new). The new checks
    cover the foreign-key/generated-column rule, the columns
    table having no key on user_id, all 50 tables being created,
    purging a user deleting his own columns with their values and
    hidden-column rows, and names_for_records returning the
    owner's columns in position order. The whole suite now runs
    against real MySQL 8.0. No database change beyond the one
    foreign key, and no screen or feature change. Apply only this
    latest zip, not the older ones in order. Back up first and
    keep your live .env untouched, as before.
91. FIVE APPLICATION-LETTER FORMATS, AND LETTER DATES IN DAY-MONTH-YEAR (2026-11-16)
    Two things the user asked for on the LV-0001 letter, plus the
    formats. (1) The letter's dates now read day-month-year on
    screen: the header date is "16 November 2026" and the subject
    range is "(17 November 2026 – 19 November 2026)". The PDF
    already wrote them that way; the detail page and the public
    code page still showed 2026-11-16, so both now use the same
    _long_date() the PDF uses. The small dates in the page header
    and the From / To / Reason rows under the letter are unchanged
    — they are page details, not the letter. (2) The first sentence
    no longer says "request leave application": the kind is called
    "Leave Application", so the old wording repeated it. Every
    leave kind now has its own formal wording, used for new
    applications (letters already sent keep the text they were
    submitted with; the applicant can still change any word of
    the pre-filled letter before sending):
      Leave Application (kept, LV): "I am writing to request
        leave for 3 days, from 17 November 2026 to 19 November
        2026, for personal reason. ..."
      Casual Leave (CL): "I am writing to request casual leave
        for 2 days, ... for urgent personal work. ..."
      Sick Leave (SL): "I am writing to request sick leave for
        3 days, ... as I am unwell and under a doctor's care. A
        medical certificate is attached for your reference. ..."
      Annual Leave (AL): "I would like to avail my annual leave
        for 10 days, ... for family trip. ..."
      Maternity Leave (ML, new): "I am writing to request
        maternity leave for 180 days, ... as I am expecting my
        baby in December 2026. ..." — the month comes from the
        from-date, and maternity leave is counted in days like
        the other kinds. The reason the applicant types is used
        for the generic, casual and annual wordings ("for ...");
        sick and maternity use their own fixed phrasing, and the
        typed reason is still stored and shown in the Reason row
        under the letter.
    The department admin adds the formats from the Application
    kinds page: "Create starter kinds" now adds all five at once
    (Maternity Leave and Leave Application are new there — the
    button still skips kinds the department already has, so
    running it again adds nothing twice), and "+ New kind" adds
    more any time. Each kind appears as its own Create card on
    the Application Letters page. The wording lives in two
    places that must stay in step: _default_body() in
    routes_applications.py (server) and fillBody() in
    templates/application_form.html (the form's JavaScript,
    which fills the letter in as the applicant picks dates and
    a reason). A kind is matched by its name: "maternity",
    "sick", "annual" or "casual" anywhere in the name picks that
    wording; anything else gets the plain wording.
    How to apply: extract this zip, then run
        docker compose up -d --build
    This zip includes everything from build 71, so apply only
    this one. If the portal comes up with no data (only the seed
    admin account), the migration from section 86 has not run
    yet — see section 90. No database change. Tests: 926/926
    checks pass on the work copy and on a fresh extract (909
    from builds up to 71 + 17 new). The new checks cover the
    starters creating all five formats with the right prefixes
    and no duplicates on a second run, each kind's wording, the
    form's JavaScript carrying the same branches, the detail
    page and the public code page showing the letter dates in
    day-month-year (and the PDF still doing so), and Maternity
    Leave appearing as a Create card. Back up first and keep
    your live .env untouched, as before.
92. TEMPLATE DROPDOWN ON THE NEW KIND PAGE, AND DELETE FOR A KIND (2026-11-16)
    The department admin was typing the kind name by hand on the
    New kind page — and typing the wrong number prefix with it
    ("Annual Leave" with LV). The page now has a Template dropdown
    at the top listing the five ready-made leave formats: Annual
    Leave, Sick Leave, Casual Leave, Maternity Leave and Leave
    Application. Picking one fills in the kind name and the right
    number prefix (AL, SL, CL, ML, LV) — the kind name IS the
    template name. Leaving the dropdown on "Custom kind" keeps the
    old way: type any name and prefix. The same five feed the
    "Create starter kinds" button, so the two stay in step.
    A kind name is unique per department now: adding a kind the
    department already has is refused ("A kind called ... already
    exists in your department.") instead of making a second kind
    with the same name, and renaming a kind to a name another kind
    has is refused the same way. A kind that was deleted does not
    count — adding it again brings it back.
    Deleting a kind is a new option on the Application kinds page:
    a Delete button next to Edit on every kind row. The delete is
    soft, like the invoice templates: the kind disappears from the
    kinds list and from the Create cards at once and cannot be used
    for a new application, but the applications already made from
    it stay exactly as they are — the kind row is kept behind the
    scenes for them. The kind can be brought back by running
    "Create starter kinds" again or adding it again by name, and
    bringing it back keeps its number counter, so an application
    number is never reused. Only the department's own dept admin
    can delete a kind (a regular user or a dept admin of another
    department gets 403). The Custom Application kind cannot be
    deleted: it is the department's default kind, and the startup
    backfill would only put it back — so it has no Delete button.
    The "How kinds work" card on the kinds page now lists all five
    starters instead of only the first three.
    How to apply: extract this zip, then run
        docker compose up -d --build
    This zip includes everything from build 72, so apply only this
    one. If the portal comes up with no data (only the seed admin
    account), the migration from section 86 has not run yet — see
    section 90. No database change (the delete reuses the kind's
    existing status column). Tests: 947/947 checks pass on the work
    copy and on a fresh extract (926 from builds up to 72 + 21 new).
    The new checks cover the dropdown listing all five formats and
    the JavaScript that fills the name and prefix, the duplicate
    guards on add and on rename, adding a kind from the filled-in
    form and it appearing as a Create card, the soft delete leaving
    the list and the Create cards and refusing new applications
    from it, an application made from a deleted kind still opening
    and its PDF still downloading, both ways of bringing a deleted
    kind back (adding it again by name, and the starters button)
    keeping one row and the number counter, the Custom kind having
    no Delete button and refusing the delete, and the 403s for a
    regular user and for a dept admin of another department. The
    form's JavaScript was also syntax-checked with node --check.
    Back up first and keep your live .env untouched, as before.
93. NO "ASSIGNED TO" DROPDOWN ON THE SALES PIPELINE ADD/EDIT ROW FORMS (2026-11-16)
    The Sales Pipeline "Add row" form had an "Assigned to" dropdown
    (Mohaiminul / Syful / Shanjid / Prince / Imtiaz). A row belongs
    to the user who adds it, so the dropdown is gone from both the
    Add form and the Edit form. Adding a row sets "Assigned to" to
    the adder's name automatically, and editing keeps the stored
    value — the record can never be reassigned to someone else.
    The name is matched to the column's options where possible, so
    the pipeline report keeps grouping the person under the name
    already used there: a user called "Syful Islam" is assigned to
    "Syful". If no option matches the adder's name, their full name
    is used as it stands. Whoever adds the row — a KAM, a dept
    admin, anyone — is the one it is assigned to. The rule is
    enforced on the server, not only by hiding the field: a value
    sent for the missing field anyway is ignored, and the missing
    field never wipes the stored value on edit. The "Assigned to"
    column itself still shows in the tab, on the row detail page
    and in the report; rows added before this build keep the value
    they already had. The rule covers any dropdown column named
    "Assigned to" on any department-database tab (today only the
    Sales Pipeline tab has one).
    How to apply: extract this zip, then run
        docker compose up -d --build
    This zip includes everything from build 73, so apply only this
    one. If the portal comes up with no data (only the seed admin
    account), the migration from section 86 has not run yet — see
    section 90. No database change. Tests: 958/958 checks pass on
    the work copy and on a fresh extract (947 from builds up to 73
    + 11 new). The new checks cover both forms having no Assigned
    to field while the other fields still show, a new row being
    assigned to the adder, a submitted Assigned to value being
    ignored, a KAM's full name being matched to the option already
    used, editing keeping the stored assignee, the column still
    showing on the tab, the pipeline report still downloading for
    the auto-assigned rows, and a dept admin adding a row being
    assigned to themselves. Back up first and keep your live .env
    untouched, as before.
94. SALES PIPELINE REPORT NO LONGER CRASHES WHEN NO ROW IS OPEN OR DONE (2026-11-16)
    Live bug: on the Sales Pipeline tab, ticking one row and clicking
    Report returned a 500 Internal Server Error instead of the PDF.
    The cause: the report's "Pipeline MRC by KAM" bar chart is built
    from the selected rows that are Open or Done. When the selection
    had none of those — the row's Deal stage was blank, or every
    selected row was Terminated — the chart was built from an empty
    list, and ReportLab refuses an empty Table ("must have at least
    a row and column"), so the whole report crashed. The report had
    only ever been tested with rows that had an Open or Done stage,
    so this was never caught. The fix (exports.py): when there is no
    Open or Done row in the selection, the report shows "No open or
    done prospects in the selected rows." where the chart would be,
    and the rest of the report (follow-up counts, KPIs, key message)
    is still made. The same guard is on the follow-up chart, and the
    bar-table helper itself now refuses to build a Table from an
    empty list, so no chart in the report can crash this way again.
    A normal selection with Open/Done rows is unchanged — the chart
    comes back as before.
    How to apply: extract this zip, then run
        docker compose up -d --build
    This zip includes everything from build 74, so apply only this
    one. If the portal comes up with no data (only the seed admin
    account), the migration from section 86 has not run yet — see
    section 90. No database change. Tests: 964/964 checks pass on
    the work copy and on a fresh extract (958 from builds up to 74
    + 6 new). The new checks cover a report from a single row with
    no deal stage, from a single Terminated row, from several rows
    with no prospects, and from a mix with one Open row (the chart
    comes back and the note goes away). Back up first and keep your
    live .env untouched, as before.
95. LEAVE BALANCES ON APPLICATION LETTERS (2026-11-16)
    The Application Letters page now shows each user how much leave
    they have left, and the HR & Admin department admin sets the
    allowance for everybody.
    (1) Leaves table: the "How approval works" card on the
    Application Letters page is replaced by a "My leaves" card — a
    small table with the headings Leaves, Total, Uses, Left. Every
    user sees their own table. The sentence that used to be in that
    card — who can open an application — now sits at the bottom of
    the page instead, so it is still there.
    (2) Leave setup: the HR & Admin department admin has a "Leave
    setup" tab on the Application Letters page (only he sees it).
    From it he chooses a leave type and sets how many days every user
    can take for it in a year. The leave type is a dropdown with
    exactly four options, in this order: Casual Leave, Sick Leave,
    Annual Leave, Maternity Leave. Saving a type that is already set
    up updates its days; the Edit button on a row fills the form with
    that leave; Delete removes it. The setup is company-wide — one
    allowance per leave type for all users — and the leave name goes
    in the Leaves column and the days in the Total column. A leave
    set to 0 days does not appear in any user's Leaves table (it
    stays in the setup table, so it can be set back). The setup
    starts empty: the HR admin sets the numbers himself. The
    example numbers in the preview pictures (Casual 7, Sick 10,
    Annual 15, Maternity 180) were never confirmed as the real
    numbers, so they are not pre-filled.
    (3) Uses and Left: Uses counts the days of the user's
    applications of that kind that are approved or still waiting for
    a decision (Pending or Checked) — the days are deducted when the
    application is sent. If any step user rejects it, the deducted
    days are added back; if the last step user approves it, the days
    stay deducted. Left is Total minus Uses. Only kinds that have a
    leave setup are counted; the generic "Leave Application" kind
    and the Custom Application kind have no balance and are never
    blocked.
    (4) Blocking: a user cannot apply for a leave kind when the days
    asked for are more than the days left — the create form refuses
    it and says how many days are left. Asking for exactly the days
    left is allowed.
    (5) Red: the leave the user has applied for shows its Uses and
    Left in red, while the application is still waiting for a
    decision. The red shows in the user's own table and in the HR
    step user's view of the applicant's table, so it is clear which
    kind of leave is being asked for. Once nothing is pending, the
    red goes away.
    (6) HR view: the HR & Admin step user — the HR user chosen in
    the application's approval chain — sees the applicant's Leaves
    table at the top of the right side of the application detail
    page. A step user who is not in HR does not see it, and neither
    does the applicant on the detail page (the applicant sees their
    own table on the Application Letters page).
    (7) Changing the leave dates: on the application detail page,
    in the decision area, the person whose turn it is sees a Leave
    dates picker (From and To), already filled with the dates the
    applicant chose. Any step user can change the dates when it is
    their turn. The leave balance updates with the new day count,
    and the change is written as a note on the detail page and on
    the PDF — for example, "Leave dates changed by HR Admin:
    17 November 2026 – 19 November 2026 → 18 November 2026 –
    20 November 2026 (3 days → 4 days)." The new dates must still
    fit in the applicant's balance, the same rule as applying — the
    application's own days are freed first, so the step user can set
    up to the total less what the applicant uses on other
    applications. The letter body is the applicant's own words and
    is not rewritten when the dates change; the new dates appear in
    the subject (which is made fresh each time), the Details and the
    note. A Custom Application has no leave dates, so it has no
    date picker. Only the person whose turn it is can change the
    dates — a later step user and the applicant get a 403.
    Two new tables: leave_setup (one row per leave type) and
    application_date_changes (one row per date change, so the note
    can be shown). The database now has 52 tables. The two table-
    count checks (build 67 and build 71) were updated from 50 to 52.
    Open point, not decided in this build: the allowance is counted
    per year — Uses counts only the applications whose leave starts
    in the current year, so the balance resets each January. The
    preview pictures said "Days per year" and this was not corrected,
    but if you want the balance to be a running total that never
    resets, say so and it will be changed.
    How to apply: extract this zip, then run
        docker compose up -d --build
    This zip includes everything from build 75, so apply only this
    one. If the portal comes up with no data (only the seed admin
    account), the migration from section 86 has not run yet — see
    section 90. Back up first and keep your live .env untouched, as
    before. Tests: 994/994 checks pass on the work copy and on a
    fresh extract (964 from builds up to 75 + 30 new). The new checks
    cover the HR admin setting up three leave types (including 0
    days), a regular user being refused the setup (403) and having no
    Leave setup tab, the Leaves table replacing How approval works,
    a 0-day leave not appearing, Uses and the red after applying,
    a 13-day application being refused when only 12 are left, exactly
    12 days being allowed, a rejection giving the days back, an
    approval keeping them deducted, the red going away with nothing
    pending, the HR step user seeing the applicant's table (and a
    non-HR step user and the applicant not seeing it), the date
    picker being pre-filled for the current step user, a date change
    updating the balance and appearing as a note on the page and the
    PDF, a 20-day change being refused, a later step user and the
    applicant being refused the date change (403), and deleting a
    leave setup. The upgrade was also checked: this code starts on a
    build-75 database (50 tables), creates the two new tables, and
    serves the login page.

96. LEAVES TOTAL ROW, DATE-CHANGE NOTE IN THE HR NOTE, NO EDITING AFTER SENDING, SUBJECT ON THE CREATE FORM (2026-11-16)
    Five changes to the leave application letters, all from the live
    portal after build 76.
    (1) Total row. Both Leaves tables — "My leaves" on the
    Application Letters page and "Leaves — {applicant}" on the
    application detail page — now end with a Total row, always the
    last row however many leave kinds are set up. It sums the Total,
    Uses and Left columns (for example, Casual 10 + Sick 14 +
    Annual 21 = Total 45). It is bold with a line above it, and it
    is never shown in red.
    (2) The leave-date-change note. When the HR & Admin step user
    changes the leave dates, the note is written in the user's own
    words and put into the HR note box, so the HR user can edit it
    there before saving it:
        "Leave date change by the Hr Admin : from 17 November 2026 -
        19 November 2026 to 17 November 2026 - 18 November 2026
        ( from 3 days to 2 days)"
    If there is already a note in the box, the new one is added
    after it on a new line, so nothing the HR user wrote before is
    lost. Saving the note (Save note) shows it on the detail page
    and on the PDF. The separate "Leave date changes" block on the
    detail page and the separate date-change paragraphs on the PDF
    are gone — the note lives only in the HR note, which already
    shows on the page and the PDF under "FOR OFFICE USE".
    (3) No "HR note —" label. The note is shown as just the message
    on the detail page (the letter) and on the PDF, with no
    "HR note — Hr Admin:" in front of it. The label is gone from
    both places.
    (4) Frozen after sending. Once an application is sent, nobody
    can edit anything inside it. The Edit button is gone from the
    detail page for everyone — the applicant, the step users and
    the HR & Admin department admin — and opening the Edit page or
    saving an edit is refused (403). The only things that change
    after sending are the HR note and the leave dates, and only the
    HR & Admin user who is a step in this application's chain may
    do those, when it is their turn. Approving and rejecting still
    work as before — that is the chain deciding, not editing.
    (5) The note box and the date change are for the step HR user
    only. A step user from any other department (for example the
    Sales Admin who checks first) sees no HR note box and no Leave
    dates picker, and is refused (403) if they try either. The HR
    & Admin department admin also cannot use the note or change
    the dates unless they are themself the step HR user in that
    application's chain. The HR step user can use them when it is
    their turn, while the application is undecided.
    (6) Subject on the create form, not on the detail page. The
    Subject box is on the New application form only, where the
    user is creating the application — it is not on the detail
    page for anyone. For a leave kind it is filled in from the
    kind, the days and the dates once the dates are picked, and
    the user may change the words there. If the user leaves it as
    filled in, nothing of their own is stored, so the subject
    keeps being made from the current dates and follows a date
    change. If they change the words, their subject is stored and
    shown in the letter and on the PDF. For a Custom Application
    the Subject box is unchanged (the user writes it themself).
    No database change in this build. The two build-76 tables are
    unchanged; application_date_changes still records each date
    change, but nothing is read from it for display any more.
    How to apply: extract this zip, then run
        docker compose up -d --build
    This zip includes everything from build 76, so apply only this
    one. Back up first and keep your live .env untouched, as
    before. Tests: 1036/1036 checks pass on the work copy and on a
    fresh extract (994 from builds up to 76 + 42 new). The new
    checks cover the Total row and that it is last, the Subject box
    on the create form and that the detail page has none, leaving
    the subject as filled in storing nothing and changing it
    storing the user's words (shown in the letter and the PDF),
    the Edit page and the edit being refused for the owner, the
    current step user and the HR department admin (403) and the
    Edit button being gone, a Sales step user and the HR
    department admin seeing no note box or date picker and being
    refused the date change (403), the HR step user seeing the
    picker and the note box on their turn, the date change writing
    the note in the user's words into the HR note and showing it
    on the page and the PDF with no label, the subject following
    the new dates, the balance following the new day count, and
    the HR step user editing and saving the note. The upgrade was
    also checked: this code starts on a build-76 database (52
    tables) and serves the login page.


97. TAB SHARING BY THE DEPARTMENT ADMIN; ROW SHARING REMOVED (2026-11-16)
    A department admin now shares a whole Department Database tab's
    All rows with another department or one specific user. A normal
    user can no longer share one record with anyone, and every row
    share a user already made is gone.
    (1) The Share box is gone from every row's detail page, and the
    "Share this row" and "Shared with" parts are gone with it. The
    old row-share web address answers 404. A row share that was
    already in the database no longer lets anyone open or edit the
    row, and the first start of this build deletes all of them.
    The hint on a tab page now reads "Everyone in this department
    can see every row in a tab. Only the row's owner can edit it."
    and the same words are on the Add/Edit row form and in the
    notifications help. A row's public QR is unchanged.
    (2) On every Department Database tab except Invoices and Request
    items, the department admin of the department that owns the tab
    sees a Permission button on the left of the Select button. A
    regular user never sees it, and it is not on the Invoices or
    Request items tabs. The portal admin can also open it.
    (3) Pressing Permission opens a full page for that tab, with two
    parts: "Shared with departments" and "Shared with individual
    users". Each part lists who already has access (with a Remove
    button) and a form to add one: pick the department or the user,
    pick View or Edit, and add. Only other departments are listed
    (never the admin's own department) and only users from other
    departments. Adding the same department or user again changes
    their access instead of making a second grant. When a tab is
    shared, the other side's department admins (for a department
    grant) or that user (for a user grant) get a notification with a
    link to the tab; removing a grant notifies them too.
    (4) View means see all the rows in the tab and open them, and
    change nothing. Edit means see all the rows and edit the
    existing rows only: the user cannot add a new row, cannot delete
    a row, and cannot change the tab's columns, settings or
    permissions. When both a department grant and a personal grant
    exist for the same person, the better one wins.
    (5) The shared tab appears in the other side's Department
    Database named exactly as the tab name followed by the owning
    department's name in parentheses, with no space before the
    parenthesis — for example Client Info(Sales & Marketing). A
    department grant puts the tab in every user of that
    department's Department Database. An individual user grant puts
    it only in that one user's Department Database; other users in
    that user's department do not see it.
    (6) The granted side sees only the All rows view: no My rows,
    no Deleted, no Permission button, no Add row, and no Tabs,
    Delegates or Columns buttons. The tab page shows only the Total
    rows and Follow-ups due cards. Export, Print and the Sales
    Pipeline Report work on a shared tab the same as on an own tab.
    (7) New table ddb_tab_shares (tab, department or user, access
    view/edit, who made it, when) — 53 tables in total. The old
    ddb_row_shares table is still there but is never read and its
    rows are deleted on the first start of this build. When a user
    account is erased for good, any tab share granted to that user
    goes with it. Tested: 1086/1086 automated checks (1036 of build
    77 plus 50 new) on the work copy and on a fresh extract of this
    zip, against real MySQL 8.0. The upgrade was also checked: this
    code starts on a build-77 database (52 tables), creates the new
    table (53 tables) and deletes the old row shares, and serves the
    login page.


98. DELETED TABS GO TO THE RECYCLE BIN; SHARED TAB STAYS ON INVOICES AND
    REQUEST ITEMS; NO "APPLY TO" LINE ON LEAVE KINDS (2026-11-16)
    (1) A deleted Department Database tab no longer stays on the Tabs
    page. It leaves that page and goes to the Recycle Bin, into a new
    Others tab. The Tabs page now shows only live tabs (no deleted
    tag, no Restore button there). In the Bin's Others tab the deleted
    tab is listed with its department, who deleted it and when it will
    be erased, and it can be restored from there (with its rows) or
    deleted forever. Restoring refuses when a live tab now has the
    same name. A deleted tab is erased for good after 30 days, with
    its rows and columns. Who sees the Others tab: the portal admin
    (every department's deleted tabs) and the department admin or
    delegate of a department (that department's deleted tabs). A
    regular user never sees it. The same erase rule as other Bin
    items applies: only the portal admin can erase a tab a permission
    user or the portal admin deleted. New column ddb_tabs.deleted_by
    (who deleted the tab); no new table, still 53 tables.
    (2) A tab shared with a department or a user used to vanish from
    the tabs row when the user opened the Invoices or Request items
    tab, because those two pages built their tabs row from only the
    department's own tabs. They now use the same tabs row as the main
    Department Database page — own tabs plus the shared tabs — so the
    shared tab stays visible on every tab.
    (3) On the Application Letters page, the line "Apply to an HR &
    Admin user" is gone from the leave kind cards (Leave Application,
    Casual Leave, Sick Leave, Annual Leave, Maternity Leave). Custom
    Application still says "Write your own subject and body".
    Tested: 1113/1113 automated checks (1086 of build 78 plus 27 new)
    on the work copy and on a fresh extract of this zip, against real
    MySQL 8.0. The upgrade was also checked: this code starts on a
    build-78 database (53 tables), adds the deleted_by column and
    serves the login page.


==============================================================================
 99. OFFICE MAIL FOR APPLICATIONS (2026-11-16)
==============================================================================
 1. Mail settings page (portal admin only). Settings -> Mail settings
    (or /admin/mail-settings). Only the portal admin can open it. The
    admin enters everything the portal needs to send mail, and all mail
    goes from this one account:
      - Mail address to send from (the sender address)
      - Password (of that mail address)
      - Mail server (the SMTP server, e.g. mail.hrctech.net for the
        office Icewarp mail, smtp.gmail.com for Gmail,
        smtp.office365.com for Outlook)
      - Port (leave empty for the usual port: 587 for STARTTLS, 465
        for SSL)
      - Encryption: STARTTLS (port 587), SSL (port 465) or None
    Leaving the password blank when saving keeps the saved password.
    The password is stored in the portal's database (settings table).
    For Gmail, Google does not accept the normal account password for
    sending mail — use an App Password from Google instead. The portal
    server must be able to reach the mail server (outbound SMTP).
    A "Send a test mail" box on the same page sends a test mail to an
    address the admin types, so the settings can be checked before any
    real mail goes out.
 2. Each user adds their own mail address in My settings (new Email
    box). A user who has not added an email gets no mail. A bad email
    address is refused when saving.
 3. When a user creates an application, the portal mails:
      - the creator, to their own mail: "You created a [kind]
        application [number]" (with the dates and who it is now with);
      - the step user whose turn it is: "[creator] created a [kind]
        application [number] — waiting for your approval" (with the
        dates and their step, and a link to open it in the portal).
    When a step approves and the application moves to the next step,
    that next step user gets the same "waiting for your approval"
    mail. No mail is sent when the application is finally approved or
    rejected, and no mail is sent for invoices or item requests — only
    for application letters, as asked.
    READING (open): only the step user whose turn it is gets the mail,
    not every step user at once. The chain is strict order, so
    "waiting for your approval" is only true for the person whose turn
    it is. If you want all step users mailed at once when the
    application is created, say so and it will be changed.
    A failed send never breaks creating or deciding an application:
    the application is still created/decided, the mail just does not
    go out. If the sender mail is not set up at all, no mail is sent
    and nothing breaks.
    New: mail.py (the SMTP helper, Python's built-in smtplib, no new
    package) and templates/admin_mail_settings.html. New column
    users.email. No new table, still 53 tables.
    Tested: 1133/1133 automated checks (1113 of build 79 plus 20 new)
    on the work copy and on a fresh extract of this zip, against real
    MySQL 8.0. The upgrade was also checked: this code starts on a
    build-79 database (53 tables), adds the users.email column, keeps
    the old users, and serves the login page.


==============================================================================
 100. MORNING REMINDERS FOLLOW THE TIMEZONE IN .ENV (2026-11-17)
==============================================================================
 The morning reminders (the signature-upload reminder, the personal
 record reminders and the Department Database meeting reminders) used
 to measure "morning" in the server's own local time. The portal ships
 with the server set to UTC, so the 07:00 reminder only started at
 13:00 Dhaka time — users checking in the Dhaka morning saw nothing.
 Now the reminders read the timezone from the .env file (the TZ line,
 which docker-compose reads into the container) and measure the morning
 in that timezone: whatever TZ the .env gives — Asia/Dhaka, UTC or
 anything else — the reminders go out from REMINDER_HOUR (07:00) in
 that timezone. No department is left out: the signature reminder
 already had no department filter, and it is now tested with a Billing
 & Revenue department user too. No schema change, still 53 tables.
 To make the morning a Dhaka morning, the live .env needs
 TZ=Asia/Dhaka (then restart the portal). If the .env says UTC, the
 reminders still go out from 07:00 UTC.
 Tested: 1141/1141 automated checks (1133 of build 80 plus 8 new) on
 the work copy and on a fresh extract of this zip, against real MySQL
 8.0. The upgrade was also checked: this code starts on a build-80
 database (53 tables) and serves the login page.


==============================================================================
 101. SALES PIPELINE TEMPLATE ONLY FOR SALES & MARKETING (2026-11-17)
==============================================================================
 The "Sales Pipeline" template was listed on the Tabs page of every
 department, although the Sales Pipeline is the Sales & Marketing
 department's own default tab. Now the template is only offered on the
 Tabs page of the Sales & Marketing department: every other department
 sees the other templates (Client Info, Meetings, Employee Info,
 Billing, Accounts, Custom tab) without it, and a non-Sales department
 cannot create a Sales Pipeline tab by posting the form either — such
 a post falls back to a blank tab. Sales & Marketing is unchanged: it
 keeps its default Sales Pipeline tab, and its Tabs page still offers
 the template. Tabs another department already made from this template
 are left as they are; this only stops new ones from being offered.
 No schema change, still 53 tables.
 Tested: 1150/1150 automated checks (1141 of build 81 plus 9 new) on
 the work copy and on a fresh extract of this zip, against real MySQL
 8.0. The upgrade was also checked: this code starts on a build-81
 database (53 tables) and serves the login page.

==============================================================================
 102. APPLICATION LETTERS REMOVED (2026-11-17)
==============================================================================
 The whole Application Letters feature is gone from the portal, by the
 user's instruction. The Application Letters page is gone (My / Received
 / All tabs, the Leave setup tab, all Create cards), with it every kind
 (Leave Application, Casual Leave, Sick Leave, Annual Leave, Maternity
 Leave, Custom Application), the Leaves table and the HR & Admin Leave
 setup (days per year), the three-step approval chain, the letter PDFs,
 the public QR and code pages for letters, and Search QR opening a
 letter. The "Application Letters" link is gone from the menu, and the
 Recycle Bin no longer lists letters. All of the data goes with it:
 every existing letter, kind, leave setup, date change and approval
 history is erased when the new code first starts on the live database
 (the six tables are dropped). A database backup taken before applying
 is the only way back — back up first.

 KEPT, untouched: the office mail feature (build 80). The Mail settings
 page, the mail-sending code, the users' mail addresses and the Email
 box in My settings all stay and still work; the mail has no automatic
 trigger any more, since the only mails the portal sent were the
 application-letter ones. The settings-page hint text and the Email box
 hint were rewritten so they no longer talk about applications.
 Signatures stay too: the signature upload in My settings, the morning
 signature reminder, and the signatures on invoices and item requests
 are unchanged, and the designation box stays for the same reason.
 Everything else is untouched: My records, the Department Database
 with all its tabs and the Sales Pipeline, Invoices and Request items
 with their approval chains and public QR, Search QR for invoices,
 requests, rows and public links, the dashboard, users, departments,
 settings and notifications.

 What was removed from the code: the whole routes_applications.py
 file; the 7 application page templates; the letter PDF builder
 (exports.application_pdf); the 6 tables (application_kinds,
 applications, application_history, application_steps, leave_setup,
 application_date_changes) in the schema, plus the upgrade code that
 used to backfill them and seed the Custom Application kind; the
 Bin's application section and its restore/erase routes; the Search
 QR lookup for letters; the application checks in the invoice,
 request and code uniqueness checks; and the "application letters"
 mentions in the Bin, notifications and settings help texts.
 The Management department and its user stay: invoice and item
 request chains still use a Management step person.

 Schema change: 53 tables become 47. No new files; 8 files are gone
 (routes_applications.py and the 7 application templates).
 Tested: 657/657 automated checks on the work copy and on a fresh
 extract of this zip, against real MySQL 8.0 (636 checks for the rest
 of the portal plus 21 new build-83 checks). The upgrade was also
 checked: this code starts on a build-82 database (53 tables, with a
 letter, a kind, leave setup and mail settings) and drops the six
 tables to 47, keeps the user, their mail address and the mail
 settings, and serves the login page with /applications answering 404.

==============================================================================
 103. SALES PIPELINE TAB REMOVED (2026-11-18)
==============================================================================
 The default Sales Pipeline tab is gone from the Sales & Marketing
 department, with all its rows, by the user's instruction. The tab no
 longer appears on the department's page, and the code behind it is
 gone too: the bit that created the tab by default when a Sales &
 Marketing department was made, the startup check that re-created it,
 the 12-column definition, the "Sales Pipeline" template on the Tabs
 page (so no department can make one again), and the Report button
 with its report PDF, since that report only worked on a tab with
 those columns. The "Assigned to" auto-fill stays: it works on any
 tab with an "Assigned to" dropdown, not only the pipeline, and is
 still tested on a plain tab.

 All of the data goes with the tab: every Sales Pipeline row in the
 Sales & Marketing department is erased when the new code first starts
 on the live database. A database backup taken before applying is the
 only way back — back up first. Tabs another department made from the
 template before build 82 are left alone: they are ordinary tabs now
 (their Report button is gone with the report). Everything else is
 untouched: My records, the Department Database with all its other
 tabs, Invoices and Request items with their approval chains and
 public QR, Search QR, the dashboard, users, departments, settings
 and notifications.

 What was removed from the code: core.SALES_PIPELINE_COLUMNS,
 core.ensure_sales_pipeline_tab and core.sales_dept_id; the Sales &
 Marketing branch of core.create_department; the pipeline backfill in
 models._upgrade_ddb_tabs (replaced by models._drop_sales_pipeline_tab,
 which deletes the tab and its rows on upgrade); the "pipeline" entry
 of routes_deptdb.TEMPLATE_TABS and the _templates_for filter;
 routes_deptdb._has_report_columns, _sales_pipeline_data and the
 /deptdb/report route; exports.sales_pipeline_report_pdf with its
 _band/_hbar/_bar_table helpers; the Report button in
 templates/deptdb.html and the .reportguard script in templates/base.html.

 No schema change, still 47 tables. No files added or removed.
 Tested: 607/607 automated checks on the work copy and on a fresh
 extract of this zip, against real MySQL 8.0 (the suite run needs the
 morning hour for one page-load reminder check, so it was run with
 TZ=UTC). The upgrade was also checked: this code starts on a build-83
 database (47 tables, with a Sales Pipeline tab holding rows and
 another Sales tab) and deletes the pipeline tab, its rows and its
 values, keeps the other tab and the user, and serves the login page
 with /deptdb/report answering 404.

==============================================================================
 104. CLIENT ONBOARDING TAB IN THE DEPARTMENT DATABASE (2026-11-18)
==============================================================================
 A new default tab, "Client onboarding", sits next to Invoices and Request
 items on the Department Database page. It follows the customer workflow
 diagram:

   1. A Sales user fills three pages in one form: (1) the client, (2) the
      contacts and the account manager, (3) the services, one block per SOF
      (SOF number, service, details, optional SOF file). Several contacts
      and several SOFs are allowed; at least one of each is needed.
   2. Save sends the request to the Sales admin (the Sales department
      admin, a delegate, or the portal admin), who approves or rejects.
      A rejection needs a reason; the client goes back to the Sales user,
      who changes it and saves again (it is sent for approval again).
   3. Approved: the client is saved and appears in the "Approved client"
      dropdown on the tab. Revenue Assurance is told first and sees it
      (view only); Transmission, Core and Technical support see the full
      record.
   4. SAN report: ONE upload only, by any one of Transmission, Core or
      Technical support. The upload is atomic, so two people uploading at
      the same moment cannot both succeed. Revenue Assurance and all Sales
      users are notified and can download it.
   5. Activation date: only Revenue Assurance can set or change it. Setting
      it completes the client and sends the final record to Finance (a
      later change tells Finance again).

 Status: Waiting for approval -> Approved -> SAN report uploaded ->
 Completed (or Rejected, back to Waiting for approval after the fix).

 WHO SEES WHAT
   Sales department, portal admin ....... every client, at every stage
   The Sales user who made it ........... their own client at every stage
   Revenue Assurance, Transmission,
   Core, Technical support .............. from Approved onward
   Finance .............................. only when Completed
   Everyone else ........................ the tab is not shown at all
 Each client page shows a checklist of the flow, its history (who did what
 and when), and the To do sub-tab lists what is waiting for the viewer.

 SETUP (portal admin): Department Database > Client onboarding > Setup.
 Pick the department for Sales, Revenue Assurance, Transmission, Core,
 Technical support and Finance. Until it is saved, departments are matched
 by name (Sales, Revenue Assurance, Transmission, Core, Technical support or
 Technical, Finance). The portal admin can also remove a wrong SAN report
 before the activation date is set, so a new one can be uploaded.

 NOT INCLUDED (ask if you want them): deleting a client / Recycle Bin,
 Excel or PDF export of clients, public QR and Search QR for clients, and
 an extra "forward" button for Revenue Assurance (all four reviewing
 departments see the client as soon as it is approved).

 Schema change: 47 tables become 51 (client_onboardings, client_contacts,
 client_services, client_history). They are created automatically when the
 new code first starts; nothing existing is changed or deleted. Purging a
 user never deletes a client (the user columns are ON DELETE SET NULL).
 New file: routes_clients.py. New templates: deptdb_clients, client_form,
 client_detail, client_setup. Changed: app.py, models.py, routes_deptdb.py,
 deptdb.html, deptdb_invoices.html, deptdb_requests.html.
 Upload files go to the same attachment folder as other Department
 Database files (allowed types and the per-file size limit are the same).

 Tested: 127 automated end-to-end checks of this flow (every role, every
 step, refused actions, one-upload rule, file keep/replace/remove on edit,
 notifications, search and filters), plus all 74 templates parse and all
 Python files compile. NOT tested: against real MySQL 8.0 and in Docker (not
 available where this build was made); the checks ran on the real portal
 code with SQLite standing in for MySQL. After applying, run
   docker compose up -d --build
 and watch  docker compose logs portal  on the first start. Back up first.
 105. CLIENT DETAIL PAGE 500 ON MYSQL 8.0 — FIXED (2026-11-18)
==============================================================================
 The client onboarding feature (section 104) was tested on SQLite, where
 this worked; on the live MySQL 8.0 it broke every client detail page
 (/clients/1, /clients/2, ...) with a 500 Internal Server Error.

 Cause: routes_clients.py, _load(), joined the users table with the short
 name "dec":
   LEFT JOIN users dec ON dec.id=c.decided_by
 DEC is a reserved word in MySQL 8.0 (short for DECIMAL), so MySQL refused
 the query with error 1064. The query runs before any permission check, so
 the page failed for every user. The tab list, the create form, the setup
 page and the approve flow were not affected — they use other queries.

 Fix: the short name is now "decider" in that one query (the join and
 "decider.full_name AS decided_name"). Nothing else changed: no schema
 change (still 51 tables: 47 + the 4 client tables from section 104), no
 other file touched.

 Tested: the fix was reproduced and verified against real MySQL 8.0 — the
 detail page now opens (200) for the portal admin, the Sales user who
 created the client and the Sales admin, the setup page, the tab list and
 the new-client form all open, and approving a client works and the detail
 page still opens after approval. The build-84 regression suite was also
 run against this code: 604 of 607 checks pass; the 3 remaining failures
 are checks that expect exactly 47 tables, which is the build-83 count —
 the code now correctly has 51 tables with the 4 client tables.
 106. RECYCLE BIN USER PURGE 500 — FIXED (2026-11-18)
==============================================================================
 Purging a deleted user from the Recycle Bin with "Yes, delete all work
 too" showed 500 Internal Server Error. The account could not be erased
 at all — the "No, keep their work" choice was not affected, because it
 never deletes the account.

 Cause: core.purge_user_account() deletes the user's work, then clears a
 long list of places that still name them, and finally deletes the
 account row. It missed five places, each holding a plain foreign key
 to users, so MySQL refused the final DELETE with error 1451:
   activity_log.user_id (every action the user ever did is logged),
   item_request_history.user_id (a request they created or changed),
   ddb_tabs.deleted_by (a DeptDB tab they deleted),
   item_request_kinds.created_by (a request kind they created),
   users.created_by (another account they created).
 Any ONE of these on a deleted user broke the purge; a deleted user
 with none of them purged fine, which is why the tests never caught it.
 The same failure also broke the automatic 30-day cleanup
 (purge_expired calls the same function).

 Fix: five UPDATEs in purge_user_account, next to the other clears, set
 each of these to NULL before the DELETE. The rows stay — only the link
 to the erased account is cleared. The activity log and the request
 history keep their username column, so the history stays readable; a
 tab, a kind or an account created by the erased user keeps working
 with no creator named. No schema change, still 51 tables.

 Tested: all six cases against real MySQL 8.0 — a deleted user with no
 leftover references, and one with each of the five — now purge with
 302 and the account is gone, with every referencing row kept and its
 link NULL. Full regression suite: 619/619 checks (607 from build 84
 plus 12 new b87 purge checks; the three table-count checks now expect
 51 tables, 47 from build 83 plus the 4 client tables from build 85).

==============================================================================
107. RECYCLE BIN "DELETED USERS' DATA" TAB (build 88, 2026-11-18)
==============================================================================
 A deleted user whose work was kept ("No" to "You want to delete this
 user all work from the portal too?") left the Users tab and the Users
 list, and there was no way in the portal to erase them for good — the
 account and their data just sat in the database until the 30 days
 ended. The Recycle Bin now has a fourth tab, "Deleted users' data",
 for the true portal admin only. It lists exactly those users —
 deleted, already removed from the Bin, data still in the database —
 with their name, username, department, who deleted them and when, and
 the date their data would vanish on its own. The portal admin ticks
 the names and clicks "Delete all", and the user and ALL their data go
 at once: their records, Department Database rows, invoices, item
 requests, own columns and public links, plus every reference that
 would block the delete (the same wipe as purging with "Yes, delete
 all work too", core.purge_user_account with delete_work=True). The
 action asks for confirmation first and cannot be undone. Users still
 in the Bin (not yet purged) are never listed here and cannot be
 erased from this tab; a permission user or regular user never sees
 the tab, and posting to it directly returns 403. No schema change,
 still 51 tables.

 Tested: 14 new b88 checks against real MySQL 8.0 — the tab lists the
 No-purged user and not the Bin user, the Users tab still lists the
 Bin user and not the No-purged one, the tab and the action are hidden
 from a regular user and a permission user (403), Delete all erases
 two ticked users and all of their work at once while an unticked user
 stays, and a Bin user posted to Delete all is left untouched. Full
 regression suite: 633/633 checks (619 from build 87 plus 14 new b88
 checks).

==============================================================================
108. REVENUE ASSURANCE FORWARD / REJECT + ATTACHMENT ACCESS REMOVED
     (build 89, 2026-11-19)
==============================================================================
 (A) Client onboarding: Revenue Assurance must forward first. After the
 Sales & Marketing admin approves a client, the client is now visible
 ONLY to Revenue Assurance (view only). It does not go to Transmission,
 Core or Technical support yet. The Revenue Assurance department admin
 (portal admin too, as with the Sales approval) decides on the client
 page, with a dropdown: "Forward to Transmission, Core and Technical
 support" or "Reject — send it back to the Sales user". Forwarding
 moves the client to a new status, "forwarded": only then can
 Transmission, Core and Technical support see the full record, and only
 then can one of them upload the SAN report. Rejecting asks for a
 reason (required): the client goes back to the Sales user with the
 reason shown on the page ("Rejected by ...: ..."), who fixes it and
 saves again to send it back for approval. The "Where it is in the
 flow" list on the client page gained the forward step between
 "Revenue Assurance sees it first" and "Transmission, Core, Technical
 support". The Sales admin's approval message no longer tells the
 three technical departments at once — they are told when Revenue
 Assurance forwards. Clients already approved before this build stay
 approved until the Revenue Assurance admin forwards or rejects them
 from their client page; until then Transmission, Core and Technical
 support cannot see them. The status list gained "forwarded"; the
 database CHECK on client_onboardings.status is widened on upgrade
 (DROP CHECK + ADD CHECK — MODIFY COLUMN only adds a second CHECK and
 the old one would still block 'forwarded', error 3819). No new
 tables, still 51 tables.

 (B) Attachment access is gone. The "User Attachment Access" page
 (Admin > Users button, menu link, route /admin/user-attachment-access
 and the old /admin/ddb-attachment-access redirect) and its code are
 removed, and the "Can use attachment columns" tick on the Add/Edit
 user form is removed. From now on EVERY user can upload attachments
 and add an Attachment column to their own My records, and every
 department admin can create attachment columns in the Department
 Database — no tick anywhere. The users.can_ddb_attachment column
 stays in the database, unused; the CSV import still writes it, which
 has no effect now.

 (C) Virus scanning (no code change). The "could not be scanned"
 error on every upload means the live server has CLAMAV_HOST set
 (usually "clamav") while the ClamAV container is not running, so the
 name does not resolve and every upload is refused. To turn scanning
 off: in the LIVE .env, make the CLAMAV_HOST line empty (CLAMAV_HOST=)
 or delete the line, then restart the portal (docker compose up -d).
 With CLAMAV_HOST empty, uploads skip the scanner entirely. To keep
 scanning instead, start the scanner: COMPOSE_PROFILES=scan docker
 compose up -d (the first start downloads the virus database, so
 allow a few minutes before uploading). The .env inside this zip
 already has CLAMAV_HOST empty, and the live .env must still not be
 overwritten by the zip's .env.

 Tested: 16 new b89 client-flow checks against real MySQL 8.0 — the
 CHECK upgrade on an older database, approval shows the client to
 Revenue Assurance only, Transmission gets 404 before the forward,
 the dropdown is on the page, the forward makes it visible and lets
 the SAN upload through, rejecting without a reason is refused,
 rejecting with a reason goes back to the Sales user with the reason
 shown, and a decided client cannot be decided again. Full regression
 suite: 630/630 checks (619 from build 87, 14 from build 88, and the
 build-61 attachment-access checks rewritten for the removal: the
 pages are 404, the tick is gone, and an unticked user adds an
 Attachment column and uploads a file).

==============================================================================
109. CLIENT STATUS FONT + THE .env COMMENT THAT TURNED SCANNING ON
     (build 90, 2026-11-19)
==============================================================================
 (A) The Status card on the client page was set in the big-number KPI
 size (1.9rem), so a long status phrase filled the whole card in huge
 type. The Status KPI now uses a small text size (1.1rem) through a
 new .k1.txt class; the other KPI values (Services, Contacts,
 Activation date) stay at the big size.

 (B) Why uploads still failed with the scan error even though the live
 .env had CLAMAV_HOST empty: the line in the .env was
 "CLAMAV_HOST=                   # set to: clamav". Docker Compose
 reads a comment on the same line as an EMPTY value as the value
 itself, so the running portal saw CLAMAV_HOST="# set to: clamav" —
 scanning on, host unresolvable, every upload refused with
 "[Errno -2] Name or service not known" (proved by
 "docker compose exec portal env | grep CLAMAV" on the live server).
 The other .env lines have a real value before their comment, so
 theirs are fine; only an empty value has this trap. The fix on the
 server: make the CLAMAV_HOST line bare ("CLAMAV_HOST=" with nothing
 after it — or delete the line), then "docker compose up -d" to
 recreate the container (a plain restart keeps the old container and
 its old value). In this zip the comment moved to its own line above
 CLAMAV_HOST=, so the shipped .env is genuinely empty. The value did
 not change (still empty); the .env md5 changed because the line did.
 Never put a comment on the same line as an empty value in the .env.
 (The live .env also had TZ=Dhaka/Asia, which is backwards — the
 correct name is Asia/Dhaka; see README section 100.)

 Tested: 18 client-flow checks against real MySQL 8.0 (16 from build
 89 plus the .env line check and the Status card class check). Full
 regression suite: 630/630 checks. The client page was rendered to a
 JPG proof (b90-client-status-font.jpg) showing the smaller status.

------------------------------------------------------------------------------
109. (build 90) CLIENT STATUS FONT + THE .env COMMENT THAT TURNED SCANNING ON
------------------------------------------------------------------------------
 (A) The Status card on the client page was set in the big-number KPI
 size (1.9rem), so a long status phrase filled the whole card in huge
 type. The Status KPI now uses a small text size (1.1rem) through a
 new .k1.txt class; the other KPI values (Services, Contacts,
 Activation date) stay at the big size.

 (B) Why uploads still failed with the scan error even though the live
 .env had CLAMAV_HOST empty: the line in the .env was
 "CLAMAV_HOST=                   # set to: clamav". Docker Compose
 reads a comment on the same line as an EMPTY value as the value
 itself, so the running portal saw CLAMAV_HOST="# set to: clamav" —
 scanning on, host unresolvable, every upload refused with
 "[Errno -2] Name or service not known" (proved by
 "docker compose exec portal env | grep CLAMAV" on the live server).
 The other .env lines have a real value before their comment, so
 theirs are fine; only an empty value has this trap. The fix on the
 server: make the CLAMAV_HOST line bare ("CLAMAV_HOST=" with nothing
 after it — or delete the line), then "docker compose up -d" to
 recreate the container (a plain restart keeps the old container and
 its old value). In this zip the comment moved to its own line above
 CLAMAV_HOST=, so the shipped .env is genuinely empty. The value did
 not change (still empty); the .env md5 changed because the line did.
 Never put a comment on the same line as an empty value in the .env.
 (The live .env also had TZ=Dhaka/Asia, which is backwards — the
 correct name is Asia/Dhaka; see README section 100.)

 Tested: 18 client-flow checks against real MySQL 8.0 (16 from build
 89 plus the .env line check and the Status card class check). Full
 regression suite: 630/630 checks. The client page was rendered to a
 JPG proof (b90-client-status-font.jpg) showing the smaller status.

------------------------------------------------------------------------------
110. (build 91) REJECTED CLIENT: REVENUE ASSURANCE LANDS ON THE CLIENT LIST
------------------------------------------------------------------------------
 After the Revenue Assurance admin rejected a client, the page sent
 them back to that client — but a rejected client is invisible to
 Revenue Assurance (only Sales, its owner and the portal admin can
 open it), so the page came back "page not found" (404). Now the
 reject sends the admin to the Client onboarding page (the clients
 tab list), where the "Rejected. It went back to the Sales user."
 message shows. A forward is unchanged: the admin can still open a
 forwarded client, so it still goes back to the client page.

 NOTE — if the portal container keeps restarting after applying a
 build with "pymysql.err.OperationalError: (1045, \"Access denied
 for user 'portal' ...\")": the live .env was overwritten by the
 zip's .env when the zip was extracted over the project. The zip's
 .env carries the placeholder MYSQL_PASSWORD=portal-change-me, which
 does not match the password stored in the live database, so MySQL
 refuses the portal's login and the container restarts forever. The
 code in the build does not touch MySQL logins. To recover: check
 "grep MYSQL_PASSWORD ~/inventory_portal/.env" — if it shows
 portal-change-me, put the real password back (it is on the photo of
 the live .env, or in any backup of it), and while there restore the
 other live values the overwrite took (PORTAL_PORT=8100,
 TZ=Asia/Dhaka, CLAMAV_HOST= bare, REMINDER_HOUR=7). Then
 "docker compose up -d" to recreate the container. Never
 "docker compose down -v" — that deletes the database. Before
 applying any zip, back the live .env up first
 ("cp .env .env.bak") and put it back after extracting.

 Tested: 23 client-flow checks against real MySQL 8.0 (18 from build
 90 plus 5 new reject/forward redirect checks). Full regression
 suite: 630/630 checks.

------------------------------------------------------------------------------
111. (build 92) ACTIVATION DATE: NO BOX ON THE TOP, SALES SETS IT, FINANCE
     WAITS FOR THE FORWARD
------------------------------------------------------------------------------
 (a) The Activation date box is GONE from the top of the client page
 (the KPI row is now Status / Services / Contacts only). The date
 itself still shows on the page, in the Client card.
 (b) The Sales person who creates the record now sets the activation
 date: a new Activation date box on page 1 of the create form. It
 may be left blank — then Revenue Assurance fills it in later. A
 date that is not a real date is refused. The date is stored with
 who set it. A rejected client keeps its date when it is saved
 again, and the Sales user can change it there.
 (c) Revenue Assurance can still change the date after the SAN report
 is uploaded, but changing it no longer completes the record and no
 longer tells Finance. Finance still cannot open the record.
 (d) Sending the record to Finance is now a separate step: after the
 SAN report is uploaded and the date is on the record, the Revenue
 Assurance admin forwards it with the new Forward to Finance button
 on the client page. Only then does the record become Completed,
 only then can Finance open it, and only then is Finance told.
 Forwarding with no date on the record is refused ("Set the
 activation date first."). The flow list has the new step ("Revenue
 Assurance forwards it to Finance") between the activation date and
 Finance receiving the record, and the SAN-uploaded status now reads
 "waiting for activation date and forward to Finance". Changing the
 date on a record that is already with Finance still tells Finance,
 as before. The forward is an admin action (Revenue Assurance dept
 admin or portal admin), like the first forward; any Revenue
 Assurance user can still edit the date.

 Tested: 45 client-flow checks against real MySQL 8.0 (23 from build
 91 plus 22 new build-92 checks: no date box on the top, the date on
 the create form, blank and bad dates, the date edit not completing
 the record, Finance blind until the forward, the forward needing a
 date, Finance seeing the date after the forward). Full regression
 suite: 630/630 checks.

------------------------------------------------------------------------------
112. (build 93) CONFIGURABLE ADD CLIENT FORM, PER-SOF ACTIVATION DATE AND
     SOF PDF, ACCOUNT MANAGER INFORMATION
------------------------------------------------------------------------------
 (a) The Add Client form's fields are now set by the Sales & Marketing
 department admin: a new "Form setup" button on the Client onboarding
 tab opens /clients/form-setup, where the admin sets, for each of the
 three pages, each field's column name, input type and whether it is
 required. Input types are the same as before (Text, Long text,
 Number, Date, Dropdown, Yes-No). The fields that were there before
 are the defaults; the admin adds fields on top of them or changes
 them. A structural field (client name, contact name, SOF number,
 SOF service, SOF activation date) cannot be made optional and its
 type cannot be changed. A custom field can be renamed, moved up or
 down, or removed (removing it deletes its saved values too). Custom
 values are stored per client, per contact and per SOF (new tables
 client_form_fields and client_field_values; 53 tables now).
 (b) The activation date now lives on EVERY SOF, not on the client.
 The Sales person sets it for each SOF when creating the record; a
 SOF without a date is refused, and a date that is not a real date
 is refused. There is no activation date box on the client page any
 more and no date in the Client card. A client created before this
 build keeps its old client-level date copied onto each of its SOFs
 that has none (the old client_onboardings.activation_date column
 stays in the database, unused).
 (c) After the SAN report is uploaded, Revenue Assurance can change a
 SOF's activation date from the date box on that SOF's row. Changing
 it does not complete the record and does not tell Finance. Only the
 Revenue Assurance admin (or the portal admin) can edit it — an
 ordinary Revenue Assurance user cannot (build 92 let any Revenue
 Assurance user edit the client-level date). Changing the date on a
 record that is already with Finance still tells Finance, as before.
 (d) Forwarding to Finance now needs an activation date on EVERY SOF.
 Forwarding with a SOF that has none is refused ("Set the activation
 date on every SOF first (… still has none)."). The Forward button
 stays hidden until every SOF is dated, with the hint "Set the
 activation date on every SOF first."
 (e) Every SOF row has a Download PDF button on its right. One PDF per
 SOF, in the Service Order Form format: HRC logo and company name
 and address top left, "Service Order Form" top right, client and
 SOF details (SOF number, date, activation date, account manager),
 the service, the contacts, and the Prepared By / Checked By /
 Approved By signature blocks (Checked By is whoever approved the
 record, Approved By whoever forwarded it). The SOF has its own
 public share code (HRC- plus a random five digits, unique across
 invoices, requests, DeptDB rows and SOFs): the code page opens
 without a login, and Search QR finds it.
 (f) The account manager's information is shown under the account
 manager dropdown on the contacts page: full name, designation,
 phone and email. Full name and designation are filled in from the
 information given when the manager's account was created; phone
 and email come from what the manager gave at their first login.
 Picking a manager fills all four in, and the Sales person can
 change them on the form — the change is for THIS client only and
 never touches the manager's profile. New users give their full
 name, designation, phone and email together with their new password
 on the forced change-password page at first login, and can change
 them later in My settings (phone is a new column on the user).
 (g) Side fixes in this build: the client-status CHECK upgrade in
 models._upgrade_client_status matched the stored clause with the
 quoted form "'forwarded'", which MySQL's escaped clause
 (_utf8mb4\'forwarded\') never contains — so the widened CHECK was
 dropped and re-added on every upgrade, and the second DROP on the
 same table inside one uncommitted init_db transaction could
 deadlock with InnoDB's statistics thread (seen once while testing
 this build: init_db hung for minutes waiting on a metadata lock).
 It now matches the bare word "forwarded". The "Who does what" hint
 on the Client onboarding tab now reads "Finance sees it once
 Revenue Assurance forwards it." The old client-level activation
 route is gone; the date is edited per SOF.

 Tested: 69 client-flow checks against real MySQL 8.0 (23 from build
 91 plus 46 new build-93 checks: form setup, per-SOF dates, SOF PDF
 and code page, the RA per-SOF edit, the forward gate, first-login
 information, the upgrade copy of the old date). Full regression
 suite: 630/630 checks.

------------------------------------------------------------------------------
113. (build 94) NO SIGNATURE OR APPROVAL BLOCKS IN THE SOF PDF
------------------------------------------------------------------------------
 The SOF PDF no longer has any signature or approval format: the
 Prepared By / Checked By / Approved By blocks are gone. Everything
 else in the PDF is unchanged — the HRC logo and company name and
 address, the "Service Order Form" title, the client and SOF details
 (SOF number, date, activation date, account manager), the service,
 the contacts, and the QR with the share code at the bottom left.
 The signature lookup that only fed the SOF PDF is gone too, and the
 invoice and request PDFs still have their signature blocks as
 before.

 Tested: 70 client-flow checks against real MySQL 8.0 (69 from build
 93 plus 1 new build-94 check: no Prepared By / Checked By /
 Approved By text in the SOF PDF). Full regression suite: 630/630
 checks.

------------------------------------------------------------------------------
114. (build 95) DELETE BUTTON ON EVERY FIELD IN THE CLIENT FORM SETUP
------------------------------------------------------------------------------
 The Add Client form setup page now has a Delete button on the right
 of every field row, not only on the fields the Sales admin added
 himself. The Sales & Marketing admin can delete a default field too:
 the old refusal ("A default field cannot be removed.") is gone.

 The five structural fields still cannot be deleted — Client name,
 Contact name, SOF number, Service, and Activation date — because the
 Add Client form cannot work without them. Trying to delete one is
 refused with "A structural field cannot be removed." The other nine
 defaults can be deleted: Business type, Address, Phone, Email, Notes
 (page 1); Designation, Phone, Email (page 2, contacts); Details
 (page 3, services).

 Deleting a field works the same for a default as for a field the
 admin added: the field disappears from the Add Client form and from
 the client page, and everything already entered in it is deleted
 with it. Default fields keep their values in the real columns
 (Business type, Address, Phone, Email, Notes on the client; the
 contact's Designation, Phone, Email; the SOF's Details), so deleting
 one clears those columns for every client. A deleted default can be
 added back with + Add field under the same name, but its old values
 are gone. Nothing else changes: default fields still cannot change
 type, the structural ones stay required, and only the Sales admin
 (or the portal admin) can open the form setup page.

 Tested: 77 client-flow checks against real MySQL 8.0 (70 from build
 94 plus 7 new build-95 checks: the Delete button on a default row
 and none on a structural row, the test client's values in the
 default fields, deleting a default clears its values and hides it
 from the form and the client page, a structural field cannot be
 deleted, a deleted default can be added back with its old values
 gone, deleting a contact / SOF default clears its column and hides
 its column). Full regression suite: 630/630 checks.

==============================================================================
115. CLIENT PAGE FIXES: SERIAL NUMBERS, TIMES IN THE PORTAL TIMEZONE,
    DOWNLOAD SOF, HIDDEN HISTORY, ACCOUNT-MANAGER TABLE AND WATCHERS
    (build 96, 2026-11-22)
==============================================================================
 (A) Client numbers are plain serials from 1: the list, the client
     page heading and the SOF PDF show "5" instead of "CL-0005". The
     search box still finds a client by typing "5" or "CL-0005", and a
     number is never reused after a client is deleted.
 (B) "Added by" is gone from the Client onboarding list and from the
     client page, but the notification when a client is added still
     goes to the Sales admin: "sales user sent a new client 'X' for
     approval."
 (C) The list's Activation column shows every SOF's activation date
     for that client (for example "2026-11-18, 2026-12-01"). It used
     to show the stale client-level activation_date, which has been
     unused since build 93 and is empty on new clients.
 (D) Every date and time the portal shows is now in the TZ from the
     .env file (Asia/Dhaka). The database container runs on UTC, so
     every time it stores (notifications, history, activity, sessions,
     comments, record dates) is read as UTC and shown in the portal's
     timezone through the new showdttz filter. Dates and times a user
     typed (DeptDB date columns, reminder dates, meeting times) are
     shown exactly as typed and are never shifted. Watch tomorrow
     07:00 and tell us whether the signature reminder arrives at
     07:00 Dhaka — the reminder itself was already set to go from
     07:00, and it fired at 09:32 on 2026-11-22 only because the
     portal was first opened after 07:00 that morning.
 (E) A SOF number cannot repeat: saving a client is refused when a
     SOF number is used twice in the same client or is already used on
     another client, and the error names the number. Editing a client
     and keeping its own SOF numbers still works.
 (F) Every SOF row has a "Download SOF" button that downloads the
     file uploaded as the attachment in the services part of the form.
     When no file was uploaded the row shows "—". The SOF PDF itself
     is unchanged and still downloads from the public share-code page.
 (G) History on the client page is hidden when the page opens. A
     "Show history" button on the right of the History heading shows
     it; clicking again hides it.
 (H) The client page has its own "Account manager" section with a
     table of the manager's contact details: Name, Designation,
     Phone, Email. The three account-manager rows are no longer in
     the Client card.
 (I) Once a Sales user has added a client, the account manager of
     that client and the Sales admin get every notification about
     it: approval, rejection by the Sales admin or by Revenue
     Assurance, the Revenue Assurance forward, the SAN upload, an
     activation date being set or changed, and the forward to
     Finance. The people who got those notifications before still
     get them (the owner, Revenue Assurance, Transmission / Core /
     Technical support, Finance), and nobody is told about their own
     action. Two things told nobody before and tell the account
     manager and the Sales admin now: removing the SAN report, and
     changing an activation date before the record is completed. The
     very first "client added" notice still goes to the Sales admin
     only; the account manager starts getting them from the approval
     onwards, and a re-save (edit) tells the account manager too.

 Tested: 99 client-flow checks against real MySQL 8.0 (77 from build
 95 plus 22 new build-96 checks: the client with two SOFs is created
 and the add notice goes to the Sales admin only; the plain serial
 number on the client page, the list and the SOF PDF; no Added by
 column or line; the list shows both SOF dates; a stored UTC time is
 shown in Dhaka time on the Notifications page, in History and on
 the SAN line, while a date-only value is unchanged; a repeated SOF
 number is refused in the same client and on another client and the
 error names the number, while keeping your own numbers on edit
 works; the Download SOF button downloads the uploaded file, no
 button when no file was uploaded, and the SOF PDF is still on the
 code page; History is hidden with a Show history button; the
 Account manager table shows name, designation, phone and email; the
 account manager and the Sales admin are told about the approval,
 the rejection, the re-save, the forward, the SAN upload, the
 activation date change, the SAN removal and the forward to Finance
 — and the forward tells them once, not once per technical
 department). Full regression suite: 630/630 checks.

==============================================================================
116. ACCOUNT MANAGER EDITS BEFORE APPROVAL, ACCOUNT MANAGER IN
    CONTACTS AND AT THE TOP, AND THE UI AT 70% (build 97, 2026-11-22)
==============================================================================
 (A) While a client is still waiting for the Sales admin's approval,
     its account manager can open it and change the data, with the
     same "Change and save again" form (client info, contacts,
     services). The client stays waiting for approval after the
     change — the change does not approve it, and the Sales admin can
     still approve or reject it. When the account manager changes it,
     the Sales admin and the owner are told it was changed and is
     still waiting for approval. The Sales user who made the client
     still cannot change it while it is pending, unless they are also
     the account manager, and the Sales admin cannot change it either
     (they approve or reject it). A rejected client is still changed
     by the owner or the Sales admin as before, and once approved
     nobody can edit it.
 (B) The Account manager table moved into the Contacts card, under
     its own "Account manager" heading and above the contacts table.
     It is no longer a section of its own after the Client card, and
     the Client card has nothing about the account manager in it.
 (C) The account manager is highlighted at the top of the client
     page: a fourth card in the row with Status, Services (SOF) and
     Contacts shows his name, with his designation underneath.
 (D) The whole portal looks the way it looked with the browser
     zoomed out to 70%, with the browser zoom left at 100%: one
     screen-only rule (root zoom .7) makes everything smaller by the
     same amount — text, cards, tables, buttons, the login page too.
     Printing is unchanged. (Build 98 moved the zoom from the body
     to the root element — see section 117 — because the body zoom
     shrank the full-height login background. Build 99 removed the
     zoom entirely — see section 118 — because the login still
     showed the white band: the portal is back to its normal size
     and fills the screen at every browser zoom.)

 Tested: 114 client-flow checks against real MySQL 8.0 (99 from
 build 96 plus 15 build-97 checks: the account manager can open
 the edit form on a pending client and save a change that keeps it
 pending, the Sales admin and the owner are told about the change
 and the account manager is not told about their own change, the
 owner, the Sales admin and another Sales user cannot change a
 pending client, the account manager cannot change an approved
 client, the Account manager table sits inside the Contacts card
 and the Client card has nothing about the account manager, the
 Account manager card at the top shows his name and designation,
 and the stylesheet carries the screen-only 70% rule). Full
 regression suite: 630/630 checks.

==============================================================================
117. THE 70% ZOOM FIXED ON THE LOGIN PAGE (build 98, 2026-11-22)
==============================================================================
 Build 97 put the 70% zoom on the body, and the login page came out
 wrong: its blue background only covered the top 70% of the screen
 and the bottom was a white band. The cause is that the login
 background is 100vh tall, and 100vh inside a zoomed body is 70%
 of the real screen. The zoom now sits on the root element instead,
 so it behaves exactly like the browser's own zoom: the layout
 viewport itself is scaled, 100vh still means the full screen, and
 the login background fills the screen again. Nothing else changes:
 the portal still looks like the browser zoomed out to 70% with the
 browser zoom at 100%, and printing is unchanged. (Side effect of
 the root zoom, the same as the browser's own zoom: the narrow-screen
 rules now switch at a narrower window, since the layout viewport is
 wider than the window.)

 Superseded by build 99 (section 118): the login still showed the
 white band, so the fixed zoom was removed entirely.

 Tested: 114 client-flow checks and the full 630/630 regression
 suite against real MySQL 8.0, on the work copy and on a fresh
 extract of the zip.

==============================================================================
118. THE ZOOM RULE REMOVED — THE PORTAL IS RESPONSIVE NOW (build 99,
    2026-11-22)
==============================================================================
 The login page still showed the white band at 100% browser zoom,
 after two zoom fixes (body, then the root element). The fixed zoom
 is gone entirely: there is no zoom rule anywhere in the stylesheet
 any more. With no zoom rule, 100vh is the visual viewport at EVERY
 browser zoom, so the login background fills the screen whether the
 browser is zoomed out, at 100% or zoomed in — and the narrow rules
 (card stacked, hero hidden under 980px) take over when the window,
 or the zoom, makes the page narrow. That is the responsive
 behaviour: the page follows the browser's zoom instead of fighting
 it. The only viewport-sized elements are the login background
 (.lgx, 100vh) and the narrow login column (.side, 100vh); the two
 fixed panels and the sticky bar on narrow screens are unchanged.

 One plain consequence: the portal is back to its normal size at
 100% browser zoom — the smaller 70% look from builds 97 and 98 is
 gone with the zoom rule. If it is still wanted smaller, the
 browser's own zoom now works properly on every page (it was the
 fixed zoom that broke the login), or a proper responsive rescale
 can be built instead of a zoom rule.

 Tested: the real login page rendered to JPG at 1440x900 and at
 700x900 — the gradient fills the whole page at both widths, no
 white band (b99-login-desktop.jpg, b99-login-narrow.jpg). The
 narrow render is WeasyPrint, which does not apply width media
 queries, so it shows the gradient filling a narrow page but not
 the column switch itself; the column switch is the existing
 980px rule and is judged in real Chrome. 114 client-flow checks
 and the full 630/630 regression suite against real MySQL 8.0, on
 the work copy and on a fresh extract of the zip.

 Superseded by build 100 (section 119): the 70% look is back, with
 the login gradient on the page body so the band cannot return.

==============================================================================
119. THE 70% LOOK IS BACK, AND THE WHITE BAND CANNOT RETURN
    (build 100, 2026-11-22)
==============================================================================
 The user showed the portal pages are still big at 100% browser
 zoom, while the login band itself was fixed. The 70% look is back:
 the zoom sits on the body again, screen only. It sits on the body
 and not the root element this time, so the narrow rules still
 switch at the real window width. And the band cannot come back
 with it: the login gradient moved off the .lgx panel onto the page
 body itself (a new bodyclass block in base.html, set to
 login-page by the login template). A body's background paints the
 whole canvas, so the screen is gradient even if the panel's 100vh
 ever comes out short at some zoom; the .lgx keeps its layout and
 is transparent now, so the one gradient shows through it with no
 seam. The rule is screen only, so printing is unchanged.

 Tested: the real login page rendered to JPG at 1440x900 and at
 700x900 — the gradient fills the whole page at both widths, no
 white band (b100-login-desktop.jpg, b100-login-narrow.jpg). The
 narrow render is WeasyPrint, which does not apply width media
 queries, so it shows the gradient filling a narrow page but not
 the column switch itself; the column switch is the existing
 980px rule and is judged in real Chrome. 114 client-flow checks
 and the full 630/630 regression suite against real MySQL 8.0, on
 the work copy and on a fresh extract of the zip.

 Superseded by build 101 (section 120): the band came back, so the
 gradient is back on the panel, made taller to fill the screen.

==============================================================================
120. THE LOGIN BAND IS FIXED BY A TALLER PANEL (build 101, 2026-11-22)
==============================================================================
 The login page still showed a band at the bottom: the gradient
 stopped at about 70% of the screen and a darker band sat below
 it. The cause is the body's background: it is sized to the body's
 own box (100vh in layout pixels) and painted scaled by the zoom,
 so it covered only the top 70% of the screen and then repeated
 dark below it. The gradient is back on the .lgx panel, and the
 panel is min-height calc(100vh / .7) — 100vh inside the zoomed
 body is 70% of the screen, so a panel 1 / .7 times as tall is
 exactly the full screen once the zoom paints it. The narrow login
 column is stretched the same way. The body gradient, the
 bodyclass block in base.html and the login-page class are all
 gone. The zoom stays on the body (not the root element), so the
 narrow rules still switch at the real window width. The gradient
 is drawn over the taller panel, so it reads a touch darker than
 the no-zoom login — same colours, same angle, no seam.

 Tested: the real login page rendered to JPG at 1440x1286 (the
 panel's full height, as the browser shows it scaled to the
 screen) — the gradient fills the whole panel with no seam, card
 and hero centred (b101-login-desktop.jpg). WeasyPrint ignores the
 zoom, so a 900px-high render cuts the tall panel in half; the
 1286px render is the honest one. 114 client-flow checks and the
 full 630/630 regression suite against real MySQL 8.0, on the work
 copy and on a fresh extract of the zip.

121. EACH SERVICE HAS ITS OWN STATUS, AND THE ACCOUNT MANAGER CAN ADD
    OR EDIT SERVICES ON A FINISHED CLIENT (build 102, 2026-11-22)
==============================================================================
 The Client onboarding list and the client page now treat each SOF
 as its own service with its own status, and the account manager
 can add a service or edit an activated one on a finished client
 through the Sales department admin.

 THE LIST
 The clients sort in ascending order. The Status column counts the
 client's services by their own state: "Activated n" in green,
 "Terminated n" in red, and "Pending n" in yellow, shown only when
 a pending edited SOF is in flow. The client's own status (Pending,
 Approved, Forwarded, SAN uploaded, Completed, Rejected) moved to
 a new Flow column. The Activation column shows each activation
 date followed by the short service name in brackets, for example
 "2026-11-18 (internet)". A new Terminated column shows the same
 for terminated services: the termination date with the short
 service name in brackets. The filters grew too: an account manager
 filter, a month filter (pick a month, then Activation or
 Termination, to see that month's activations or terminations),
 and the status filter now also offers Pending SOF, Activated SOF
 and Terminated SOF.

 SERVICE TYPE AND DESCRIPTION
 The SOF page has two new fields the user must fill: service type
 and service description. The service type is the short service
 name — it is what shows in brackets after the dates on the list
 and on the client page. Both fields are structural on the Add
 Client form setup (page 3), so they cannot be deleted like the
 other defaults. On a database upgraded from an earlier build,
 each existing SOF takes its service name as its service type, and
 is marked activated where its client is finished and its
 activation date is set, or terminated where it already has a
 termination date.

 ADD SERVICES
 On a finished client, "+ Add services" sits on the right of
 "Services (SOF)". It opens the same Add Client form for the
 account manager, who can edit the client contact information and
 add a new Service SOF; after adding, the flow continues as it
 should. A contact change applies at once. A new SOF does not
 appear on the client until the Sales department admin approves
 it; after approval it is pending, and Revenue Assurance sets its
 activation date, which makes it activated. The portal admin can
 also use Add services, and a portal admin's changes apply at
 once with no approval step.

 EDITING A SOF
 Each SOF row has an Edit button on its right. Only an activated
 SOF can be edited — a terminated SOF cannot be edited at all,
 and the account manager can edit again only after the full flow
 has run. The edit page lets the account manager change the SOF
 and add a termination date, a commercial impact date and a
 termination reason (the reason is optional; the two dates are
 only needed when the service is being terminated). Nothing
 changes on the client while the edit waits: the SOF keeps its
 old values and stays activated. The Sales department admin
 receives a notification naming that specific SOF, with the edit
 history showing what changed, and approves or rejects it from
 the card on the client page (a rejection needs a reason). After
 approval, only that specific SOF goes to pending — the client
 stays finished and no other SOF is touched — and the full flow
 starts again for that SOF. The termination itself takes effect
 after the full flow: when Revenue Assurance sets the activation
 date on the pending SOF, it becomes terminated, and the
 termination date then shows on the list's Terminated column with
 the short service name in brackets, and on the client page under
 the SOF as "Terminated <date> · Commercial impact <date> ·
 <reason>". The portal admin's own SOF edit applies at once, with
 no approval step.

 THE CLIENT PAGE
 The Contacts card now has a "Client contact person" heading on
 top of the contact-person information, and both the account
 manager table and the contact-person table use the same fixed
 column widths, so each column name lines up with its data. The
 Services table gained a Type column (the short service name), a
 Status column (the SOF's own pill: green Activated, yellow
 Pending, red Terminated) and the Edit column, and shows the
 service description under the service name.

 Tested: the client page and the list rendered to JPG and read
 back (b102-client-detail.jpg, b102-client-list.jpg) — the
 heading, the aligned tables, the Services table and the
 Status/Flow/Activation/Terminated columns are all as described.
 142 client-flow checks and the full 634/634 regression suite
 against real MySQL 8.0, on the work copy and on a fresh extract
 of the zip.

122. THE WHOLE PORTAL IS RESTYLED TO THE GLASS DESIGN (build 103, 2026-11-22)
==============================================================================
 Every page of the portal now looks like the design in
 glass-ui-all-pages.zip (27 JPGs): a soft pastel gradient
 background, frosted glass cards, and a floating glass sidebar
 on the left instead of the top header bar. Nothing about the
 features changed — only the look. All build-102 features stay:
 the per-SOF statuses, the Flow column, the SOF edit approval
 flow, the filters, the contacts alignment and Add services
 are all still there, restyled in glass. The PDFs do not change
 at all.

 THE SIDEBAR
 The top header bar is gone. Navigation lives in a floating
 glass panel on the left, grouped the way the design shows it:
 Workspace (Dashboard, All records, Users' records, My records,
 Department database, Invoice templates), Tools (Search QR,
 Reminders, Recycle bin, Public QR links, Reports) and
 Administration (Users, Departments, Import users, Activity,
 Sessions, Settings). The links and their permission rules are
 exactly the ones the top bar had: a department admin sees
 Users under Administration, a regular user sees only their own
 pages, and so on. The user card sits at the bottom of the
 sidebar, with the appearance (light/dark/auto) choice, My
 settings and Log out in its menu. The notifications bell
 floats at the top right of the content, with the unread count
 badge, as before. On a phone the sidebar becomes a drawer
 opened from the menu button in the top bar.

 THE GLASS LOOK
 Cards, tables, KPI cards and the tab bar are frosted glass:
 translucent white with a soft blur over the gradient, a white
 border and a big radius. Table headers have no band and rows
 have no stripes any more, so the glass shows through; the
 active tab is the teal-to-blue gradient pill. Buttons keep the
 portal's teal-to-blue gradient. The login page is the design's
 login: the pastel gradient, the frosted card on the left with
 "Welcome back", and the hero on the right reading "Every
 record, one clear place." with the second line in gradient
 teal-to-blue. The dark theme is the design's dark login and
 dashboard: a deep navy gradient with dark glass cards and
 light text, and the same light/dark/auto choice in the menu
 and under the login card. The 70% zoom stays, and the gradient
 is painted the build-101-safe way: the login panel and the
 sidebar are made taller by the same amount as the zoom
 shrinks them, so they fill the screen exactly and no band can
 come back.

 WHAT THE PICTURES SHOW THAT THE PORTAL DOES NOT HAVE
 The design pictures show three things the portal does not
 have, and they were NOT added: "Comments and suggestions" on
 a record, "Recent scans" on Search QR, and notification
 preference toggles. Those are new features, not a restyle;
 ask for them and they can be built. The pictures also use
 sample data (names, invoice numbers, share codes) — the
 portal keeps its real data, its real invoice numbers, its
 real HRC-##### share codes and its real branding from the
 settings. Two small simplifications: the KPI cards have no
 little icon chip in the corner (that would have meant
 threading an icon through every KPI on every page), and the
 tables have no avatar chips inside them (only the user card
 in the sidebar has one). The bell floats at the top right of
 the content instead of sitting inside each page's title row;
 the content keeps 84px of right padding so it never covers a
 page's own buttons.

 Tested: the login page and the dashboard rendered to JPG and
 read back (b103-login.jpg, b103-login-dark.jpg,
 b103-dashboard.jpg), and the client onboarding list and client
 page the same way (b103-client-list.jpg,
 b103-client-detail.jpg) — the sidebar, the glass cards, the
 KPI rows, the Status/Flow/Activation/Terminated columns and
 the SOF table are all as described. 149 client-flow checks
 and the full 638/638 regression suite against real MySQL 8.0,
 on the work copy and on a fresh extract of the zip.

==============================================================================
 123. DASHBOARD CHARTS, WIDER CLIENT LIST, USER MENU, LOGO AND MONTH RANGE
     (2026-11-23)
==============================================================================
 Five small fixes on the glass pages, from your photos of the live
 portal (2026-11-23):

 (1) DASHBOARD CHARTS. On "Records by department" the department
     names sat off to the side of their bars — "IT" under one bar,
     "Revenue Assurance" under another. The three chart rows (the
     numbers, the bars, the names) were three separate flex rows, and
     the name row gave long names wider columns than the bars got.
     Every column in all three rows is now exactly the same width,
     so each name sits centred under its own bar and long names wrap
     inside their own column. The same fix covers the chart on the
     client page, which shares the rows.

 (2) WIDER CLIENT LIST. The middle of the Client onboarding list
     was squeezed: the Status pills split across two lines
     ("Activated" over "0") and the Flow text wrapped to four or
     five lines. The list page is now wider (the page cap is
     1560px instead of 1400px), the right-hand rail is narrower
     (280px instead of 340px), the table has a minimum width of
     1080px so it scrolls sideways on a narrow screen instead of
     crushing, and a Status pill never splits across lines. Only
     the client list page changed — the dashboard, the other
     Department Database tabs and the client page keep the old
     widths.

 (3) USER MENU. Clicking your name opened the Appearance / My
     settings / Log out box right on top of the name, so you could
     not see who was signed in. The box now opens just above the
     user card, and your name and avatar stay visible below it.
     (On a phone it is still the full-width sheet at the top.)

 (4) THE LOGO. The sidebar showed a plain "H" tile where the old
     top bar showed the real HRC logo. The real logo image is back
     in that spot — the same logo the login page uses. If no logo
     is set in the settings, the "H" tile shows instead. In the
     dark theme the logo sits on a white chip, like on the login
     page, so it stays readable on the dark glass.

 (5) MONTH FILTER, NOW A RANGE. The Client onboarding filter had
     one single month. It is now a From month and a To month, with
     the same Activation / Termination choice beside them: pick a
     span (for example November 2026 to January 2027) and the list
     shows the clients activated — or terminated — inside it. It
     works the same for every user: portal admin, department admin
     and regular user (there was never a role check on this filter
     in the code). If From is later than To, the two are swapped
     instead of giving an empty list. An old link with a single
     ?month= still works and counts as From = To = that month.

 OPEN: you said the month could not be selected, and did not say
 whether the month box would not open at all when clicked, or
 whether picking a month and clicking Apply left the list
 unchanged. The new From/To filters were tested end to end —
 including as a plain sales user — and the list filters correctly.
 If the new month boxes still will not open on your machine,
 tell me: the boxes are the same kind of month input as before,
 so that would be a browser-side problem, not the filter.

 Tested: the dashboard and the client list rendered to JPG and
 read back (b104-dashboard.jpg, b104-client-list.jpg) — the logo
 in the sidebar, the chart names centred under their bars, the
 Status pills on one line, the wider Flow column, and the From /
 To month boxes in the filter row — and the user menu open above
 the user card (b104-popup.jpg). 161 client-flow checks and the
 full 643/643 regression suite against real MySQL 8.0, on the work
 copy and on a fresh extract of the zip.

==============================================================================
 124. EVERY PAGE WIDER, CENTRED USER MENU, SHORT SAN LABEL, SAME-SIZE
     CONTACT BOX, ONE SAN REPORT PER SOF, APPROVAL NOTICE FIX, SOF
     COLUMNS AND SOF VIEW PAGE (2026-11-23)
==============================================================================
 Eight things from your photos and messages of 2026-11-23. The first
 six are built; the last two are NOT built yet — they are listed as
 OPEN below, and the old behaviour stays until you answer the
 questions.

 (1) EVERY PAGE AT THE CLIENT-LIST SIZE. You said: not just the
     Client onboarding page — every page should look like the
     Client onboarding page size. The page width is now 1560px on
     every page (it was 1400px), and the side rail is 280px on
     every page. The separate "wide" rules for the client list are
     gone, because the base rules are now the same size.

 (2) USER MENU CENTRED. You said: when you click the user name,
     the pop-up goes slightly to the right, it should be in the
     middle. The cause was not the zoom: the sidebar carries a
     backdrop blur, and a blurred element becomes the measuring
     point for a fixed pop-up inside it, so the old pop-up was
     measured from the sidebar's edge and sat about 21px right of
     centre with a small overhang — exactly what your photo
     showed. The menu is now positioned inside the sidebar and
     centred over the user card, with your name still visible
     below it. (On a phone it is still the full-width sheet at
     the top.)

 (3) SHORT SAN LABEL. The Flow pill for a client waiting after
     the SAN upload wrapped to four lines. It now reads
     "SAN report uploaded - waiting for Revenue Assurance" — in
     the list, in the status filter and in the flow list on the
     client page.

 (4) CONTACT BOX THE SAME SIZE AS THE ACCOUNT MANAGER'S BOX.
     On the New client form the contact box looked narrower than
     the account manager's box. The cause: the contact box's
     Remove button sat inside the box, and a box that holds a
     floating button is squeezed narrower by the button's width.
     The Remove button now sits on its own row above the fields,
     on the contact rows and on the service rows, so both boxes
     are exactly the same width.

 (5) ONE SAN REPORT PER SOF. Each SOF gets its own SAN report,
     uploaded by Transmission, Core or Technical support once
     Revenue Assurance has forwarded the client. The client
     counts as SAN-uploaded only when EVERY SOF has its report.
     Revenue Assurance can set a SOF's activation date as soon
     as that SOF's report is up (the date is set after all the
     reports are in, as before, because the client only reaches
     "SAN uploaded" when every SOF has one). Forward to Finance
     still needs a date on every SOF. Clients that already have
     the one client-level SAN keep it: on upgrade it is copied
     onto each of their SOFs. Once a SOF's SAN is uploaded it
     cannot be replaced; only the portal admin can remove one
     while the client is not completed. One change from the old
     client-level remove: removing a SAN now sends the client
     back to "forwarded", where it came from — the old code sent
     it back to "approved", which was wrong. The old
     client-level SAN upload, remove and download addresses are
     gone; the client page now has one "SAN reports" card with
     one block per SOF.

 (6) APPROVAL NOTICE FIXED. You asked why the first notification
     went to everyone, when it should only go to Revenue
     Assurance. The cause: when the Sales admin approved a
     client, the message telling Revenue Assurance to forward
     it was sent to Revenue Assurance AND to the watchers (the
     account manager and the Sales admin), so the sales user
     got both the plain "client was approved" notice and the
     Revenue Assurance instruction. The instruction now goes to
     Revenue Assurance users only; the account manager and the
     Sales admin still get the plain approval notice, once each.

 (7) SOF TABLE COLUMNS AND VIEW PAGE. The Services table now
     has a Termination date column and a Commercial impact date
     column after the Activation date, and the small termination
     line under the service is gone (the reason moved with it).
     There is a View button on the right of each SOF row, before
     Edit. It opens a page for that one SOF with every detail:
     number, service, type, description, activation date,
     termination date, commercial impact date, termination
     reason, status, the uploaded SOF file, share code, its SAN
     report, and the history of that SOF. This adds one new
     template file, templates/sof_view.html.

 OPEN — (8) THE SOF-EDIT WORKFLOW. You described the correct
     flow after a sales user edits a SOF: the change goes to the
     Sales admin for approval with a proper notification, then
     to Revenue Assurance as view only, then RA forwards it to
     Transmission, Core and Technical support, they re-upload
     the SAN for that specific edited SOF, RA and Sales are
     notified of the upload, then RA can edit the termination
     date and commercial impact date if they want, then forward
     it to Finance — the same process if the sales user edits
     anything else on the SOF. This is NOT built in this zip:
     the edited-SOF flow is still the build 102 one (the SOF
     goes pending after the Sales admin approves, and Revenue
     Assurance sets its activation date — there is no RA
     forward step, no SAN re-upload step, no RA date-edit
     stage and no forward-to-Finance step for an edited SOF).
     The three questions from the confirmation are still
     open: who can edit a SOF (account manager only, or the
     client owner too); can RA reject the change at the
     forward stage, or only forward it; and can RA change the
     activation date at the date-edit stage (a newly added SOF
     has none yet).

 OPEN — (9) DEPARTMENT DATABASE COLUMN PICKER. You asked for
     an option where the Sales admin can edit which columns
     are visible on the Department Database tabs' All-rows
     summary. This is NOT built in this zip. The portal already
     has a per-column "Shown in forms, lists and CSV" tick on
     the column edit page, but that hides the column
     everywhere, one column at a time — it is not a picker for
     the All-rows summary. The questions from the confirmation
     are still open: All-rows only, or My rows too; per tab,
     each tab its own set; and who — the department admin for
     their own department's tabs, portal admin for any.

 OPEN — NARROW CENTRED FORMS. The form pages with a centred
     inner box (for example the small 460px forms) will NOT
     visibly widen under the new 1560px page size, because the
     box itself is still 460px wide. They are left as they
     are in this zip. Say if you want those centred forms
     widened too.

 Tested: 177 client-flow checks and the full 646/646 regression
 suite against real MySQL 8.0, on the work copy and on a fresh
 extract of the zip. CSS audit: 0 parse errors, 150 defined
 classes; the new template uses only existing classes. Renders
 read back: the client list (short SAN label), the client
 detail (Termination and Commercial impact columns, View
 buttons, the SAN reports card), the SOF page, the form page
 (contact box the same width as the account manager's box),
 the dashboard and the user menu centred over the user card.

==============================================================================
 125. CLIENT LIST FILTER: A CALENDAR WITH DATE SELECTION, AND
     ACTIVATION / TERMINATION (2026-11-23)
==============================================================================
 Two small changes to the Client onboarding filter, from your
 message of 2026-11-23:

 (1) A CALENDAR FOR FROM AND TO. The From and To boxes were
     month-only boxes — you could only pick a month. They are
     now date boxes: click one and the browser opens a calendar,
     and you pick an exact day. The filter then matches clients
     whose activation date (or termination date) falls between
     the two days you picked, instead of matching a whole month.
     An impossible date is ignored and the list is left
     unfiltered. If From is later than To, the two are swapped
     instead of giving an empty list. Picking only a From date
     works (from that day onward), and only a To date works (up
     to that day).

 (2) ACTIVATION AND TERMINATION, NOT "ACTIVATION MONTH". The
     dropdown beside the From and To boxes read "Activation in
     month" and "Termination in month". The two choices now read
     just "Activation" and "Termination". Picking Activation
     filters by the SOF activation date, picking Termination
     filters by the SOF termination date.

 Old links still work: a single ?month=2026-12 counts as the
 whole of December (the 1st to the 31st), and a From/To pair
 written as months counts the same way. The chosen dates stay
 in the boxes and in the sub-tab links after you click Apply.

 Tested: 186 client-flow checks and the full 647/647 regression
 suite against real MySQL 8.0, on the work copy and on a fresh
 extract of the zip. The list was rendered to JPG and read back
 (b106-client-list.jpg) — the From and To boxes are date boxes
 and the dropdown reads "Activation".

==============================================================================
 126. BULK DELETE WITH A PASSWORD ON EVERY RECORD PAGE, AND THE
     DASHBOARD CHART LISTS EVERY TAB (2026-11-23)
==============================================================================
 From your messages of 2026-11-23: every record page should
 have Select, Select all and Delete for the portal admin and
 the administrative permission user, every delete should ask
 for a password, any tab added later should get the same
 buttons, and the dashboard Department database chart should
 show every tab, not only invoices.

 (1) SELECT, SELECT ALL AND DELETE ON EVERY RECORD PAGE.
     The buttons are on:
       - My records — every tab (Mine, Shared by me, Shared
         with me, My department, Other departments). The
         Delete button that was already in the bulk bar for
         your own records now asks for your password (see
         point 2). The portal admin's view of another user's
         records now has Select, Select all and Delete too —
         before this build that view had only a Delete button
         on each row, no way to tick several at once.
       - Users' records (the All records page) — the bulk
         bar's Delete, with a password box beside it.
       - Every Department Database tab — the regular tabs,
         the Invoices tab and the Request items tab. Each
         tab's rows get tick boxes, Select and Select all
         buttons, and a password box with a Delete button.
     The buttons are part of the shared tab pages, so any
     tab added on the Department database page later gets
     them on its own — nothing has to be added tab by tab.
     A department admin or a regular user sees no Delete
     button and no password box, and the delete route
     refuses them (403).

 (2) EVERY DELETE ASKS FOR THE PASSWORD. The password box
     sits beside the Delete button. The password you type
     is checked on every single delete — a fresh session
     never stands in for it, so deleting twice in a row
     asks twice. A wrong password, or an empty one, deletes
     nothing and says so. This is the same password check
     the single invoice and request deletes already use.

 (3) WHAT DELETE DOES. Exactly what deleting one of the
     item does today: the item is moved to the Recycle Bin
     for 30 days, where it can be restored — nothing is
     erased for good. Department Database rows: one summary
     notification per tab, saying how many rows were
     deleted. Invoices and item requests: nobody is told,
     the same as when a portal admin deletes one on its
     own. Personal records: each owner whose record was
     deleted is told once, with the count.

 (4) THE DASHBOARD CHART LISTS EVERY TAB. The Department
     database chart counted the regular tabs and the
     Invoices tab, but never the Request items tab or the
     Client onboarding tab — on the live portal that left
     the requests and the clients out of the chart entirely.
     It now lists every tab that has rows: the regular
     tabs, Invoices, Request items and Client onboarding,
     and the total is the sum of the listed tabs. A tab
     added later appears as soon as it has rows.

 OPEN — DELETE ON THE CLIENT ONBOARDING TAB. The Client
     onboarding tab has no Delete button in this zip. It
     is the one tab where deleting has no rule yet: there
     has never been a way to delete a client at all, so
     nothing says what should happen to its SOFs, its
     uploaded SAN reports, its history and its share
     codes when it goes. Say what a deleted client should
     do and it will be built.

 OPEN — ONE-BY-ONE DELETES AND THE PASSWORD. The new bulk
     Delete asks for the password every time. Deleting a
     single Department Database row or a single personal
     record still does not ask for one (deleting a single
     invoice or request already does). Say if those should
     ask too.

 OPEN, carried forward from build 105: (g) the SOF-edit
     workflow rework (Revenue Assurance forward step, SAN
     re-upload for the edited SOF, Revenue Assurance
     date-edit stage, forward to Finance); (h) the
     Department Database All-rows column picker; the
     narrow centred forms (the small centred boxes will
     not visibly widen under the 1560px page size);
     whether the 07:00 signature reminder arrives at
     07:00 Dhaka; whether accounts_user is gone and the
     Accounts department deleted.

 Tested: 202 client-flow checks and the full 661/661
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the
 Department Database tab (Select, Select all, password box
 and Delete beside the tab pills) and the dashboard
 (Sales & Marketing 18 rows — Vendor List 2, Invoices 2,
 Request items 1, Client onboarding 13).

==============================================================================
 127. THE PASSWORD POPS UP ONLY AFTER CLICKING DELETE, AND THE
     CLIENT ONBOARDING TAB GETS SELECT, SELECT ALL AND DELETE
     (2026-11-23)
==============================================================================
 Two corrections to build 107, from your photos of it live:

 (1) THE PASSWORD BOX NO LONGER SITS IN THE TOOLBAR. On every
     record page the toolbar now shows only Select, Select all
     and Delete — the password box is gone from between Select
     all and Delete. Clicking Delete opens a pop-up, the same
     pop-up the single invoice and request deletes already use:
     it says how many items will be deleted, asks for your
     password, and has Cancel and Delete buttons. Typing the
     password and clicking Delete deletes them. Nothing about
     the check changed: the password is still typed fresh on
     every delete, a wrong password still deletes nothing, and
     the items still go to the Recycle Bin for 30 days. The
     pages are: My records, the My department tab, Users'
     records, and every Department Database tab.

     While copying that pop-up, one old wrong line was fixed:
     the single invoice and single request pop-ups said "This
     will permanently delete... This cannot be undone." That
     has not been true since build 60 — deleting one moves it
     to the Recycle Bin for 30 days, where it can be restored.
     Both pop-ups now say so. The number is still never
     reused.

 (2) THE CLIENT ONBOARDING TAB HAS SELECT, SELECT ALL AND
     DELETE. It was the one tab left without them, because
     deleting a client had no agreed rule. The rule built here
     follows the rule every other document already has:
       - Deleting a client moves it to the Recycle Bin for
         30 days, where it can be restored — with its SOFs,
         contacts, history and share codes exactly as they
         were. Erasing it for good removes the client and
         everything under it: its SOFs, contacts, history,
         custom values, SOF edits, and its uploaded SOF and
         SAN files. After 30 days it is erased the same way
         on its own.
       - A deleted client disappears from the Client
         onboarding list, from its detail page, from its
         SOF code pages, and from the dashboard's Client
         onboarding count, until it is restored.
       - Only the portal admin and the administrative
         permission user see the buttons; a department admin
         or a regular user sees none, and the delete route
         refuses them. The owner or a portal admin can
         restore it from the Bin; erasing it for good follows
         the same rule as for invoices — a permission user
         cannot erase one he deleted himself, one the portal
         admin deleted, or one another permission user
         deleted.
     Say if a deleted client should do something different.

 OPEN, carried forward: (g) the SOF-edit workflow rework
     (Revenue Assurance forward step, SAN re-upload for the
     edited SOF, Revenue Assurance date-edit stage, forward
     to Finance); (h) the Department Database All-rows
     column picker; the narrow centred forms (the small
     centred boxes will not visibly widen under the 1560px
     page size); whether one-by-one row and personal-record
     deletes should ask for a password; whether the 07:00
     signature reminder arrives at 07:00 Dhaka; whether
     accounts_user is gone and the Accounts department
     deleted.

 Tested: 217 client-flow checks and the full 672/672
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the
 Client onboarding tab (Select, Select all and Delete, no
 password box in the toolbar) and the Department Database
 tab at 1440px (Permission, Select, Select all and Delete,
 no password box). The pop-up itself only opens after a
 click, so it cannot appear in a still render.

==============================================================================
 128. CLIENT ONBOARDING IS THE SALES DEFAULT TAB, EVERY TAB HAS A
     PERMISSION BUTTON, AND THE RECYCLE BIN GETS BULK DELETE FOREVER
     (2026-11-23)
==============================================================================
 This build is the one you confirmed in four answers on 2026-11-23.

 (1) CLIENT ONBOARDING IS THE DEFAULT TAB FOR SALES & MARKETING,
     AND THE FIRST TAB FROM THE LEFT FOR THE SIX FLOW DEPARTMENTS.
     Opening the Department database as a Sales & Marketing user
     now opens the Client onboarding tab, not the first regular
     tab. For Revenue Assurance, Finance, Transmission, Core and
     Technical support the tab sits first from the left, before
     Invoices and Request items. No other department sees it at
     all — opening the tab directly gives a 404 — unless the
     Sales admin shares it with them (see (3)).

 (2) EVERY TAB HAS A PERMISSION BUTTON FOR THE DEPARTMENT ADMIN.
     The Client onboarding, Invoices and Request items tabs each
     have a Permission button at the left of their toolbar, for
     the admin of the department that owns the tab (and the
     portal admin). Regular DeptDB tabs keep the Permission
     button they already had. Clicking it opens a page where the
     admin picks which other departments, or which individual
     users, may see that tab.

 (3) SHARING A SPECIAL TAB IS VIEW ONLY, AND THE GRANTED USER
     SEES EVERYTHING IN IT. The share is always view only —
     there is no Edit choice on the page. A granted department
     or user sees every client, invoice or request in the tab,
     and can open one to read it. They cannot change anything:
     no + New client, no Permission button, no Select or Delete
     on the shared tab, and every action route still refuses
     them (approve, status change, delete and the rest all give
     403). The shared tab is named the way you wrote it:
     Client onboarding(Sales & Marketing), Invoices(Sales &
     Marketing), Request items(Sales & Marketing) — and the
     same for any other owning department. The page carries the
     line "Shared by Sales & Marketing — view only. You see
     every client here, and can open one to read it. You cannot
     change anything." Removing a share takes the tab away
     again at once, and the granted department or user is told.
     The new shares live in a new table, special_tab_shares
     (55 tables in the database now); the old whole-tab sharing
     for regular DeptDB tabs is unchanged.

 (4) SELECT, SELECT ALL AND DELETE FOREVER ON TOP OF EVERY
     RECYCLE BIN TAB, FOR THE PORTAL ADMIN. Records, Users,
     Others and Deleted users' data all have the three buttons
     on top. Tick the items, click Delete forever, type your
     password in the pop-up, then confirm — password first,
     then the confirm, the same order as on the record pages.
     A wrong password deletes nothing. Each ticked item is
     erased exactly as its own Delete forever button erases
     it: records, rows, invoices, requests, clients and tabs
     go with everything under them, and the portal admin's
     erase rule is kept per item — a permission user cannot
     erase a deletion made by himself, by the portal admin,
     or by another permission user; those are skipped and
     counted, and the message says so. On the Users tab the
     confirm asks one question for all the ticked users at
     once: delete their work too? Yes erases everyone's work
     at once, No takes everyone out of the Bin and keeps
     everyone's work until the 30 days end (the same as the
     single-user No). The Deleted users' data tab stays
     true-portal-admin only, as before, and its old "Delete
     all" is now the same Delete forever button. The old
     single-item Delete forever buttons are untouched.

 (5) THE SIDEBAR SAYS "PORTAL". The small line under the
     company name in the sidebar now reads "Portal", not
     "Records portal".

 (6) NO SERVICE TYPE ON THE NEW CLIENT FORM. The Service
     type box is gone from page 3 of the New client form and
     from the SOF edit page — Service and Service type were
     the same thing. The short service name shown in brackets
     after each activation and termination date on the list is
     now the Service itself. A SOF created before this build
     keeps the service type it already had; on upgrade, a
     Service type field left in the form setup is removed and
     the Service description field is kept. Creating a client
     still requires the Service description.

 OPEN, carried forward: (g) the SOF-edit workflow rework
     (Revenue Assurance forward step, SAN re-upload for the
     edited SOF, Revenue Assurance date-edit stage, forward
     to Finance); (h) the Department Database All-rows
     column picker; the narrow centred forms (the small
     centred boxes will not visibly widen under the 1560px
     page size); whether one-by-one row and personal-record
     deletes should ask for a password; whether the 07:00
     signature reminder arrives at 07:00 Dhaka; whether
     accounts_user is gone and the Accounts department
     deleted.

 Tested: 254 client-flow checks and the full 687/687
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the Client
 onboarding tab as the portal admin (Permission first in
 the toolbar, Select, Select all and Delete), the shared
 Client onboarding tab as an HR user (the view-only line,
 every client listed, no New client, no Permission, no
 Delete), the Recycle Bin (Select, Select all and Delete
 forever on top), and page 3 of the New client form (SOF
 number, Service, Activation date, Service description,
 SOF file — no Service type box). The password pop-up only
 opens after a click, so it cannot appear in a still render.

 129. THE EDITED-SOF FLOW, THE DATE LOCK, AND SERIAL NUMBERS THAT
     CLOSE RANKS (2026-11-23)
==============================================================================
 This build is the one you confirmed in eight answers on 2026-11-23.

 (1) THE EDITED-SOF FLOW, IN STAGES. After the flow has finished, an
     account manager changing an activated SOF, or setting its
     termination date and commercial impact date, works like this:
       a. As soon as the account manager saves, that SOF goes to
          pending — the client itself stays finished — and the
          Sales admin is told the SOF number and what changed.
       b. The Sales admin approves or rejects it. A rejection puts
          the SOF back to activated with its old values, and the
          account manager is told why. An approval applies the
          change to the SOF (it stays pending) and tells Revenue
          Assurance the approval and what changed. A termination
          takes effect only at the very end, never at approval.
       c. Revenue Assurance forwards the change to Transmission,
          Core and Technical support. Revenue Assurance cannot
          reject it — there is no reject step here, only forward.
       d. One of those three departments uploads ANOTHER SAN report
          for the edited SOF. The old report stays: the SOF keeps
          every report it ever had, listed under SAN reports with
          who uploaded each one and when, and every one of them
          still downloads. After the upload, Revenue Assurance,
          Sales and the account manager are told.
       e. Revenue Assurance can change the dates — activation,
          termination and commercial impact, all three — if
          required, and then forwards the finished change to
          Finance.
       f. Forwarding to Finance makes the change take effect: the
          SOF becomes activated, or terminated if it has a
          termination date. Finance, the account manager who
          made the change and the Sales admin are told.
     One change at a time per SOF: while a change is in flight, the
     SOF takes no second change — the Add services form leaves it
     alone and says so, and the single-SOF edit page only opens for
     an activated SOF. A restart while a change is in flight no
     longer flips the SOF to activated: the old upgrade backfill
     now leaves every SOF with an open change alone.

 (2) THE DATES LOCK AFTER FINANCE. Once Revenue Assurance has
     forwarded the record to Finance, the activation date, the
     termination date and the commercial impact date cannot be
     changed by Revenue Assurance any more — the date box is gone
     from the SOF row for everyone except the portal admin and an
     administrative permission user. The row stays where it is; it
     locks, it does not disappear. The portal admin (or
     administrative permission user) changes the dates from a small
     form on the SOF row itself, and Revenue Assurance, Finance
     and Sales are told what changed and what the SOF now is.

 (3) ADDING A SOF WORKS NOW. When the account manager adds another
     SOF to a finished client, he CAN set its activation date and
     upload the SOF file — both travel with the change and land on
     the SOF when the Sales admin approves it. The date he sets
     stays; Revenue Assurance does not set it fresh, it only
     changes it at the dates stage of the flow. A SOF he adds
     without a date waits for one: Revenue Assurance sets it at
     the dates stage, or the portal admin sets it from the dates
     form on the client page.

 (4) SERIAL NUMBERS CLOSE RANKS. Wherever a number starts from 1
     — clients, invoices and item requests — deleting one leaves
     no gap:
       - If records 2 to 4 are deleted and there is a 5th, the 5th
         becomes 2, the 6th becomes 3, and so on.
       - If there is no later record, the next one added takes the
         freed number.
     Invoices close ranks inside their own template, requests
     inside their own kind, clients across the whole list. The
     numbers are renumbered at the delete itself (a single delete
     or a bulk delete), and the template or kind counter is reset
     to one past the last live number. Restoring a deleted
     invoice, request or client from the Recycle Bin gives it a
     NEW number at the end of the sequence — its old number was
     already taken by the renumbering.
     PLEASE NOTE: an issued invoice's number can now change when
     an earlier invoice in the same template is deleted. The
     invoice number is still the official number for payment
     and accounts; only its position in the sequence moves.

 (5) THE SAN HISTORY. A new table, client_sof_san_uploads, holds
     every SAN report a SOF ever had (56 tables in total). The
     SOF's own san_file always points at the latest upload, so the
     SOF page and the SOF PDF are unchanged. On upgrade, each
     SOF's current report becomes the first row of its history.
     Removing a report (portal admin, while the record is not
     finished) takes the latest one off and brings the previous
     one back as the current report; if the removed report was
     the edited SOF's, its change waits for a new upload again.

 OPEN, carried forward: (h) the Department Database All-rows
     column picker; the narrow centred forms (the small centred
     boxes will not visibly widen under the 1560px page size);
     whether one-by-one row and personal-record deletes should
     ask for a password; whether the 07:00 signature reminder
     arrives at 07:00 Dhaka; whether accounts_user is gone and
     the Accounts department deleted.

 Tested: 283 client-flow checks and the full 696/696
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the staged
 SOF-edit flow on a client page (the dates form and Forward
 to Finance for one change, the Forward button for another,
 and the portal admin's three-date form on the SOF row), the
 Client onboarding list (serials 1 to 7 in order, Select,
 Select all and Delete in the toolbar), and the shared
 clients view and the Recycle Bin as before.

 130. SIX SMALL FIXES FROM YOUR 2026-11-24 PHOTOS (2026-11-24)
==============================================================================
 This build is the six fixes you reported on 2026-11-24, after
 build 110 went live.

 (1) THE ADMIN'S DATES, ONE PER COLUMN. The portal admin's three
     date boxes on a SOF row were all stacked inside the
     Activation date column, with Termination date and
     Commercial impact date showing only a dash. Now there is
     one box under each heading — activation under Activation
     date, termination under Termination date, commercial
     impact under Commercial impact date — and one Save dates
     button for the row. The same three dates, the same
     permission (portal admin and administrative permission
     user), the same notifications to Revenue Assurance,
     Finance and Sales. The boxes are one form split across
     the three columns, so saving still sends all three dates
     together.

 (2) THE FLOW SHOWS WHERE A SOF CHANGE IS. The Client onboarding
     list showed a client's Flow as Completed even while one
     of its SOFs was pending with a change in flight. Now,
     while a SOF change is in flight, the Flow column shows
     that change's stage — "Waiting for the Sales admin",
     "Approved — waiting for Revenue Assurance to forward it",
     "Forwarded — waiting for a new SAN report", or "SAN report
     uploaded — Revenue Assurance may change the dates" — with
     the SOF number in front, and the pill turns amber. If two
     SOFs have changes in flight, the column shows each SOF
     with its own stage. When the change finishes, the Flow
     goes back to the client's own status.

 (3) NO SHARE CODE ON THE SOF VIEW PAGE. The SOF's own View page
     no longer shows a Share code row. The SOF's public code
     page itself is unchanged — the code still exists and
     still opens from Search QR.

 (4) EVERY SAN REPORT ON THE SOF VIEW PAGE. The SOF's own View
     page showed only the latest SAN report. Now it lists
     every report the SOF ever had, oldest first, each with
     its own Download, who uploaded it and when, and "for the
     edited SOF" where it was uploaded for an edited SOF —
     the same list as the client page shows. Uploading and
     removing a report work as before.

 (5) THE ACCOUNT MANAGER CAN EDIT A TERMINATED SOF. After the
     termination date was confirmed, a terminated SOF had no
     Edit button for the account manager. Now the Edit button
     shows for an activated or a terminated SOF, and the edit
     page opens for both. Saving sends the SOF to Pending and
     the change runs the whole staged flow again, exactly as
     an edit of an activated SOF does — including through the
     Add services form, which now also sends a changed
     terminated SOF to pending. The portal admin already had
     Edit on every SOF; nobody else gains it.

 (6) THE NOTIFICATIONS PAGE, TIDIER. Three pieces are gone from
     the Notifications page: the "Warn me — 3 days ahead" card
     at the top, the "Warn me before a reminder date" dropdown
     with its Save button, and the "Who gets told what" card
     on the right. The Notifications and Unread cards, the
     Select / Mark all as read / Clear all buttons, the
     message list, and the My records / Reminders links stay
     exactly as they were. The reminders themselves do not
     change: records you own still warn 1 day before and on
     the day itself from 07:00, and the extra days-ahead
     reminder keeps going at whatever each user already saved
     — the setting stays in the database, the page just no
     longer shows it or lets anyone change it.

 OPEN, carried forward: (h) the Department Database All-rows
     column picker; the narrow centred forms (the small centred
     boxes will not visibly widen under the 1560px page size);
     whether one-by-one row and personal-record deletes should
     ask for a password; whether the 07:00 signature reminder
     arrives at 07:00 Dhaka; whether accounts_user is gone and
     the Accounts department deleted.

 Tested: 293 client-flow checks and the full 704/704
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the client
 page with one date box under each heading and the staged
 flow, the Client onboarding list showing a change in flight
 in the Flow column, the SOF View page with every SAN report
 and no share code, and the Notifications page without its
 warn-me and who-gets-told cards.

 131. THE ADD-SERVICE OVERWRITE FIX, SOF FILES KEPT, AND RA'S DATE
     BOXES ONLY WHEN THE ACCOUNT MANAGER SET THEM (2026-11-24)
==============================================================================
 This build fixes the bug you reported on 2026-11-24: when the
 account manager added a new service to an existing customer, the
 new service was typed over the existing SOF instead of being
 added as a new one.

 (1) ADD SERVICES IS BLANK FOR THE ACCOUNT MANAGER. The Add
     services form no longer shows the existing SOFs at all —
     the services page is blank, with one empty block where the
     account manager fills the new service and uploads its SOF.
     The client page stays locked (view only) and the contacts
     stay editable. An existing SOF can no longer be overwritten
     from this form, even by a crafted request: the server
     ignores any row carrying an existing SOF. To change a SOF,
     the account manager uses that SOF's own Edit button. The
     portal admin's own form is unchanged — the existing SOFs
     still show there, and the admin's changes still apply at
     once.

 (2) THE SOF FILE IS REQUIRED — ON A NEW SERVICE AND ON EVERY
     EDIT. A new service cannot be saved without its SOF file,
     and neither can an edited service — not even when the edit
     only changes a date. The Edit page has a file upload now,
     marked required for the account manager. The portal admin
     may still leave it off; if the admin does replace a file,
     it joins the same history below.

 (3) EVERY SOF FILE IS KEPT — ONE DOWNLOAD PER FILE. A SOF
     used to keep only its latest file; approving an edit
     deleted the old one. Now every file a SOF ever had is
     kept: the Download SOF column on the client page lists
     them all, oldest first, each with its own Download, and
     the SOF View page shows the same list. A file uploaded
     for an edited SOF is marked "for the edited SOF". A
     rejected change still removes the file it uploaded, as
     before. On upgrade, each SOF's current file becomes the
     first row of its history (57 tables in total).

 (4) RA'S TERMINATION AND COMMERCIAL IMPACT BOXES ONLY WHEN
     THE ACCOUNT MANAGER SET THEM. While Revenue Assurance
     forwards a SOF change to Finance, the termination date
     and commercial impact date boxes now appear together only
     when the account manager's change carries one of those
     dates. A new service never carries them, so RA sees only
     the activation date box there. A date posted for a change
     that carries neither is ignored. The activation box is
     unchanged.

 The new service still runs the same staged flow — Sales
 admin approval, Revenue Assurance forward, a new SAN report,
 Revenue Assurance dates, forward to Finance — and the Sales
 admin's notification still carries the new service's name,
 its description and the client name.

 One thing this build cannot undo: the live 90 Mbps SOF-0001
 on /clients/12 was already overwritten by the 100 Mbps
 SOF-0002 before this fix. The fix stops it happening again,
 but the old SOF does not come back by itself — its old
 values are in the SOF changes history, so after applying
 this build the 90 Mbps service can be added again as a new
 SOF if you want it back.

 OPEN, carried forward: (h) the Department Database All-rows
     column picker; the narrow centred forms (the small centred
     boxes will not visibly widen under the 1560px page size);
     whether one-by-one row and personal-record deletes should
     ask for a password; whether the 07:00 signature reminder
     arrives at 07:00 Dhaka; whether accounts_user is gone and
     the Accounts department deleted.

 Tested: 307 client-flow checks and the full 718/718
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the client
 page with two SOF downloads on one SOF and the staged flow,
 the account manager's blank Add services page, the SOF View
 page with both SOF files, and the Client onboarding list as
 before.

132. THE ACCOUNT MANAGER EDITS THE ACTIVATION DATE, THE APPROVAL
     WRITES IT, THE EDITED-SOF NOTE SITS ONLY ON EDIT FILES, AND
     THE TYPE COLUMN IS SERVICE DESCRIPTION (2026-11-24)
==============================================================================
 This build fixes the four things you reported on 2026-11-24
 from your photos of /clients/12:

 (1) THE ACCOUNT MANAGER EDITS THE ACTIVATION DATE FROM THE
     EDIT BUTTON. The activation date box on the Edit SOF page
     is no longer locked: the account manager sets it there
     when it changes, just like the other fields. The SOF file
     is still required on the edit, even for a date-only
     change. The page no longer says the date is set by
     Revenue Assurance instead — Revenue Assurance can still
     change it later in the flow, before forwarding the change
     to Finance.

 (2) THE APPROVAL WRITES THE EDITED ACTIVATION DATE TO THE
     SOF. Approving a SOF change used to write every edited
     field to the SOF except the activation date, so an edited
     activation date never reached the Services list. Now it
     lands at the Sales admin's approval, like the rest of the
     change. The same hole existed in two more places and is
     fixed there too: the portal admin's own Edit save, and the
     portal admin's Add services save for an existing SOF
     (a blank box there keeps the old date rather than wiping
     it). A date Revenue Assurance sets at the dates stage
     already reached the list — that part was checked and
     works — and still does.

 (3) "FOR THE EDITED SOF" ONLY ON A FILE AN EDIT UPLOADED.
     The Download SOF list used to mark every file "for the
     edited SOF" — including a new SOF's very first file — so
     both files on /clients/12 carried the note. Now the note
     sits only on a file uploaded by editing that SOF; a new
     SOF's first file carries no note. Files already live are
     fixed by this build with no data change needed. The SAN
     reports are untouched — their note stays as it was.

 (4) THE TYPE COLUMN IS NOW SERVICE DESCRIPTION. There is no
     field called Type, so the Services table no longer has a
     Type column: it has a Service description column instead,
     with the description under it, and the Service column
     shows only the service name. The SOF View page loses its
     Type row too; its Service description row stays. The
     short name in brackets after each date on the client
     list is unchanged — that is the service name, and it was
     never the Type column.

 An edit with no activation date is refused — a finished SOF
 always has one, so it cannot be cleared from the Edit page.

 OPEN, carried forward: (h) the Department Database All-rows
     column picker; the narrow centred forms (the small centred
     boxes will not visibly widen under the 1560px page size);
     whether one-by-one row and personal-record deletes should
     ask for a password; whether the 07:00 signature reminder
     arrives at 07:00 Dhaka; whether accounts_user is gone and
     the Accounts department deleted.

 Tested: 317 client-flow checks and the full 725
 regression suite against real MySQL 8.0, on the work copy
 and on a fresh extract of the zip. CSS audit: 0 parse
 errors, 150 defined classes. Renders read back: the client
 page with the Service description column and one note only
 on the edited file, the SOF View page with no Type row, the
 Edit SOF page with the activation date editable, and the
 Client onboarding list as before.


133. THE CLIENT DETAIL PAGE FITS AT 100% BROWSER ZOOM (no files added or removed)

The client detail page looked zoomed in: opening a client (for example
/clients/13 "tusar") cut the right-hand "Where it is in the flow" rail
off the screen, and zooming the browser out to 70% shrank the whole page
to a tiny 49% instead of fixing it. The list page looked fine at the
same zoom. The text size was the same on both pages — the detail page
was not zoomed, it was WIDER than the screen.

Root cause: the Services (SOF) table's min-content is wider than the
page's main column — eleven columns, nowrap download buttons with long
filenames ("Download report_activity_2026-11-24.xlsx"), three date
inputs and nowrap headers. The page layout is the .tw grid (1fr + 280px
rail), and a grid item's default min-width:auto refuses to shrink below
its content's min-content, so the table forced the whole main column
wider than the viewport and pushed the 280px rail off-screen. The list
page's table is narrower, so it never hit this. Reproduced locally with
a client carrying the same long SOF filenames: the render shows the rail
and the Download column cut off at the right edge, exactly like the
user's photo.

Fix (one CSS rule, static/style.css): .tw>*{min-width:0}. The grid
children may now shrink below their content size, and the table's
existing .tb{overflow-x:auto} scrolls the wide Services table inside
its own card instead of blowing out the page. Nothing else changes:
where the content already fits (the list page and every other .tw
page), min-width:0 has no effect, and the 280px rail track is
unchanged. No template, route or database change.

Verification note: WeasyPrint cannot show this fix — its grid
implementation ignores min-width:0 on grid items and expands wide
tables to full content width instead of scrolling them, so the
before/after renders are identical. The fix is the standard CSS grid
rule (the same min-width:0 principle as build 104's chart-label fix,
which works live). Please confirm live: open a client detail page at
100% browser zoom — the whole page including the right-hand rail
should be visible with no sideways scroll, and the Services table
scrolls inside its own card if it is wider than the column.

Tests: 320/320 client checks and the full 728/728 regression
suite, work copy AND fresh extract, real MySQL 8.0. CSS audit: 0 errors, 150 defined classes.


134. THE MIDDLE FILLS THE WIDTH — NO MORE EMPTY SPACE ON THE RIGHT
(no files added or removed)

Every page was capped at 1560px wide (build 105 — the client list's
width), so on a wide screen the middle floated with a wide empty band
on its right (and a matching one on its left, next to the sidebar).
The user asked to use the extra space on the right so the middle is
wider and the space on its right matches the space on its left.

The fix is one CSS rule: the max-width:1560px cap is removed from
main in static/style.css, so the middle now fills the whole mainwrap
— its left edge sits the usual small gap from the sidebar and its
right edge sits the same small gap from the screen edge. Nothing else
changes: the 280px rail, the page padding, the phone collapse and the
centred narrow forms are untouched, and the login page (main.bare)
already had no cap. The wider middle also gives wide tables more
room, so the client detail page's Services table is less likely to
need its sideways scroll (build 114's rule stays as the safety net).

This changes EVERY page, not just Invoice templates — it is the one
width rule for the whole portal. The look was shown to the user first
(probe115-before / probe115-after at a 1920px screen) and approved
before building.

Tests: 323/323 client checks and the full 731/731 regression
suite, work copy AND fresh extract, real MySQL 8.0. CSS audit: 0
errors, 150 defined classes. Renders read back: the Invoice
templates page at full width with its rail, the client list and the
client detail page as before, only wider.

OPEN: (h) DeptDB All-rows column picker, narrow centred forms,
one-by-one delete password question, 07:00 reminder + accounts_user
confirmations still unanswered.
