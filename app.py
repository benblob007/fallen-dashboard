"""
THE FALLEN - Web Dashboard (v5 - Complete Feature Set)
Full staff dashboard, moderation cases, rank ladder, events, embeds,
notifications, seasons, activity tracking, bot status, clan rules.
"""
import os, time, json, datetime
import httpx
from contextlib import asynccontextmanager
from collections import defaultdict
from fastapi import FastAPI, Request, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from db import db, WARNING_CATEGORIES, LEVEL_CARD_BACKGROUNDS, EMBED_CATEGORIES, ESCALATION_THRESHOLDS
import auth

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests=60, window=60):
        super().__init__(app); self.max_requests = max_requests; self.window = window; self.requests = defaultdict(list)
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/static"): return await call_next(request)
        ip = request.client.host if request.client else "unknown"; now = time.time()
        self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window]
        if len(self.requests[ip]) >= self.max_requests: return JSONResponse({"error": "Rate limited"}, status_code=429)
        self.requests[ip].append(now); return await call_next(request)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try: await db.connect()
    except Exception as e: print(f"DB connect failed: {e}")
    print("THE FALLEN Dashboard v5 live!")
    yield
    try: await db.close()
    except: pass

app = FastAPI(title="The Fallen Dashboard", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware, max_requests=120, window=60)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# == HELPERS ==
def _get_ip(r: Request) -> str:
    return r.headers.get("x-forwarded-for", r.client.host if r.client else "unknown").split(",")[0].strip()

async def _ctx(request: Request) -> dict:
    user = auth.get_session(request)
    is_staff = user.get("is_staff", False) if user else False
    notif_count = 0
    if user and is_staff:
        notif_count = await db.get_unread_count(user["id"])
    # Get user theme preference
    theme = "dark"
    if user:
        prefs = await db.get_user_prefs(user["id"])
        theme = prefs.get("theme", "dark") if prefs else "dark"
    return {"request": request, "user": user, "is_staff": is_staff,
            "notif_count": notif_count, "theme": theme}

def _fnum(n):
    if n is None: return "0"
    return f"{int(n):,}"
def _ftime(seconds):
    if not seconds: return "0m"
    s = int(seconds); h, m = s // 3600, (s % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"
def _elo_rank(elo):
    elo = int(elo or 1000)
    if elo >= 2000: return ("Grandmaster", "T", "#ffd700")
    if elo >= 1800: return ("Diamond", "D", "#b9f2ff")
    if elo >= 1600: return ("Platinum", "P", "#e5e4e2")
    if elo >= 1400: return ("Gold", "G", "#f39c12")
    if elo >= 1200: return ("Silver", "S", "#95a5a6")
    return ("Bronze", "B", "#cd7f32")
def _level_progress(xp, level):
    xp, level = xp or 0, level or 0
    cur = level*level*50; nxt = (level+1)*(level+1)*50; needed = nxt-cur
    if needed <= 0: return 100
    return min(100, max(0, int(((xp-cur)/needed)*100)))
def _time_ago(iso_str):
    if not iso_str: return "Never"
    try:
        if isinstance(iso_str, str): dt = datetime.datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        else: dt = iso_str
        if dt.tzinfo is None: dt = dt.replace(tzinfo=datetime.timezone.utc)
        now = datetime.datetime.now(datetime.timezone.utc); secs = (now-dt).total_seconds()
        if secs < 60: return "Just now"
        if secs < 3600: return f"{int(secs//60)}m ago"
        if secs < 86400: return f"{int(secs//3600)}h ago"
        return f"{int(secs//86400)}d ago"
    except: return str(iso_str)[:10]

templates.env.filters["fnum"] = _fnum
templates.env.filters["ftime"] = _ftime
templates.env.filters["timeago"] = _time_ago
templates.env.globals["elo_rank"] = _elo_rank
templates.env.globals["level_progress"] = _level_progress

# == ERROR HANDLERS ==
@app.exception_handler(404)
async def not_found(r: Request, exc):
    return templates.TemplateResponse("error.html", {"request":r,"user":auth.get_session(r),"is_staff":False,"theme":"dark","notif_count":0,"error_code":404,"error_title":"Page Not Found","error_msg":"The page you are looking for does not exist."}, status_code=404)
@app.exception_handler(500)
async def server_error(r: Request, exc):
    return templates.TemplateResponse("error.html", {"request":r,"user":auth.get_session(r),"is_staff":False,"theme":"dark","notif_count":0,"error_code":500,"error_title":"Server Error","error_msg":"Something went wrong."}, status_code=500)
@app.exception_handler(Exception)
async def generic_error(r: Request, exc):
    print(f"[ERROR] {type(exc).__name__}: {exc}")
    try:
        return templates.TemplateResponse("error.html", {"request":r,"user":None,"is_staff":False,"theme":"dark","notif_count":0,"error_code":500,"error_title":"Server Error","error_msg":str(exc)[:200]}, status_code=500)
    except:
        return HTMLResponse(f"<h1>Server Error</h1><p>{str(exc)[:200]}</p>", status_code=500)

# ================================================
# AUTH ROUTES
# ================================================
@app.get("/auth/login")
async def login(): return RedirectResponse(auth.get_login_url())

