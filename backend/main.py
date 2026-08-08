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
import uuid
from google import genai
from google.genai import types
from typing import List, Optional
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify, Response
import gridfs
from pypdf import PdfReader
from bson import ObjectId

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

# 1. Initialize the core FastAPI application
app = FastAPI()

# 2. Configure CORS middleware 
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://goldenkeyscapital.app",
        "https://www.goldenkeyscapital.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # Allows all Vercel preview/deployment URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Define your router and endpoints
router = APIRouter(prefix="/api", tags=["Authentication"])

api_key = os.getenv("GEMINI_CLIENT_ID", "").strip()
client = genai.Client(api_key=api_key)

class PromptRequest(BaseModel):
    userData: str

class ChatTurn(BaseModel):
    role: str
    text: str

class ChatRequest(BaseModel):
    history: List[ChatTurn]
    new_message: str
    ssoToken: Optional[str] = None
    code: Optional[str] = None
    userData: Optional[str] = None # Added for caching user context

def get_constitution() -> str:
    file_path = BASE_DIR / "constitution.txt"
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return "You are a helpful, concise assistant powered by Gemini 3.1 Flash Lite."

def _google_client_id() -> str:
    return (
        os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        or os.environ.get("VITE_GOOGLE_CLIENT_ID", "").strip()
    )

def verifyGoogleID(token: str) -> dict:
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

