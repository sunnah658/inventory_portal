#!/bin/sh
# backup.sh - backup the database and attachments, optionally copy them to another machine.
#
#   ./backup.sh            run by hand, or from cron (see README.txt section 9)
#
# Steps: 1) the portal makes a safe database backup inside its volume
#        2) the backups and attachments are copied to ./backups-copy on this server
#        3) if REMOTE_TARGET is set in backup.conf, everything is copied to that machine
cd "$(dirname "$0")" || exit 1
[ -f backup.conf ] && . ./backup.conf

echo "$(date '+%F %T') backup started"
docker compose exec -T portal python backup.py || { echo "ERROR: the portal container is not running"; exit 1; }

mkdir -p backups-copy/db backups-copy/uploads
docker compose cp portal:/data/backups/. ./backups-copy/db/ || exit 1
docker compose cp portal:/data/uploads/. ./backups-copy/uploads/ || exit 1

# keep the newest 60 database copies on this server
ls -1t backups-copy/db/portal_*.db 2>/dev/null | tail -n +61 | xargs -r rm --

if [ -n "$REMOTE_TARGET" ]; then
    echo "copying to $REMOTE_TARGET"
    rsync -az -e "ssh -o BatchMode=yes ${SSH_OPTIONS}" backups-copy/ "$REMOTE_TARGET"/ \
        || { echo "ERROR: copy to the other machine failed (see README.txt, troubleshooting)"; exit 1; }
fi
echo "$(date '+%F %T') backup finished: $(pwd)/backups-copy"