@app.get("/auth/callback")
async def callback(request: Request, code: str = None, error: str = None):
    if error or not code: return RedirectResponse("/?error=auth_failed")
    token_data = await auth.exchange_code(code)
    if not token_data: return RedirectResponse("/?error=token_failed")
    access_token = token_data.get("access_token")
    discord_user = await auth.get_discord_user(access_token)
    if not discord_user: return RedirectResponse("/?error=user_failed")
    user_id = discord_user["id"]; uid_int = int(user_id)
    guild_id = os.getenv("GUILD_ID", ""); role_ids = []; nick = None
    if guild_id:
        member = await auth.get_user_guild_member(access_token, guild_id)
        if member: role_ids = member.get("roles", []); nick = member.get("nick")

    # === AUTO-DETECT PERMISSIONS ===
    is_staff = False; permission_tier = 0; section_perms = {}

    # 1. Check ADMIN_USER_IDS env override (always tier 3)
    if uid_int in auth.get_admin_user_ids():
        is_staff = True; permission_tier = 3
        print(f"[AUTH] {uid_int} → tier 3 via ADMIN_USER_IDS")

    # 2. Check Discord guild permissions (owner, admin, manage, kick/ban)
    if guild_id:
        guild_perms = await auth.get_user_guild_permissions(access_token, guild_id)
        if guild_perms["tier"] > permission_tier:
            permission_tier = guild_perms["tier"]
            is_staff = True
            print(f"[AUTH] {uid_int} → tier {permission_tier} via Discord permissions")

    # 3. Check DB staff_roles table (manually assigned)
    db_result = await db.is_db_staff(uid_int)
    if db_result[0]:
        is_staff = True; permission_tier = max(permission_tier, db_result[1])
        section_perms = db_result[2] if len(db_result) > 2 else {}
        print(f"[AUTH] {uid_int} → tier {db_result[1]} via staff_roles table")

    # 4. Check role_config table (Discord role → tier mapping, set by bot or admin)
    role_is_staff, role_tier = await db.check_role_permissions(role_ids)
    if role_is_staff:
        is_staff = True; permission_tier = max(permission_tier, role_tier)
        print(f"[AUTH] {uid_int} → tier {role_tier} via role_config table")

    # 5. Fallback: Check STAFF_ROLE_IDS env (legacy, tier 2)
    if not is_staff and auth.check_is_staff(uid_int, role_ids):
        is_staff = True; permission_tier = max(permission_tier, 2)
        print(f"[AUTH] {uid_int} → tier 2 via STAFF_ROLE_IDS env fallback")

    # === BUILD SESSION ===
    avatar_hash = discord_user.get("avatar")
    avatar_url = (f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png?size=128" if avatar_hash else f"https://cdn.discordapp.com/embed/avatars/{uid_int%5}.png")
    session = {"id": uid_int, "username": nick or discord_user.get("global_name") or discord_user.get("username","Unknown"),
        "discord_username": discord_user.get("username","Unknown"), "avatar": avatar_url,
        "is_staff": is_staff, "permission_tier": permission_tier, "section_perms": section_perms, "role_ids": role_ids}
    db_user = await db.get_user(uid_int)
    if db_user: session["level"] = db_user.get("level", 0); session["roblox_username"] = db_user.get("roblox_username")

    # Auto-register staff in staff_roles if detected via Discord perms but not in DB
    if is_staff and permission_tier > 0 and not db_result[0]:
        try:
            await db.auto_register_staff(uid_int, session["username"], permission_tier)
            print(f"[AUTH] Auto-registered {session['username']} as tier {permission_tier} staff")
        except: pass

    # Log staff session with IP
    if is_staff:
        ip = _get_ip(request)
        await db.log_staff_session(uid_int, session["username"], ip, "login")
    print(f"[AUTH] {session['username']} (staff={is_staff}, tier={permission_tier})")
    response = RedirectResponse("/profile"); auth.set_session(response, session); return response

@app.get("/auth/logout")
async def logout():
    response = RedirectResponse("/"); auth.clear_session(response); return response

@app.get("/auth/debug", response_class=HTMLResponse)
async def auth_debug(request: Request):
    c = await _ctx(request); c["session"] = auth.get_session(request)
    c["role_configs"] = await db.get_role_configs(); c["staff_members"] = await db.get_staff_members()
    c["config"] = {"GUILD_ID": os.getenv("GUILD_ID","NOT SET"), "STAFF_ROLE_IDS": os.getenv("STAFF_ROLE_IDS","NOT SET"),
        "ADMIN_USER_IDS": os.getenv("ADMIN_USER_IDS","NOT SET") if c.get("is_staff") else "HIDDEN",
        "DASHBOARD_URL": os.getenv("DASHBOARD_URL","NOT SET")}
    return templates.TemplateResponse("auth_debug.html", c)

# ================================================
# PUBLIC ROUTES
# ================================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    c = await _ctx(request)
    try: c["stats"] = await db.get_server_stats(); c["top_players"] = await db.get_leaderboard("xp", limit=5); c["war_record"] = await db.get_war_record()
    except Exception as e: print(f"[HOME] {e}"); c.update(stats={}, top_players=[], war_record={"total":0,"wins":0,"losses":0,"draws":0})
    return templates.TemplateResponse("home.html", c)

@app.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard(request: Request, sort: str = Query("xp"), page: int = Query(1, ge=1)):
    c = await _ctx(request); pp = 25; off = (page-1)*pp
    try: c["players"] = await db.get_leaderboard(sort, limit=pp, offset=off); c["total_users"] = await db.get_total_users()
    except: c.update(players=[], total_users=0)
    c.update(sort=sort, page=page, per_page=pp, offset=off)
    return templates.TemplateResponse("leaderboard.html", c)

@app.get("/raids", response_class=HTMLResponse)
async def raids(request: Request):
    c = await _ctx(request)
    try: c["recent_raids"] = await db.get_recent_raids(15); c["raid_leaders"] = await db.get_raid_leaderboard(10); c["war_record"] = await db.get_war_record(); c["recent_wars"] = await db.get_wars(10)
    except: c.update(recent_raids=[], raid_leaders=[], war_record={"total":0,"wins":0,"losses":0,"draws":0}, recent_wars=[])
    return templates.TemplateResponse("raids.html", c)

@app.get("/duels", response_class=HTMLResponse)
async def duels(request: Request):
    c = await _ctx(request)
    try: c["recent_duels"] = await db.get_duel_history(50); c["elo_top"] = await db.get_leaderboard("elo_rating", limit=10); c["elo_dist"] = await db.get_elo_distribution()
    except: c.update(recent_duels=[], elo_top=[], elo_dist={})
    return templates.TemplateResponse("duels.html", c)

# ================================================
# PUBLIC TOURNAMENTS
# ================================================
@app.get("/tournaments", response_class=HTMLResponse)
async def tournaments_page(request: Request):
    c = await _ctx(request)
    try:
        all_t = await db.get_tournaments(limit=50)
        c["active"] = [t for t in all_t if t["status"] == "active"]
        c["upcoming"] = [t for t in all_t if t["status"] in ("draft", "open")]
        c["completed"] = [t for t in all_t if t["status"] == "completed"]
    except: c.update(active=[], upcoming=[], completed=[])
    return templates.TemplateResponse("tournaments.html", c)

@app.get("/tournament/{tid}", response_class=HTMLResponse)
async def tournament_detail_public(request: Request, tid: int):
    c = await _ctx(request)
    try:
        c["tournament"] = await db.get_tournament(tid)
        if c.get("user") and c["tournament"]:
            c["is_joined"] = any(p["user_id"] == c["user"]["id"] for p in (c["tournament"].get("participants") or []))
        else: c["is_joined"] = False
    except: c["tournament"] = None; c["is_joined"] = False
    return templates.TemplateResponse("tournament_view.html", c)

@app.post("/tournament/{tid}/join")
async def tournament_join(request: Request, tid: int):
    user = auth.get_session(request)
    if not user: return RedirectResponse("/auth/login")
    t = await db.get_tournament(tid)
    if not t: return RedirectResponse("/tournaments?error=not_found", status_code=303)
    if t["status"] not in ("draft", "open"): return RedirectResponse(f"/tournament/{tid}?error=registration_closed", status_code=303)
    # Check if already joined
    participants = t.get("participants") or []
    if any(p["user_id"] == user["id"] for p in participants):
        return RedirectResponse(f"/tournament/{tid}?error=already_joined", status_code=303)
    # Check capacity
    if len(participants) >= t.get("bracket_size", 8):
        return RedirectResponse(f"/tournament/{tid}?error=tournament_full", status_code=303)
    # Check entry fee
    if t.get("entry_fee", 0) > 0:
        profile = await db.get_user(user["id"])
        if not profile or (profile.get("coins") or 0) < t["entry_fee"]:
            return RedirectResponse(f"/tournament/{tid}?error=not_enough_coins", status_code=303)
        # Deduct fee
        await dispatch_action("add_coins", user["id"], user["id"], "Tournament Entry", {"amount": -t["entry_fee"], "reason": f"Tournament #{tid} entry"})
    await db.add_tournament_participant(tid, user["id"])
    return RedirectResponse(f"/tournament/{tid}?joined=1", status_code=303)

@app.post("/tournament/{tid}/leave")
async def tournament_leave(request: Request, tid: int):
    user = auth.get_session(request)
    if not user: return RedirectResponse("/auth/login")
    t = await db.get_tournament(tid)
    if not t or t["status"] not in ("draft", "open"): return RedirectResponse(f"/tournament/{tid}?error=cannot_leave", status_code=303)
    await db.remove_tournament_participant(tid, user["id"])
    # Refund entry fee
    if t.get("entry_fee", 0) > 0:
        await dispatch_action("add_coins", user["id"], user["id"], "Tournament Refund", {"amount": t["entry_fee"], "reason": f"Tournament #{tid} refund"})
    return RedirectResponse(f"/tournament/{tid}?left=1", status_code=303)

@app.get("/economy", response_class=HTMLResponse)
async def economy(request: Request):
    c = await _ctx(request)
    try: c["eco"] = await db.get_economy_stats(); c["shop"] = await db.get_shop_catalog()
    except: c.update(eco={"total_coins_circulation":0,"avg_coins":0,"richest":[]}, shop=[])
    # Add user profile for balance display
    if c.get("user"):
        try: c["profile"] = await db.get_user(c["user"]["id"])
        except: c["profile"] = None
    return templates.TemplateResponse("economy.html", c)

@app.post("/economy/buy")
async def economy_buy(request: Request, item_key: str = Form(...)):
    c = await _ctx(request)
    if not c.get("user"): return RedirectResponse("/economy?error=login_required", status_code=303)
    uid = c["user"]["id"]
    profile = await db.get_user(uid)
    if not profile: return RedirectResponse("/economy?error=no_profile", status_code=303)
    shop = {item["key"]: item for item in await db.get_shop_catalog()}
    item = shop.get(item_key)
    if not item: return RedirectResponse("/economy?error=item_not_found", status_code=303)
    if (profile.get("coins") or 0) < item["price"]: return RedirectResponse("/economy?error=not_enough_coins", status_code=303)
    await dispatch_action("shop_buy", uid, uid, c["user"].get("username","?"), {"item_key": item_key, "item_name": item["name"], "price": item["price"]})
    return RedirectResponse("/economy?purchased=1", status_code=303)

@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    c = await _ctx(request)
    try: c["data"] = await db.get_analytics()
    except: c["data"] = {}
    return templates.TemplateResponse("analytics.html", c)

@app.get("/clan", response_class=HTMLResponse)
async def clan(request: Request):
    c = await _ctx(request)
    try:
        c["stats"] = await db.get_server_stats(); c["war_record"] = await db.get_war_record()
        c["roster"] = await db.get_roster_with_names(); c["positions"] = await db.get_open_positions()
        c["rules"] = await db.get_clan_rules(); c["current_season"] = await db.get_current_season()
    except: c.update(stats={}, war_record={"total":0,"wins":0,"losses":0,"draws":0}, roster=[], positions=[], rules=[], current_season=None)
    return templates.TemplateResponse("clan.html", c)

@app.get("/apply", response_class=HTMLResponse)
async def apply_page(request: Request):
    c = await _ctx(request)
    if not c["user"]: return RedirectResponse("/auth/login")
    try: c["positions"] = await db.get_open_positions(); c["my_apps"] = await db.get_user_applications(c["user"]["id"])
    except: c.update(positions=[], my_apps=[])
    return templates.TemplateResponse("apply.html", c)

@app.post("/apply/submit")
async def apply_submit(request: Request, position_id: int = Form(...), answers: str = Form(...)):
    user = auth.get_session(request)
    if not user: return RedirectResponse("/auth/login")
    if not answers or len(answers.strip()) < 20:
        return RedirectResponse("/apply?error=application_too_short_-_minimum_20_characters", status_code=303)
    try:
        ok = await db.submit_application(user["id"], position_id, answers)
        if ok:
            await db.add_audit(user["id"], user.get("username","?"), "submitted_application", target_id=position_id)
            await db.add_notification(None, "application", "New Application", f"{user.get('username','?')} applied", "/staff/recruitment", is_global=True)
            return RedirectResponse("/apply?submitted=1", status_code=303)
        else:
            return RedirectResponse("/apply?error=already_applied_for_this_position", status_code=303)
    except Exception as e:
        return RedirectResponse(f"/apply?error=submission_failed", status_code=303)

# ================================================
# AUTHENTICATED ROUTES
# ================================================
@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request):
    c = await _ctx(request)
    if not c["user"]: return RedirectResponse("/auth/login")
    uid = c["user"]["id"]
    try:
        c["profile"] = await db.get_user(uid); c["xp_rank"] = await db.get_user_rank(uid, "xp")
        c["elo_rank_pos"] = await db.get_user_rank(uid, "elo_rating")
        c["duel_history"] = await db.get_user_duel_history(uid, 10)
        c["applications"] = await db.get_user_applications(uid)
        c["rank_name"] = await db.get_user_rank_name(uid)
        c["rank_history"] = await db.get_rank_history(uid, 10)
    except: c.update(profile=None, xp_rank=0, elo_rank_pos=0, duel_history=[], applications=[], rank_name="Unknown", rank_history=[])
    return templates.TemplateResponse("profile.html", c)

