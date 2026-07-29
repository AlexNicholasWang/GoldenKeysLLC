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
        "https://goldenkeyscapital.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
def _google_client_id() -> str:
    return (
        os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        or os.environ.get("VITE_GOOGLE_CLIENT_ID", "").strip()
    )
def verifyGoogleID(token: str) -> dict:
    """
    Verify Google ID token and return token payload.
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
            token,
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
    return idinfo
def user_is_onboarded(user) -> bool:
    return user.get("onboarded", False)
# 3. Define your router and endpoints
router = APIRouter(prefix="/api", tags=["Authentication"])
class TicketCreateBody(BaseModel):
    ssoToken: str
    code: str
    ticketType: str
    dateCreated: str
    notes: str
    urgency: str
@router.post("/create-ticket")
def create_ticket(body: TicketCreateBody):
    """
    Verify Google ID token and prepend a ticket to the matching tenant's ticket list.
    """
    # gemini clutched up on this one
    idinfo = verifyGoogleID(body.ssoToken)
    email = idinfo.get("email", "").strip().lower()
    code = body.code.strip()
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        toInsert = {
            "ticket-type": body.ticketType,
            "date-created": body.dateCreated,
            "notes": body.notes,
            "status": "Incomplete",
            "ugency": body.urgency,
        }
        result = db.landlords.update_one(
            {
                "code": code, 
                "tenants.email": email
            },
            {
                "$push": {
                    "tenants.$.tickets": {
                        "$each": [toInsert],
                        "$position": 0
                    }
                }
            }
        )
        if result.matched_count == 0:
            raise HTTPException(
                status_code=404,
                detail=f"No tenant account found with email '{email}' under landlord code '{code}'."
            )
        return "Ticket Successfully Created"
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Something went wrong: {exc}",
        ) from exc
class TenantChangeBody(BaseModel):
    ssoToken: str
    tenantEmail: str
    address: str
    rent: float
    day: int
    date: str
@router.post("/change-tenant-info")
def change_tenant_info(body: TenantChangeBody):
    """
    Verify Google ID token, upsert user, return onboarded status.
    """
    idinfo = verifyGoogleID(body.ssoToken)
    email = idinfo.get("email")
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        user = db.landlords.find_one({"email": email})
        tenants = user.get("tenants")
        result = db.landlords.update_one(
            {"email": email},
            {
                "$set": {
                    "tenants.$[t].address": body.address,
                    "tenants.$[t].rent": body.rent,
                    "tenants.$[t].day": body.day,
                    "tenants.$[t].date": body.date
                }
            },
            array_filters=[
                {"t.email": body.tenantEmail}
            ]
        )
        message = "Successfully Updated"
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database error during sign-in: {exc}",
        ) from exc
    return message
class GoogleTokenBody(BaseModel):
    token: str
class TenantDataRequestBody(BaseModel):
    code: str
    token: str
@router.post("/get-tenant-data")
def get_tenant_data(body: TenantDataRequestBody):
    """
    Verify Google ID token, upsert user, return onboarded status.
    """
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")

    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        landlord = db.landlords.find_one({"code": body.code})
        if landlord is None:
            raise HTTPException(
                status_code=404, 
                detail="Invalid code. No landlord matches this configuration."
            )
        tenants = landlord.get("tenants")
        for tenant in tenants:
            if(tenant["email"] == email):
                first_name = tenant.get("fist_name")
                last_name = tenant.get("last_name")
                address = tenant.get("address")
                date = tenant.get("date")
                day = tenant.get("day")
                rent = tenant.get("rent")
                tickets = tenant.get("tickets")
                message = "Success"
                return {
                    "message": message,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "address": address,
                    "date": date,
                    "day": day,
                    "rent": rent,
                    "tickets": tickets,
                }
        raise HTTPException(
                status_code=404, 
                detail="No tenant found."
            )
    # bookmark
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="No tenant found",
        )

@router.post("/google-sso-landlord")
def google_sso_landlord(body: GoogleTokenBody):
    """
    Verify Google ID token, upsert user, return onboarded status.
    """
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
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
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
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
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
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
@router.post("/google-sso-tenant-signin")
def google_sso_tenant_signin(body: GoogleTokenBody):
    """
    Verify Google ID token, upsert user, return onboarded status.
    """
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
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
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
    google_id = idinfo["sub"]
    tenants = []
    name = ""
    message = ""
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
