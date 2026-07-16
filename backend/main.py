import os
from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel
from pymongo import MongoClient
from dotenv import load_dotenv
from pathlib import Path
import random

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

@router.post("/google-sso-landlord")
def google_sso_landlord(body: GoogleTokenBody):
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
            users = db.landlords.find()
            code = ""
            isCodeUnique = False
            isCurrentCodeUnique = True
            while(isCodeUnique == False):
                isCurrentCodeUnique = True
                code = "".join(chr(random.randint(65, 90)) for _ in range(7))
                for i in users:
                    if(code == i["code"]):
                        isCurrentCodeUnique = False
                if(isCurrentCodeUnique == True):
                    isCodeUnique = True
            db.landlords.insert_one(
                {
                    "email": email,
                    "googleId": google_id,
                    "first_name": idinfo.get("given_name", ""),
                    "last_name": idinfo.get("family_name", ""),
                    "code": code,
                    "tenants": []
                }
            )
            user = db.landlords.find_one({"email": email})
            name = user.get("first_name") + " " + user.get("last_name")
            code = user.get("code")
            message = f"Signed up as {name}. Code is {code}."
        else:
            user = db.landlords.find_one({"email": email})
            name = user.get("first_name") + " " + user.get("last_name")
            code = user.get("code")
            message = f"Signed in as {name}. Code is {code}."

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
        "firstName": user.get("first_name"),
        "lastName": user.get("last_name"),
        "code": user.get("code"),
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

@app.get("/api/config")
def get_config():
    """
    Expose public configuration variables to the frontend.
    """
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="Google Client ID not configured on server")
    
    return {"google_client_id": client_id}


@router.post("/google-sso-landlord")
def google_sso_landlord(body: GoogleTokenBody):
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
            users = db.landlords.find()
            code = ""
            isCodeUnique = False
            isCurrentCodeUnique = True
            while(isCodeUnique == False):
                isCurrentCodeUnique = True
                code = "".join(chr(random.randint(65, 90)) for _ in range(7))
                for i in users:
                    if(code == i["code"]):
                        isCurrentCodeUnique = False
                if(isCurrentCodeUnique == True):
                    isCodeUnique = True
            db.landlords.insert_one(
                {
                    "email": email,
                    "googleId": google_id,
                    "first_name": idinfo.get("given_name", ""),
                    "last_name": idinfo.get("family_name", ""),
                    "code": code,
                    "tenants": []
                }
            )
            user = db.landlords.find_one({"email": email})
            name = user.get("first_name") + " " + user.get("last_name")
            code = user.get("code")
            message = f"Signed up as {name}. Code is {code}."
        else:
            user = db.landlords.find_one({"email": email})
            name = user.get("first_name") + " " + user.get("last_name")
            code = user.get("code")
            message = f"Signed in as {name}. Code is {code}."

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

class VerifyCodeBody(BaseModel):
    code: str

@app.post("/api/verify-code")
def verify_code(body: VerifyCodeBody):
    search_code = body.code.strip()
    if not search_code:
        raise HTTPException(status_code=400, detail="Provided code cannot be empty")
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        landlord = db.landlords.find_one({"code": search_code})
        if(landlord is None):
            raise HTTPException(
                status_code=404, 
                detail="Invalid code. No landlord matches this configuration."
            )
        name = landlord.get("first_name", "") + " " + landlord.get("last_name", "")
        return {
            "status": "success",
            "landlord_name": name
        }
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database error during code validation: {exc}",
        ) from exc

class TenantSignupBody(BaseModel):
    token: str
    code: str
@router.post("/google-sso-tenant-signup")
def google_sso_tenant_signup(body: TenantSignupBody):
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
        landlords = db.landlords.find()
        for landlord in landlords:
            for tenant in landlord.get("tenants"):
                if(tenant["email"] == email):
                    raise HTTPException(status_code=405, detail="Already signed up as a tenant. Cannot sign up twice")
        landlord = db.landlords.find_one({"code": body.code})
        if(landlord == None):
            raise HTTPException(status_code=400, detail="Landlord not found") 
        query_filter = {"code": body.code, "tenants.email": {"$ne": email}}
        new_tenant_data = {
            "email": email,
            "googleId": google_id,
            "first_name": idinfo.get("given_name", ""),
            "last_name": idinfo.get("family_name", "")
        }
        update_operation = {"$push": {"tenants": new_tenant_data}}
        result = db.landlords.update_one(query_filter, update_operation)
        fullName = idinfo.get("given_name", "") + " " + idinfo.get("family_name", "")
        landlordName = f"{landlord.get('first_name', '')} {landlord.get('last_name', '')}".strip()
        if result.modified_count == 0:
            # Landlord code was valid, but 0 modifications means the email was already in the array
            message = f"Welcome back! You are already enrolled in {landlordName}'s community as {fullName}."
        else:
            # Modification count is 1, meaning they were successfully added
            message = f"Success! You enrolled in {landlordName}'s community as {fullName}."
        # add to landlord the user
        onboarded = user_is_onboarded(landlord)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database error during sign-in: {exc}",
        ) from exc

    profile = landlord.get("local_storage", []) if (onboarded and landlord) else None
    return {
        "message": message,
        "email": email,
        "onboarded": onboarded,
        "token": body.token,
        "profile": profile,
    }

@router.post("/google-sso-tenant-signin") # bookmark
def google_sso_tenant_signin(body: GoogleTokenBody):
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
    landlord_name = ""
    tenant_name = ""
    landlord_code = ""
    doesTenantExist = False
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        
        # Fixed the database collection mismatch here (using 'users' consistently)
        landlords = db.landlords.find()
        for landlord in landlords:
            for tenant in landlord.get("tenants"):
                if(tenant["email"] == email):
                    doesTenantExist = True
                    landlord_name = landlord.get("first_name") + " " +  landlord.get("last_name")
                    tenant_name = tenant["first_name"] + " " + tenant["last_name"]
                    landlord_code = landlord.get("code")
                    message = f"Signed in as {tenant_name} in {landlord_name}'s community"
        if(doesTenantExist == False):
            raise HTTPException(status_code=404, detail="Tenant's account does not exist. Try signing up with your landlord's code.")
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database error during sign-in: {exc}",
        ) from exc
    return {
        "message": message,
        "email": email,
        "landlord_name": landlord_name,
        "tenant_name": tenant_name,
        "landlord_code": landlord_code,
        "token": body.token,
    }

@router.post("/get-landlord-data")
def get_landlord_data(body: GoogleTokenBody):
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
    tenants = []
    name = ""
    email = idinfo.get("email")
    message = ""
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
            raise HTTPException(status_code=404, detail="Could not authenticate. Please try signing in again.");
        else:
            user = db.landlords.find_one({"email": email})
            name = user.get("first_name") + " " + user.get("last_name")
            code = user.get("code")
            tenants = user.get("tenants")
            message = f"Welcome back {name}"

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
        "tenants": tenants,
        "name": name,
        "onboarded": onboarded,
        "token": body.token,
        "profile": profile,
    }


# 4. Register the router onto the main app instance


app.include_router(router)
