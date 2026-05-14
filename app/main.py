import json
import random
import shutil
import os
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import engine, get_db, Base
from models import User, Recipe
from schemas import UserCreate, RecipeCreate, RecipeUpdate, RecipeOut
from passlib.context import CryptContext
from itsdangerous import URLSafeTimedSerializer, BadSignature
import uuid

# --- setup ---
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Recipe Rotator")

# Disable caching for static files (CSS, texts, JS) so edits apply immediately
class NoCacheStaticMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheStaticMiddleware)

# Static files (CSS, texts, images, JS)
STATIC_DIR = Path(__file__).parent / "frontend" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Uploads directory for recipe images
UPLOADS_DIR = Path(__file__).parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Jinja2 templates
TEMPLATES_DIR = Path(__file__).parent / "frontend" / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

SECRET_KEY = "super-secret-key-change-in-production"
serializer = URLSafeTimedSerializer(SECRET_KEY)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- texts loader (re-reads JSON on every request, no restart needed) ---
TEXTS_PATH = STATIC_DIR / "texts.json"  # STATIC_DIR already points to frontend/static

def load_texts() -> dict:
    with open(TEXTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def T(key: str, **kwargs) -> str:
    """Get a translated string and format it with optional kwargs."""
    texts = load_texts()
    value = texts.get(key, key)
    if kwargs:
        value = value.format(**kwargs)
    return value

# --- password helpers ---
def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    return pwd_context.verify(password, hashed)

# --- auth helpers ---
def create_session_token(user_id: int) -> str:
    return serializer.dumps({"user_id": user_id})

def get_user_from_token(token: str, db: Session):
    try:
        data = serializer.loads(token, max_age=86400 * 7)
        user = db.query(User).filter(User.id == data["user_id"]).first()
        return user
    except (BadSignature, KeyError):
        return None

def get_current_user(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session")
    if not token:
        return None
    return get_user_from_token(token, db)

# --- template context helper ---
def ctx(request: Request, user=None, **extra) -> dict:
    """Build a template context dict with texts, user, and request."""
    return {"request": request, "texts": load_texts(), "user": user, **extra}

# --- image upload helper ---
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

def save_uploaded_image(file: UploadFile) -> str:
    """Save uploaded file to uploads dir and return the URL path. Returns empty string if no file."""
    if not file or not file.filename:
        return ""
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return ""
    # Generate unique filename to avoid collisions
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = UPLOADS_DIR / unique_name
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return f"/uploads/{unique_name}"

def delete_image(image_url: str):
    """Delete an uploaded image file by its URL."""
    if not image_url or not image_url.startswith("/uploads/"):
        return
    filename = image_url.replace("/uploads/", "")
    file_path = UPLOADS_DIR / filename
    if file_path.exists():
        file_path.unlink()

# =============================================
# AUTH PAGES
# =============================================

@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return templates.TemplateResponse("auth.html", ctx(request,
        form_title=T("register_title"),
        form_action="/register",
        label_username=T("label_username"),
        label_password=T("label_password"),
        btn_submit=T("btn_register"),
        btn_class="btn-success",
        bottom_link=T("register_has_account"),
    ))


@app.post("/register")
def register(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(username=username, hashed_password=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_session_token(user.id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(key="session", value=token, httponly=True, max_age=86400 * 7, samesite="lax", path="/")
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("auth.html", ctx(request,
        form_title=T("login_title"),
        form_action="/login",
        label_username=T("label_username"),
        label_password=T("label_password"),
        btn_submit=T("btn_login"),
        btn_class="btn-primary",
        bottom_link=T("login_no_account"),
    ))


@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_session_token(user.id)
    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(key="session", value=token, httponly=True, max_age=86400 * 7, samesite="lax", path="/")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("session")
    return resp

# =============================================
# MAIN PAGE (landing + random recipe)
# =============================================

@app.get("/debug")
def debug_session(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("session")
    user = get_current_user(request, db)
    return {"token_present": bool(token), "token_value": token[:40] + "..." if token else None, "user": user.username if user else None, "cookies": dict(request.cookies)}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)

    if not user:
        return templates.TemplateResponse("index.html", ctx(request,
            hero_title=T("hero_title"),
            hero_subtitle=T("hero_subtitle"),
            hero_cta_start=T("hero_cta_start"),
            hero_cta_login=T("hero_cta_login"),
        ))

    recipe = db.query(Recipe).filter(Recipe.user_id == user.id).order_by(func.random()).first()

    if not recipe:
        return templates.TemplateResponse("index.html", ctx(request, user=user,
            no_recipes_yet=T("no_recipes_yet"),
            no_recipes_hint=T("no_recipes_hint"),
            btn_add_recipe=T("btn_add_recipe"),
        ))

    return templates.TemplateResponse("index.html", ctx(request, user=user,
        recipe=recipe,
        today_recipe=T("today_recipe"),
        ingredients=T("ingredients"),
        instructions=T("instructions"),
        btn_details=T("btn_details"),
        added_on=T("added_on"),
        btn_another=T("btn_another"),
    ))

# =============================================
# RECIPE LIST
# =============================================

@app.get("/recipes", response_class=HTMLResponse)
def recipe_list(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    recipes = db.query(Recipe).filter(Recipe.user_id == user.id).order_by(Recipe.created_at.desc()).all()

    return templates.TemplateResponse("recipes.html", ctx(request, user=user,
        recipes=recipes,
        all_recipes_count=T("all_recipes_count", count=len(recipes)),
        btn_new_recipe=T("btn_new_recipe"),
        btn_open=T("btn_open"),
        no_recipes_list=T("no_recipes_list"),
    ))

# =============================================
# CREATE RECIPE (MUST be before /recipes/{recipe_id})
# =============================================

@app.get("/recipes/new", response_class=HTMLResponse)
def new_recipe_form(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    return templates.TemplateResponse("recipe_form.html", ctx(request, user=user,
        form_title=T("new_recipe_title"),
        form_action="/api/recipes",
        label_dish_name=T("label_dish_name"),
        label_ingredients=T("label_ingredients"),
        label_instructions=T("label_instructions"),
        label_image_url=T("label_image_url"),
        placeholder_image_url=T("placeholder_image_url"),
        btn_cancel=T("btn_cancel"),
        btn_save=T("btn_save"),
        cancel_url="/recipes",
    ))

# =============================================
# SINGLE RECIPE VIEW
# =============================================

@app.get("/recipes/{recipe_id}", response_class=HTMLResponse)
def recipe_detail(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    recipe = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user.id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return templates.TemplateResponse("recipe_detail.html", ctx(request, user=user,
        recipe=recipe,
        ingredients=T("ingredients"),
        instructions=T("instructions"),
        btn_edit=T("btn_edit"),
        btn_delete=T("btn_delete"),
        btn_back=T("btn_back"),
    ))

# =============================================
# EDIT RECIPE
# =============================================

@app.get("/recipes/{recipe_id}/edit", response_class=HTMLResponse)
def edit_recipe_form(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)

    recipe = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user.id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")

    return templates.TemplateResponse("recipe_form.html", ctx(request, user=user,
        recipe=recipe,
        form_title=T("edit_recipe_title"),
        form_action=f"/api/recipes/{recipe_id}/update",
        label_dish_name=T("label_dish_name"),
        label_ingredients=T("label_ingredients"),
        label_instructions=T("label_instructions"),
        label_image_url=T("label_image_url_edit"),
        placeholder_image_url=T("placeholder_image_url"),
        btn_cancel=T("btn_cancel"),
        btn_save=T("btn_save"),
        cancel_url=f"/recipes/{recipe_id}",
    ))

# =============================================
# API ENDPOINTS
# =============================================

@app.get("/api/recipes", response_model=list[RecipeOut])
def api_get_recipes(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return db.query(Recipe).filter(Recipe.user_id == user.id).order_by(Recipe.created_at.desc()).all()


@app.get("/api/recipes/random", response_model=RecipeOut)
def api_get_random(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    recipe = db.query(Recipe).filter(Recipe.user_id == user.id).order_by(func.random()).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="No recipes")
    return recipe


@app.post("/api/recipes")
async def api_create_recipe(
    title: str = Form(...),
    ingredients: str = Form(...),
    instructions: str = Form(...),
    image: UploadFile = File(None),
    request: Request = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    image_url = save_uploaded_image(image)
    recipe = Recipe(
        title=title,
        ingredients=ingredients,
        instructions=instructions,
        image_url=image_url,
        user_id=user.id,
    )
    db.add(recipe)
    db.commit()
    db.refresh(recipe)
    resp = RedirectResponse(url=f"/recipes/{recipe.id}", status_code=302)
    return resp


@app.post("/api/recipes/{recipe_id}/update")
async def api_update_recipe(
    recipe_id: int,
    title: str = Form(...),
    ingredients: str = Form(...),
    instructions: str = Form(...),
    image: UploadFile = File(None),
    request: Request = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user.id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    recipe.title = title
    recipe.ingredients = ingredients
    recipe.instructions = instructions

    # If a new image was uploaded, replace the old one
    if image and image.filename:
        # Delete old uploaded image if it was a local upload
        delete_image(recipe.image_url)
        recipe.image_url = save_uploaded_image(image)

    db.commit()
    db.refresh(recipe)
    resp = RedirectResponse(url=f"/recipes/{recipe_id}", status_code=302)
    return resp


@app.delete("/api/recipes/{recipe_id}")
def api_delete_recipe(recipe_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id, Recipe.user_id == user.id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    # Delete associated image if it's a local upload
    delete_image(recipe.image_url)
    db.delete(recipe)
    db.commit()
    return {"detail": "deleted"}