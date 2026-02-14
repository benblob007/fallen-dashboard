"""
✝ THE FALLEN ✝ — Web Dashboard (v3)
Full-featured dashboard with auto-role config, staff management, moderation panel.
"""

import os, time
from contextlib import asynccontextmanager
from collections import defaultdict
from fastapi import FastAPI, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from db import db, WARNING_CATEGORIES
import auth


# ==========================================
# RATE LIMITING MIDDLEWARE
# ==========================================
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests=60, window=60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window = window
        self.requests = defaultdict(list)

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/static"):
            return await call_next(request)
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
        if len(self.requests[ip]) >= self.max_requests:
            return JSONResponse({"error": "Rate limited"}, status_code=429)
        self.requests[ip].append(now)
        return await call_next(request)


# ==========================================
# APP SETUP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    staff_roles = auth.get_staff_role_ids()
    admin_ids = auth.get_admin_user_ids()
    print(f"✝ THE FALLEN ✝ Dashboard live!")
    print(f"[CONFIG] GUILD_ID: {os.getenv('GUILD_ID', 'NOT SET')}")
    print(f"[CONFIG] STAFF_ROLE_IDS: {staff_roles or 'NOT SET'}")
    print(f"[CONFIG] ADMIN_USER_IDS: {admin_ids or 'NOT SET'}")
    yield
    await db.close()

app = FastAPI(title="The Fallen Dashboard", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware, max_requests=120, window=60)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ==========================================
# TEMPLATE HELPERS
# ==========================================
def _ctx(request: Request) -> dict:
    user = auth.get_session(request)
    return {
        "request": request,
        "user": user,
        "is_staff": user.get("is_staff", False) if user else False,
    }

def _fnum(n) -> str:
    if n is None: return "0"
    return f"{int(n):,}"

def _ftime(seconds) -> str:
    if not seconds: return "0m"
    s = int(seconds)
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"

def _elo_rank(elo) -> tuple:
    elo = int(elo or 1000)
    if elo >= 2000: return ("Grandmaster", "🏆", "#ffd700")
    if elo >= 1800: return ("Diamond", "💎", "#b9f2ff")
    if elo >= 1600: return ("Platinum", "🥇", "#e5e4e2")
    if elo >= 1400: return ("Gold", "🥈", "#f39c12")
    if elo >= 1200: return ("Silver", "🥉", "#95a5a6")
    return ("Bronze", "⚔️", "#cd7f32")

def _level_progress(xp, level) -> int:
    xp, level = xp or 0, level or 0
    cur = level * level * 50
    nxt = (level + 1) * (level + 1) * 50
    needed = nxt - cur
    if needed <= 0: return 100
    return min(100, max(0, int(((xp - cur) / needed) * 100)))

def _time_ago(iso_str) -> str:
    if not iso_str: return "Never"
    try:
        import datetime
        if isinstance(iso_str, str):
            dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        else:
            dt = iso_str
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = now - dt
        secs = diff.total_seconds()
        if secs < 60: return "Just now"
        if secs < 3600: return f"{int(secs//60)}m ago"
        if secs < 86400: return f"{int(secs//3600)}h ago"
        return f"{int(secs//86400)}d ago"
    except:
        return str(iso_str)[:10]

templates.env.filters["fnum"] = _fnum
templates.env.filters["ftime"] = _ftime
templates.env.filters["timeago"] = _time_ago
templates.env.globals["elo_rank"] = _elo_rank
templates.env.globals["level_progress"] = _level_progress


# ==========================================
# ERROR HANDLERS
# ==========================================
@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse("error.html", {
        "request": request, "user": auth.get_session(request), "is_staff": False,
        "error_code": 404, "error_title": "Page Not Found",
        "error_msg": "The page you're looking for doesn't exist."
    }, status_code=404)

@app.exception_handler(500)
async def server_error(request: Request, exc):
    return templates.TemplateResponse("error.html", {
        "request": request, "user": auth.get_session(request), "is_staff": False,
        "error_code": 500, "error_title": "Server Error",
        "error_msg": "Something went wrong. Try again later."
    }, status_code=500)


