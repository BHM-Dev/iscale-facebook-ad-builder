from app.database import engine, Base, SessionLocal
from app.models import *
from app.core.security import get_password_hash
from datetime import date
from decimal import Decimal

def init_db():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Tables created successfully!")

def seed_roles_and_permissions():
    """Seed default roles and permissions"""
    db = SessionLocal()
    try:
        # Define default permissions
        default_permissions = [
            ("brands:read", "View brands"),
            ("brands:write", "Create and edit brands"),
            ("brands:delete", "Delete brands"),
            ("products:read", "View products"),
            ("products:write", "Create and edit products"),
            ("products:delete", "Delete products"),
            ("ads:read", "View ads"),
            ("ads:write", "Create and edit ads"),
            ("ads:delete", "Delete ads"),
            ("campaigns:read", "View campaigns"),
            ("campaigns:write", "Create and edit campaigns"),
            ("campaigns:delete", "Delete campaigns"),
            ("templates:read", "View templates"),
            ("templates:write", "Create and edit templates"),
            ("templates:delete", "Delete templates"),
            ("users:read", "View users"),
            ("users:write", "Manage users"),
            ("pnl:read", "View the P&L tracker"),
            ("pnl:write", "Add and edit P&L cost entries"),
        ]

        # Create permissions if they don't exist
        permissions = {}
        for name, description in default_permissions:
            existing = db.query(Permission).filter(Permission.name == name).first()
            if not existing:
                perm = Permission(name=name, description=description)
                db.add(perm)
                db.flush()
                permissions[name] = perm
                print(f"  Created permission: {name}")
            else:
                permissions[name] = existing

        # Define default roles with their permissions
        default_roles = {
            "admin": {
                "description": "Full access to all resources",
                "permissions": list(permissions.keys())
            },
            "manager": {
                "description": "Can manage brands, products, ads, and campaigns",
                "permissions": [
                    "brands:read", "brands:write",
                    "products:read", "products:write",
                    "ads:read", "ads:write",
                    "campaigns:read", "campaigns:write",
                    "templates:read", "templates:write",
                    "pnl:read", "pnl:write",
                ]
            },
            "editor": {
                "description": "Can create and edit ads and templates",
                "permissions": [
                    "brands:read",
                    "products:read",
                    "ads:read", "ads:write",
                    "templates:read", "templates:write",
                ]
            },
            "viewer": {
                "description": "Read-only access",
                "permissions": [
                    "brands:read",
                    "products:read",
                    "ads:read",
                    "campaigns:read",
                    "templates:read",
                ]
            }
        }

        # Create roles if they don't exist
        for role_name, role_data in default_roles.items():
            existing = db.query(Role).filter(Role.name == role_name).first()
            if not existing:
                role = Role(name=role_name, description=role_data["description"])
                # Add permissions to role
                for perm_name in role_data["permissions"]:
                    if perm_name in permissions:
                        role.permissions.append(permissions[perm_name])
                db.add(role)
                print(f"  Created role: {role_name}")
            else:
                # Backfill any permissions added to the definition after the role
                # was first created — without this, new permissions never reach
                # existing roles and the feature silently 403s in production.
                current = {p.name for p in existing.permissions}
                added = []
                for perm_name in role_data["permissions"]:
                    if perm_name not in current and perm_name in permissions:
                        existing.permissions.append(permissions[perm_name])
                        added.append(perm_name)
                if added:
                    print(f"  Role exists: {role_name} (granted: {', '.join(added)})")
                else:
                    print(f"  Role exists: {role_name}")

        db.commit()
        print("Roles and permissions seeded successfully!")

    except Exception as e:
        db.rollback()
        print(f"Error seeding roles and permissions: {e}")
        raise
    finally:
        db.close()

def seed_default_pnl_costs():
    """Seed standing P&L costs that should exist on every environment."""
    db = SessionLocal()
    try:
        existing_redtrack = (
            db.query(PnlCostEntry)
            .filter(PnlCostEntry.ad_account_id.is_(None))
            .filter(PnlCostEntry.label == "RedTrack subscription")
            .filter(PnlCostEntry.amount == Decimal("350.00"))
            .filter(PnlCostEntry.cost_type == "recurring_monthly")
            .filter(PnlCostEntry.allocation_method == "by_spend")
            .filter(PnlCostEntry.effective_from == date(2026, 7, 1))
            .filter(PnlCostEntry.effective_to.is_(None))
            .first()
        )
        if existing_redtrack:
            if not existing_redtrack.vendor:
                existing_redtrack.vendor = "RedTrack"
                db.commit()
            print("  P&L default cost exists: RedTrack subscription")
            return

        db.add(PnlCostEntry(
            ad_account_id=None,
            label="RedTrack subscription",
            category="tooling",
            cost_type="recurring_monthly",
            amount=Decimal("350.00"),
            allocation_method="by_spend",
            effective_from=date(2026, 7, 1),
            effective_to=None,
            notes="Seeded default monthly RedTrack platform cost.",
            vendor="RedTrack",
            source="manual",
        ))
        db.commit()
        print("  Created P&L default cost: RedTrack subscription ($350/mo)")
    except Exception as e:
        db.rollback()
        print(f"Error seeding default P&L costs: {e}")
        raise
    finally:
        db.close()

def create_superuser(email: str, password: str, name: str = "Admin"):
    """Create a superuser if one doesn't exist"""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            print(f"User {email} already exists")
            return

        hashed_password = get_password_hash(password)
        user = User(
            email=email,
            hashed_password=hashed_password,
            name=name,
            is_superuser=True,
            is_active=True
        )

        # Add admin role
        admin_role = db.query(Role).filter(Role.name == "admin").first()
        if admin_role:
            user.roles.append(admin_role)

        db.add(user)
        db.commit()
        print(f"Superuser {email} created successfully!")

    except Exception as e:
        db.rollback()
        print(f"Error creating superuser: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    print("\nSeeding roles and permissions...")
    seed_roles_and_permissions()
    print("\nSeeding default P&L costs...")
    seed_default_pnl_costs()

    # Optionally create a default superuser (requires env vars)
    import os
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_password = os.getenv("ADMIN_PASSWORD")
    if admin_email and admin_password:
        print(f"\nCreating superuser ({admin_email})...")
        create_superuser(admin_email, admin_password)
    else:
        print("\nSkipping superuser creation (set ADMIN_EMAIL and ADMIN_PASSWORD to create one)")
