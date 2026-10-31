"""
Apply schema.sql and schema_formulation.sql to whatever MYSQL_* points at.

Meant for a fresh RDS instance, with no mysql client installed:

    cd backend && source venv/bin/activate
    python scripts/init_remote_db.py            # connects and applies
    python scripts/init_remote_db.py --dry-run  # parse only, no connection

Run it with a user that has DDL rights (the RDS master user), not the
application user, which deliberately has none. Put that user in MYSQL_USER /
MYSQL_PASSWORD for this one run.

schema.sql DROPs and recreates its tables, so this refuses to run against a
database that already has CellSpark tables unless you pass --force. Nothing is
suppressed: the first error stops the run, and any server warning is printed.
The schema files are applied exactly as they are.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(HERE, "..")
sys.path.insert(0, BACKEND)

from app import db as _db   # noqa: E402,F401  (loads backend/.env)

SCHEMA_FILES = ["schema.sql", "schema_formulation.sql"]


def split_statements(sql: str):
    """Split a script on ';', ignoring comments and quoted text."""
    out, buf, quote = [], [], None
    i = 0
    while i < len(sql):
        c = sql[i]
        if quote:
            buf.append(c)
            if c == "\\" and i + 1 < len(sql):
                buf.append(sql[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c in ("'", '"', "`"):
            quote = c
            buf.append(c)
        elif sql.startswith("--", i) and (i + 2 >= len(sql) or sql[i + 2] in " \t\r\n"):
            while i < len(sql) and sql[i] != "\n":
                i += 1
            continue
        elif c == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="parse the files, do not connect")
    ap.add_argument("--force", action="store_true",
                    help="apply even if CellSpark tables already exist (DROPs them)")
    args = ap.parse_args()

    scripts = []
    for name in SCHEMA_FILES:
        with open(os.path.join(BACKEND, name), encoding="utf-8") as fh:
            scripts.append((name, split_statements(fh.read())))

    if args.dry_run:
        for name, stmts in scripts:
            print(f"{name}: {len(stmts)} statements")
        return 0

    import pymysql

    missing = [k for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD") if not os.environ.get(k)]
    if missing:
        print(f"Set {', '.join(missing)} in backend/.env first.", file=sys.stderr)
        return 2

    db_name = os.environ.get("MYSQL_DB") or "cellspark"
    conn = pymysql.connect(
        host=os.environ["MYSQL_HOST"], port=int(os.environ.get("MYSQL_PORT") or 3306),
        user=os.environ["MYSQL_USER"], password=os.environ["MYSQL_PASSWORD"],
        connect_timeout=10, autocommit=True,
    )
    cur = conn.cursor()
    cur.execute("SELECT VERSION()")
    print(f"Connected to {os.environ['MYSQL_HOST']} — server {cur.fetchone()[0]}")
    if db_name != "cellspark":
        print(f"WARNING: MYSQL_DB is {db_name!r} but the schema files create and USE "
              f"'cellspark'. The application will not find its tables.")

    cur.execute("SHOW DATABASES LIKE 'cellspark'")
    if cur.fetchone() and not args.force:
        cur.execute("SELECT COUNT(*) FROM information_schema.tables "
                    "WHERE table_schema = 'cellspark'")
        n = cur.fetchone()[0]
        if n:
            print(f"Database 'cellspark' already has {n} tables. schema.sql DROPs them, "
                  f"so nothing was changed. Re-run with --force to rebuild.", file=sys.stderr)
            return 3

    for name, stmts in scripts:
        print(f"Applying {name} ({len(stmts)} statements)")
        for stmt in stmts:
            cur.execute(stmt)
            cur.execute("SHOW WARNINGS")
            for level, code, msg in cur.fetchall():
                first = stmt.split("\n", 1)[0][:60]
                print(f"  {level} {code}: {msg}   [{first}]")

    cur.execute("USE cellspark")
    cur.execute("SHOW TABLES")
    tables = [r[0] for r in cur.fetchall()]
    print(f"\n{len(tables)} tables in cellspark:")
    for t in tables:
        print(f"  {t}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