# ==========================================
# AUTH ROUTES
# ==========================================
@app.get("/auth/login")
async def login():
    return RedirectResponse(auth.get_login_url())

@app.get("/auth/callback")
async def callback(request: Request, code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/?error=auth_failed")
    token_data = await auth.exchange_code(code)
    if not token_data:
        return RedirectResponse("/?error=token_failed")
    access_token = token_data.get("access_token")
    discord_user = await auth.get_discord_user(access_token)
    if not discord_user:
        return RedirectResponse("/?error=user_failed")
    user_id = discord_user["id"]
    uid_int = int(user_id)
    guild_id = os.getenv("GUILD_ID", "")
    role_ids = []
    nick = None
    if guild_id:
        member = await auth.get_user_guild_member(access_token, guild_id)
        if member:
            role_ids = member.get("roles", [])
            nick = member.get("nick")

    # Check staff status from multiple sources
    is_staff = auth.check_is_staff(uid_int, role_ids)
    permission_tier = 0

    # 1. Admin override (env var)
    if uid_int in auth.get_admin_user_ids():
        is_staff = True
        permission_tier = 3

    # 2. Check database staff_roles table (manual adds)
    db_is_staff, db_tier = await db.is_db_staff(uid_int)
    if db_is_staff:
        is_staff = True
        permission_tier = max(permission_tier, db_tier)

    # 3. Check role_config table (auto-role mapping)
    role_is_staff, role_tier = await db.check_role_permissions(role_ids)
    if role_is_staff:
        is_staff = True
        permission_tier = max(permission_tier, role_tier)

    # 4. Env var STAFF_ROLE_IDS fallback
    if not is_staff and auth.check_is_staff(uid_int, role_ids):
        is_staff = True
        permission_tier = max(permission_tier, 2)

    avatar_hash = discord_user.get("avatar")
    avatar_url = (f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128"
                  if avatar_hash else f"https://cdn.discordapp.com/embed/avatars/{uid_int % 5}.png")

    session = {
        "id": uid_int,
        "username": nick or discord_user.get("global_name") or discord_user.get("username", "Unknown"),
        "discord_username": discord_user.get("username", "Unknown"),
        "avatar": avatar_url,
        "is_staff": is_staff,
        "permission_tier": permission_tier,
        "role_ids": role_ids,
    }
    db_user = await db.get_user(uid_int)
    if db_user:
        session["level"] = db_user.get("level", 0)
        session["roblox_username"] = db_user.get("roblox_username")
    print(f"[AUTH] ✅ {session['username']} logged in (staff={is_staff}, tier={permission_tier}, roles={len(role_ids)})")
    response = RedirectResponse("/profile")
    auth.set_session(response, session)
    return response

@app.get("/auth/logout")
async def logout():
    response = RedirectResponse("/")
    auth.clear_session(response)
    return response

@app.get("/auth/debug", response_class=HTMLResponse)
async def auth_debug(request: Request):
    c = _ctx(request)
    c["session"] = auth.get_session(request)
    c["role_configs"] = await db.get_role_configs()
    c["staff_members"] = await db.get_staff_members()
    c["config"] = {
        "GUILD_ID": os.getenv("GUILD_ID", "NOT SET"),
        "STAFF_ROLE_IDS": os.getenv("STAFF_ROLE_IDS", "NOT SET"),
        "ADMIN_USER_IDS": os.getenv("ADMIN_USER_IDS", "NOT SET") if c.get("is_staff") else "HIDDEN",
        "DASHBOARD_URL": os.getenv("DASHBOARD_URL", "NOT SET"),
    }
    return templates.TemplateResponse("auth_debug.html", c)


# ==========================================
# PUBLIC ROUTES
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    c = _ctx(request)
    try:
        c["stats"] = await db.get_server_stats()
        c["top_players"] = await db.get_leaderboard("xp", limit=5)
        c["war_record"] = await db.get_war_record()
    except Exception as e:
        print(f"[HOME] {e}")
        c.update(stats={}, top_players=[], war_record={"total":0,"wins":0,"losses":0,"draws":0})
    return templates.TemplateResponse("home.html", c)

@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request, sort: str = Query("xp"), page: int = Query(1, ge=1)):
    c = _ctx(request)
    pp = 25
    off = (page - 1) * pp
    try:
        c["players"] = await db.get_leaderboard(sort, limit=pp, offset=off)
        c["total_users"] = await db.get_total_users()
    except Exception as e:
        print(f"[LB] {e}")
        c.update(players=[], total_users=0)
    c.update(sort=sort, page=page, per_page=pp, offset=off)
    return templates.TemplateResponse("leaderboard.html", c)

