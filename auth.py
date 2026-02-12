"""
✝ THE FALLEN ✝ — Discord OAuth2 Authentication
Handles login/logout via Discord and session management.
"""

import os
import httpx
from typing import Optional, Dict
from itsdangerous import URLSafeTimedSerializer
from fastapi import Request, Response
from fastapi.responses import RedirectResponse

# Discord OAuth2 endpoints
DISCORD_API = "https://discord.com/api/v10"
AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = f"{DISCORD_API}/oauth2/token"
USER_URL = f"{DISCORD_API}/users/@me"
GUILDS_URL = f"{DISCORD_API}/users/@me/guilds"
GUILD_MEMBER_URL = f"{DISCORD_API}/users/@me/guilds/{{guild_id}}/member"

# Scopes we request
SCOPES = "identify guilds guilds.members.read"

# Cookie settings
SESSION_COOKIE = "fallen_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

# Staff role names to check
STAFF_ROLE_NAMES = {
    "Staff",
    "The Fallen Sovereign〢Owner",
    "The Fallen Right Hand〢Co-Owner",
    "The Fallen Marshal〢Head of Staff",
}


def _get_serializer():
    secret = os.getenv("SECRET_KEY", "fallback-dev-secret-change-me")
    return URLSafeTimedSerializer(secret)


def get_redirect_uri():
    """Build the OAuth redirect URI from environment or default."""
    base = os.getenv("DASHBOARD_URL", "https://fallen-dashboard.onrender.com")
    return f"{base}/auth/callback"


def get_login_url(state: str = "") -> str:
    """Generate the Discord OAuth2 authorization URL."""
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
        resp = await client.post(TOKEN_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if resp.status_code != 200:
            print(f"[AUTH] Token exchange failed: {resp.status_code} {resp.text}")
            return None
        return resp.json()


async def get_discord_user(access_token: str) -> Optional[Dict]:
    """Fetch the authenticated user's Discord profile."""
    headers = {"Authorization": f"Bearer {access_token}"}
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(USER_URL, headers=headers)
        if resp.status_code != 200:
            return None
        return resp.json()


async def get_user_guild_roles(access_token: str, guild_id: str) -> list:
    """Get the user's roles in a specific guild."""
    headers = {"Authorization": f"Bearer {access_token}"}
    url = GUILD_MEMBER_URL.format(guild_id=guild_id)
    
    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data.get("roles", [])


def set_session(response: Response, user_data: dict):
    """Store user data in a signed cookie."""
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
    """Read user data from signed cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    
    s = _get_serializer()
    try:
        data = s.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except Exception:
        return None


def clear_session(response: Response):
    """Remove the session cookie."""
    response.delete_cookie(SESSION_COOKIE)
