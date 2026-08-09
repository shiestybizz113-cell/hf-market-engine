from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from datetime import datetime, timezone
from app.core.database import get_db
from app.core.security import (
    get_password_hash, verify_password, create_access_token, decode_token, oauth2_scheme
)
from app.models.schemas import UserCreate, UserOut, Token
import uuid

router = APIRouter(prefix="/auth", tags=["auth"])


async def get_current_user(token: str = Depends(oauth2_scheme)):
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/register", response_model=UserOut)
async def register(payload: UserCreate):
    db = get_db()
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = {
        "_id": str(uuid.uuid4()),
        "email": payload.email.lower(),
        "hashed_password": get_password_hash(payload.password),
        "full_name": payload.full_name,
        "plan": "free",
        "created_at": datetime.now(timezone.utc),
    }
    await db.users.insert_one(user)
    return UserOut(
        id=user["_id"],
        email=user["email"],
        full_name=user["full_name"],
        plan=user["plan"],
        created_at=user["created_at"],
    )


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    db = get_db()
    user = await db.users.find_one({"email": form_data.username.lower()})
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token({"sub": user["_id"]})
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user=Depends(get_current_user)):
    return UserOut(
        id=current_user["_id"],
        email=current_user["email"],
        full_name=current_user.get("full_name"),
        plan=current_user.get("plan", "free"),
        created_at=current_user["created_at"],
    )