@app.get("/raids", response_class=HTMLResponse)
async def raids(request: Request):
    c = _ctx(request)
    try:
        c["recent_raids"] = await db.get_recent_raids(15)
        c["raid_leaders"] = await db.get_raid_leaderboard(10)
        c["war_record"] = await db.get_war_record()
        c["recent_wars"] = await db.get_wars(10)
    except Exception as e:
        print(f"[RAIDS] {e}")
        c.update(recent_raids=[], raid_leaders=[], war_record={"total":0,"wins":0,"losses":0,"draws":0}, recent_wars=[])
    return templates.TemplateResponse("raids.html", c)

@app.get("/duels", response_class=HTMLResponse)
async def duels(request: Request):
    c = _ctx(request)
    try:
        c["recent_duels"] = await db.get_duel_history(50)
        c["elo_top"] = await db.get_leaderboard("elo_rating", limit=10)
        c["elo_dist"] = await db.get_elo_distribution()
    except Exception as e:
        print(f"[DUELS] {e}")
        c.update(recent_duels=[], elo_top=[], elo_dist={})
    return templates.TemplateResponse("duels.html", c)

@app.get("/economy", response_class=HTMLResponse)
async def economy(request: Request):
    c = _ctx(request)
    try:
        c["eco"] = await db.get_economy_stats()
        c["shop"] = await db.get_shop_catalog()
    except Exception as e:
        print(f"[ECONOMY] {e}")
        c.update(eco={"total_coins_circulation":0,"avg_coins":0,"richest":[]}, shop=[])
    return templates.TemplateResponse("economy.html", c)

@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    c = _ctx(request)
    try:
        c["data"] = await db.get_analytics()
    except Exception as e:
        print(f"[ANALYTICS] {e}")
        c["data"] = {}
    return templates.TemplateResponse("analytics.html", c)

@app.get("/clan", response_class=HTMLResponse)
async def clan(request: Request):
    c = _ctx(request)
    try:
        c["stats"] = await db.get_server_stats()
        c["war_record"] = await db.get_war_record()
        c["roster"] = await db.get_roster_with_names()
        c["positions"] = await db.get_open_positions()
    except Exception as e:
        print(f"[CLAN] {e}")
        c.update(stats={}, war_record={"total":0,"wins":0,"losses":0,"draws":0}, roster=[], positions=[])
    return templates.TemplateResponse("clan.html", c)

@app.get("/apply", response_class=HTMLResponse)
async def apply_page(request: Request):
    c = _ctx(request)
    if not c["user"]:
        return RedirectResponse("/auth/login")
    try:
        c["positions"] = await db.get_open_positions()
        c["my_apps"] = await db.get_user_applications(c["user"]["id"])
    except Exception as e:
        print(f"[APPLY] {e}")
        c.update(positions=[], my_apps=[])
    return templates.TemplateResponse("apply.html", c)

@app.post("/apply/submit")
async def apply_submit(request: Request, position_id: int = Form(...), answers: str = Form(...)):
    user = auth.get_session(request)
    if not user:
        return RedirectResponse("/auth/login")
    ok = await db.submit_application(user["id"], position_id, answers)
    if ok:
        await db.add_audit(user["id"], user.get("username", "?"), "submitted_application",
                          target_id=position_id, details=f"Applied to position {position_id}")
    return RedirectResponse("/apply?submitted=1", status_code=303)


