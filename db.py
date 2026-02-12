"""
✝ THE FALLEN ✝ — Dashboard Database
Connects to the same PostgreSQL database as the Discord bot.
Read-only for safety — the bot handles all writes.
"""

import os
import asyncpg
from typing import Optional, List, Dict, Any


class DashboardDB:
    """Async database connection for the dashboard."""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Create connection pool."""
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
    # USER QUERIES
    # ==========================================
    
    async def get_user(self, user_id: int) -> Optional[Dict]:
        """Get a single user's data."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
            return dict(row) if row else None
    
    async def get_leaderboard(self, sort_by: str = "xp", limit: int = 50, offset: int = 0) -> List[Dict]:
        """Get leaderboard sorted by a column."""
        allowed = {"xp", "level", "coins", "elo_rating", "voice_time", "messages",
                    "wins", "raid_wins", "raid_participation", "weekly_xp", "monthly_xp",
                    "training_attendance", "tryout_attendance"}
        if sort_by not in allowed:
            sort_by = "xp"
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT user_id, xp, level, coins, elo_rating, voice_time, messages, "
                f"wins, losses, raid_wins, raid_losses, raid_participation, "
                f"weekly_xp, monthly_xp, training_attendance, tryout_attendance, "
                f"roblox_username, verified, achievements, last_active "
                f"FROM users ORDER BY {sort_by} DESC NULLS LAST LIMIT $1 OFFSET $2",
                limit, offset
            )
            return [dict(r) for r in rows]
    
    async def get_user_rank(self, user_id: int, sort_by: str = "xp") -> int:
        """Get a user's rank position on a leaderboard."""
        allowed = {"xp", "level", "elo_rating", "voice_time", "messages", "raid_participation"}
        if sort_by not in allowed:
            sort_by = "xp"
        
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT COUNT(*) + 1 AS rank FROM users WHERE {sort_by} > "
                f"(SELECT COALESCE({sort_by}, 0) FROM users WHERE user_id = $1)",
                user_id
            )
            return row["rank"] if row else 0
    
    async def search_users(self, query: str, limit: int = 20) -> List[Dict]:
        """Search users by roblox username."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, xp, level, coins, elo_rating, roblox_username, verified "
                "FROM users WHERE LOWER(roblox_username) LIKE LOWER($1) "
                "ORDER BY xp DESC LIMIT $2",
                f"%{query}%", limit
            )
            return [dict(r) for r in rows]
    
    async def get_total_users(self) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM users")
            return row["cnt"]
    
    # ==========================================
    # STATS / OVERVIEW
    # ==========================================
    
    async def get_server_stats(self) -> Dict:
        """Get aggregate server statistics."""
        async with self.pool.acquire() as conn:
            stats = await conn.fetchrow('''
                SELECT 
                    COUNT(*) AS total_users,
                    COUNT(*) FILTER (WHERE verified = true) AS verified_users,
                    SUM(xp) AS total_xp,
                    SUM(coins) AS total_coins,
                    SUM(messages) AS total_messages,
                    AVG(level)::int AS avg_level,
                    MAX(level) AS max_level,
                    SUM(wins + losses) AS total_duels,
                    SUM(raid_participation) AS total_raid_participations,
                    SUM(training_attendance) AS total_trainings,
                    COUNT(*) FILTER (WHERE last_active > NOW() - INTERVAL '7 days') AS active_7d,
                    COUNT(*) FILTER (WHERE last_active > NOW() - INTERVAL '24 hours') AS active_24h
                FROM users
            ''')
            return dict(stats) if stats else {}
    
    # ==========================================
    # RAIDS & WARS
    # ==========================================
    
    async def get_recent_raids(self, limit: int = 20) -> List[Dict]:
        """Get recent raid sessions."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM raid_sessions ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]
    
    async def get_raid_leaderboard(self, limit: int = 20) -> List[Dict]:
        """Get top raiders by participation."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT user_id, raids_participated, raids_won, raids_lost, "
                "total_xp_earned, total_coins_earned, mvp_count "
                "FROM raid_stats ORDER BY raids_participated DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]
    
    async def get_wars(self, limit: int = 10) -> List[Dict]:
        """Get recent wars."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM wars ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]
    
    async def get_war_record(self) -> Dict:
        """Get overall war W/L record."""
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
    
    # ==========================================
    # TOURNAMENTS
    # ==========================================
    
    async def get_tournaments(self, limit: int = 10) -> List[Dict]:
        """Get recent tournaments."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM tournaments ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]
    
    # ==========================================
    # WARNINGS (Staff only)
    # ==========================================
    
    async def get_recent_warnings(self, limit: int = 50) -> List[Dict]:
        """Get recent warnings."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM warnings WHERE active = true "
                "ORDER BY created_at DESC LIMIT $1", limit
            )
            return [dict(r) for r in rows]
    
    async def get_user_warnings(self, user_id: int) -> List[Dict]:
        """Get all warnings for a user."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM warnings WHERE user_id = $1 ORDER BY created_at DESC",
                user_id
            )
            return [dict(r) for r in rows]
    
    # ==========================================
    # RECRUITMENT
    # ==========================================
    
    async def get_open_positions(self) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM recruitment_positions WHERE status = 'open' "
                "ORDER BY created_at DESC"
            )
            return [dict(r) for r in rows]
    
    async def get_applications(self, status: str = None, limit: int = 50) -> List[Dict]:
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
    
    async def get_user_applications(self, user_id: int) -> List[Dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT a.*, p.title as position_title FROM recruitment_applications a "
                "LEFT JOIN recruitment_positions p ON a.position_id = p.id "
                "WHERE a.user_id = $1 ORDER BY a.created_at DESC", user_id
            )
            return [dict(r) for r in rows]


# Singleton
db = DashboardDB()
