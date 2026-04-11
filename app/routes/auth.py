from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from app.config.database import db
from app.config.settings import settings
from app.schemas.user_schema import User

router = APIRouter()

@router.post("/login")
def login(user: User):
    db_user = db.users.find_one({"username": user.username})

    if not db_user:
        is_default_admin = (
            user.username == settings.DEFAULT_ADMIN_USERNAME
            and user.password == settings.DEFAULT_ADMIN_PASSWORD
        )

        if is_default_admin and settings.AUTO_CREATE_DEFAULT_ADMIN:
            db.users.insert_one(
                {
                    "username": settings.DEFAULT_ADMIN_USERNAME,
                    "password": settings.DEFAULT_ADMIN_PASSWORD,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return {"message": "Login successful"}

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    if db_user["password"] != user.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    return {"message": "Login successful"}