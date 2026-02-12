"""
✝ THE FALLEN ✝ — Web Dashboard
Main application. Connects to the same PostgreSQL database as the Discord bot.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from db import db
import auth


# ==========================================
# APP LIFECYCLE
# ==========================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    await db.connect()
    print("✝ THE FALLEN ✝ Dashboard is live!")
    yield
    await db.close()
    print("Dashboard shutting down.")


app = FastAPI(title="The Fallen Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ==========================================
# TEMPLATE HELPERS
# ==========================================

def _base_context(request: Request) -> dict:
    """Base context passed to every template."""
    user = auth.get_session(request)
    return {
        "request": request,
        "user": user,
        "is_staff": user.get("is_staff", False) if user else False,
    }


def _format_number(n) -> str:
    """Format large numbers with commas."""
    if n is None:
        return "0"
    return f"{int(n):,}"


def _format_voice_time(seconds) -> str:
    """Format seconds into readable time."""
    if not seconds:
        return "0m"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _elo_rank(elo: int) -> tuple:
    """Return (name, emoji) for an ELO rating."""
    if elo >= 2000: return ("Grandmaster", "🏆")
    if elo >= 1800: return ("Diamond", "💎")
    if elo >= 1600: return ("Platinum", "🥇")
    if elo >= 1400: return ("Gold", "🥈")
    if elo >= 1200: return ("Silver", "🥉")
    return ("Bronze", "⚔️")


def _level_progress(xp: int, level: int) -> int:
    """Calculate XP progress percentage to next level."""
    xp_for_current = level * level * 50
    xp_for_next = (level + 1) * (level + 1) * 50
    needed = xp_for_next - xp_for_current
    progress = xp - xp_for_current
    if needed <= 0:
        return 100
    return min(100, max(0, int((progress / needed) * 100)))


# Register filters for Jinja2
templates.env.filters["fnum"] = _format_number
templates.env.filters["ftime"] = _format_voice_time
templates.env.globals["elo_rank"] = _elo_rank
templates.env.globals["level_progress"] = _level_progress


# ==========================================
# AUTH ROUTES
# ==========================================

@app.get("/auth/login")
async def login(request: Request):
    """Redirect to Discord OAuth."""
    return RedirectResponse(auth.get_login_url())


@app.get("/auth/callback")
async def callback(request: Request, code: str = None, error: str = None):
    """Handle Discord OAuth callback."""
    if error or not code:
        return RedirectResponse("/?error=auth_failed")
    
    # Exchange code for token
    token_data = await auth.exchange_code(code)
    if not token_data:
        return RedirectResponse("/?error=token_failed")
    
    access_token = token_data.get("access_token")
    
    # Get Discord user info
    discord_user = await auth.get_discord_user(access_token)
    if not discord_user:
        return RedirectResponse("/?error=user_failed")
    
    # Check if user is staff by checking guild roles
    guild_id = os.getenv("GUILD_ID", "")
    is_staff = False
    role_ids = []
    
    if guild_id:
        role_ids = await auth.get_user_guild_roles(access_token, guild_id)
    
    # Build session data
    avatar_hash = discord_user.get("avatar")
    user_id = discord_user["id"]
    
    if avatar_hash:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
    else:
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{int(user_id) % 5}.png"
    
    session_data = {
        "id": int(user_id),
        "username": discord_user.get("global_name") or discord_user.get("username", "Unknown"),
        "avatar": avatar_url,
        "is_staff": is_staff,  # We'll enhance this with role checking
        "role_ids": role_ids,
    }
    
    # Check database for this user
    db_user = await db.get_user(int(user_id))
    if db_user:
        session_data["level"] = db_user.get("level", 0)
    
    response = RedirectResponse("/profile")
    auth.set_session(response, session_data)
    return response


@app.get("/auth/logout")
async def logout():
    """Clear session and redirect home."""
    response = RedirectResponse("/")
    auth.clear_session(response)
    return response


# ==========================================
# PUBLIC ROUTES
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Home page with server overview."""
    ctx = _base_context(request)
    
    try:
        ctx["stats"] = await db.get_server_stats()
        ctx["top_players"] = await db.get_leaderboard("xp", limit=5)
        ctx["war_record"] = await db.get_war_record()
    except Exception as e:
        print(f"[HOME] Database error: {e}")
        ctx["stats"] = {}
        ctx["top_players"] = []
        ctx["war_record"] = {"total": 0, "wins": 0, "losses": 0, "draws": 0}
    
    return templates.TemplateResponse("home.html", ctx)


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(
    request: Request,
    sort: str = Query("xp", description="Sort column"),
    page: int = Query(1, ge=1),
):
    """Leaderboard page with sortable columns."""
    ctx = _base_context(request)
    
    per_page = 25
    offset = (page - 1) * per_page
    
    try:
        ctx["players"] = await db.get_leaderboard(sort, limit=per_page, offset=offset)
        ctx["total_users"] = await db.get_total_users()
    except Exception as e:
        print(f"[LB] Database error: {e}")
        ctx["players"] = []
        ctx["total_users"] = 0
    
    ctx["sort"] = sort
    ctx["page"] = page
    ctx["per_page"] = per_page
    ctx["offset"] = offset
    
    return templates.TemplateResponse("leaderboard.html", ctx)


