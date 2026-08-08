#!/bin/sh
# pgAdmin seed: register ContextForge server connections and store the dev
# password, so pgAdmin opens a working connection with zero manual setup.
#
# Password storage note: pgAdmin 9's servers.json loader ignores Password /
# SavePassword keys, and in server mode without a master password the crypt
# key is the user's LOGIN password (keyManager.set at login). So we write
# password = pgAdmin_crypto.encrypt(POSTGRES_PASSWORD, PGADMIN_DEFAULT_PASSWORD)
# directly into the config DB. If you change the pgAdmin login password,
# re-run this seed (docker compose up -d pgadmin_seed --force-recreate) or
# stored passwords will no longer decrypt.
set -eu

DB=/var/lib/pgadmin/pgadmin4.db

# pgAdmin creates its config DB on first boot; wait for it.
i=0
while [ ! -f "$DB" ]; do
  i=$((i + 1))
  if [ "$i" -gt 60 ]; then
    echo "❌ pgAdmin config DB never appeared at $DB"
    exit 1
  fi
  echo "⏳ Waiting for pgAdmin config DB..."
  sleep 2
done

# Idempotency: drop our managed entries before re-importing (load-servers
# does not deduplicate by name).
/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('$DB')
conn.execute(\"delete from server where name like 'ContextForge%'\")
conn.commit()
print('cleared previous ContextForge server entries')
"

/venv/bin/python3 /pgadmin4/setup.py load-servers /pgadmin4/servers.json --user "${PGADMIN_DEFAULT_EMAIL:-admin@example.com}"

/venv/bin/python3 - <<'PYEOF'
import os
import sqlite3
import sys

os.chdir("/pgadmin4")
sys.path.insert(0, "/pgadmin4")

import config  # must be imported before pgadmin.* (breaks a circular import)

from pgadmin.utils.crypto import decrypt, encrypt
sys.path.insert(0, "/pgadmin4")

from pgadmin.utils.crypto import decrypt, encrypt

db_path = "/var/lib/pgadmin/pgadmin4.db"
login_password = os.environ.get("PGADMIN_DEFAULT_PASSWORD", "changeme")
pg_password = os.environ.get("POSTGRES_PASSWORD", "mysecretpassword")

conn = sqlite3.connect(db_path)
rows = conn.execute("select id, name from server where name like 'ContextForge%'").fetchall()
for sid, name in rows:
    conn.execute("update server set password=?, save_password=1 where id=?", (encrypt(pg_password, login_password).decode(), sid))
conn.commit()

failures = 0
for sid, name in rows:
    stored = conn.execute("select password from server where id=?", (sid,)).fetchone()[0]
    ok = decrypt(stored.encode(), login_password).decode() == pg_password
    print(f"  {name}: password stored, crypto round-trip {'OK' if ok else 'FAILED'}")
    failures += 0 if ok else 1
conn.close()
sys.exit(1 if failures else 0)
PYEOF

echo "✅ pgAdmin seeding complete"