@app.get("/customize", response_class=HTMLResponse)
async def customize_page(request: Request):
    return RedirectResponse("/profile", status_code=302)

@app.post("/customize/set_bg")
async def customize_set_bg(request: Request, bg_key: str = Form(...)):
    return RedirectResponse("/profile", status_code=302)

# User preferences (theme)
@app.post("/preferences/theme")
async def set_theme(request: Request, theme: str = Form(...)):
    user = auth.get_session(request)
    if not user: return RedirectResponse("/auth/login")
    if theme in ("dark", "light"):
        await db.set_user_prefs(user["id"], theme=theme)
    referer = request.headers.get("referer", "/")
    return RedirectResponse(referer, status_code=303)

# ================================================
# STAFF HELPERS
# ================================================
def _require_staff(c): return not c["user"] or not c["is_staff"]
def _require_tier(c, tier):
    if _require_staff(c): return True
    return (c["user"].get("permission_tier", 0) or 0) < tier

async def dispatch_action(action_type, target_user_id, staff_id, staff_name, params=None):
    """Send action to bot — tries direct API first, falls back to DB queue.
    Direct API (aiohttp server in bot): instant execution, ~50ms
    DB queue (polling fallback): up to 30s delay
    """
    bot_api_url = os.getenv("BOT_API_URL", "")
    if bot_api_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(f"{bot_api_url}/api/action", json={
                    "action_type": action_type, "target_user_id": target_user_id,
                    "staff_id": staff_id, "staff_name": staff_name, "params": params or {}
                })
                if resp.status_code == 200 and resp.json().get("ok"):
                    return resp.json()
        except Exception as e:
            print(f"[ACTION] Direct API failed ({e}), falling back to DB queue")
    return await db.queue_action(action_type, target_user_id, staff_id, staff_name, params)
def _has_section_perm(c, section, action="view"):
    if _require_staff(c): return False
    tier = c["user"].get("permission_tier", 0) or 0
    if tier >= 3: return True  # Owner has all perms
    sp = c["user"].get("section_perms") or {}
    sec = sp.get(section, {})
    if isinstance(sec, dict): return sec.get(action, False) or sec.get("view", False)
    return bool(sec)

# ================================================
# STAFF ROUTES
# ================================================
@app.get("/staff", response_class=HTMLResponse)
async def staff_dashboard(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["stats"] = await db.get_server_stats(); c["recent_warnings"] = await db.get_recent_warnings(20)
        c["recent_audit"] = await db.get_audit_log(10); c["guardian"] = await db.get_guardian_stats()
        c["mod_stats"] = await db.get_mod_stats(); c["bot_status"] = await db.get_bot_current_status()
        c["current_season"] = await db.get_current_season()
        apps = await db.get_applications("applied", 50); c["pending_apps"] = len(apps)
        disputes = await db.get_disputes("open", 50); c["open_disputes"] = len(disputes)
        c["action_stats"] = await db.get_action_stats()
    except: c.update(stats={}, recent_warnings=[], recent_audit=[], guardian={}, mod_stats={}, bot_status=None, current_season=None, pending_apps=0, open_disputes=0, action_stats={"pending":0,"done":0,"failed":0})
    ip = _get_ip(request)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "viewed_staff_dashboard", ip=ip)
    await db.update_staff_activity(c["user"]["id"], "Viewed dashboard")
    return templates.TemplateResponse("staff/dashboard.html", c)

# -- Global Search --
@app.get("/staff/search", response_class=HTMLResponse)
async def staff_search(request: Request, q: str = ""):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    c["query"] = q; c["results"] = {}
    if q and len(q) >= 2:
        try: c["results"] = await db.global_search(q)
        except: c["results"] = {"users": [], "cases": [], "events": [], "embeds": []}
    return templates.TemplateResponse("staff/search.html", c)

# -- Member Management --
@app.get("/staff/members", response_class=HTMLResponse)
async def staff_members(request: Request, q: str = ""):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    c["query"] = q; c["results"] = []
    if q and len(q) >= 2:
        try: c["results"] = await db.search_users(q)
        except: pass
    return templates.TemplateResponse("staff/members.html", c)