@app.get("/raids", response_class=HTMLResponse)
async def raids(request: Request):
    """Raids & Wars page."""
    ctx = _base_context(request)
    
    try:
        ctx["recent_raids"] = await db.get_recent_raids(15)
        ctx["raid_leaders"] = await db.get_raid_leaderboard(10)
        ctx["war_record"] = await db.get_war_record()
        ctx["recent_wars"] = await db.get_wars(10)
    except Exception as e:
        print(f"[RAIDS] Database error: {e}")
        ctx["recent_raids"] = []
        ctx["raid_leaders"] = []
        ctx["war_record"] = {"total": 0, "wins": 0, "losses": 0, "draws": 0}
        ctx["recent_wars"] = []
    
    return templates.TemplateResponse("raids.html", ctx)


# ==========================================
# AUTHENTICATED ROUTES
# ==========================================

@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    """Your profile page (requires login)."""
    ctx = _base_context(request)
    
    if not ctx["user"]:
        return RedirectResponse("/auth/login")
    
    user_id = ctx["user"]["id"]
    
    try:
        ctx["profile"] = await db.get_user(user_id)
        ctx["xp_rank"] = await db.get_user_rank(user_id, "xp")
        ctx["elo_rank_pos"] = await db.get_user_rank(user_id, "elo_rating")
        ctx["applications"] = await db.get_user_applications(user_id)
    except Exception as e:
        print(f"[PROFILE] Database error: {e}")
        ctx["profile"] = None
        ctx["xp_rank"] = 0
        ctx["elo_rank_pos"] = 0
        ctx["applications"] = []
    
    return templates.TemplateResponse("profile.html", ctx)


# ==========================================
# STAFF ROUTES
# ==========================================

@app.get("/staff", response_class=HTMLResponse)
async def staff_dashboard(request: Request):
    """Staff dashboard (requires staff role)."""
    ctx = _base_context(request)
    
    if not ctx["user"] or not ctx["is_staff"]:
        return RedirectResponse("/?error=unauthorized")
    
    try:
        ctx["stats"] = await db.get_server_stats()
        ctx["recent_warnings"] = await db.get_recent_warnings(20)
        ctx["open_positions"] = await db.get_open_positions()
        ctx["pending_apps"] = await db.get_applications("applied", 10)
    except Exception as e:
        print(f"[STAFF] Database error: {e}")
        ctx["stats"] = {}
        ctx["recent_warnings"] = []
        ctx["open_positions"] = []
        ctx["pending_apps"] = []
    
    return templates.TemplateResponse("staff/dashboard.html", ctx)


@app.get("/staff/members", response_class=HTMLResponse)
async def staff_members(request: Request, q: str = ""):
    """Staff member lookup."""
    ctx = _base_context(request)
    
    if not ctx["user"] or not ctx["is_staff"]:
        return RedirectResponse("/?error=unauthorized")
    
    ctx["query"] = q
    ctx["results"] = []
    
    if q and len(q) >= 2:
        try:
            ctx["results"] = await db.search_users(q)
        except Exception as e:
            print(f"[STAFF-SEARCH] Error: {e}")
    
    return templates.TemplateResponse("staff/members.html", ctx)


@app.get("/staff/member/{user_id}", response_class=HTMLResponse)
async def staff_member_detail(request: Request, user_id: int):
    """Staff view of a specific member."""
    ctx = _base_context(request)
    
    if not ctx["user"] or not ctx["is_staff"]:
        return RedirectResponse("/?error=unauthorized")
    
    try:
        ctx["member"] = await db.get_user(user_id)
        ctx["warnings"] = await db.get_user_warnings(user_id)
        ctx["applications"] = await db.get_user_applications(user_id)
    except Exception as e:
        print(f"[STAFF-MEMBER] Error: {e}")
        ctx["member"] = None
        ctx["warnings"] = []
        ctx["applications"] = []
    
    return templates.TemplateResponse("staff/member_detail.html", ctx)
