"""PocketSmart: AI Budget Planner - FastAPI backend."""
import os
import json
import uuid
import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

import bcrypt
import jwt
from jwt import PyJWTError
from dotenv import load_dotenv
from PIL import Image
from fastapi import (FastAPI, HTTPException, Depends, File, UploadFile, Form,
                     Request, status)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import (RegisterUser, UserInDB, Token, UserSession, HomeBudgetInput,
                    PartyBudgetInput, JewelryBudgetInput)
from gemini_utils import (get_home_recommendations, get_party_recommendations,
                          get_jewelry_recommendations)

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# FastAPI app initialization
app = FastAPI(title="PocketSmart: AI Budget Planner")

SECRET_KEY = os.getenv("SECRET_KEY", "your_secret_key")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files and templates
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

# ---------------------------------------------------------------------------
# Simple JSON-file persistence (users + history) and in-memory sessions
# ---------------------------------------------------------------------------
USERS_FILE = os.path.join(DATA_DIR, "users.json")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
_lock = threading.Lock()


def _load(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _save(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


users_db: Dict[str, Dict[str, Any]] = _load(USERS_FILE, {})
user_recommendations: Dict[str, list] = _load(HISTORY_FILE, {})
active_sessions: Dict[str, UserSession] = {}
blacklisted_tokens: set = set()


def now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def authenticate_user(db: Dict[str, Any], username: str, password: str) -> Optional[UserInDB]:
    data = db.get(username.lower())
    if not data or not verify_password(password, data["hashed_password"]):
        return None
    return UserInDB(**data)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = data.copy()
    payload["exp"] = now() + (expires_delta or timedelta(minutes=15))
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def get_token(request: Request) -> Optional[str]:
    """Read the JWT from the httpOnly cookie or the Authorization header."""
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    return token


async def get_current_user(request: Request, token: Optional[str]) -> Optional[UserInDB]:
    if not token or token in blacklisted_tokens:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except PyJWTError:
        return None
    username = payload.get("sub")
    data = users_db.get(username) if username else None
    if not data:
        return None
    # Recreate the session if the server restarted
    session = active_sessions.get(username)
    if session is None:
        session = UserSession(username=username, login_time=now(), last_activity=now(), token=token)
        active_sessions[username] = session
    session.last_activity = now()
    return UserInDB(**data)


async def get_current_active_user(request: Request) -> UserInDB:
    token = await get_token(request)
    user = await get_current_user(request, token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    if user.disabled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Redirect unauthenticated page loads to /login; return JSON for API calls."""
    page_routes = {"/dashboard", "/home-planner", "/party-planner", "/jewelry-planner", "/history"}
    if exc.status_code == 401 and request.method == "GET" and request.url.path in page_routes:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


def save_to_history(username: str, recommendation_type: str, input_data: dict, result: dict) -> str:
    rec_id = str(uuid.uuid4())
    entry = {
        "id": rec_id,
        "timestamp": now().isoformat(),
        "username": username,
        "recommendation_type": recommendation_type,
        "input_data": input_data,
        "summary": {"total_budget": result.get("total_budget"),
                    "remaining_budget": result.get("remaining_budget"),
                    "categories": [c.get("category") for c in result.get("budget_breakdown", [])]},
        "full_result": result,
    }
    with _lock:
        user_recommendations.setdefault(username, []).append(entry)
        _save(HISTORY_FILE, user_recommendations)
    return rec_id


def save_upload_file(upload: UploadFile, content: bytes) -> str:
    if not (upload.content_type or "").startswith("image/"):
        raise HTTPException(400, "Please upload an image file (PNG, JPG, WEBP).")
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image is too large (max 8 MB).")
    ext = os.path.splitext(upload.filename or "")[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".png"
    name = f"{now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as f:
        f.write(content)
    try:
        with Image.open(path) as im:
            im.verify()
    except Exception:
        os.remove(path)
        raise HTTPException(400, "The uploaded file is not a valid image.")
    return path


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page"""
    return templates.TemplateResponse(request, "index.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page"""
    token = await get_token(request)
    if await get_current_user(request, token):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve the registration page"""
    token = await get_token(request)
    if await get_current_user(request, token):
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    return templates.TemplateResponse(request, "register.html", {"request": request})


# ---------------------------------------------------------------------------
# Auth endpoints
# ---------------------------------------------------------------------------
@app.post("/register")
async def register(user: RegisterUser):
    """Register a new user with a securely hashed password"""
    key = user.username.lower()
    with _lock:
        if key in users_db:
            raise HTTPException(400, "Username already registered")
        if any(u["email"].lower() == user.email.lower() for u in users_db.values()):
            raise HTTPException(400, "Email already registered")
        users_db[key] = {"username": key, "email": user.email, "full_name": user.full_name,
                         "hashed_password": hash_password(user.password), "disabled": False}
        _save(USERS_FILE, users_db)
    return {"message": "Registration successful"}


@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    """Login endpoint to get access token"""
    user = authenticate_user(users_db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password",
                            headers={"WWW-Authenticate": "Bearer"})
    access_token = create_access_token(
        data={"sub": user.username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))

    existing_user_data: Dict[str, Any] = {}
    if user.username in active_sessions:
        existing_user_data = active_sessions[user.username].user_data
        blacklisted_tokens.add(active_sessions[user.username].token)
    active_sessions[user.username] = UserSession(
        username=user.username, login_time=now(), last_activity=now(),
        token=access_token, user_data=existing_user_data)

    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(key="access_token", value=access_token, httponly=True,
                        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60, samesite="lax")
    return response


@app.post("/logout")
async def logout(request: Request):
    """Logout user by blacklisting their token and clearing session"""
    token = await get_token(request)
    if token:
        blacklisted_tokens.add(token)
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
            if username and username in active_sessions:
                del active_sessions[username]
        except PyJWTError:
            pass
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="access_token")
    return response


@app.get("/logout")
async def logout_get(request: Request):
    return await logout(request)


# ---------------------------------------------------------------------------
# Session endpoints
# ---------------------------------------------------------------------------
@app.get("/session-info")
async def get_session_info(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
    """Get current user's session information"""
    if current_user.username in active_sessions:
        session = active_sessions[current_user.username]
        return {
            "username": session.username,
            "login_time": session.login_time,
            "last_activity": session.last_activity,
            "session_duration": (now() - session.login_time).total_seconds() // 60,  # minutes
            "user_data": session.user_data,
        }
    raise HTTPException(status_code=404, detail="No active session found")


@app.post("/session-data")
async def update_session_data(data: Dict[str, Any], request: Request,
                              current_user: UserInDB = Depends(get_current_active_user)):
    """Update user's session data"""
    if current_user.username in active_sessions:
        s = active_sessions[current_user.username]
        s.user_data.update(data)
        s.last_activity = now()
        return {"message": "Session data updated", "data": s.user_data}
    raise HTTPException(status_code=404, detail="No active session found")


# ---------------------------------------------------------------------------
# Authenticated pages
# ---------------------------------------------------------------------------
def _page(name: str):
    async def handler(request: Request, current_user: UserInDB = Depends(get_current_active_user)):
        return templates.TemplateResponse(request, name, {"request": request, "user": current_user})
    return handler


app.get("/dashboard", response_class=HTMLResponse)(_page("dashboard.html"))
app.get("/home-planner", response_class=HTMLResponse)(_page("home_planner.html"))
app.get("/party-planner", response_class=HTMLResponse)(_page("party_planner.html"))
app.get("/jewelry-planner", response_class=HTMLResponse)(_page("jewelry_planner.html"))
app.get("/history", response_class=HTMLResponse)(_page("history.html"))


# ---------------------------------------------------------------------------
# Planner endpoints (/generate-* are aliases of the *-budget routes)
# ---------------------------------------------------------------------------
def _remember(username: str, key: str, payload: dict):
    if username in active_sessions:
        active_sessions[username].user_data[key] = {"timestamp": now().isoformat(), **payload}


@app.post("/home-budget")
@app.post("/generate-home")
async def plan_home_budget(budget_input: HomeBudgetInput, request: Request,
                           current_user: UserInDB = Depends(get_current_active_user)):
    """Generate home budget recommendations"""
    _remember(current_user.username, "last_home_budget", {
        "budget": budget_input.total_budget,
        "requirements": {"lights": budget_input.num_lights, "fans": budget_input.num_fans,
                         "furniture": budget_input.num_furniture,
                         "dining_tables": budget_input.num_dining_tables}})
    result = await run_in_threadpool(get_home_recommendations, budget_input)
    rooms = [n for n, f in (("Living Room", budget_input.has_living_room),
                            ("Kitchen", budget_input.has_kitchen),
                            ("Bedroom", budget_input.has_bedroom)) if f]
    input_data = budget_input.model_dump()
    input_data["rooms"] = rooms
    result["id"] = save_to_history(current_user.username, "home", input_data, result)
    return result


@app.post("/party-budget")
@app.post("/generate-party")
async def plan_party_budget(budget_input: PartyBudgetInput, request: Request,
                            current_user: UserInDB = Depends(get_current_active_user)):
    """Generate party budget recommendations"""
    _remember(current_user.username, "last_party_budget", {
        "budget": budget_input.total_budget, "party_type": budget_input.party_type,
        "guests": budget_input.num_guests})
    result = await run_in_threadpool(get_party_recommendations, budget_input)
    input_data = budget_input.model_dump()
    input_data["needs"] = [n for n, f in (("Catering", budget_input.needs_catering),
                                          ("Decoration", budget_input.needs_decoration),
                                          ("Entertainment", budget_input.needs_entertainment)) if f]
    result["id"] = save_to_history(current_user.username, "party", input_data, result)
    return result


@app.post("/jewelry-budget")
@app.post("/generate-jewelry")
async def plan_jewelry_budget(
    request: Request,
    total_budget: float = Form(...),
    occasion: str = Form(...),
    preferences: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    current_user: UserInDB = Depends(get_current_active_user),
):
    """Generate jewelry budget recommendations with optional outfit image"""
    if total_budget <= 0:
        raise HTTPException(400, "Budget must be greater than zero.")
    budget_input = JewelryBudgetInput(total_budget=total_budget, occasion=occasion.strip() or "General",
                                      preferences=preferences)
    image_path = None
    has_image = bool(image and image.filename)
    if has_image:
        image_path = save_upload_file(image, await image.read())

    _remember(current_user.username, "last_jewelry_budget", {
        "budget": budget_input.total_budget, "occasion": budget_input.occasion, "has_image": has_image})
    result = await run_in_threadpool(get_jewelry_recommendations, budget_input, image_path)

    input_data = budget_input.model_dump()
    input_data["has_image"] = has_image
    if has_image:
        input_data["image"] = image.filename
    result["id"] = save_to_history(current_user.username, "jewelry", input_data, result)
    return result


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
@app.get("/recommendation-history")
async def get_recommendation_history(request: Request,
                                     current_user: UserInDB = Depends(get_current_active_user)):
    """Get the user's recommendation history (newest first)"""
    items = user_recommendations.get(current_user.username, [])
    history = sorted(items, key=lambda x: x["timestamp"], reverse=True)
    return {"history": [{"id": i["id"], "timestamp": i["timestamp"], "type": i["recommendation_type"],
                         "input": i["input_data"], "summary": i["summary"]} for i in history]}


@app.get("/recommendation-details/{recommendation_id}")
async def get_recommendation_details(recommendation_id: str, request: Request,
                                     current_user: UserInDB = Depends(get_current_active_user)):
    """Get the full details of a specific recommendation"""
    for item in user_recommendations.get(current_user.username, []):
        if item["id"] == recommendation_id:
            return {"id": item["id"], "timestamp": item["timestamp"], "type": item["recommendation_type"],
                    "input": item["input_data"], "full_result": item["full_result"]}
    raise HTTPException(status_code=404, detail="Recommendation not found")


# ---------------------------------------------------------------------------
# Startup: background cleanup of expired sessions
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def setup_session_cleanup():
    """Background task to clean up expired sessions"""
    async def cleanup_expired_sessions():
        while True:
            current_time = now()
            expired = [u for u, s in active_sessions.items()
                       if (current_time - s.last_activity).total_seconds() > 1800]
            for username in expired:
                print(f"Removing expired session for {username}")
                active_sessions.pop(username, None)
            await asyncio.sleep(300)

    asyncio.create_task(cleanup_expired_sessions())


# Main entry point
if __name__ == "__main__":
    import uvicorn
    print("Starting PocketSmart: AI Budget Planner...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
