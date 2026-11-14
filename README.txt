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
