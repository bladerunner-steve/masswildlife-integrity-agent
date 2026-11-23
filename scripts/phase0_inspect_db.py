"""Phase 0 read-only MySQL inspection for masswildlife.inaturalist.

What it does: connects as the agent account (from .env), sets the session READ ONLY,
and prints SHOW GRANTS, SHOW CREATE TABLE, SHOW INDEX, row count, MAX(id)/MAX(created_at)
and 5 sample rows (long text truncated). It refuses to continue if the grants exceed
SELECT/INSERT/UPDATE on masswildlife.*. MYSQL_PASSWORD is never printed.

AI-assisted (Claude); reviewed by the project author.
Verified by: running it manually at Checkpoint 0; output reviewed in chat. No automated test
(one-off discovery script, not part of the agent).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {"SELECT", "INSERT", "UPDATE"}


def main() -> int:
    load_dotenv(ROOT / ".env")
    missing = [k for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE") if not os.getenv(k)]
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
        return 2
    db = os.environ["MYSQL_DATABASE"]
    conn = pymysql.connect(
        host=os.environ["MYSQL_HOST"], port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        database=db, charset="utf8mb4", cursorclass=pymysql.cursors.Cursor,
    )
    print(f"Connected as {os.environ['MYSQL_USER']}@{os.environ['MYSQL_HOST']} (password not shown)")
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")

        print("\n== SHOW GRANTS FOR CURRENT_USER() ==")
        cur.execute("SHOW GRANTS FOR CURRENT_USER()")
        excess = []
        for (g,) in cur.fetchall():
            print(" ", g)
            m = re.match(r"GRANT (.+?) ON (\S+) TO", g)
            if not m:
                continue
            privs = {p.strip().upper() for p in m.group(1).split(",")}
            target = m.group(2).replace("`", "")
            if privs == {"USAGE"} and target == "*.*":
                continue  # the default "can log in" grant
            if target != f"{db}.*" or not privs <= ALLOWED:
                excess.append(g)
        if excess:
            print("\nSTOP: grants exceed SELECT/INSERT/UPDATE on masswildlife.*:")
            for g in excess:
                print("  ", g)
            return 3
        print("  -> OK: only SELECT/INSERT/UPDATE on", f"{db}.*")

        print("\n== SHOW CREATE TABLE inaturalist ==")
        cur.execute("SHOW CREATE TABLE inaturalist")
        print(cur.fetchone()[1])

        print("\n== SHOW INDEX FROM inaturalist ==")
        cur.execute("SHOW INDEX FROM inaturalist")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            r = dict(zip(cols, row))
            print(f"  key={r['Key_name']} non_unique={r['Non_unique']} seq={r['Seq_in_index']} col={r['Column_name']}")

        print("\n== Counts ==")
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT id), MAX(id), MAX(created_at), MIN(created_at) FROM inaturalist")
        n, nd, mx, mxc, mnc = cur.fetchone()
        print(f"  rows={n} distinct_ids={nd} max_id={mx} max_created_at={mxc!r} min_created_at={mnc!r}")

        print("\n== Duplicate ids (top 5) ==")
        cur.execute("SELECT id, COUNT(*) c FROM inaturalist GROUP BY id HAVING c > 1 ORDER BY c DESC LIMIT 5")
        dups = cur.fetchall()
        print("  none" if not dups else "\n".join(f"  id={i} count={c}" for i, c in dups))

        print("\n== 5 sample rows (newest by id; text truncated to 60 chars) ==")
        cur.execute("SELECT * FROM inaturalist ORDER BY id DESC LIMIT 5")
        cols = [d[0] for d in cur.description]
        for row in cur.fetchall():
            print("  ---")
            for c, v in zip(cols, row):
                s = repr(v)
                print(f"    {c} = {s[:60] + '...' if len(s) > 60 else s}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
