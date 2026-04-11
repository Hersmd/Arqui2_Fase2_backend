from fastapi import APIRouter
from app.config.database import db
from app.schemas.user_schema import User

router = APIRouter()

@router.post("/login")
def login(user: User):
    db_user = db.users.find_one({"username": user.username})

    if not db_user:
        return {"error": "User not found"}

    if db_user["password"] != user.password:
        return {"error": "Invalid credentials"}

    return {"message": "Login successful"}