# ==========================================
# AUTHENTICATED ROUTES
# ==========================================
@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    c = _ctx(request)
    if not c["user"]:
        return RedirectResponse("/auth/login")
    uid = c["user"]["id"]
    try:
        c["profile"] = await db.get_user(uid)
        c["xp_rank"] = await db.get_user_rank(uid, "xp")
        c["elo_rank_pos"] = await db.get_user_rank(uid, "elo_rating")
        c["duel_history"] = await db.get_user_duel_history(uid, 10)
        c["applications"] = await db.get_user_applications(uid)
    except Exception as e:
        print(f"[PROFILE] {e}")
        c.update(profile=None, xp_rank=0, elo_rank_pos=0, duel_history=[], applications=[])
    return templates.TemplateResponse("profile.html", c)


# ==========================================
# STAFF ROUTES
# ==========================================
def _require_staff(c):
    return not c["user"] or not c["is_staff"]

@app.get("/staff", response_class=HTMLResponse)
async def staff_dashboard(request: Request):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["stats"] = await db.get_server_stats()
        c["recent_warnings"] = await db.get_recent_warnings(20)
        c["open_positions"] = await db.get_open_positions()
        c["pending_apps"] = await db.get_applications("applied", 10)
        c["recent_audit"] = await db.get_audit_log(10)
        c["guardian"] = await db.get_guardian_stats()
    except Exception as e:
        print(f"[STAFF] {e}")
        c.update(stats={}, recent_warnings=[], open_positions=[], pending_apps=[], recent_audit=[], guardian={})
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "viewed_staff_dashboard")
    return templates.TemplateResponse("staff/dashboard.html", c)

@app.get("/staff/members", response_class=HTMLResponse)
async def staff_members(request: Request, q: str = ""):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    c["query"] = q
    c["results"] = []
    if q and len(q) >= 2:
        try:
            c["results"] = await db.search_users(q)
        except Exception as e:
            print(f"[STAFF-SEARCH] {e}")
        if c["results"]:
            await db.add_audit(c["user"]["id"], c["user"].get("username","?"),
                              "searched_members", details=f"query: {q}")
    return templates.TemplateResponse("staff/members.html", c)

@app.get("/staff/member/{user_id}", response_class=HTMLResponse)
async def staff_member_detail(request: Request, user_id: int):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["member"] = await db.get_user(user_id)
        c["warn_data"] = await db.get_user_warnings(user_id)
        c["duel_history"] = await db.get_user_duel_history(user_id, 20)
        c["applications"] = await db.get_user_applications(user_id)
        c["warn_categories"] = WARNING_CATEGORIES
        c["transactions"] = await db.get_transactions(user_id, 20)
        c["action_history"] = await db.get_action_history(user_id, 15)
    except Exception as e:
        print(f"[STAFF-MEMBER] {e}")
        c.update(member=None, warn_data={"warnings":[],"total_points":0},
                 duel_history=[], applications=[], warn_categories=WARNING_CATEGORIES,
                 transactions=[], action_history=[])
    c["success"] = request.query_params.get("success", "")
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"),
                      "viewed_member", target_id=user_id)
    return templates.TemplateResponse("staff/member_detail.html", c)


# ── Staff Action POST Routes ────────────────────────────

@app.post("/staff/action/warn/{user_id}")
async def staff_action_warn(request: Request, user_id: int,
                             category: str = Form(...), reason: str = Form("")):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    await db.queue_action("warn", user_id, staff["id"], staff.get("username","?"),
                          {"category": category, "reason": reason})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_warn",
                      target_id=user_id, details=f"{category}: {reason[:100]}")
    return RedirectResponse(f"/staff/member/{user_id}?success=warn_queued", status_code=303)

@app.post("/staff/action/timeout/{user_id}")
async def staff_action_timeout(request: Request, user_id: int,
                                duration: int = Form(10), reason: str = Form("")):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    await db.queue_action("timeout", user_id, staff["id"], staff.get("username","?"),
                          {"duration_minutes": duration, "reason": reason})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_timeout",
                      target_id=user_id, details=f"{duration}m: {reason[:100]}")
    return RedirectResponse(f"/staff/member/{user_id}?success=timeout_queued", status_code=303)

