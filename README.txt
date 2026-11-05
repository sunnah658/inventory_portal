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
