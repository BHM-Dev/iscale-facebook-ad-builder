from typing import Callable, List, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import User
from app.core.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# These are plain ``def`` on purpose. FastAPI runs sync dependencies in its threadpool;
# as ``async def`` their blocking ``db.query`` (and lazy role/permission loads) ran on
# the single event loop, so one slow DB checkout stalled every request in the process.


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    """Get the current authenticated user from the JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get the current user and verify they are active"""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user


def require_role(role_name: str) -> Callable:
    """Dependency that requires the user to have a specific role"""
    def role_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:
        if not current_user.has_role(role_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role_name}' required"
            )
        return current_user
    return role_checker


def require_any_role(role_names: List[str]) -> Callable:
    """Dependency that requires the user to have at least one of the specified roles"""
    def role_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:
        if not any(current_user.has_role(role) for role in role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these roles required: {', '.join(role_names)}"
            )
        return current_user
    return role_checker


def require_permission(permission_name: str) -> Callable:
    """Dependency that requires the user to have a specific permission"""
    def permission_checker(
        current_user: User = Depends(get_current_active_user)
    ) -> User:
        if not current_user.has_permission(permission_name):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission '{permission_name}' required"
            )
        return current_user
    return permission_checker


def get_current_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Require the current user to be a superuser"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required"
        )
    return current_user


# Optional auth - returns None if not authenticated
def get_optional_user(
    token: Optional[str] = Depends(OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)),
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get the current user if authenticated, otherwise return None"""
    if token is None:
        return None

    payload = decode_access_token(token)
    if payload is None:
        return None

    user_id: str = payload.get("sub")
    if user_id is None:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    return user
