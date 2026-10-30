"""Auth dependencies are plain def (2026-10-30) so their DB lookups run in the threadpool, not on the event loop."""
import inspect
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import Base, get_db
from app.core import deps
from app.models import User
from app.core.security import create_access_token, get_password_hash

def test_auth_me_with_sync_deps():
    assert not inspect.iscoroutinefunction(deps.get_current_user)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng, tables=[t for n, t in Base.metadata.tables.items() if n in ("users","roles","permissions","user_roles","role_permissions")])
    S = sessionmaker(bind=eng)
    db = S(); u = User(email="a@b.c", hashed_password=get_password_hash("x"), name="A", is_active=True, is_superuser=True); db.add(u); db.commit(); uid = u.id; db.close()
    def _db():
        s = S()
        try: yield s
        finally: s.close()
    app.dependency_overrides[get_db] = _db
    try:
        c = TestClient(app)
        tok = create_access_token({"sub": str(uid)})
        r = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == "a@b.c"
        assert c.get("/api/v1/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401
        big = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}", "Accept-Encoding": "gzip"})
        assert big.status_code == 200
    finally:
        app.dependency_overrides.clear()
