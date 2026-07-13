import os
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path

current_dir = Path(__file__).resolve().parent
load_dotenv(dotenv_path=current_dir / ".env")

# 1. Initialize the core FastAPI application
app = FastAPI()

# 2. Configure CORS middleware 
# Since your frontend is in a separate folder, it will run on a different port (e.g., 5500 via VS Code Live Server)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Define your router and endpoints
router = APIRouter(prefix="/api", tags=["Authentication"])

class GoogleTokenBody(BaseModel):
    token: str

def _google_client_id() -> str:
    return (
        os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        or os.environ.get("VITE_GOOGLE_CLIENT_ID", "").strip()
    )

# Placeholder helper function (ensure this is defined or imported in your actual code)
def user_is_onboarded(user) -> bool:
    return user.get("onboarded", False)

@router.post("/google-sso")
def google_sso(body: GoogleTokenBody):
    """
    Verify Google ID token, upsert user, return onboarded status.
    """
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "Set GOOGLE_CLIENT_ID in backend/.env, or VITE_GOOGLE_CLIENT_ID in frontend/.env "
                "(same OAuth 2.0 Web client ID from Google Cloud Console)."
            ),
        )

    try:
        idinfo = id_token.verify_oauth2_token(
            body.token,
            google_requests.Request(),
            client_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Google token",
        )

    email = idinfo.get("email")
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Google account has no email on file",
        )

    google_id = idinfo["sub"]

    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        
        # Fixed the database collection mismatch here (using 'users' consistently)
        user = db.landlords.find_one({"email": email})
        if user is None:
            db.landlords.insert_one(
                {
                    "email": email,
                    "googleId": google_id,
                    "first_name": idinfo.get("given_name", ""),
                    "last_name": idinfo.get("family_name", ""),
                }
            )
            user = db.landlords.find_one({"email": email})
            message = f"Signed up as {email}"
        else:
            message = f"Signed in as {email}"

        onboarded = user_is_onboarded(user)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database error during sign-in: {exc}",
        ) from exc

    profile = user.get("local_storage", []) if (onboarded and user) else None
    return {
        "message": message,
        "email": email,
        "onboarded": onboarded,
        "token": body.token,
        "profile": profile,
    }

# 4. Register the router onto the main app instance
app.include_router(router)

router = APIRouter(prefix="/api", tags=[])

router = APIRouter(prefix="/api", tags=["Authentication"])

class GoogleTokenBody(BaseModel):
    token: str


def _google_client_id() -> str:
    return (
        os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        or os.environ.get("VITE_GOOGLE_CLIENT_ID", "").strip()
    )


@router.post("/google-sso")
def google_sso(body: GoogleTokenBody):
    """
    Verify Google ID token, upsert user, return onboarded status (one round trip).
    """
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(
            status_code=500,
            detail=(
                "Set GOOGLE_CLIENT_ID in backend/.env, or VITE_GOOGLE_CLIENT_ID in frontend/.env "
                "(same OAuth 2.0 Web client ID from Google Cloud Console)."
            ),
        )

    try:
        idinfo = id_token.verify_oauth2_token(
            body.token,
            google_requests.Request(),
            client_id,
        )
    except ValueError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired Google token",
        )

    email = idinfo.get("email")
    if not email:
        raise HTTPException(
            status_code=401,
            detail="Google account has no email on file",
        )

    google_id = idinfo["sub"]

    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        user = db.landlords.find_one({"email": email})
        if user is None:
            db.landlords.insert_one(
                {
                    "email": email,
                    "googleId": google_id,
                    "first_name": idinfo["given_name"],
                    "last_name": idinfo["family_name"],
                }
            )
            user = db.landlords.find_one({"email": email})
            message = f"Signed up as {email}"
        else:
            message = f"Signed in as {email}"

        onboarded = user_is_onboarded(user)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database error during sign-in: {exc}",
        ) from exc

    profile = user.get("local_storage", []) if (onboarded and user) else None
    return {
        "message": message,
        "email": email,
        "onboarded": onboarded,
        "token": body.token,
        "profile": profile,
    }

@app.get("/api/config")
def get_config():
    """
    Expose public configuration variables to the frontend.
    """
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="Google Client ID not configured on server")
    
    return {"google_client_id": client_id}

app.include_router(router)