@app.post("/staff/action/kick/{user_id}")
async def staff_action_kick(request: Request, user_id: int, reason: str = Form("")):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    if (staff.get("permission_tier", 0) or 0) < 2:
        return RedirectResponse(f"/staff/member/{user_id}?error=insufficient_permissions", status_code=303)
    await db.queue_action("kick", user_id, staff["id"], staff.get("username","?"),
                          {"reason": reason})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_kick",
                      target_id=user_id, details=reason[:200])
    return RedirectResponse(f"/staff/member/{user_id}?success=kick_queued", status_code=303)

@app.post("/staff/action/ban/{user_id}")
async def staff_action_ban(request: Request, user_id: int, reason: str = Form("")):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    if (staff.get("permission_tier", 0) or 0) < 3:
        return RedirectResponse(f"/staff/member/{user_id}?error=insufficient_permissions", status_code=303)
    await db.queue_action("ban", user_id, staff["id"], staff.get("username","?"),
                          {"reason": reason})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_ban",
                      target_id=user_id, details=reason[:200])
    return RedirectResponse(f"/staff/member/{user_id}?success=ban_queued", status_code=303)

@app.post("/staff/action/adjust_xp/{user_id}")
async def staff_action_xp(request: Request, user_id: int, amount: int = Form(...)):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    await db.queue_action("add_xp", user_id, staff["id"], staff.get("username","?"),
                          {"amount": amount})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_xp_adjust",
                      target_id=user_id, details=f"{amount:+d} XP")
    return RedirectResponse(f"/staff/member/{user_id}?success=xp_queued", status_code=303)

@app.post("/staff/action/adjust_coins/{user_id}")
async def staff_action_coins(request: Request, user_id: int,
                              amount: int = Form(...), reason: str = Form("")):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    await db.queue_action("add_coins", user_id, staff["id"], staff.get("username","?"),
                          {"amount": amount, "reason": reason})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_coin_adjust",
                      target_id=user_id, details=f"{amount:+d} FC: {reason[:80]}")
    return RedirectResponse(f"/staff/member/{user_id}?success=coins_queued", status_code=303)

@app.post("/staff/action/set_elo/{user_id}")
async def staff_action_elo(request: Request, user_id: int, elo: int = Form(...)):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    await db.queue_action("set_elo", user_id, staff["id"], staff.get("username","?"),
                          {"elo": elo})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_elo_set",
                      target_id=user_id, details=f"Set ELO → {elo}")
    return RedirectResponse(f"/staff/member/{user_id}?success=elo_queued", status_code=303)

@app.post("/staff/action/remove_warn/{user_id}")
async def staff_action_remove_warn(request: Request, user_id: int,
                                    warning_id: int = Form(...)):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    staff = c["user"]
    await db.queue_action("remove_warning", user_id, staff["id"], staff.get("username","?"),
                          {"warning_id": warning_id})
    await db.add_audit(staff["id"], staff.get("username","?"), "queued_remove_warn",
                      target_id=user_id, details=f"Warning #{warning_id}")
    return RedirectResponse(f"/staff/member/{user_id}?success=warn_remove_queued", status_code=303)


@app.get("/staff/audit", response_class=HTMLResponse)
async def staff_audit(request: Request):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["logs"] = await db.get_audit_log(200)
    except Exception as e:
        print(f"[AUDIT] {e}")
        c["logs"] = []
    return templates.TemplateResponse("staff/audit_log.html", c)

@app.get("/staff/analytics", response_class=HTMLResponse)
async def staff_analytics(request: Request):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["data"] = await db.get_analytics()
        c["eco"] = await db.get_economy_stats()
    except Exception as e:
        print(f"[STAFF-ANALYTICS] {e}")
        c.update(data={}, eco={})
    return templates.TemplateResponse("staff/analytics.html", c)

@app.get("/staff/guardian", response_class=HTMLResponse)
async def staff_guardian(request: Request):
    c = _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["guardian"] = await db.get_guardian_stats()
        c["guardian_events"] = await db.get_guardian_audit_events(30)
    except Exception as e:
        print(f"[GUARDIAN] {e}")
        c.update(guardian={}, guardian_events=[])
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "viewed_guardian")
    return templates.TemplateResponse("staff/guardian.html", c)


# ══════════════════════════════════════════════════════════
# STAFF SETTINGS — Staff management + Auto-role config
# ══════════════════════════════════════════════════════════

