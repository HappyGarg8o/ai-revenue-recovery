"""
setup_database.py — turn an empty Supabase project into a working demo.

Run this once after cloning. It checks your credentials, verifies the four
tables exist, loads the seed batch, and tells you exactly what to do next
if something is missing.

    python setup_database.py           # check, then seed if empty
    python setup_database.py --force   # wipe and re-seed from scratch
    python setup_database.py --check   # verify only, change nothing

The one thing this script cannot do for you is create the tables. Supabase's
REST API does not accept DDL, so schema.sql has to be pasted into the SQL
editor by hand — it is a single copy-paste, and the script prints the link
and waits for you to do it.
"""

import csv
import io
import os
import sys

# config loads .env into the environment. Import it first, or the credential
# check below reads a bare os.environ and reports "not set" for a project
# whose .env is sitting right there.
try:
    import config  # noqa: F401
except Exception:  # noqa: BLE001 - a missing dep is reported properly further down
    pass

SEED_CUSTOMERS = os.path.join("data", "customers.csv")
SEED_TRANSACTIONS = os.path.join("data", "transactions.csv")

TABLES = ("customers", "transactions", "interventions", "audit_log")

# Postgres wants real types, but a CSV is all strings.
NUMERIC = {"amount"}
INTEGER = {"attempt_count"}


def _ok(msg):
    print(f"  [ok]    {msg}")


def _warn(msg):
    print(f"  [warn]  {msg}")


def _fail(msg):
    print(f"  [FAIL]  {msg}")


