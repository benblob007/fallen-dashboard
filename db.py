"""
✝ THE FALLEN ✝ — Dashboard Database
Reads from the json_data table where the bot stores its data as a JSON blob.
The bot stores all user data under json_data key='main_data' → { "users": { "id": {...} } }
"""

import os
import json
import asyncpg
import datetime
from typing import Optional, List, Dict, Any


class DashboardDB:
    """Reads the bot's json_data table to serve dashboard pages."""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        
        self.pool = await asyncpg.create_pool(
            url, min_size=2, max_size=8,
            command_timeout=15,
            server_settings={"application_name": "FallenDashboard"}
        )
        print("✅ Dashboard connected to database")
    
    async def close(self):
        if self.pool:
            await self.pool.close()
    
    # ==========================================
    # CORE: Load the bot's JSON data
    # ==========================================
    
    async def _get_main_data(self) -> Dict:
        """Load the main_data JSON blob from json_data table."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT data FROM json_data WHERE key = 'main_data'")
            if row and row["data"]:
                if isinstance(row["data"], str):
                    return json.loads(row["data"])
                return row["data"]
        return {"users": {}, "roster": []}
    
    async def _get_all_users(self) -> Dict[str, Dict]:
        """Get all users dict from the main data blob."""
        data = await self._get_main_data()
        return data.get("users", {})
    
    # ==========================================
    # USER QUERIES
    # ==========================================
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get a single user's data."""
        users = await self._get_all_users()
        user = users.get(str(user_id))
        if user:
            user["user_id"] = user_id
        return user
    
    async def get_leaderboard(self, sort_by: str = "xp", limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get leaderboard sorted by a field."""
        allowed = {"xp", "level", "coins", "elo_rating", "voice_time", "messages",
                    "wins", "raid_wins", "raid_participation", "weekly_xp", "monthly_xp",
                    "training_attendance", "tryout_attendance"}
        if sort_by not in allowed:
            sort_by = "xp"
        
        users = await self._get_all_users()
        
        user_list = []
        for uid, udata in users.items():
            udata["user_id"] = int(uid)
            user_list.append(udata)
        
        user_list.sort(key=lambda u: u.get(sort_by, 0) or 0, reverse=True)
        return user_list[offset:offset + limit]
    
    async def get_user_rank(self, user_id: int, sort_by: str = "xp") -> int:
        """Get a user's rank position."""
        users = await self._get_all_users()
        uid = str(user_id)
        
        if uid not in users:
            return 0
        
        user_val = users[uid].get(sort_by, 0) or 0
        rank = 1
        for other_uid, other_data in users.items():
            if other_uid != uid and (other_data.get(sort_by, 0) or 0) > user_val:
                rank += 1
        return rank
    
    async def search_users(self, query: str, limit: int = 20) -> List[Dict]:
        """Search users by roblox username."""
        users = await self._get_all_users()
        query_lower = query.lower()
        
        results = []
        for uid, udata in users.items():
            roblox_name = udata.get("roblox_username") or ""
            if query_lower in roblox_name.lower():
                udata["user_id"] = int(uid)
                results.append(udata)
                if len(results) >= limit:
                    break
        
        results.sort(key=lambda u: u.get("xp", 0) or 0, reverse=True)
        return results
    
    async def get_total_users(self) -> int:
        users = await self._get_all_users()
        return len(users)
    
    # ==========================================
    # STATS / OVERVIEW
    # ==========================================
    
    async def get_server_stats(self) -> Dict:
        """Get aggregate server statistics from all users."""
        users = await self._get_all_users()
        
        if not users:
            return {
                "total_users": 0, "verified_users": 0, "total_xp": 0,
                "total_coins": 0, "total_messages": 0, "avg_level": 0,
                "max_level": 0, "total_duels": 0, "total_raid_participations": 0,
                "total_trainings": 0, "active_7d": 0, "active_24h": 0,
            }
        
        now = datetime.datetime.now(datetime.timezone.utc)
        
        stats = {
            "total_users": len(users),
            "verified_users": 0,
            "total_xp": 0,
            "total_coins": 0,
            "total_messages": 0,
            "avg_level": 0,
            "max_level": 0,
            "total_duels": 0,
            "total_raid_participations": 0,
            "total_trainings": 0,
            "active_7d": 0,
            "active_24h": 0,
        }
        
        total_level = 0
        
        for uid, u in users.items():
            if u.get("verified"):
                stats["verified_users"] += 1
            stats["total_xp"] += u.get("xp", 0) or 0
            stats["total_coins"] += u.get("coins", 0) or 0
            stats["total_messages"] += u.get("messages", 0) or 0
            
            level = u.get("level", 0) or 0
            total_level += level
            if level > stats["max_level"]:
                stats["max_level"] = level
            
            stats["total_duels"] += (u.get("wins", 0) or 0) + (u.get("losses", 0) or 0)
            stats["total_raid_participations"] += u.get("raid_participation", 0) or 0
            stats["total_trainings"] += u.get("training_attendance", 0) or 0
            
            last_active = u.get("last_active")
            if last_active:
                try:
                    if isinstance(last_active, str):
                        la = datetime.datetime.fromisoformat(last_active.replace("Z", "+00:00"))
                    else:
                        la = last_active
                    
                    if la.tzinfo is None:
                        la = la.replace(tzinfo=datetime.timezone.utc)
                    
                    diff = now - la
                    if diff.total_seconds() < 86400:
                        stats["active_24h"] += 1
                    if diff.total_seconds() < 604800:
                        stats["active_7d"] += 1
                except (ValueError, TypeError):
                    pass
        
        if stats["total_users"] > 0:
            stats["avg_level"] = total_level // stats["total_users"]
        
        return stats
    
    # ==========================================
    # RAIDS & WARS (from proper tables)
    # ==========================================
    
    async def get_recent_raids(self, limit: int = 20) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM raid_sessions ORDER BY created_at DESC LIMIT $1", limit
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_raid_leaderboard(self, limit: int = 20) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT user_id, raids_participated, raids_won, raids_lost, "
                    "total_xp_earned, total_coins_earned, mvp_count "
                    "FROM raid_stats ORDER BY raids_participated DESC LIMIT $1", limit
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_wars(self, limit: int = 10) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM wars ORDER BY created_at DESC LIMIT $1", limit
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_war_record(self) -> Dict:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow('''
                    SELECT 
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE status = 'won') AS wins,
                        COUNT(*) FILTER (WHERE status = 'lost') AS losses,
                        COUNT(*) FILTER (WHERE status = 'draw') AS draws
                    FROM wars WHERE status IN ('won', 'lost', 'draw')
                ''')
                return dict(row) if row else {"total": 0, "wins": 0, "losses": 0, "draws": 0}
        except Exception:
            return {"total": 0, "wins": 0, "losses": 0, "draws": 0}
    
    # ==========================================
    # TOURNAMENTS
    # ==========================================
    
    async def get_tournaments(self, limit: int = 10) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM tournaments ORDER BY created_at DESC LIMIT $1", limit
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    # ==========================================
    # WARNINGS (from JSON blob)
    # ==========================================
    
    async def get_recent_warnings(self, limit: int = 50) -> List[Dict]:
        """Get recent warnings across all users from JSON data."""
        users = await self._get_all_users()
        
        all_warnings = []
        for uid, u in users.items():
            for w in u.get("warnings", []):
                warning = dict(w)
                warning["user_id"] = int(uid)
                warning["active"] = not warning.get("expired", False)
                all_warnings.append(warning)
        
        all_warnings.sort(
            key=lambda w: w.get("timestamp", w.get("date", "")),
            reverse=True
        )
        return all_warnings[:limit]
    
    async def get_user_warnings(self, user_id: int) -> List[Dict]:
        user = await self.get_user(user_id)
        if not user:
            return []
        warnings = user.get("warnings", [])
        for w in warnings:
            w["active"] = not w.get("expired", False)
        return warnings
    
    # ==========================================
    # RECRUITMENT (from proper tables)
    # ==========================================
    
    async def get_open_positions(self) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM recruitment_positions WHERE status = 'open' "
                    "ORDER BY created_at DESC"
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_applications(self, status: str = None, limit: int = 50) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                if status:
                    rows = await conn.fetch(
                        "SELECT * FROM recruitment_applications WHERE status = $1 "
                        "ORDER BY created_at DESC LIMIT $2", status, limit
                    )
                else:
                    rows = await conn.fetch(
                        "SELECT * FROM recruitment_applications "
                        "ORDER BY created_at DESC LIMIT $1", limit
                    )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_user_applications(self, user_id: int) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT a.*, p.title as position_title FROM recruitment_applications a "
                    "LEFT JOIN recruitment_positions p ON a.position_id = p.id "
                    "WHERE a.user_id = $1 ORDER BY a.created_at DESC", user_id
                )
                return [dict(r) for r in rows]
        except Exception:
            return []


# Singleton
db = DashboardDB()
