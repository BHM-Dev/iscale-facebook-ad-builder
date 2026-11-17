"""Read-only: compare the deployed Drive copy parser with a candidate version on every production package.

Run INSIDE the API container (it uses the app's DB session and Drive client). Copy the candidate
drive_sync_service.py to /tmp/newdss.py first. Writes nothing to the database, Drive or Meta.

    scp backend/app/services/drive_sync_service.py ubuntu@adbuilder.velocitymx.io:/tmp/newdss.py
    scp scripts/ops/drive_parser_compare.py ubuntu@adbuilder.velocitymx.io:/tmp/cmp.py
    ssh ubuntu@adbuilder.velocitymx.io 'docker cp /tmp/newdss.py ad-builder-api:/tmp/newdss.py && docker cp /tmp/cmp.py ad-builder-api:/tmp/cmp.py \
      && docker exec -w /app -e PYTHONPATH=/app ad-builder-api python -u /tmp/cmp.py'

Takes ~20 min. Prints every package whose bindings differ (copy_id, headline, primary text, aspect, landing page,
CTA, pairing) and a final "same: N changed: M" line. A change is acceptable only when the old side was an error and
the new side resolves copy that a spot check confirms is right, or the difference is a transient Drive error.
"""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("newdss", "/tmp/newdss.py")
newdss = importlib.util.module_from_spec(spec)
sys.modules["newdss"] = newdss
spec.loader.exec_module(newdss)

from app.database import SessionLocal  # noqa: E402
from app.models import DriveAsset  # noqa: E402
from app.services import drive_sync_service as olddss  # noqa: E402

db = SessionLocal()
old, new = olddss.DriveSyncService(db), newdss.DriveSyncService(db)
client = old._client()
reps = {}
for fid, path in db.query(DriveAsset.drive_file_id, DriveAsset.folder_path).filter(DriveAsset.archived == False).all():  # noqa: E712
    reps.setdefault(path, fid)
packages = {}
for path, fid in reps.items():
    try:
        pkg = old._find_package_folder(client.files().get(fileId=fid, fields="id,name,parents", supportsAllDrives=True).execute())
    except Exception:
        pkg = None
    if pkg:
        packages.setdefault(pkg, path)
print("packages:", len(packages))


def run(svc, pkg):
    svc._folder_metadata_cache = {}
    try:
        meta = svc._folder_copy_metadata(pkg, force=True)
        return {k: (v.get("copy_id"), (v.get("copy") or {}).get("headline"), (v.get("copy") or {}).get("primary_text"),
                    v.get("aspect"), v.get("landing_page"), v.get("cta"), v.get("copy_pairing_status"))
                for k, v in (meta.get("assets_by_drive_id") or {}).items()}
    except Exception as exc:
        return f"ERR {type(exc).__name__}: {str(exc)[:160]}"


same = changed = 0
for pkg, path in packages.items():
    a, b = run(old, pkg), run(new, pkg)
    if a == b:
        same += 1
        continue
    changed += 1
    print("CHANGED", path)
    print("   old:", a if isinstance(a, str) else f"{len(a)} assets")
    print("   new:", b if isinstance(b, str) else f"{len(b)} assets")
print(f"same: {same} changed: {changed}")
db.rollback()
db.close()
