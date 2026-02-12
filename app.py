"""
✝ THE FALLEN ✝ — Dashboard Database
Reads from the bot's PostgreSQL json_data table.

Data sources:
  json_data key='main_data'     → { "users": {...}, "roster": [...] }
  json_data key='duels_data'    → { "elo": {...}, "duel_history": [...] }
  json_data key='warnings_data' → { "users": {...}, "recent_warnings": [...] }
"""

import os
import json
import asyncpg
import datetime
from typing import Optional, List, Dict, Any


class DashboardDB:
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
    # CORE: Load JSON blobs
    # ==========================================
    
    async def _get_json_blob(self, key: str) -> Dict:
        """Load a JSON blob from the json_data table by key."""
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT data FROM json_data WHERE key = $1", key
                )
                if row and row["data"]:
                    d = row["data"]
                    return json.loads(d) if isinstance(d, str) else d
        except Exception as e:
            print(f"[DB] Error loading {key}: {e}")
        return {}
    
    async def _get_main_data(self) -> Dict:
        return await self._get_json_blob("main_data") or {"users": {}, "roster": []}
    
    async def _get_duels_data(self) -> Dict:
        return await self._get_json_blob("duels_data") or {"elo": {}}
    
    async def _get_warnings_data(self) -> Dict:
        return await self._get_json_blob("warnings_data") or {"users": {}, "recent_warnings": []}
    
    async def _get_all_users(self) -> Dict[str, Dict]:
        data = await self._get_main_data()
        return data.get("users", {})
    
    # ==========================================
    # ROSTER / STAGE RANK
    # ==========================================
    
    async def get_roster(self) -> List:
        """Get the 10-slot roster array."""
        data = await self._get_main_data()
        return data.get("roster", [None] * 10)
    
    async def get_stage_rank(self, user_id: int) -> Optional[int]:
        """Get a user's stage rank (1-10) or None if not on roster."""
        roster = await self.get_roster()
        uid = user_id  # roster stores ints or strings
        for i, slot in enumerate(roster):
            if slot is not None and str(slot) == str(uid):
                return i + 1
        return None
    
    # ==========================================
    # USER QUERIES (with ELO merged in)
    # ==========================================
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get a user's full data including ELO and warnings."""
        users = await self._get_all_users()
        user = users.get(str(user_id))
        if not user:
            return None
        
        user["user_id"] = user_id
        
        # Merge ELO
        duels = await self._get_duels_data()
        user["elo_rating"] = duels.get("elo", {}).get(str(user_id), 1000)
        
        # Merge warnings
        warnings_data = await self._get_warnings_data()
        warn_user = warnings_data.get("users", {}).get(str(user_id), {})
        user["warnings"] = warn_user.get("warnings", [])
        user["warning_points"] = warn_user.get("total_points", 0)
        
        # Stage rank
        user["stage_rank"] = await self.get_stage_rank(user_id)
        
        return user
    
    async def get_leaderboard(self, sort_by: str = "xp", limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get leaderboard sorted by a field."""
        allowed = {"xp", "level", "coins", "elo_rating", "voice_time", "messages",
                    "wins", "raid_wins", "raid_participation", "weekly_xp", "monthly_xp",
                    "training_attendance", "tryout_attendance"}
        if sort_by not in allowed:
            sort_by = "xp"
        
        users = await self._get_all_users()
        duels = await self._get_duels_data()
        elo_map = duels.get("elo", {})
        roster = (await self._get_main_data()).get("roster", [])
        
        user_list = []
        for uid, udata in users.items():
            udata["user_id"] = int(uid)
            udata["elo_rating"] = elo_map.get(uid, 1000)
            # Stage rank
            stage = None
            for i, slot in enumerate(roster):
                if slot is not None and str(slot) == uid:
                    stage = i + 1
                    break
            udata["stage_rank"] = stage
            user_list.append(udata)
        
        user_list.sort(key=lambda u: u.get(sort_by, 0) or 0, reverse=True)
        return user_list[offset:offset + limit]
    
    async def get_user_rank(self, user_id: int, sort_by: str = "xp") -> int:
        users = await self._get_all_users()
        uid = str(user_id)
        if uid not in users:
            return 0
        
        if sort_by == "elo_rating":
            duels = await self._get_duels_data()
            elo_map = duels.get("elo", {})
            user_val = elo_map.get(uid, 1000)
            rank = 1
            for other_uid in users:
                if other_uid != uid and elo_map.get(other_uid, 1000) > user_val:
                    rank += 1
            return rank
        
        user_val = users[uid].get(sort_by, 0) or 0
        rank = 1
        for other_uid, other_data in users.items():
            if other_uid != uid and (other_data.get(sort_by, 0) or 0) > user_val:
                rank += 1
        return rank
    
    async def search_users(self, query: str, limit: int = 20) -> List[Dict]:
        users = await self._get_all_users()
        duels = await self._get_duels_data()
        elo_map = duels.get("elo", {})
        query_lower = query.lower()
        
        results = []
        for uid, udata in users.items():
            roblox_name = udata.get("roblox_username") or ""
            if query_lower in roblox_name.lower():
                udata["user_id"] = int(uid)
                udata["elo_rating"] = elo_map.get(uid, 1000)
                results.append(udata)
                if len(results) >= limit:
                    break
        
        results.sort(key=lambda u: u.get("xp", 0) or 0, reverse=True)
        return results
    
    async def get_total_users(self) -> int:
        users = await self._get_all_users()
        return len(users)
    
    # ==========================================
    # STATS
    # ==========================================
    
    async def get_server_stats(self) -> Dict:
        users = await self._get_all_users()
        
        empty = {
            "total_users": 0, "verified_users": 0, "total_xp": 0,
            "total_coins": 0, "total_messages": 0, "avg_level": 0,
            "max_level": 0, "total_duels": 0, "total_raid_participations": 0,
            "total_trainings": 0, "active_7d": 0, "active_24h": 0,
        }
        if not users:
            return empty
        
        now = datetime.datetime.now(datetime.timezone.utc)
        stats = dict(empty)
        stats["total_users"] = len(users)
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
    # WARNINGS
    # ==========================================
    
    async def get_recent_warnings(self, limit: int = 50) -> List[Dict]:
        """Get recent warnings from the warnings_data blob."""
        wdata = await self._get_warnings_data()
        
        # Try the pre-built recent list first
        recent = wdata.get("recent_warnings", [])
        if recent:
            return recent[:limit]
        
        # Fallback: collect from all users
        all_warnings = []
        for uid, uinfo in wdata.get("users", {}).items():
            for w in uinfo.get("warnings", []):
                warning = dict(w)
                warning["user_id"] = int(uid)
                warning["active"] = not warning.get("expired", False)
                all_warnings.append(warning)
        
        all_warnings.sort(
            key=lambda w: w.get("timestamp", ""),
            reverse=True
        )
        return all_warnings[:limit]
    
    async def get_user_warnings(self, user_id: int) -> Dict:
        """Get warning data for a specific user."""
        wdata = await self._get_warnings_data()
        return wdata.get("users", {}).get(str(user_id), {"warnings": [], "total_points": 0})
    
    # ==========================================
    # RAIDS & WARS (from enhanced DB tables)
    # ==========================================
    
    async def get_recent_raids(self, limit: int = 20) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                # Check what columns exist
                cols = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'raid_sessions'"
                )
                if not cols:
                    return []
                col_names = [c["column_name"] for c in cols]
                order = "created_at" if "created_at" in col_names else "id"
                rows = await conn.fetch(
                    f"SELECT * FROM raid_sessions ORDER BY {order} DESC LIMIT $1", limit
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_raid_leaderboard(self, limit: int = 20) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM raid_stats ORDER BY raids_participated DESC LIMIT $1", limit
                )
                return [dict(r) for r in rows]
        except Exception:
            return []
    
    async def get_wars(self, limit: int = 10) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                cols = await conn.fetch(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'wars'"
                )
                if not cols:
                    return []
                col_names = [c["column_name"] for c in cols]
                order = "created_at" if "created_at" in col_names else "id"
                rows = await conn.fetch(
                    f"SELECT * FROM wars ORDER BY {order} DESC LIMIT $1", limit
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
    # RECRUITMENT (from enhanced DB tables)
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


db = DashboardDB()