@app.get("/staff/member/{user_id}", response_class=HTMLResponse)
async def staff_member_detail(request: Request, user_id: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["member"] = await db.get_user(user_id); c["warn_data"] = await db.get_user_warnings(user_id)
        c["duel_history"] = await db.get_user_duel_history(user_id, 20)
        c["applications"] = await db.get_user_applications(user_id)
        c["warn_categories"] = WARNING_CATEGORIES; c["transactions"] = await db.get_transactions(user_id, 20)
        c["action_history"] = await db.get_action_history(user_id, 15)
        c["staff_notes"] = await db.get_notes(user_id, 30)
        c["mod_cases"] = await db.get_user_cases(user_id, 30)
        c["rank_name"] = await db.get_user_rank_name(user_id)
        c["rank_history"] = await db.get_rank_history(user_id, 20)
    except:
        c.update(member=None, warn_data={"warnings":[],"total_points":0}, duel_history=[], applications=[],
                 warn_categories=WARNING_CATEGORIES, transactions=[], action_history=[],
                 staff_notes=[], mod_cases=[], rank_name="Unknown", rank_history=[])
    c["success"] = request.query_params.get("success", "")
    c["permission_tier"] = c["user"].get("permission_tier", 0)
    ip = _get_ip(request)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "viewed_member", target_id=user_id, ip=ip)
    return templates.TemplateResponse("staff/member_detail.html", c)

