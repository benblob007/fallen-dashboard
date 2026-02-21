"""
✝ THE FALLEN ✝ — Discord OAuth2 Authentication
Handles login/logout, session management, and role-based staff detection.

Staff detection uses Discord role IDs (not names) because that's what the API returns.
Set STAFF_ROLE_IDS in environment as comma-separated Discord role IDs.
Set ADMIN_USER_IDS as comma-separated Discord user IDs for emergency override.
"""

import os
import httpx
from typing import Optional, Dict, List, Set
from itsdangerous import URLSafeTimedSerializer
from fastapi import Request, Response

# Discord OAuth2 endpoints
DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API}/oauth2/token"
USER_URL = f"{DISCORD_API}/users/@me"
GUILD_MEMBER_URL = f"{DISCORD_API}/users/@me/guilds/{{guild_id}}/member"

# Scopes
SCOPES = "identify guilds guilds.members.read"

# Cookie settings
SESSION_COOKIE = "fallen_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def _get_serializer():
    secret = os.getenv("SECRET_KEY", "fallback-dev-secret-change-me")
    return URLSafeTimedSerializer(secret)


def get_staff_role_ids() -> Set[str]:
    """Get staff role IDs from environment. Returns set of role ID strings."""
    raw = os.getenv("STAFF_ROLE_IDS", "")
    if not raw:
        return set()
    return {r.strip() for r in raw.split(",") if r.strip()}


def get_admin_user_ids() -> Set[int]:
    """Get admin user IDs from environment (emergency override). Returns set of user ID ints."""
    raw = os.getenv("ADMIN_USER_IDS", "")
    if not raw:
        return set()
    result = set()
    for uid in raw.split(","):
        uid = uid.strip()
        if uid.isdigit():
            result.add(int(uid))
    return result


def check_is_staff(user_id: int, role_ids: List[str]) -> bool:
    """
    Check if a user is staff based on:
    1. Admin user ID override (ADMIN_USER_IDS env)
    2. Discord role IDs matching STAFF_ROLE_IDS env
    """
    # Check admin override first
    admin_ids = get_admin_user_ids()
    if user_id in admin_ids:
        print(f"[AUTH] ✅ User {user_id} granted staff via ADMIN_USER_IDS override")
        return True
    
    # Check role IDs
    staff_roles = get_staff_role_ids()
    if not staff_roles:
        print(f"[AUTH] ⚠️ STAFF_ROLE_IDS not set — no one can access staff panel via roles")
        return False
    
    user_roles = set(str(r) for r in role_ids)
    matching = user_roles & staff_roles
    
    if matching:
        print(f"[AUTH] ✅ User {user_id} granted staff via role IDs: {matching}")
        return True
    
    print(f"[AUTH] ❌ User {user_id} denied staff. Their roles: {user_roles}, required: {staff_roles}")
    return False


def get_redirect_uri():
    base = os.getenv("DASHBOARD_URL", "https://fallen-dashboard.onrender.com")
    return f"{base}/auth/callback"


def get_login_url(state: str = "") -> str:
    client_id = os.getenv("DISCORD_CLIENT_ID")
    redirect = get_redirect_uri()
    return (
        f"{AUTHORIZE_URL}?"
        f"client_id={client_id}&"
        f"redirect_uri={redirect}&"
        f"response_type=code&"
        f"scope={SCOPES.replace(' ', '%20')}&"
        f"prompt=consent"
    )


async def exchange_code(code: str) -> Optional[Dict]:
    """Exchange an authorization code for an access token."""
    data = {
        "client_id": os.getenv("DISCORD_CLIENT_ID"),
        "client_secret": os.getenv("DISCORD_CLIENT_SECRET"),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": get_redirect_uri(),
    }
    
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if resp.status_code != 200:
            print(f"[AUTH] ❌ Token exchange failed: {resp.status_code} {resp.text}")
            return None
        print(f"[AUTH] ✅ Token exchange successful")
        return resp.json()


async def get_discord_user(access_token: str) -> Optional[Dict]:
    """Fetch the authenticated user's Discord profile."""
    headers = {"Authorization": f"Bearer {access_token}"}
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(USER_URL, headers=headers)
        if resp.status_code != 200:
            print(f"[AUTH] ❌ User fetch failed: {resp.status_code}")
            return None
        user = resp.json()
        print(f"[AUTH] ✅ Got Discord user: {user.get('username')} ({user.get('id')})")
        return user


async def get_user_guild_member(access_token: str, guild_id: str) -> Optional[Dict]:
    """Get the user's full guild member data including roles and nickname."""
    headers = {"Authorization": f"Bearer {access_token}"}
    url = GUILD_MEMBER_URL.format(guild_id=guild_id)
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            print(f"[AUTH] ❌ Guild member fetch failed: {resp.status_code} {resp.text}")
            print(f"[AUTH] URL was: {url}")
            return None
        data = resp.json()
        roles = data.get("roles", [])
        nick = data.get("nick", "")
        print(f"[AUTH] ✅ Guild member data: nick={nick}, roles={roles}")
        return data


def set_session(response: Response, user_data: dict):
    s = _get_serializer()
    token = s.dumps(user_data)
    response.set_cookie(
        SESSION_COOKIE, token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax"
    )


def get_session(request: Request) -> Optional[Dict]:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    s = _get_serializer()
    try:
        return s.loads(token, max_age=SESSION_MAX_AGE)
    except Exception:
        return None


def clear_session(response: Response):
    response.delete_cookie(SESSION_COOKIE)
