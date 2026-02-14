"""
✝ THE FALLEN ✝ — Dashboard Database (v3)
All data sources: main_data, duels_data, warnings_data + enhanced DB tables.
Auto-role config, staff management, avatar cache.
"""

import os, json, asyncpg, datetime
from typing import Optional, List, Dict
from collections import Counter

SHOP_ITEMS = {
    "private_tryout": {"name": "⚔️ Private Tryout Ticket", "price": 500, "type": "ticket"},
    "custom_role": {"name": "🎨 Custom Role Request", "price": 2000, "type": "ticket"},
    "custom_role_color": {"name": "🎨 Custom Role Color", "price": 1500, "type": "ticket"},
    "hoisted_role": {"name": "👑 Hoisted Role", "price": 5000, "type": "ticket"},
    "custom_level_bg": {"name": "🖼️ Custom Level Card BG", "price": 3000, "type": "background"},
    "elo_shield": {"name": "🛡️ ELO Shield", "price": 1000, "type": "consumable"},
    "training_reserve": {"name": "📋 Training Slot Reserve", "price": 300, "type": "consumable"},
    "coaching_session": {"name": "🎯 1v1 Coaching Session", "price": 1500, "type": "coaching"},
}


class DashboardDB:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        url = os.getenv("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL not set")
        self.pool = await asyncpg.create_pool(
            url, min_size=2, max_size=8, command_timeout=15,
            server_settings={"application_name": "FallenDashboard"}
        )
        async with self.pool.acquire() as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS dashboard_audit_log (
                id SERIAL PRIMARY KEY, staff_id BIGINT NOT NULL, staff_name TEXT,
                action TEXT NOT NULL, target_id BIGINT, details TEXT,
                created_at TIMESTAMP DEFAULT NOW())''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS staff_roles (
                id SERIAL PRIMARY KEY, discord_user_id BIGINT UNIQUE NOT NULL,
                display_name TEXT DEFAULT '', permission_tier INTEGER DEFAULT 1,
                added_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS role_config (
                id SERIAL PRIMARY KEY, discord_role_id BIGINT UNIQUE NOT NULL,
                role_name TEXT DEFAULT '', permission_tier INTEGER DEFAULT 1,
                added_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
        print("✅ Dashboard DB connected")

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ── JSON blob loaders ──────────────────────────
    async def _blob(self, key: str) -> Dict:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT data FROM json_data WHERE key = $1", key)
                if row and row["data"]:
                    d = row["data"]
                    return json.loads(d) if isinstance(d, str) else d
        except Exception as e:
            print(f"[DB] blob({key}): {e}")
        return {}

    async def _main(self) -> Dict:
        return await self._blob("main_data") or {"users": {}, "roster": []}

    async def _duels(self) -> Dict:
        return await self._blob("duels_data") or {"elo": {}, "duel_history": []}

    async def _warnings(self) -> Dict:
        return await self._blob("warnings_data") or {"users": {}, "recent_warnings": []}

    async def _users(self) -> Dict[str, Dict]:
        return (await self._main()).get("users", {})

    async def _qall(self, query: str, *args) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                return [dict(r) for r in await conn.fetch(query, *args)]
        except:
            return []

    async def _qone(self, query: str, *args) -> Optional[Dict]:
        try:
            async with self.pool.acquire() as conn:
                r = await conn.fetchrow(query, *args)
                return dict(r) if r else None
        except:
            return None

    # ── Avatar helper ──────────────────────────────
    def get_avatar_url(self, user: Dict) -> str:
        if user.get("avatar_url"):
            return user["avatar_url"]
        uid = user.get("user_id", 0)
        return f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"

    # ── Roster ─────────────────────────────────────
    async def get_roster(self) -> List:
        return (await self._main()).get("roster", [None] * 10)

    async def get_roster_with_names(self) -> List[Dict]:
        roster = await self.get_roster()
        users = await self._users()
        result = []
        for i, slot in enumerate(roster if roster else [None]*10):
            if slot is not None:
                uid = str(slot)
                u = users.get(uid, {})
                name = u.get("roblox_username") or u.get("username") or f"User {uid}"
                result.append({"slot": i+1, "user_id": uid, "name": name, "filled": True})
            else:
                result.append({"slot": i+1, "user_id": None, "name": None, "filled": False})
        return result

    async def get_stage_rank(self, uid: int) -> Optional[int]:
        for i, slot in enumerate(await self.get_roster()):
            if slot is not None and str(slot) == str(uid):
                return i + 1
        return None

    # ── Single user (merged all sources) ───────────
    async def get_user(self, user_id: int) -> Optional[Dict]:
        users = await self._users()
        u = users.get(str(user_id))
        if not u:
            return None
        u["user_id"] = user_id
        duels = await self._duels()
        u["elo_rating"] = duels.get("elo", {}).get(str(user_id), 1000)
        wu = (await self._warnings()).get("users", {}).get(str(user_id), {})
        u["warnings"] = wu.get("warnings", [])
        u["warning_points"] = wu.get("total_points", 0)
        u["stage_rank"] = await self.get_stage_rank(user_id)
        u["avatar_url"] = self.get_avatar_url(u)
        u["inventory_items"] = [
            {"id": iid, **(SHOP_ITEMS.get(iid, {"name": iid, "price": 0, "type": "unknown"}))}
            for iid in (u.get("inventory") or [])
        ]
        return u

    # ── Leaderboard ────────────────────────────────
    async def get_leaderboard(self, sort_by: str = "xp", limit: int = 50, offset: int = 0) -> List[Dict]:
        allowed = {"xp", "level", "coins", "elo_rating", "voice_time", "messages",
                    "wins", "raid_wins", "raid_participation", "weekly_xp", "monthly_xp",
                    "training_attendance", "tryout_attendance"}
        if sort_by not in allowed:
            sort_by = "xp"
        users = await self._users()
        elo_map = (await self._duels()).get("elo", {})
        lst = []
        for uid, u in users.items():
            u["user_id"] = int(uid)
            u["elo_rating"] = elo_map.get(uid, 1000)
            u["avatar_url"] = self.get_avatar_url(u)
            lst.append(u)
        lst.sort(key=lambda x: x.get(sort_by, 0) or 0, reverse=True)
        return lst[offset:offset + limit]

    async def get_user_rank(self, user_id: int, sort_by: str = "xp") -> int:
        users = await self._users()
        uid = str(user_id)
        if uid not in users: return 0
        if sort_by == "elo_rating":
            elo = (await self._duels()).get("elo", {})
            val = elo.get(uid, 1000)
            return 1 + sum(1 for u in users if u != uid and elo.get(u, 1000) > val)
        val = users[uid].get(sort_by, 0) or 0
        return 1 + sum(1 for u, d in users.items() if u != uid and (d.get(sort_by, 0) or 0) > val)

    async def search_users(self, query: str, limit: int = 20) -> List[Dict]:
        users = await self._users()
        elo_map = (await self._duels()).get("elo", {})
        q = query.lower()
        results = []
        for uid, u in users.items():
            name = u.get("roblox_username") or ""
            if q in name.lower() or q in uid:
                u["user_id"] = int(uid)
                u["elo_rating"] = elo_map.get(uid, 1000)
                u["avatar_url"] = self.get_avatar_url(u)
                results.append(u)
                if len(results) >= limit: break
        results.sort(key=lambda x: x.get("xp", 0) or 0, reverse=True)
        return results

    async def get_total_users(self) -> int:
        return len(await self._users())

    # ── Duel History ───────────────────────────────
    async def get_duel_history(self, limit: int = 50) -> List[Dict]:
        h = (await self._duels()).get("duel_history", [])
        h.sort(key=lambda d: d.get("completed_at", ""), reverse=True)
        return h[:limit]

    async def get_user_duel_history(self, user_id: int, limit: int = 30) -> List[Dict]:
        uid = str(user_id)
        h = (await self._duels()).get("duel_history", [])
        filtered = [d for d in h if d.get("winner") == uid or d.get("loser") == uid]
        filtered.sort(key=lambda d: d.get("completed_at", ""), reverse=True)
        return filtered[:limit]

    async def get_elo_distribution(self) -> Dict:
        elo_map = (await self._duels()).get("elo", {})
        buckets = Counter()
        for elo in elo_map.values():
            if elo >= 2000: buckets["2000+ GM"] += 1
            elif elo >= 1800: buckets["1800-1999 Diamond"] += 1
            elif elo >= 1600: buckets["1600-1799 Platinum"] += 1
            elif elo >= 1400: buckets["1400-1599 Gold"] += 1
            elif elo >= 1200: buckets["1200-1399 Silver"] += 1
            else: buckets["<1200 Bronze"] += 1
        return dict(buckets)

    # ── Economy ────────────────────────────────────
    async def get_economy_stats(self) -> Dict:
        users = await self._users()
        total = sum(u.get("coins", 0) or 0 for u in users.values())
        richest = sorted(users.items(), key=lambda x: x[1].get("coins", 0) or 0, reverse=True)[:10]
        return {
            "total_coins_circulation": total,
            "avg_coins": total // max(len(users), 1),
            "richest": [{"user_id": int(uid), "coins": u.get("coins", 0) or 0,
                         "name": u.get("roblox_username", "Unknown"),
                         "level": u.get("level", 0)} for uid, u in richest],
        }

    async def get_shop_catalog(self) -> List[Dict]:
        return [{"id": k, **v} for k, v in SHOP_ITEMS.items()]

    # ── Analytics ──────────────────────────────────
    async def get_analytics(self) -> Dict:
        users = await self._users()
        now = datetime.datetime.now(datetime.timezone.utc)
        level_dist = Counter()
        activity = {"24h": 0, "7d": 0, "30d": 0, "inactive": 0}
        msg_total = voice_total = verified_count = level_sum = 0
        for u in users.values():
            lvl = u.get("level", 0) or 0
            bucket = f"{(lvl // 10) * 10}-{(lvl // 10) * 10 + 9}"
            level_dist[bucket] += 1
            level_sum += lvl
            msg_total += u.get("messages", 0) or 0
            voice_total += u.get("voice_time", 0) or 0
            if u.get("verified"): verified_count += 1
            la = u.get("last_active")
            if la:
                try:
                    if isinstance(la, str): la = datetime.datetime.fromisoformat(la.replace("Z", "+00:00"))
                    if la.tzinfo is None: la = la.replace(tzinfo=datetime.timezone.utc)
                    days = (now - la).total_seconds() / 86400
                    if days < 1: activity["24h"] += 1
                    elif days < 7: activity["7d"] += 1
                    elif days < 30: activity["30d"] += 1
                    else: activity["inactive"] += 1
                except: activity["inactive"] += 1
            else: activity["inactive"] += 1
        def top5(key):
            s = sorted(users.items(), key=lambda x: x[1].get(key, 0) or 0, reverse=True)[:5]
            return [{"name": u.get("roblox_username", "Unknown"), "value": u.get(key, 0) or 0} for _, u in s]
        return {
            "total_users": len(users), "verified_count": verified_count,
            "avg_level": level_sum // max(len(users), 1),
            "level_distribution": dict(sorted(level_dist.items())),
            "activity_breakdown": activity, "total_messages": msg_total,
            "total_voice_seconds": voice_total, "top_xp": top5("xp"),
            "top_messages": top5("messages"), "top_voice": top5("voice_time"),
            "top_raiders": top5("raid_participation"), "top_duelers": top5("wins"),
            "elo_distribution": await self.get_elo_distribution(),
        }

    # ── Server Stats ───────────────────────────────
    async def get_server_stats(self) -> Dict:
        users = await self._users()
        empty = {"total_users": 0, "verified_users": 0, "total_xp": 0, "total_coins": 0,
                 "total_messages": 0, "avg_level": 0, "max_level": 0, "total_duels": 0,
                 "total_raid_participations": 0, "total_trainings": 0, "active_7d": 0, "active_24h": 0}
        if not users: return empty
        now = datetime.datetime.now(datetime.timezone.utc)
        s = dict(empty)
        s["total_users"] = len(users)
        tl = 0
        for u in users.values():
            if u.get("verified"): s["verified_users"] += 1
            s["total_xp"] += u.get("xp", 0) or 0
            s["total_coins"] += u.get("coins", 0) or 0
            s["total_messages"] += u.get("messages", 0) or 0
            lvl = u.get("level", 0) or 0
            tl += lvl
            if lvl > s["max_level"]: s["max_level"] = lvl
            s["total_duels"] += (u.get("wins", 0) or 0) + (u.get("losses", 0) or 0)
            s["total_raid_participations"] += u.get("raid_participation", 0) or 0
            s["total_trainings"] += u.get("training_attendance", 0) or 0
            la = u.get("last_active")
            if la:
                try:
                    if isinstance(la, str): la = datetime.datetime.fromisoformat(la.replace("Z", "+00:00"))
                    if la.tzinfo is None: la = la.replace(tzinfo=datetime.timezone.utc)
                    diff = (now - la).total_seconds()
                    if diff < 86400: s["active_24h"] += 1
                    if diff < 604800: s["active_7d"] += 1
                except: pass
        s["avg_level"] = tl // s["total_users"]
        return s

    # ── Warnings ───────────────────────────────────
    async def get_recent_warnings(self, limit: int = 50) -> List[Dict]:
        wdata = await self._warnings()
        recent = wdata.get("recent_warnings", [])
        if recent: return recent[:limit]
        all_w = []
        for uid, info in wdata.get("users", {}).items():
            for w in info.get("warnings", []):
                w2 = dict(w); w2["user_id"] = int(uid); w2["active"] = not w.get("expired", False)
                all_w.append(w2)
        all_w.sort(key=lambda w: w.get("timestamp", ""), reverse=True)
        return all_w[:limit]

    async def get_user_warnings(self, user_id: int) -> Dict:
        return (await self._warnings()).get("users", {}).get(
            str(user_id), {"warnings": [], "total_points": 0})

    # ── Raids & Wars ───────────────────────────────
    async def get_recent_raids(self, limit=20) -> List[Dict]:
        return await self._qall("SELECT * FROM raid_sessions ORDER BY id DESC LIMIT $1", limit)

    async def get_raid_leaderboard(self, limit=20) -> List[Dict]:
        result = await self._qall("SELECT * FROM raid_stats ORDER BY raids_participated DESC LIMIT $1", limit)
        if result: return result
        users = await self._users()
        raiders = []
        for uid, u in users.items():
            rp = u.get("raid_participation", 0) or 0
            if rp > 0:
                raiders.append({
                    "user_id": int(uid), "roblox_username": u.get("roblox_username", "Unknown"),
                    "raids_participated": rp, "raid_participation": rp,
                    "raids_won": u.get("raid_wins", 0) or 0, "raid_wins": u.get("raid_wins", 0) or 0,
                    "mvp_count": u.get("mvp_count", 0) or 0,
                })
        raiders.sort(key=lambda x: x["raids_participated"], reverse=True)
        return raiders[:limit]

    async def get_wars(self, limit=10) -> List[Dict]:
        return await self._qall("SELECT * FROM wars ORDER BY id DESC LIMIT $1", limit)

    async def get_war_record(self) -> Dict:
        r = await self._qone("""SELECT COUNT(*) total,
            COUNT(*) FILTER (WHERE status='won') wins,
            COUNT(*) FILTER (WHERE status='lost') losses,
            COUNT(*) FILTER (WHERE status='draw') draws
            FROM wars WHERE status IN ('won','lost','draw')""")
        return r or {"total": 0, "wins": 0, "losses": 0, "draws": 0}

    # ── Recruitment ────────────────────────────────
    async def get_open_positions(self) -> List[Dict]:
        return await self._qall("SELECT * FROM recruitment_positions WHERE status='open' ORDER BY created_at DESC")

    async def get_applications(self, status=None, limit=50) -> List[Dict]:
        if status:
            return await self._qall("SELECT * FROM recruitment_applications WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM recruitment_applications ORDER BY created_at DESC LIMIT $1", limit)

    async def get_user_applications(self, user_id: int) -> List[Dict]:
        return await self._qall(
            "SELECT a.*, p.title as position_title FROM recruitment_applications a "
            "LEFT JOIN recruitment_positions p ON a.position_id=p.id "
            "WHERE a.user_id=$1 ORDER BY a.created_at DESC", user_id)

    async def submit_application(self, user_id: int, position_id: int, answers: str) -> bool:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO recruitment_applications (user_id, position_id, answers, status) "
                    "VALUES ($1, $2, $3, 'applied')", user_id, position_id, answers)
            return True
        except Exception as e:
            print(f"[DB] Application submit error: {e}")
            return False

    # ── Audit Log ──────────────────────────────────
    async def add_audit(self, staff_id, staff_name, action, target_id=None, details=None):
        try:
            async with self.pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO dashboard_audit_log (staff_id, staff_name, action, target_id, details) "
                    "VALUES ($1,$2,$3,$4,$5)", staff_id, staff_name, action, target_id, details)
        except Exception as e:
            print(f"[AUDIT] {e}")

    async def get_audit_log(self, limit=100) -> List[Dict]:
        return await self._qall("SELECT * FROM dashboard_audit_log ORDER BY created_at DESC LIMIT $1", limit)

    # ── Guardian Stats ─────────────────────────
    async def get_guardian_stats(self) -> Dict:
        data = await self._blob("guardian_stats")
        return data or {"commands_today": 0, "errors_today": 0, "active_abuse_flags": 0,
                        "abuse_scores": {}, "top_users_today": [], "restricted_users": [], "updated_at": None}

    async def get_guardian_audit_events(self, limit=50) -> List[Dict]:
        return await self._qall(
            "SELECT * FROM dashboard_audit_log WHERE action LIKE 'guardian_%%' "
            "ORDER BY created_at DESC LIMIT $1", limit)

    # ── Pending Actions ────────────────────────
    async def queue_action(self, action_type, target_user_id, staff_id, staff_name, params=None) -> int:
        try:
            async with self.pool.acquire() as conn:
                await conn.execute("""CREATE TABLE IF NOT EXISTS pending_dashboard_actions (
                    id SERIAL PRIMARY KEY, action_type TEXT NOT NULL,
                    target_user_id BIGINT NOT NULL, staff_id BIGINT NOT NULL,
                    staff_name TEXT, params JSONB DEFAULT '{}',
                    status TEXT DEFAULT 'pending', result TEXT,
                    created_at TIMESTAMP DEFAULT NOW(), executed_at TIMESTAMP)""")
                row = await conn.fetchrow(
                    "INSERT INTO pending_dashboard_actions "
                    "(action_type, target_user_id, staff_id, staff_name, params) "
                    "VALUES ($1,$2,$3,$4,$5) RETURNING id",
                    action_type, target_user_id, staff_id, staff_name, json.dumps(params or {}))
                return row["id"] if row else 0
        except Exception as e:
            print(f"[QUEUE] {e}")
            return 0

    async def get_pending_actions(self, limit=50) -> List[Dict]:
        return await self._qall("SELECT * FROM pending_dashboard_actions ORDER BY created_at DESC LIMIT $1", limit)

    async def get_action_history(self, target_id=None, limit=30) -> List[Dict]:
        if target_id:
            return await self._qall(
                "SELECT * FROM pending_dashboard_actions WHERE target_user_id = $1 ORDER BY created_at DESC LIMIT $2", target_id, limit)
        return await self._qall("SELECT * FROM pending_dashboard_actions ORDER BY created_at DESC LIMIT $1", limit)

    async def get_transactions(self, user_id=None, limit=50) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                if user_id:
                    rows = await conn.fetch("SELECT * FROM coin_transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2", user_id, limit)
                else:
                    rows = await conn.fetch("SELECT * FROM coin_transactions ORDER BY created_at DESC LIMIT $1", limit)
                return [dict(r) for r in rows]
        except: return []

    # ══════════════════════════════════════════════
    # STAFF ROLE MANAGEMENT
    # ══════════════════════════════════════════════

    async def get_staff_members(self) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                return [dict(r) for r in await conn.fetch("SELECT * FROM staff_roles ORDER BY permission_tier DESC, created_at ASC")]
        except: return []

    async def add_staff_member(self, discord_user_id, display_name, permission_tier, added_by):
        async with self.pool.acquire() as conn:
            await conn.execute('''INSERT INTO staff_roles (discord_user_id, display_name, permission_tier, added_by)
                VALUES ($1, $2, $3, $4) ON CONFLICT (discord_user_id) DO UPDATE SET display_name = $2, permission_tier = $3''',
                discord_user_id, display_name, permission_tier, added_by)

    async def remove_staff_member(self, discord_user_id):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM staff_roles WHERE discord_user_id = $1", discord_user_id)

    async def is_db_staff(self, discord_user_id) -> tuple:
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow("SELECT permission_tier FROM staff_roles WHERE discord_user_id = $1", discord_user_id)
                if row: return True, row["permission_tier"]
                return False, 0
        except: return False, 0

    # ══════════════════════════════════════════════
    # AUTO-ROLE CONFIGURATION
    # ══════════════════════════════════════════════

    async def get_role_configs(self) -> List[Dict]:
        try:
            async with self.pool.acquire() as conn:
                return [dict(r) for r in await conn.fetch("SELECT * FROM role_config ORDER BY permission_tier DESC, created_at ASC")]
        except: return []

    async def add_role_config(self, discord_role_id, role_name, permission_tier, added_by):
        async with self.pool.acquire() as conn:
            await conn.execute('''INSERT INTO role_config (discord_role_id, role_name, permission_tier, added_by)
                VALUES ($1, $2, $3, $4) ON CONFLICT (discord_role_id) DO UPDATE SET role_name = $2, permission_tier = $3''',
                discord_role_id, role_name, permission_tier, added_by)

    async def remove_role_config(self, discord_role_id):
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM role_config WHERE discord_role_id = $1", discord_role_id)

    async def check_role_permissions(self, role_ids: list) -> tuple:
        if not role_ids: return False, 0
        try:
            async with self.pool.acquire() as conn:
                role_ids_int = [int(r) for r in role_ids]
                rows = await conn.fetch("SELECT permission_tier FROM role_config WHERE discord_role_id = ANY($1)", role_ids_int)
                if rows:
                    return True, max(r["permission_tier"] for r in rows)
                return False, 0
        except Exception as e:
            print(f"[DB] check_role_permissions: {e}")
            return False, 0


