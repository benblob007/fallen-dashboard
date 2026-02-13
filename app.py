"""
✝ THE FALLEN ✝ — Web Dashboard
Main application with role-based staff access, auth debugging, and proper error handling.
"""

import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from db import db
import auth


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    print("✝ THE FALLEN ✝ Dashboard is live!")
    # Log config on startup
    staff_roles = auth.get_staff_role_ids()
    admin_ids = auth.get_admin_user_ids()
    guild_id = os.getenv("GUILD_ID", "NOT SET")
    print(f"[CONFIG] GUILD_ID: {guild_id}")
    print(f"[CONFIG] STAFF_ROLE_IDS: {staff_roles or 'NOT SET — staff panel disabled'}")
    print(f"[CONFIG] ADMIN_USER_IDS: {admin_ids or 'NOT SET — no override'}")
    yield
    await db.close()


app = FastAPI(title="The Fallen Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ==========================================
# TEMPLATE HELPERS
# ==========================================

def _base_context(request: Request) -> dict:
    user = auth.get_session(request)
    return {
        "request": request,
        "user": user,
        "is_staff": user.get("is_staff", False) if user else False,
    }


def _format_number(n) -> str:
    if n is None: return "0"
    return f"{int(n):,}"


def _format_voice_time(seconds) -> str:
    if not seconds: return "0m"
    seconds = int(seconds)
    h, m = seconds // 3600, (seconds % 3600) // 60
    return f"{h}h {m}m" if h > 0 else f"{m}m"


def _elo_rank(elo) -> tuple:
    elo = int(elo or 1000)
    if elo >= 2000: return ("Grandmaster", "🏆")
    if elo >= 1800: return ("Diamond", "💎")
    if elo >= 1600: return ("Platinum", "🥇")
    if elo >= 1400: return ("Gold", "🥈")
    if elo >= 1200: return ("Silver", "🥉")
    return ("Bronze", "⚔️")


def _level_progress(xp, level) -> int:
    xp, level = xp or 0, level or 0
    xp_for_current = level * level * 50
    xp_for_next = (level + 1) * (level + 1) * 50
    needed = xp_for_next - xp_for_current
    if needed <= 0: return 100
    return min(100, max(0, int(((xp - xp_for_current) / needed) * 100)))


templates.env.filters["fnum"] = _format_number
templates.env.filters["ftime"] = _format_voice_time
templates.env.globals["elo_rank"] = _elo_rank
templates.env.globals["level_progress"] = _level_progress


# ==========================================
# AUTH ROUTES
# ==========================================

@app.get("/auth/login")
async def login():
    return RedirectResponse(auth.get_login_url())


@app.get("/auth/callback")
async def callback(request: Request, code: str = None, error: str = None):
    """Handle Discord OAuth callback with full staff detection."""
    if error or not code:
        print(f"[AUTH] Callback error: {error}")
        return RedirectResponse("/?error=auth_failed")
    
    # Step 1: Exchange code for token
    token_data = await auth.exchange_code(code)
    if not token_data:
        return RedirectResponse("/?error=token_failed")
    
    access_token = token_data.get("access_token")
    
    # Step 2: Get Discord user info
    discord_user = await auth.get_discord_user(access_token)
    if not discord_user:
        return RedirectResponse("/?error=user_failed")
    
    user_id = discord_user["id"]
    user_id_int = int(user_id)
    
    # Step 3: Get guild member data (roles)
    guild_id = os.getenv("GUILD_ID", "")
    role_ids = []
    nick = None
    
    if guild_id:
        member_data = await auth.get_user_guild_member(access_token, guild_id)
        if member_data:
            role_ids = member_data.get("roles", [])
            nick = member_data.get("nick")
        else:
            print(f"[AUTH] ⚠️ Could not fetch guild member for {user_id} — they may not be in the server")
    else:
        print(f"[AUTH] ⚠️ GUILD_ID not set — cannot check roles")
    
    # Step 4: Check staff status
    is_staff = auth.check_is_staff(user_id_int, role_ids)
    
    # Step 5: Build avatar URL
    avatar_hash = discord_user.get("avatar")
    if avatar_hash:
        avatar_url = f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
    else:
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{user_id_int % 5}.png"
    
    # Step 6: Build session
    session_data = {
        "id": user_id_int,
        "username": nick or discord_user.get("global_name") or discord_user.get("username", "Unknown"),
        "discord_username": discord_user.get("username", "Unknown"),
        "avatar": avatar_url,
        "is_staff": is_staff,
        "role_ids": role_ids,
    }
    
    # Step 7: Merge bot data
    db_user = await db.get_user(user_id_int)
    if db_user:
        session_data["level"] = db_user.get("level", 0)
        session_data["roblox_username"] = db_user.get("roblox_username")
    
    print(f"[AUTH] ✅ Login complete: {session_data['username']} (staff={is_staff}, roles={len(role_ids)})")
    
    response = RedirectResponse("/profile")
    auth.set_session(response, session_data)
    return response


@app.get("/auth/logout")
async def logout():
    response = RedirectResponse("/")
    auth.clear_session(response)
    return response


@app.get("/auth/debug", response_class=HTMLResponse)
async def auth_debug(request: Request):
    """Debug endpoint - shows your session data and auth config.
    Useful for finding your role IDs to set STAFF_ROLE_IDS.
    """
    ctx = _base_context(request)
    session = auth.get_session(request)
    
    config_info = {
        "GUILD_ID": os.getenv("GUILD_ID", "NOT SET"),
        "STAFF_ROLE_IDS": os.getenv("STAFF_ROLE_IDS", "NOT SET"),
        "ADMIN_USER_IDS": os.getenv("ADMIN_USER_IDS", "NOT SET") if ctx.get("is_staff") else "HIDDEN",
        "DASHBOARD_URL": os.getenv("DASHBOARD_URL", "NOT SET"),
    }
    
    ctx["session"] = session
    ctx["config"] = config_info
    return templates.TemplateResponse("auth_debug.html", ctx)


# ==========================================
# PUBLIC ROUTES
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    ctx = _base_context(request)
    try:
        ctx["stats"] = await db.get_server_stats()
        ctx["top_players"] = await db.get_leaderboard("xp", limit=5)
        ctx["war_record"] = await db.get_war_record()
        ctx["roster"] = await db.get_roster()
    except Exception as e:
        print(f"[HOME] Database error: {e}")
        ctx["stats"] = {}
        ctx["top_players"] = []
        ctx["war_record"] = {"total": 0, "wins": 0, "losses": 0, "draws": 0}
        ctx["roster"] = []
    return templates.TemplateResponse("home.html", ctx)


@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request, sort: str = Query("xp"), page: int = Query(1, ge=1)):
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
    ctx.update({"sort": sort, "page": page, "per_page": per_page, "offset": offset})
    return templates.TemplateResponse("leaderboard.html", ctx)


@app.get("/raids", response_class=HTMLResponse)
async def raids(request: Request):
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
    ctx = _base_context(request)
    if not ctx["user"] or not ctx["is_staff"]:
        return RedirectResponse("/?error=unauthorized")
    try:
        ctx["member"] = await db.get_user(user_id)
        ctx["warn_data"] = await db.get_user_warnings(user_id)
        ctx["applications"] = await db.get_user_applications(user_id)
    except Exception as e:
        print(f"[STAFF-MEMBER] Error: {e}")
        ctx["member"] = None
        ctx["warn_data"] = {"warnings": [], "total_points": 0}
        ctx["applications"] = []
    return templates.TemplateResponse("staff/member_detail.html", ctx)