# -- Staff Notes --
@app.post("/staff/note/add/{user_id}")
async def add_note(r: Request, user_id: int, note: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.add_note(user_id, s["id"], s.get("username","?"), note)
    return RedirectResponse(f"/staff/member/{user_id}?success=note_added", status_code=303)

@app.post("/staff/note/delete/{note_id}")
async def delete_note(r: Request, note_id: int, user_id: int = Form(0)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.delete_note(note_id)
    return RedirectResponse(f"/staff/member/{user_id}?success=note_deleted", status_code=303)

@app.post("/staff/note/pin/{note_id}")
async def pin_note(r: Request, note_id: int, user_id: int = Form(0)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.toggle_pin_note(note_id)
    return RedirectResponse(f"/staff/member/{user_id}?success=note_pinned", status_code=303)

# -- Staff Action POSTs --
@app.post("/staff/action/warn/{user_id}")
async def staff_action_warn(r: Request, user_id: int, category: str = Form(...), reason: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]; ip = _get_ip(r)
    await dispatch_action("warn", user_id, s["id"], s.get("username","?"), {"category": category, "reason": reason})
    cat_info = WARNING_CATEGORIES.get(category, {})
    points = cat_info.get("points", 0)
    await db.create_case(user_id, "warning", category, "high" if cat_info.get("instant_ban") else "medium", reason, points, s["id"], s.get("username","?"))
    # Queue mod-log webhook to Discord
    await db.queue_mod_log(user_id, s["id"], s.get("username","?"), "warning", f"{category}: {reason[:100]}", {"points": points})
    # Check auto-escalation (e.g. 10pts = auto-mute, 20pts = auto-ban)
    warn_data = await db.get_user_warnings(user_id)
    total_points = warn_data.get("total_points", 0) + points
    escalation = await db.check_auto_escalation(user_id, total_points, s["id"], s.get("username","?"))
    await db.add_audit(s["id"], s.get("username","?"), "queued_warn", target_id=user_id,
        details=f"{category}: {reason[:100]}" + (f" [AUTO-ESCALATED: {escalation['action']}]" if escalation else ""), ip=ip)
    return RedirectResponse(f"/staff/member/{user_id}?success=warn_queued{'&escalated='+escalation['action'] if escalation else ''}", status_code=303)

@app.post("/staff/action/timeout/{user_id}")
async def staff_action_timeout(r: Request, user_id: int, duration: int = Form(10), reason: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]; ip = _get_ip(r)
    await dispatch_action("timeout", user_id, s["id"], s.get("username","?"), {"duration_minutes": duration, "reason": reason})
    await db.create_case(user_id, "mute", None, "medium", f"{duration}m timeout: {reason}", 0, s["id"], s.get("username","?"))
    await db.queue_mod_log(user_id, s["id"], s.get("username","?"), "timeout", f"{duration}m: {reason[:100]}")
    await db.add_audit(s["id"], s.get("username","?"), "queued_timeout", target_id=user_id, details=f"{duration}m: {reason[:100]}", ip=ip)
    return RedirectResponse(f"/staff/member/{user_id}?success=timeout_queued", status_code=303)

@app.post("/staff/action/kick/{user_id}")
async def staff_action_kick(r: Request, user_id: int, reason: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse(f"/staff/member/{user_id}?success=insufficient_perms", status_code=303)
    s = c["user"]; ip = _get_ip(r)
    await dispatch_action("kick", user_id, s["id"], s.get("username","?"), {"reason": reason})
    await db.create_case(user_id, "kick", None, "high", reason, 0, s["id"], s.get("username","?"))
    await db.queue_mod_log(user_id, s["id"], s.get("username","?"), "kick", reason[:200])
    await db.add_audit(s["id"], s.get("username","?"), "queued_kick", target_id=user_id, details=reason[:200], ip=ip)
    return RedirectResponse(f"/staff/member/{user_id}?success=kick_queued", status_code=303)

@app.post("/staff/action/ban/{user_id}")
async def staff_action_ban(r: Request, user_id: int, reason: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse(f"/staff/member/{user_id}?success=insufficient_perms", status_code=303)
    s = c["user"]; ip = _get_ip(r)
    await dispatch_action("ban", user_id, s["id"], s.get("username","?"), {"reason": reason})
    await db.create_case(user_id, "ban", None, "critical", reason, 999, s["id"], s.get("username","?"))
    await db.queue_mod_log(user_id, s["id"], s.get("username","?"), "ban", reason[:200])
    await db.add_audit(s["id"], s.get("username","?"), "queued_ban", target_id=user_id, details=reason[:200], ip=ip)
    return RedirectResponse(f"/staff/member/{user_id}?success=ban_queued", status_code=303)

@app.post("/staff/action/adjust_xp/{user_id}")
async def staff_action_xp(r: Request, user_id: int, amount: int = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await dispatch_action("add_xp", user_id, s["id"], s.get("username","?"), {"amount": amount})
    await db.add_audit(s["id"], s.get("username","?"), "queued_xp_adjust", target_id=user_id, details=f"{amount:+d} XP", ip=_get_ip(r))
    return RedirectResponse(f"/staff/member/{user_id}?success=xp_queued", status_code=303)

@app.post("/staff/action/adjust_coins/{user_id}")
async def staff_action_coins(r: Request, user_id: int, amount: int = Form(...), reason: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await dispatch_action("add_coins", user_id, s["id"], s.get("username","?"), {"amount": amount, "reason": reason})
    await db.add_audit(s["id"], s.get("username","?"), "queued_coin_adjust", target_id=user_id, details=f"{amount:+d} FC: {reason[:80]}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/member/{user_id}?success=coins_queued", status_code=303)

@app.post("/staff/action/set_elo/{user_id}")
async def staff_action_elo(r: Request, user_id: int, elo: int = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await dispatch_action("set_elo", user_id, s["id"], s.get("username","?"), {"elo": elo})
    await db.add_audit(s["id"], s.get("username","?"), "queued_elo_set", target_id=user_id, details=f"Set ELO to {elo}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/member/{user_id}?success=elo_queued", status_code=303)

@app.post("/staff/action/remove_warn/{user_id}")
async def staff_action_remove_warn(r: Request, user_id: int, warning_id: int = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await dispatch_action("remove_warning", user_id, s["id"], s.get("username","?"), {"warning_id": warning_id})
    await db.add_audit(s["id"], s.get("username","?"), "queued_remove_warn", target_id=user_id, details=f"Warning #{warning_id}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/member/{user_id}?success=warn_remove_queued", status_code=303)

# -- Promote/Demote --
@app.post("/staff/action/promote/{user_id}")
async def staff_action_promote(r: Request, user_id: int, new_rank: str = Form(...), reason: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    s = c["user"]; old_rank = await db.get_user_rank_name(user_id)
    await db.add_rank_change(user_id, old_rank, new_rank, f"Manual: {reason}", s["id"])
    await dispatch_action("set_rank", user_id, s["id"], s.get("username","?"), {"rank": new_rank, "reason": reason})
    await db.add_audit(s["id"], s.get("username","?"), "promoted", target_id=user_id, details=f"{old_rank} -> {new_rank}: {reason[:100]}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/member/{user_id}?success=rank_changed", status_code=303)

# ================================================
# MODERATION CASES
# ================================================
@app.get("/staff/cases", response_class=HTMLResponse)
async def staff_cases(request: Request, status: str = ""):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["cases"] = await db.get_cases(status or None, 50)
        c["mod_stats"] = await db.get_mod_stats()
    except: c.update(cases=[], mod_stats={})
    c["filter_status"] = status
    return templates.TemplateResponse("staff/cases.html", c)

@app.get("/staff/case/{case_id}", response_class=HTMLResponse)
async def staff_case_detail(request: Request, case_id: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["case"] = await db.get_case(case_id)
    except: c["case"] = None
    c["success"] = request.query_params.get("success", "")
    users = await db._users()
    if c["case"]:
        uid = str(c["case"]["target_user_id"])
        c["target_name"] = users.get(uid, {}).get("roblox_username", f"User {uid}")
    return templates.TemplateResponse("staff/case_detail.html", c)

@app.post("/staff/case/{case_id}/evidence")
async def add_case_evidence(r: Request, case_id: int, evidence_type: str = Form("note"), content: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.add_evidence(case_id, evidence_type, content, s["id"], s.get("username","?"))
    return RedirectResponse(f"/staff/case/{case_id}?success=evidence_added", status_code=303)

@app.post("/staff/case/{case_id}/resolve")
async def resolve_case(r: Request, case_id: int, resolution: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.resolve_case(case_id, resolution, s["id"])
    await db.add_audit(s["id"], s.get("username","?"), "resolved_case", details=f"Case #{case_id}: {resolution[:100]}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/case/{case_id}?success=resolved", status_code=303)

@app.post("/staff/cases/create")
async def create_case(r: Request, target_user_id: int = Form(...), case_type: str = Form(...),
        category: str = Form(""), severity: str = Form("medium"), reason: str = Form(""), points: int = Form(0)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    case = await db.create_case(target_user_id, case_type, category, severity, reason, points, s["id"], s.get("username","?"))
    await db.add_audit(s["id"], s.get("username","?"), f"created_case_{case_type}", target_id=target_user_id, details=reason[:200], ip=_get_ip(r))
    if case: return RedirectResponse(f"/staff/case/{case['id']}?success=created", status_code=303)
    return RedirectResponse("/staff/cases?error=create_failed", status_code=303)

# ================================================
# RANK LADDER
# ================================================
@app.get("/staff/ranks", response_class=HTMLResponse)
async def staff_ranks(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["ranks"] = await db.get_rank_ladder(); c["recent_changes"] = await db.get_rank_history(limit=20)
    except: c.update(ranks=[], recent_changes=[])
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/ranks.html", c)

@app.post("/staff/ranks/update/{rank_id}")
async def update_rank(r: Request, rank_id: int, rank_name: str = Form(...), min_xp: int = Form(0),
        min_level: int = Form(0), perks: str = Form(""), auto_promote: bool = Form(False), color: str = Form(""), role_id: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    rid = int(role_id) if role_id.isdigit() else None
    await db.update_rank(rank_id, rank_name, min_xp, min_level, perks, auto_promote, color or None, rid)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "updated_rank", details=rank_name, ip=_get_ip(r))
    return RedirectResponse("/staff/ranks?success=updated", status_code=303)

@app.post("/staff/ranks/add")
async def add_rank(r: Request, rank_name: str = Form(...), min_xp: int = Form(0), min_level: int = Form(0), perks: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    ranks = await db.get_rank_ladder()
    await db.add_rank(rank_name, len(ranks), min_xp, min_level, perks, False)
    return RedirectResponse("/staff/ranks?success=added", status_code=303)

@app.post("/staff/ranks/delete/{rank_id}")
async def delete_rank(r: Request, rank_id: int):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    await db.delete_rank(rank_id)
    return RedirectResponse("/staff/ranks?success=deleted", status_code=303)

# ================================================
# ACTIVITY TRACKING
# ================================================
@app.get("/staff/activity", response_class=HTMLResponse)
async def staff_activity(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["activity"] = await db.get_activity_stats()
        c["activity_leaders"] = await db.get_activity_leaderboard(25)
    except: c["activity"] = {}; c["activity_leaders"] = []
    return templates.TemplateResponse("staff/activity.html", c)

# ================================================
# SCHEDULED EVENTS
# ================================================
@app.get("/staff/events", response_class=HTMLResponse)
async def staff_events(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["events"] = await db.get_events(limit=30)
    except: c["events"] = []
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/events.html", c)

@app.post("/staff/events/create")
async def create_event(r: Request, title: str = Form(...), event_type: str = Form("raid"),
        description: str = Form(""), scheduled_at: str = Form(""), duration: int = Form(60),
        max_participants: int = Form(0), min_level: int = Form(0),
        xp_reward: int = Form(0), coin_reward: int = Form(0)):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    sched = datetime.datetime.fromisoformat(scheduled_at) if scheduled_at else None
    await db.create_event(title, event_type, description, sched, duration, max_participants, min_level, xp_reward, coin_reward, s["id"], s.get("username","?"))
    await db.add_audit(s["id"], s.get("username","?"), "created_event", details=title, ip=_get_ip(r))
    await db.add_notification(None, "event", f"New Event: {title}", description[:100], "/staff/events", is_global=True)
    return RedirectResponse("/staff/events?success=created", status_code=303)

@app.get("/staff/event/{eid}", response_class=HTMLResponse)
async def staff_event_detail(request: Request, eid: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["event"] = await db.get_event(eid)
    except: c["event"] = None
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/event_detail.html", c)

@app.post("/staff/event/{eid}/status")
async def update_event_status(r: Request, eid: int, status: str = Form(...), summary: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.update_event_status(eid, status, summary or None)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), f"event_{status}", details=f"Event #{eid}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/event/{eid}?success=updated", status_code=303)

@app.post("/staff/event/{eid}/attendance")
async def mark_event_attendance(r: Request, eid: int, user_id: int = Form(...), attended: bool = Form(True), score: int = Form(0)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.mark_attendance(eid, user_id, attended, score)
    return RedirectResponse(f"/staff/event/{eid}?success=attendance_updated", status_code=303)

# ================================================
# REWARDS
# ================================================
@app.get("/staff/rewards", response_class=HTMLResponse)
async def staff_rewards(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["rewards"] = await db.get_reward_mappings()
    except: c["rewards"] = []
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/rewards.html", c)

@app.post("/staff/rewards/add")
async def add_reward(r: Request, trigger_type: str = Form(...), trigger_value: str = Form(...),
        reward_type: str = Form(...), reward_value: str = Form(...), description: str = Form(""), cooldown: int = Form(0)):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.add_reward_mapping(trigger_type, trigger_value, reward_type, reward_value, description, cooldown)
    return RedirectResponse("/staff/rewards?success=added", status_code=303)

@app.post("/staff/rewards/delete/{rid}")
async def delete_reward(r: Request, rid: int):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.delete_reward_mapping(rid)
    return RedirectResponse("/staff/rewards?success=deleted", status_code=303)

@app.post("/staff/rewards/toggle/{rid}")
async def toggle_reward(r: Request, rid: int):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.toggle_reward(rid)
    return RedirectResponse("/staff/rewards?success=toggled", status_code=303)

# ================================================
# EMBED MANAGER
# ================================================
@app.get("/staff/embeds", response_class=HTMLResponse)
async def staff_embeds(request: Request, category: str = ""):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["embeds"] = await db.get_embeds(category or None)
        c["categories"] = EMBED_CATEGORIES
    except: c.update(embeds=[], categories=[])
    c["filter_category"] = category
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/embeds.html", c)

@app.get("/staff/embed/new", response_class=HTMLResponse)
async def new_embed(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    c["embed"] = None; c["categories"] = EMBED_CATEGORIES
    return templates.TemplateResponse("staff/embed_editor.html", c)

@app.get("/staff/embed/{eid}", response_class=HTMLResponse)
async def edit_embed(request: Request, eid: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["embed"] = await db.get_embed(eid)
        c["categories"] = EMBED_CATEGORIES
        if c["embed"]:
            c["embed"]["interactions_list"] = await db.get_interactions(eid)
    except: c["embed"] = None; c["categories"] = EMBED_CATEGORIES
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/embed_editor.html", c)

@app.post("/staff/embeds/save")
async def save_embed(r: Request, name: str = Form(...), category: str = Form("general"), embed_json: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        embed_data = json.loads(embed_json)
    except: return RedirectResponse("/staff/embeds?error=invalid_json", status_code=303)
    eid = await db.save_embed(name, category, embed_data, [], c["user"]["id"])
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "saved_embed", details=name, ip=_get_ip(r))
    return RedirectResponse(f"/staff/embed/{eid}?success=saved", status_code=303)

@app.post("/staff/embed/{eid}/push")
async def push_embed(r: Request, eid: int, channel_id: str = Form(...)):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    cid = int(channel_id) if channel_id.isdigit() else 0
    await dispatch_action("push_embed", 0, c["user"]["id"], c["user"].get("username","?"), {"embed_id": eid, "channel_id": cid})
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "pushed_embed", details=f"Embed #{eid} -> {cid}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/embed/{eid}?success=push_queued", status_code=303)

@app.post("/staff/embed/{eid}/rollback")
async def rollback_embed(r: Request, eid: int, version_id: int = Form(...)):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    ok = await db.rollback_embed(eid, version_id)
    return RedirectResponse(f"/staff/embed/{eid}?success={'rolled_back' if ok else 'rollback_failed'}", status_code=303)

@app.post("/staff/embed/{eid}/delete")
async def delete_embed(r: Request, eid: int):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    await db.delete_embed(eid)
    return RedirectResponse("/staff/embeds?success=deleted", status_code=303)

# ================================================
# NOTIFICATIONS
# ================================================
@app.get("/staff/notifications", response_class=HTMLResponse)
async def staff_notifications(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["notifications"] = await db.get_notifications(c["user"]["id"], limit=50)
    except: c["notifications"] = []
    return templates.TemplateResponse("staff/notifications.html", c)

@app.post("/staff/notifications/read/{nid}")
async def mark_read(r: Request, nid: int):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.mark_notification_read(nid)
    return RedirectResponse("/staff/notifications", status_code=303)

@app.post("/staff/notifications/read_all")
async def mark_all_read(r: Request):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.mark_all_read(c["user"]["id"])
    return RedirectResponse("/staff/notifications", status_code=303)

# ================================================
# BOT STATUS
# ================================================
@app.get("/staff/bot-status", response_class=HTMLResponse)
async def staff_bot_status(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["current"] = await db.get_bot_current_status()
        c["history"] = await db.get_bot_status(limit=50)
    except: c.update(current=None, history=[])
    return templates.TemplateResponse("staff/bot_status.html", c)

# ================================================
# CLAN RULES EDITOR
# ================================================
@app.get("/staff/rules", response_class=HTMLResponse)
async def staff_rules(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["rules"] = await db.get_clan_rules()
    except: c["rules"] = []
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/rules.html", c)

@app.post("/staff/rules/save")
async def save_rule(r: Request, rule_id: str = Form(""), section_title: str = Form(...),
        content: str = Form(...), section_order: int = Form(0)):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    rid = int(rule_id) if rule_id.isdigit() else None
    await db.save_clan_rule(rid, section_title, content, section_order, c["user"]["id"])
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "saved_rule", details=section_title, ip=_get_ip(r))
    return RedirectResponse("/staff/rules?success=saved", status_code=303)

@app.post("/staff/rules/delete/{rid}")
async def delete_rule(r: Request, rid: int):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    await db.delete_clan_rule(rid)
    return RedirectResponse("/staff/rules?success=deleted", status_code=303)

# ================================================
# SEASONAL SYSTEM
# ================================================
@app.get("/staff/seasons", response_class=HTMLResponse)
async def staff_seasons(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["seasons"] = await db.get_seasons(); c["current"] = await db.get_current_season()
    except: c.update(seasons=[], current=None)
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/seasons.html", c)

@app.post("/staff/seasons/create")
async def create_season(r: Request, name: str = Form(...), number: int = Form(1),
        start_date: str = Form(""), end_date: str = Form(""),
        reset_xp: bool = Form(False), reset_elo: bool = Form(False), reset_coins: bool = Form(False)):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    s_date = datetime.datetime.fromisoformat(start_date) if start_date else None
    e_date = datetime.datetime.fromisoformat(end_date) if end_date else None
    await db.create_season(name, number, s_date, e_date, reset_xp, reset_elo, reset_coins, {}, c["user"]["id"])
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "created_season", details=name, ip=_get_ip(r))
    return RedirectResponse("/staff/seasons?success=created", status_code=303)

@app.post("/staff/seasons/{sid}/activate")
async def activate_season(r: Request, sid: int):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    await db.update_season_status(sid, "active")
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "activated_season", details=f"Season #{sid}", ip=_get_ip(r))
    return RedirectResponse("/staff/seasons?success=activated", status_code=303)

@app.post("/staff/seasons/{sid}/end")
async def end_season(r: Request, sid: int):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    await db.update_season_status(sid, "completed")
    return RedirectResponse("/staff/seasons?success=ended", status_code=303)

# ================================================
# STAFF PERFORMANCE
# ================================================
@app.get("/staff/performance", response_class=HTMLResponse)
async def staff_performance(request: Request, days: int = Query(30)):
    c = await _ctx(request)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    try: c["performance"] = await db.get_staff_performance(days)
    except: c["performance"] = []
    c["days"] = days
    return templates.TemplateResponse("staff/performance.html", c)

# ================================================
# EXISTING STAFF SECTIONS
# ================================================
@app.get("/staff/economy", response_class=HTMLResponse)
async def staff_economy(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["eco"] = await db.get_economy_stats(); c["transactions"] = await db.get_transactions(limit=30); c["shop"] = await db.get_shop_catalog()
    except: c.update(eco={"total_coins_circulation":0,"avg_coins":0,"richest":[]}, transactions=[], shop=[])
    return templates.TemplateResponse("staff/economy.html", c)

@app.get("/staff/xp", response_class=HTMLResponse)
async def staff_xp(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["xp_stats"] = await db.get_xp_stats()
    except: c["xp_stats"] = {}
    return templates.TemplateResponse("staff/xp_levels.html", c)

@app.get("/staff/tournaments", response_class=HTMLResponse)
async def staff_tournaments(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["tournaments"] = await db.get_tournaments(limit=20)
    except: c["tournaments"] = []
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/tournaments.html", c)

@app.post("/staff/tournaments/create")
async def create_tournament(r: Request, title: str = Form(...), bracket_size: int = Form(8),
        entry_requirement: str = Form(""), entry_fee: int = Form(0),
        prize_pool: str = Form(""), match_rules: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    tid = await db.create_tournament(title, bracket_size, entry_requirement, entry_fee, prize_pool, match_rules, s["id"])
    if tid: await db.add_audit(s["id"], s.get("username","?"), "created_tournament", details=f"#{tid}: {title}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/tournaments?success=created", status_code=303)

@app.get("/staff/tournament/{tid}", response_class=HTMLResponse)
async def staff_tournament_detail(request: Request, tid: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["tournament"] = await db.get_tournament(tid)
    except: c["tournament"] = None
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/tournament_detail.html", c)

@app.post("/staff/tournament/{tid}/status")
async def update_tournament_status(r: Request, tid: int, status: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    if status == "active":
        # Generate random bracket on start
        bracket = await db.generate_bracket(tid)
        if not bracket:
            return RedirectResponse(f"/staff/tournament/{tid}?success=no_participants", status_code=303)
    await db.update_tournament_status(tid, status)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), f"tournament_{status}", details=f"Tournament #{tid}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/tournament/{tid}?success=status_updated", status_code=303)

@app.post("/staff/tournament/{tid}/add_player")
async def add_tournament_player(r: Request, tid: int, user_id: int = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.add_tournament_participant(tid, user_id)
    return RedirectResponse(f"/staff/tournament/{tid}?success=player_added", status_code=303)

@app.post("/staff/tournament/{tid}/disqualify")
async def disqualify_player(r: Request, tid: int, user_id: int = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.disqualify_participant(tid, user_id)
    return RedirectResponse(f"/staff/tournament/{tid}?success=player_dq", status_code=303)

@app.get("/staff/leaderboards", response_class=HTMLResponse)
async def staff_leaderboards(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["lb_stats"] = await db.get_leaderboard_stats()
    except: c["lb_stats"] = {}
    return templates.TemplateResponse("staff/leaderboards.html", c)

@app.get("/staff/audit", response_class=HTMLResponse)
async def staff_audit(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["logs"] = await db.get_audit_log(200)
    except: c["logs"] = []
    return templates.TemplateResponse("staff/audit_log.html", c)

@app.get("/staff/analytics", response_class=HTMLResponse)
async def staff_analytics(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["data"] = await db.get_analytics(); c["eco"] = await db.get_economy_stats()
    except: c.update(data={}, eco={})
    return templates.TemplateResponse("staff/analytics.html", c)

@app.get("/staff/guardian", response_class=HTMLResponse)
async def staff_guardian(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["guardian"] = await db.get_guardian_stats(); c["guardian_events"] = await db.get_guardian_audit_events(30)
    except: c.update(guardian={}, guardian_events=[])
    return templates.TemplateResponse("staff/guardian.html", c)

# ================================================
# STAFF SETTINGS
# ================================================
@app.get("/staff/settings", response_class=HTMLResponse)
async def staff_settings(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["staff_members"] = await db.get_staff_members(); c["role_configs"] = await db.get_role_configs()
        c["staff_sessions"] = await db.get_staff_sessions(limit=20)
        c["success"] = request.query_params.get("success"); c["error"] = request.query_params.get("error")
        c["staff_role_ids_display"] = os.getenv("STAFF_ROLE_IDS", "")
        c["admin_ids_display"] = os.getenv("ADMIN_USER_IDS", "")
        c["guild_id_display"] = os.getenv("GUILD_ID", "")
    except: c.update(staff_members=[], role_configs=[], staff_sessions=[])
    return templates.TemplateResponse("staff/settings.html", c)

@app.post("/staff/settings/add_staff")
async def add_staff(r: Request):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    form = await r.form(); did = form.get("discord_id","").strip(); name = form.get("display_name","").strip(); tier = int(form.get("permission_tier", 1))
    if not did.isdigit(): return RedirectResponse("/staff/settings?error=invalid_id", status_code=303)
    if tier not in (1,2,3): tier = 1
    try:
        await db.add_staff_member(int(did), name or f"User {did}", tier, c["user"]["id"])
        await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "add_staff", target_id=int(did), details=f"tier={tier}", ip=_get_ip(r))
    except: return RedirectResponse("/staff/settings?error=db_error", status_code=303)
    return RedirectResponse("/staff/settings?success=staff_added", status_code=303)

@app.post("/staff/settings/remove_staff/{user_id}")
async def remove_staff(r: Request, user_id: int):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.remove_staff_member(user_id)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "remove_staff", target_id=user_id, ip=_get_ip(r))
    return RedirectResponse("/staff/settings?success=staff_removed", status_code=303)

@app.post("/staff/settings/add_role")
async def add_role_config(r: Request):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    form = await r.form(); rid = form.get("role_id","").strip(); name = form.get("role_name","").strip(); tier = int(form.get("permission_tier", 1))
    if not rid.isdigit(): return RedirectResponse("/staff/settings?error=invalid_role_id", status_code=303)
    if tier not in (1,2,3): tier = 1
    try:
        await db.add_role_config(int(rid), name or f"Role {rid}", tier, c["user"]["id"])
        await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "add_role_config", details=f"role={rid} tier={tier}", ip=_get_ip(r))
    except: return RedirectResponse("/staff/settings?error=db_error", status_code=303)
    return RedirectResponse("/staff/settings?success=role_added", status_code=303)

@app.post("/staff/settings/remove_role/{role_id}")
async def remove_role_config(r: Request, role_id: int):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.remove_role_config(role_id)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "remove_role_config", details=f"role={role_id}", ip=_get_ip(r))
    return RedirectResponse("/staff/settings?success=role_removed", status_code=303)

# ================================================
# DUEL DISPUTES
# ================================================
@app.get("/staff/disputes", response_class=HTMLResponse)
async def staff_disputes(request: Request, status: str = ""):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["disputes"] = await db.get_disputes(status or None, 50)
    except: c["disputes"] = []
    c["filter_status"] = status
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/disputes.html", c)

@app.get("/staff/dispute/{did}", response_class=HTMLResponse)
async def staff_dispute_detail(request: Request, did: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["dispute"] = await db.get_dispute(did)
        users = await db._users()
        if c["dispute"]:
            c["challenger_name"] = users.get(str(c["dispute"]["challenger_id"]), {}).get("roblox_username", "Unknown")
            c["opponent_name"] = users.get(str(c["dispute"]["opponent_id"]), {}).get("roblox_username", "Unknown")
    except: c["dispute"] = None
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/dispute_detail.html", c)

@app.post("/staff/disputes/create")
async def create_dispute(r: Request, challenger_id: int = Form(...), opponent_id: int = Form(...), reason: str = Form(...), evidence: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    d = await db.create_dispute(0, challenger_id, opponent_id, s["id"], s.get("username","?"), reason, evidence)
    await db.add_notification(None, "dispute", "New Duel Dispute", reason[:80], "/staff/disputes", is_global=True)
    if d: return RedirectResponse(f"/staff/dispute/{d['id']}?success=created", status_code=303)
    return RedirectResponse("/staff/disputes?success=created", status_code=303)

@app.post("/staff/dispute/{did}/resolve")
async def resolve_dispute(r: Request, did: int, resolution: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.resolve_dispute(did, resolution, s["id"], s.get("username","?"))
    await db.add_audit(s["id"], s.get("username","?"), "resolved_dispute", details=f"Dispute #{did}: {resolution[:100]}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/dispute/{did}?success=resolved", status_code=303)

@app.post("/staff/dispute/{did}/reject")
async def reject_dispute(r: Request, did: int, resolution: str = Form(...)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.reject_dispute(did, resolution, s["id"], s.get("username","?"))
    return RedirectResponse(f"/staff/dispute/{did}?success=rejected", status_code=303)

# ================================================
# RECRUITMENT MANAGEMENT
# ================================================
@app.get("/staff/recruitment", response_class=HTMLResponse)
async def staff_recruitment(request: Request):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["positions"] = await db.get_all_positions()
        c["applications"] = await db.get_applications(limit=30)
        c["pending_count"] = len([a for a in c["applications"] if a.get("status") == "applied"])
    except: c.update(positions=[], applications=[], pending_count=0)
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/recruitment.html", c)

@app.post("/staff/recruitment/position/create")
async def create_position(r: Request, title: str = Form(...), description: str = Form(""), requirements: str = Form(""), max_applicants: int = Form(0)):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.create_position(title, description, requirements, max_applicants, c["user"]["id"])
    return RedirectResponse("/staff/recruitment?success=position_created", status_code=303)

@app.post("/staff/recruitment/position/{pid}/close")
async def close_position(r: Request, pid: int):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.close_position(pid)
    return RedirectResponse("/staff/recruitment?success=position_closed", status_code=303)

@app.post("/staff/recruitment/position/{pid}/reopen")
async def reopen_position(r: Request, pid: int):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    await db.reopen_position(pid)
    return RedirectResponse("/staff/recruitment?success=position_reopened", status_code=303)

@app.get("/staff/application/{aid}", response_class=HTMLResponse)
async def staff_application_detail(request: Request, aid: int):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try: c["application"] = await db.get_application(aid)
    except: c["application"] = None
    c["success"] = request.query_params.get("success", "")
    return templates.TemplateResponse("staff/application_detail.html", c)

@app.post("/staff/application/{aid}/vote")
async def vote_application(r: Request, aid: int, vote: str = Form(...), comment: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.add_vote(aid, s["id"], vote, comment)
    await db.add_audit(s["id"], s.get("username","?"), f"voted_{vote}", details=f"Application #{aid}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/application/{aid}?success=voted", status_code=303)

@app.post("/staff/application/{aid}/status")
async def update_app_status(r: Request, aid: int, status: str = Form(...), review_note: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 2): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    await db.update_application_status(aid, status, s["id"], review_note)
    await db.add_audit(s["id"], s.get("username","?"), f"app_{status}", details=f"Application #{aid}: {review_note[:100]}", ip=_get_ip(r))
    return RedirectResponse(f"/staff/application/{aid}?success={status}", status_code=303)

# ================================================
# INTERACTION CONFIG (embed buttons)
# ================================================
@app.post("/staff/embed/{eid}/interaction/add")
async def add_interaction(r: Request, eid: int, interaction_type: str = Form("button"),
        custom_id: str = Form(...), label: str = Form(...), style: str = Form("primary"),
        emoji: str = Form(""), action_type: str = Form("role_toggle"), action_value: str = Form(""),
        required_role_id: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    rid = int(required_role_id) if required_role_id.isdigit() else None
    await db.add_interaction(eid, interaction_type, custom_id, label, style, emoji, action_type, action_value, rid)
    return RedirectResponse(f"/staff/embed/{eid}?success=interaction_added", status_code=303)

@app.post("/staff/interaction/{iid}/toggle")
async def toggle_interaction(r: Request, iid: int, embed_id: int = Form(0)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.toggle_interaction(iid)
    return RedirectResponse(f"/staff/embed/{embed_id}?success=toggled", status_code=303)

@app.post("/staff/interaction/{iid}/delete")
async def delete_interaction(r: Request, iid: int, embed_id: int = Form(0)):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.delete_interaction(iid)
    return RedirectResponse(f"/staff/embed/{embed_id}?success=interaction_deleted", status_code=303)

# ================================================
# TOURNAMENT MATCH RESULTS
# ================================================
@app.post("/staff/tournament/{tid}/match_result")
async def tournament_match_result(r: Request, tid: int, round_num: int = Form(...), match_id: int = Form(...), winner_id: int = Form(...), score: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    ok = await db.update_match_result(tid, round_num, match_id, winner_id, score)
    return RedirectResponse(f"/staff/tournament/{tid}?success={'match_recorded' if ok else 'match_failed'}", status_code=303)

@app.post("/staff/tournament/{tid}/announce")
async def tournament_announce(r: Request, tid: int, channel_id: str = Form("")):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    t = await db.get_tournament(tid)
    if not t: return RedirectResponse("/staff/tournaments", status_code=303)
    dash_url = os.getenv("DASHBOARD_URL", "https://fallen-dashboard.onrender.com")
    await dispatch_action("tournament_announce", 0, c["user"]["id"], c["user"].get("username","?"), {
        "tournament_id": tid, "title": t["title"], "bracket_size": t["bracket_size"],
        "entry_fee": t.get("entry_fee", 0), "prize_pool": t.get("prize_pool", ""),
        "match_rules": t.get("match_rules", ""), "entry_requirement": t.get("entry_requirement", ""),
        "status": t["status"], "participants": len(t.get("participants", [])),
        "dashboard_url": f"{dash_url}/tournament/{tid}",
        "channel_id": int(channel_id) if channel_id.isdigit() else 0
    })
    return RedirectResponse(f"/staff/tournament/{tid}?success=announced", status_code=303)

@app.post("/staff/tournament/{tid}/open")
async def tournament_open_registration(r: Request, tid: int):
    c = await _ctx(r)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    await db.update_tournament_status(tid, "open")
    return RedirectResponse(f"/staff/tournament/{tid}?success=registration_opened", status_code=303)

# ================================================
# PUBLIC CLAN PROFILE
# ================================================
@app.get("/public", response_class=HTMLResponse)
async def public_clan(request: Request):
    c = await _ctx(request)
    try:
        c["stats"] = await db.get_server_stats(); c["war_record"] = await db.get_war_record()
        c["top_players"] = await db.get_leaderboard("xp", limit=10)
        c["rules"] = await db.get_clan_rules(); c["positions"] = await db.get_open_positions()
        c["current_season"] = await db.get_current_season()
        c["roster"] = await db.get_roster_with_names()
    except: c.update(stats={}, war_record={}, top_players=[], rules=[], positions=[], current_season=None, roster=[])
    return templates.TemplateResponse("public.html", c)

# ================================================
# BOT RESTART (with cooldown)
# ================================================
@app.post("/staff/bot-status/restart")
async def request_restart(r: Request, reason: str = Form("")):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    s = c["user"]
    ok = await db.request_restart(s["id"], s.get("username","?"), reason)
    if ok:
        await db.add_audit(s["id"], s.get("username","?"), "requested_restart", details=reason[:200], ip=_get_ip(r))
        return RedirectResponse("/staff/bot-status?success=restart_queued", status_code=303)
    return RedirectResponse("/staff/bot-status?success=cooldown_active", status_code=303)

# ================================================
# SEASONAL LEADERBOARD
# ================================================
@app.get("/staff/seasons/{sid}/leaderboard", response_class=HTMLResponse)
async def seasonal_leaderboard(request: Request, sid: int, sort: str = "xp"):
    c = await _ctx(request)
    if _require_staff(c): return RedirectResponse("/?error=unauthorized")
    try:
        c["season"] = await db._qone("SELECT * FROM seasonal_config WHERE id=$1", sid)
        c["players"] = await db.get_seasonal_leaderboard(sid, sort, 50)
    except: c.update(season=None, players=[])
    c["sort"] = sort
    return templates.TemplateResponse("staff/seasonal_leaderboard.html", c)

# ================================================
# FORCED RE-AUTH
# ================================================
@app.post("/staff/settings/force_reauth/{user_id}")
async def force_reauth(r: Request, user_id: int):
    c = await _ctx(r)
    if _require_tier(c, 3): return RedirectResponse("/?error=unauthorized")
    await db.invalidate_user_sessions(user_id)
    await db.add_audit(c["user"]["id"], c["user"].get("username","?"), "forced_reauth", target_id=user_id, ip=_get_ip(r))
    await db.add_notification(user_id, "security", "Session Invalidated", "Your permissions were changed. Please log in again.", "/auth/login")
    return RedirectResponse("/staff/settings?success=reauth_forced", status_code=303)

# ================================================
# API ENDPOINTS (for AJAX/bot)
# ================================================
@app.get("/api/health")
async def api_health():
    return {"status": "ok", "db": bool(db.pool), "version": "v6"}

@app.post("/api/bot/status")
async def api_bot_status(request: Request):
    try:
        data = await request.json()
        await db.log_bot_status(data.get("status","unknown"), data.get("event","heartbeat"),
            data.get("details",""), data.get("latency",0), data.get("guilds",0), data.get("members",0))
        return {"ok": True}
    except: return {"ok": False}

@app.get("/api/notifications/count")
async def api_notif_count(request: Request):
    user = auth.get_session(request)
    if not user: return {"count": 0}
    return {"count": await db.get_unread_count(user["id"])}

@app.get("/api/bot/pending-actions")
async def api_pending_actions():
    """Bot polls this to get pending actions (alternative to direct DB polling)."""
    try:
        actions = await db.get_pending_actions_by_status("pending", 10)
        return {"ok": True, "actions": [dict(a) for a in actions]}
    except: return {"ok": False, "actions": []}

@app.post("/api/bot/action-result")
async def api_action_result(request: Request):
    """Bot reports back action execution results."""
    try:
        data = await request.json()
        aid = data.get("action_id")
        status = data.get("status", "done")
        result = data.get("result", "")
        if aid:
            await db.update_action_status(aid, status, result)
        return {"ok": True}
    except: return {"ok": False}

@app.get("/api/bot/action-stats")
async def api_action_stats():
    """Get action queue statistics."""
    try:
        stats = await db.get_action_stats()
        return {"ok": True, **stats}
    except: return {"ok": False}

# ================================================
# ACTION QUEUE PAGE (staff)
# ================================================
@app.get("/staff/action-queue")
async def staff_action_queue(r: Request, status: str = ""):
    c = await _ctx(r)
    if _require_tier(c, 1): return RedirectResponse("/?error=unauthorized")
    c["filter_status"] = status
    c["actions"] = await db.get_action_history_filtered(status=status or None, limit=50)
    c["stats"] = await db.get_action_stats()
    return templates.TemplateResponse("staff/action_queue.html", c)