WARNING_CATEGORIES = {
    "spam": {"points": 1, "name": "Spamming"}, "arguing": {"points": 2, "name": "Arguing"},
    "disrespect": {"points": 2, "name": "Disrespect"}, "slightnsfw": {"points": 3, "name": "Slight NSFW"},
    "slightracism": {"points": 3, "name": "Slight Racism"}, "nsfw": {"points": 4, "name": "NSFW Content"},
    "religion": {"points": 4, "name": "Religion Disrespect"}, "fighting": {"points": 4, "name": "Fighting After Mute"},
    "impersonate": {"points": 4, "name": "Impersonating Staff"}, "racism": {"points": 4, "name": "Racism"},
    "severe": {"points": 5, "name": "Severe Offense"},
    "pedo": {"points": 999, "name": "Pedo Content/Defense", "instant_ban": True},
    "grape": {"points": 999, "name": "SA Jokes/Threats", "instant_ban": True},
    "extremeracism": {"points": 999, "name": "Extreme Racism", "instant_ban": True},
    "hardr": {"points": 999, "name": "Hard R", "instant_ban": True},
    "nword": {"points": 999, "name": "Excessive N Word", "instant_ban": True},
    "nazism": {"points": 999, "name": "Glorifying Nazism", "instant_ban": True},
    "hatespeech": {"points": 999, "name": "Extreme Hate Speech", "instant_ban": True},
    "homophobia": {"points": 999, "name": "Extreme Homophobia", "instant_ban": True},
    "extremereligion": {"points": 999, "name": "Extreme Religion Disrespect", "instant_ban": True},
    "threats": {"points": 999, "name": "Death Threats", "instant_ban": True},
    "doxx": {"points": 999, "name": "Doxxing", "instant_ban": True},
    "purensfw": {"points": 999, "name": "Pure NSFW/Porn", "instant_ban": True},
    "gore": {"points": 999, "name": "Extreme Gore", "instant_ban": True},
    "graphic": {"points": 999, "name": "Graphic Content", "instant_ban": True},
    "alt": {"points": 999, "name": "Alt Account", "instant_ban": True},
    "raid": {"points": 999, "name": "Nuking/Raiding", "instant_ban": True},
}

db = DashboardDB()
