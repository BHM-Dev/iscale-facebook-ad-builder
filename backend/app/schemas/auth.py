from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


# Token schemas
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenRefresh(BaseModel):
    refresh_token: str


class AccessToken(BaseModel):
    access_token: str
    token_type: str = "bearer"


# User schemas
class UserBase(BaseModel):
    email: EmailStr
    name: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserCreateFull(UserBase):
    """Extended create schema used by superusers — supports admin flag and role assignment."""
    password: str
    is_superuser: bool = False
    role_ids: List[str] = []


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None


class UserRoleUpdate(BaseModel):
    role_ids: List[str]


class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None


class RoleCreate(RoleBase):
    pass


class PermissionBase(BaseModel):
    name: str
    description: Optional[str] = None


class PermissionCreate(PermissionBase):
    pass


class PermissionResponse(PermissionBase):
    id: str
    created_at: datetime

    class Config:
        from_attributes = True


class RoleResponse(RoleBase):
    id: str
    created_at: datetime
    # Without this the frontend's hasPermission() is false for every user who
    # isn't a superuser, because it reads user.roles[].permissions and the
    # payload never carried them. That silently hid the Profit/Loss nav link
    # from Joel — admin role, not superuser — even though the backend grants
    # admin pnl:read and would have served him the data.
    permissions: List[PermissionResponse] = []

    class Config:
        from_attributes = True


class UserResponse(UserBase):
    id: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime
    roles: List[RoleResponse] = []

    class Config:
        from_attributes = True


class UserLogin(BaseModel):
    email: EmailStr
    password: str