@app.get("/staff/settings", response_class=HTMLResponse)
async def staff_settings(request: Request):
    c = _ctx(request)
    if _require_staff(c):
        return RedirectResponse("/?error=unauthorized")
    try:
        c["staff_members"] = await db.get_staff_members()
        c["role_configs"] = await db.get_role_configs()
        c["success"] = request.query_params.get("success")
        c["error"] = request.query_params.get("error")
        c["staff_role_ids_display"] = os.getenv("STAFF_ROLE_IDS", "")
        c["admin_ids_display"] = os.getenv("ADMIN_USER_IDS", "")
        c["guild_id_display"] = os.getenv("GUILD_ID", "")
    except Exception as e:
        print(f"[SETTINGS] {e}")
        c.update(staff_members=[], role_configs=[])
    return templates.TemplateResponse("staff/settings.html", c)


@app.post("/staff/settings/add_staff")
async def add_staff(request: Request):
    c = _ctx(request)
    if _require_staff(c):
        return RedirectResponse("/?error=unauthorized")
    form = await request.form()
    discord_id = form.get("discord_id", "").strip()
    display_name = form.get("display_name", "").strip()
    tier = int(form.get("permission_tier", 1))
    if not discord_id.isdigit():
        return RedirectResponse("/staff/settings?error=invalid_id", status_code=303)
    if tier not in (1, 2, 3):
        tier = 1
    try:
        await db.add_staff_member(int(discord_id), display_name or f"User {discord_id}", tier, c["user"]["id"])
        await db.add_audit(c["user"]["id"], c["user"].get("username", "?"), "add_staff",
                           target_id=int(discord_id), details=f"tier={tier} name={display_name}")
    except Exception as e:
        print(f"[SETTINGS] Add staff error: {e}")
        return RedirectResponse("/staff/settings?error=db_error", status_code=303)
    return RedirectResponse(f"/staff/settings?success=staff_added", status_code=303)


@app.post("/staff/settings/remove_staff/{user_id}")
async def remove_staff(request: Request, user_id: int):
    c = _ctx(request)
    if _require_staff(c):
        return RedirectResponse("/?error=unauthorized")
    try:
        await db.remove_staff_member(user_id)
        await db.add_audit(c["user"]["id"], c["user"].get("username", "?"), "remove_staff",
                           target_id=user_id)
    except Exception as e:
        print(f"[SETTINGS] Remove staff error: {e}")
    return RedirectResponse("/staff/settings?success=staff_removed", status_code=303)


@app.post("/staff/settings/add_role")
async def add_role_config(request: Request):
    c = _ctx(request)
    if _require_staff(c):
        return RedirectResponse("/?error=unauthorized")
    form = await request.form()
    role_id = form.get("role_id", "").strip()
    role_name = form.get("role_name", "").strip()
    tier = int(form.get("permission_tier", 1))
    if not role_id.isdigit():
        return RedirectResponse("/staff/settings?error=invalid_role_id", status_code=303)
    if tier not in (1, 2, 3):
        tier = 1
    try:
        await db.add_role_config(int(role_id), role_name or f"Role {role_id}", tier, c["user"]["id"])
        await db.add_audit(c["user"]["id"], c["user"].get("username", "?"), "add_role_config",
                           details=f"role={role_id} tier={tier} name={role_name}")
    except Exception as e:
        print(f"[SETTINGS] Add role config error: {e}")
        return RedirectResponse("/staff/settings?error=db_error", status_code=303)
    return RedirectResponse("/staff/settings?success=role_added", status_code=303)


@app.post("/staff/settings/remove_role/{role_id}")
async def remove_role_config(request: Request, role_id: int):
    c = _ctx(request)
    if _require_staff(c):
        return RedirectResponse("/?error=unauthorized")
    try:
        await db.remove_role_config(role_id)
        await db.add_audit(c["user"]["id"], c["user"].get("username", "?"), "remove_role_config",
                           details=f"role={role_id}")
    except Exception as e:
        print(f"[SETTINGS] Remove role config error: {e}")
    return RedirectResponse("/staff/settings?success=role_removed", status_code=303)