def _ask_and_write_env():
    """No credentials and a real terminal? Ask, and write .env ourselves.
    Editing a dotfile by hand is the step people get stuck on."""
    if not sys.stdin.isatty():
        return False
    if os.path.exists(".env"):
        return False

    print("""
  No .env yet. Paste two values from your Supabase dashboard
  (Project Settings -> API) and this will write the file for you.
  Press Enter on either to skip.
""")
    try:
        url = input("  Project URL  (https://xxxx.supabase.co) : ").strip()
        key = input("  Secret key   (sb_secret_... or eyJ...)  : ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if not url or not key:
        return False

    with io.open(".env", "w", encoding="utf-8") as f:
        f.write(f"SUPABASE_URL={url}\nSUPABASE_KEY={key}\nDRY_RUN=true\n")

    os.environ["SUPABASE_URL"] = url
    os.environ["SUPABASE_KEY"] = key
    _ok("wrote .env")
    return True


def check_credentials():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")

    if not url or not key:
        if _ask_and_write_env():
            url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
        else:
            _fail("SUPABASE_URL / SUPABASE_KEY are not set.")
            print("""
        Create a file named  .env  next to this script containing:

            SUPABASE_URL=https://your-project.supabase.co
            SUPABASE_KEY=your-secret-key

        Both values are in your Supabase dashboard under
        Project Settings -> API.
        """)
            return None

    if not url.startswith("https://"):
        _fail(f"SUPABASE_URL looks wrong: {url!r} (expected https://...supabase.co)")
        return None

    _ok(f"credentials found for {url}")
    return url, key


def connect():
    try:
        from supabase import create_client
    except ImportError:
        _fail("the supabase package is not installed.  pip install -r requirements.txt")
        return None

    try:
        return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    except Exception as e:  # noqa: BLE001
        _fail(f"could not create a Supabase client: {e}")
        return None


def check_tables(sb):
    """Returns (all_present, {table: row_count})."""
    counts, missing = {}, []
    for table in TABLES:
        try:
            res = sb.table(table).select("id", count="exact").limit(1).execute()
            counts[table] = res.count or 0
        except Exception as e:  # noqa: BLE001
            missing.append(table)
            counts[table] = None
            if "does not exist" not in str(e) and "PGRST205" not in str(e):
                _warn(f"{table}: {str(e)[:90]}")

    if missing:
        _fail(f"missing tables: {', '.join(missing)}")
        project = (os.environ.get("SUPABASE_URL") or "").replace(
            "https://", "").replace(".supabase.co", "")
        print(f"""
        Create them — this is the one manual step:
          1. Open  https://supabase.com/dashboard/project/{project}/sql/new
          2. Paste the whole of schema.sql
          3. Press Run
          4. Re-run this script
        """)
        return False, counts

    _ok("all four tables exist")
    return True, counts


def check_view(sb):
    try:
        sb.table("recovery_metrics").select("*").limit(1).execute()
        _ok("recovery_metrics view exists")
        return True
    except Exception:  # noqa: BLE001
        _warn("recovery_metrics view is missing — re-run the tail of schema.sql. "
              "The dashboard needs it.")
        return False


def _read_seed(path):
    if not os.path.exists(path):
        _fail(f"seed file not found: {path}")
        return None
    with io.open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in list(row):
            if key in NUMERIC:
                row[key] = float(row[key])
            elif key in INTEGER:
                row[key] = int(row[key])
    return rows


def seed(sb, force=False):
    customers = _read_seed(SEED_CUSTOMERS)
    transactions = _read_seed(SEED_TRANSACTIONS)
    if customers is None or transactions is None:
        print("\n  Regenerate them with:  python generate_synthetic_data.py")
        return False

    existing = sb.table("transactions").select("id", count="exact").limit(1).execute().count or 0

    if existing and not force:
        _ok(f"{existing} transactions already loaded — nothing to do")
        print("       (use --force to wipe and re-seed)")
        return True

    if force:
        print("\n  Wiping existing data...")
        # children first: audit_log and interventions both point at transactions
        for table in ("audit_log", "interventions", "transactions", "customers"):
            rows = sb.table(table).select("id").execute().data
            for row in rows:
                sb.table(table).delete().eq("id", row["id"]).execute()
            print(f"    cleared {len(rows):>4} rows from {table}")

    print("\n  Loading seed batch...")
    # customers first — transactions carry a foreign key onto them
    sb.table("customers").insert(customers).execute()
    print(f"    inserted {len(customers):>4} customers")
    sb.table("transactions").insert(transactions).execute()
    print(f"    inserted {len(transactions):>4} transactions")

    at_risk = sum(float(t["amount"]) for t in transactions)
    _ok(f"seeded — Rs {at_risk:,.2f} at risk across {len(transactions)} failed payments")
    return True


def main(argv):
    force = "--force" in argv
    check_only = "--check" in argv

    print("\nRevenue Recovery Agent — database setup")
    print("=" * 60)

    if not check_credentials():
        return 1

    sb = connect()
    if sb is None:
        return 1

    try:
        sb.table("customers").select("id").limit(1).execute()
        _ok("connected to Supabase")
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "401" in msg or "Invalid API key" in msg or "JWT" in msg:
            key = os.environ.get("SUPABASE_KEY", "")
            _fail("reached Supabase, but the key was rejected (401).")
            if key.startswith("sb_publishable_"):
                print("\n        That is the PUBLISHABLE key — it cannot read your "
                      "tables.\n        Use the SECRET key (sb_secret_...) from "
                      "Project Settings -> API.")
            elif key.startswith("eyJ"):
                print("\n        That is a legacy anon/service_role key. If you have "
                      "disabled\n        legacy keys, create a secret key "
                      "(sb_secret_...) and use that.")
            else:
                print("\n        Use the SECRET key (sb_secret_...) from Project "
                      "Settings -> API,\n        and check the whole value was "
                      "copied.")
            print("\n        Then:  rm .env  and run this script again.\n")
            return 1
        # a missing table is fine here; check_tables reports it properly
        if "does not exist" not in msg and "PGRST205" not in msg:
            _fail(f"could not reach Supabase: {msg[:120]}")
            return 1

    tables_ok, counts = check_tables(sb)
    if not tables_ok:
        return 1
    check_view(sb)

    if check_only:
        print("\n  Current contents:")
        for table, n in counts.items():
            print(f"    {table:<16} {n:>5} rows")
        print("\nCheck complete. Nothing was changed.")
        return 0

    if not seed(sb, force=force):
        return 1

    print("\n" + "=" * 60)
    print("""Ready. Next:

    python run_pipeline.py                 decide and execute, in dry run
    python -m streamlit run dashboard.py   open the dashboard
""")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