@router.post("/prompt")
def prompt(data: PromptRequest):
    try:
        constitution = get_constitution()
        prompt_text = f"{constitution}\n\nUser Data/Context:\n{data.userData}"
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt_text
        )
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
@router.post("/chat")
def chat(request: ChatRequest):
    try:
        constitution = get_constitution()
        user_context = request.userData or ""
        returned_user_data = None

        # Fetch and inject user context if not cached
        if request.ssoToken and request.code and not user_context:
            try:
                idinfo = verifyGoogleID(request.ssoToken)
                email = idinfo.get("email", "").strip().lower()
                clean_code = request.code.strip()

                mongo_uri = os.environ.get("MONGO_CLIENT_ID", "").strip()
                db = MongoClient(mongo_uri)["keyfolio"]
                landlord = db.landlords.find_one({"code": clean_code})

                if landlord:
                    for tenant in landlord.get("tenants", []):
                        tenant_email = tenant.get("email", "").strip().lower()
                        if tenant_email == email:
                            user_context = (
                                f"\n\n--- CURRENT TENANT CONTEXT ---\n"
                                f"Name: {tenant.get('first_name', '')} {tenant.get('last_name', '')}\n"
                                f"Email: {email}\n"
                                f"Address: {tenant.get('address', 'Unknown')}\n"
                                f"Rent Amount: ${tenant.get('rent', 'Unknown')}\n"
                                f"Rent Due Day: {tenant.get('day', 'Unknown')} of the month\n"
                                f"Landlord Name: {landlord.get('first_name', '')} {landlord.get('last_name', '')}\n"
                                f"START OF LEASE:\n\n {tenant.get('lease_pdf', 'NO LEASE UPLOADED')}\n\n"
                            )
                            print(len(user_context), flush=True)
                            returned_user_data = user_context
                            break
                    else:
                        print(f"[CHAT DEBUG] Landlord found for code '{clean_code}', but no matching tenant email for '{email}'")
                else:
                    print(f"[CHAT DEBUG] No landlord found matching code '{clean_code}'")

            except Exception as e:
                print(f"[CHAT ERROR] Could not inject user context: {e}")
        date = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y")
        system_instruction = constitution + user_context + f"\n\nIf you need it, here's the current date: {date}\n\n"
        contents = []

        for turn in request.history:
            role = "model" if turn.role in ["model", "assistant"] else "user"
            contents.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=turn.text)]
                )
            )

        contents.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=request.new_message)]
            )
        )

        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_instruction)
        )

        return {
            "response": response.text,
            "userData": returned_user_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class TicketEditBody(BaseModel):
    ssoToken: str
    tenantEmail: str
    ticketID: str
    status: str
    landlordNotes: str

@router.post("/edit-ticket")
def edit_ticket(body: TicketEditBody):
    idinfo = verifyGoogleID(body.ssoToken)
    email = idinfo.get("email", "").strip().lower()
    filter_query = {"email": email}
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        update_query = {
            "$set": {
                "tenants.$[t].tickets.$[tk].status": body.status,
                "tenants.$[t].tickets.$[tk].landlord-notes": body.landlordNotes
            }
        }
        array_filters = [
            {"t.email": body.tenantEmail},
            {"tk.ticket-id": body.ticketID}
        ]
        result = db.landlords.update_one(
            filter_query,
            update_query,
            array_filters=array_filters
        )
        if result.matched_count > 0 and result.modified_count > 0:
            return {"success": True, "message": "Ticket updated successfully."}
        elif result.matched_count > 0:
            return {"success": True, "message": "Document matched, but no changes were needed."}
        else:
            return {"success": False, "message": "Landlord, tenant, or ticket not found."}
    except Exception as exc:
        return {"success": False, "message": f"ERROR: {exc}"}

class TicketCreateBody(BaseModel):
    ssoToken: str
    code: str
    ticketType: str
    dateCreated: str
    notes: str
    urgency: str

@router.post("/create-ticket")
def create_ticket(body: TicketCreateBody):
    idinfo = verifyGoogleID(body.ssoToken)
    email = idinfo.get("email", "").strip().lower()
    code = body.code.strip()
    try:
        ticket_id = f"TKT-{uuid.uuid4().hex[:6].upper()}"
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        toInsert = {
            "ticket-type": body.ticketType,
            "date-created": body.dateCreated,
            "tenant-notes": body.notes,
            "status": "Incomplete",
            "ugency": body.urgency,
            "ticket-id": ticket_id,
            "landlord-notes": "",
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
        raise HTTPException(status_code=503, detail=f"Something went wrong: {exc}") from exc

class TenantChangeBody(BaseModel):
    ssoToken: str
    tenantEmail: str
    address: str
    rent: float
    day: int
    date: str

@router.post("/change-tenant-info")
def change_tenant_info(body: TenantChangeBody):
    idinfo = verifyGoogleID(body.ssoToken)
    email = idinfo.get("email")
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
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
            array_filters=[{"t.email": body.tenantEmail}]
        )
        message = "Successfully Updated"
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error during sign-in: {exc}") from exc
    return message


class UploadLeaseBody(BaseModel):
    ssoToken: str
    tenantEmail: str
    pdfBase64: str

@router.post("/upload-lease")
def upload_lease(body: UploadLeaseBody):
    idinfo = verifyGoogleID(body.ssoToken)
    email = idinfo.get("email")
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        result = db.landlords.update_one(
            {"email": email, "tenants.email": body.tenantEmail},
            {"$set": {"tenants.$.lease_pdf": body.pdfBase64}}
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Tenant not found under this landlord")
        return {"message": "Lease uploaded successfully"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

class GoogleTokenBody(BaseModel):
    token: str

class TenantDataRequestBody(BaseModel):
    code: str
    token: str

@router.post("/get-tenant-data")
def get_tenant_data(body: TenantDataRequestBody):
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")

    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        landlord = db.landlords.find_one({"code": body.code})
        if landlord is None:
            raise HTTPException(status_code=404, detail="Invalid code. No landlord matches this configuration.")
        tenants = landlord.get("tenants")
        for tenant in tenants:
            if(tenant["email"] == email):
                return {
                    "message": "Success",
                    "email": email,
                    "first_name": tenant.get("first_name"),
                    "last_name": tenant.get("last_name"),
                    "address": tenant.get("address"),
                    "date": tenant.get("date"),
                    "day": tenant.get("day"),
                    "rent": tenant.get("rent"),
                    "lease_pdf": tenant.get("lease_pdf"),
                    "tickets": tenant.get("tickets"),
                }
        raise HTTPException(status_code=404, detail="No tenant found.")
    except ValueError:
        raise HTTPException(status_code=404, detail="No tenant found")

@router.post("/google-sso-landlord")
def google_sso_landlord(body: GoogleTokenBody):
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
    google_id = idinfo["sub"]

    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]
        user = db.landlords.find_one({"email": email})
        
        if user is None:
            users = db.landlords.find()
            code = ""
            isCodeUnique = False
            while not isCodeUnique:
                isCurrentCodeUnique = True
                code = "".join(chr(random.randint(65, 90)) for _ in range(7))
                for i in users:
                    if code == i["code"]:
                        isCurrentCodeUnique = False
                if isCurrentCodeUnique:
                    isCodeUnique = True
                    
            db.landlords.insert_one({
                "email": email,
                "googleId": google_id,
                "first_name": idinfo.get("given_name", ""),
                "last_name": idinfo.get("family_name", ""),
                "code": code,
                "tenants": []
            })
            user = db.landlords.find_one({"email": email})
            name = f"{user.get('first_name')} {user.get('last_name')}"
            message = f"Signed up as {name}. Code is {code}."
        else:
            name = f"{user.get('first_name')} {user.get('last_name')}"
            code = user.get("code")
            message = f"Signed in as {name}. Code is {code}."

        onboarded = user_is_onboarded(user)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error during sign-in: {exc}") from exc

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
        if landlord is None:
            raise HTTPException(status_code=404, detail="Invalid code. No landlord matches this configuration.")
        name = f"{landlord.get('first_name', '')} {landlord.get('last_name', '')}"
        return {"status": "success", "landlord_name": name}
    except HTTPException as http_exc:
        raise http_exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error during code validation: {exc}") from exc

class TenantSignupBody(BaseModel):
    token: str
    code: str

@router.post("/google-sso-tenant-signup")
def google_sso_tenant_signup(body: TenantSignupBody):
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
    google_id = idinfo["sub"]
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]   
        landlords = db.landlords.find()
        for landlord in landlords:
            for tenant in landlord.get("tenants"):
                if tenant["email"] == email:
                    raise HTTPException(status_code=405, detail="Already signed up as a tenant. Cannot sign up twice")
                    
        landlord = db.landlords.find_one({"code": body.code})
        if landlord is None:
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
        
        fullName = f"{idinfo.get('given_name', '')} {idinfo.get('family_name', '')}"
        landlordName = f"{landlord.get('first_name', '')} {landlord.get('last_name', '')}".strip()
        
        if result.modified_count == 0:
            message = f"Welcome back! You are already enrolled in {landlordName}'s community as {fullName}."
        else:
            message = f"Success! You enrolled in {landlordName}'s community as {fullName}."
            
        onboarded = user_is_onboarded(landlord)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error during sign-in: {exc}") from exc
        
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
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
    landlord_name = ""
    tenant_name = ""
    landlord_code = ""
    doesTenantExist = False
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]    
        landlords = db.landlords.find()
        for landlord in landlords:
            for tenant in landlord.get("tenants"):
                if tenant["email"] == email:
                    doesTenantExist = True
                    landlord_name = f"{landlord.get('first_name')} {landlord.get('last_name')}"
                    tenant_name = f"{tenant['first_name']} {tenant['last_name']}"
                    landlord_code = landlord.get("code")
                    message = f"Signed in as {tenant_name} in {landlord_name}'s community"
                    
        if not doesTenantExist:
            raise HTTPException(status_code=404, detail="Tenant's account does not exist. Try signing up with your landlord's code.")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error during sign-in: {exc}") from exc
        
    return {
        "message": message,
        "email": email,
        "landlord_name": landlord_name,
        "tenant_name": tenant_name,
        "landlord_code": landlord_code,
        "token": body.token,
    }

@app.get("/api/config")
def get_config():
    client_id = _google_client_id()
    if not client_id:
        raise HTTPException(status_code=500, detail="Google Client ID not configured on server")
    return {"google_client_id": client_id}

@router.post("/get-landlord-data")
def get_landlord_data(body: GoogleTokenBody):
    idinfo = verifyGoogleID(body.token)
    email = idinfo.get("email")
    tenants = []
    name = ""
    message = ""
    try:
        db = MongoClient(os.environ.get("MONGO_CLIENT_ID", "").strip())["keyfolio"]      
        user = db.landlords.find_one({"email": email})
        if user is None:
            raise HTTPException(status_code=404, detail="Could not authenticate. Please try signing in again.")
        else:
            name = f"{user.get('first_name')} {user.get('last_name')}"
            tenants = user.get("tenants")
            message = f"Welcome back {name}"
        onboarded = user_is_onboarded(user)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database error during sign-in: {exc}") from exc
        
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
