"""
One-off: move pre-Phase-3 uploads out of the system temp folder.

Before Phase 3, uploads were written to $TMPDIR/cellspark_uploads, which macOS
clears periodically, and the demo MAF's row pointed at a temp folder that was
regenerated on every boot. This repoints every mutation_file row at the
permanent store, backend/data/uploads/:

  - demo MAF rows       -> data/uploads/demo/sample_patient.maf
  - files still on disk -> moved to data/uploads/<researcher_id>/<same name>
  - files already gone  -> left as they are and listed. No row is deleted:
                           the runs computed from them are still valid
                           history. The API reports file_available=false for
                           these, computed from disk; the schema has no column
                           to record it and the application user can't add one.

Row updates only (UPDATE on mutation_file), so it runs as the normal
application user. Safe to run twice: rows already in place are skipped.

    cd backend
    venv/bin/python scripts/migrate_upload_storage.py --dry-run
    venv/bin/python scripts/migrate_upload_storage.py
"""
import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import records, upload
from app.db import get_engine
from app.models import MutationFile


def inside(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    return os.path.commonpath([root, os.path.realpath(path)]) == root


def main(dry_run: bool) -> int:
    demo_path, _, demo_sha = records._ensure_demo_copy()
    moved = repointed = ok = 0
    missing = []

    with Session(get_engine()) as db:
        rows = db.execute(select(MutationFile).order_by(MutationFile.file_id)).scalars().all()
        for row in rows:
            if row.sha256 == demo_sha:
                if row.stored_path != demo_path:
                    print(f"demo   file {row.file_id}: {row.stored_path} -> {demo_path}")
                    row.stored_path = demo_path
                    repointed += 1
                else:
                    ok += 1
                continue

            if inside(row.stored_path, upload.UPLOAD_DIR) and os.path.exists(row.stored_path):
                ok += 1
                continue

            if not os.path.exists(row.stored_path):
                missing.append(row)
                continue

            dest = os.path.join(upload.UPLOAD_DIR, str(row.researcher_id),
                                os.path.basename(row.stored_path))
            print(f"move   file {row.file_id}: {row.stored_path} -> {dest}")
            if not dry_run:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.move(row.stored_path, dest)
            row.stored_path = dest
            moved += 1

        for row in missing:
            print(f"GONE   file {row.file_id} ({row.original_name}, researcher "
                  f"{row.researcher_id}): {row.stored_path} — row kept, history intact")

        if dry_run:
            db.rollback()
        else:
            db.commit()

    print(f"\n{'[dry run] ' if dry_run else ''}{ok} already in place, {moved} moved, "
          f"{repointed} demo rows repointed, {len(missing)} missing from disk.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="report only; change nothing")
    sys.exit(main(ap.parse_args().dry_run))
