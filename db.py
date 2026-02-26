"""
THE FALLEN - Dashboard Database (v5.1 - Complete Feature Set)
All data: json blobs + 25 relational tables for full clan management.
"""
import os, json, asyncpg, datetime, hashlib, random
from typing import Optional, List, Dict
from collections import Counter

SHOP_ITEMS = {
    "private_tryout": {"name": "Private Tryout Ticket", "price": 500, "type": "ticket"},
    "custom_role": {"name": "Custom Role Request", "price": 2000, "type": "ticket"},
    "custom_role_color": {"name": "Custom Role Color", "price": 1500, "type": "ticket"},
    "hoisted_role": {"name": "Hoisted Role", "price": 5000, "type": "ticket"},
    "custom_level_bg": {"name": "Custom Level Card BG", "price": 3000, "type": "background"},
    "elo_shield": {"name": "ELO Shield", "price": 1000, "type": "consumable"},
    "training_reserve": {"name": "Training Slot Reserve", "price": 300, "type": "consumable"},
    "coaching_session": {"name": "1v1 Coaching Session", "price": 1500, "type": "coaching"},
}
LEVEL_CARD_BACKGROUNDS = {
    "crimson_flame": "https://i.imgur.com/8QjK4Nf.png",
    "dark_forest": "https://i.imgur.com/VkXcNQz.png",
    "midnight_city": "https://i.imgur.com/RJ3qYxW.png",
    "blood_moon": "https://i.imgur.com/WzC7pLf.png",
    "shadow_realm": "https://i.imgur.com/PqK8vNd.png",
    "neon_grid": "https://i.imgur.com/LmB9xTc.png",
    "volcanic": "https://i.imgur.com/dFhK2Np.png",
    "fallen_crest": "https://i.imgur.com/Jx9mNvP.png",
}
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
# Default rank ladder
DEFAULT_RANKS = [
    {"rank": "Recruit", "min_xp": 0, "min_level": 0, "perks": "Basic access", "auto_promote": True},
    {"rank": "Member", "min_xp": 500, "min_level": 5, "perks": "Economy access, duels", "auto_promote": True},
    {"rank": "Veteran", "min_xp": 2000, "min_level": 15, "perks": "Raid participation", "auto_promote": True},
    {"rank": "Elite", "min_xp": 5000, "min_level": 25, "perks": "Tournament entry, custom role color", "auto_promote": True},
    {"rank": "Champion", "min_xp": 15000, "min_level": 40, "perks": "Hoisted role, coaching access", "auto_promote": False},
    {"rank": "Legend", "min_xp": 50000, "min_level": 60, "perks": "All perks, legacy badge", "auto_promote": False},
]
EMBED_CATEGORIES = [
    "rules", "roles", "ranks", "economy", "duels", "raids", "events", "tournaments",
    "welcome", "verification", "faq", "announcements", "applications", "partnerships",
    "staff_info", "custom"
]
ESCALATION_THRESHOLDS = [
    {"points": 5, "action": "timeout", "duration_minutes": 30, "reason": "Auto: 5 warning points"},
    {"points": 10, "action": "timeout", "duration_minutes": 1440, "reason": "Auto: 10 warning points (24h)"},
    {"points": 15, "action": "kick", "reason": "Auto: 15 warning points"},
    {"points": 20, "action": "ban", "reason": "Auto: 20 warning points - permanent ban"},
]
ACTIVITY_WEIGHTS = {"messages": 1.0, "voice_minutes": 0.5, "duels": 5.0, "raids": 10.0, "events": 8.0}

class DashboardDB:
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        url = os.getenv("DATABASE_URL")
        if not url:
            print("DATABASE_URL not set - running without database")
            return
        try:
            self.pool = await asyncpg.create_pool(url, min_size=2, max_size=10, command_timeout=15,
                server_settings={"application_name": "FallenDashboard"})
        except Exception as e:
            print(f"Database connection failed: {e} - running without database")
            return
        async with self.pool.acquire() as c:
            # Core tables
            await c.execute('''CREATE TABLE IF NOT EXISTS dashboard_audit_log (
                id SERIAL PRIMARY KEY, staff_id BIGINT NOT NULL, staff_name TEXT,
                action TEXT NOT NULL, target_id BIGINT, details TEXT, ip_address TEXT,
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS staff_roles (
                id SERIAL PRIMARY KEY, discord_user_id BIGINT UNIQUE NOT NULL,
                display_name TEXT DEFAULT '', permission_tier INTEGER DEFAULT 1,
                section_perms JSONB DEFAULT '{}', added_by BIGINT,
                last_login TIMESTAMP, last_action TIMESTAMP, last_action_desc TEXT,
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS role_config (
                id SERIAL PRIMARY KEY, discord_role_id BIGINT UNIQUE NOT NULL,
                role_name TEXT DEFAULT '', permission_tier INTEGER DEFAULT 1,
                section_perms JSONB DEFAULT '{}',
                added_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS pending_dashboard_actions (
                id SERIAL PRIMARY KEY, action_type TEXT NOT NULL, target_user_id BIGINT NOT NULL,
                staff_id BIGINT NOT NULL, staff_name TEXT, params JSONB DEFAULT '{}',
                status TEXT DEFAULT 'pending', result TEXT,
                created_at TIMESTAMP DEFAULT NOW(), executed_at TIMESTAMP)''')
            # Staff sessions & notes
            await c.execute('''CREATE TABLE IF NOT EXISTS staff_sessions (
                id SERIAL PRIMARY KEY, staff_id BIGINT NOT NULL, staff_name TEXT,
                ip_address TEXT, action TEXT DEFAULT 'login',
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS staff_notes (
                id SERIAL PRIMARY KEY, target_user_id BIGINT NOT NULL,
                staff_id BIGINT NOT NULL, staff_name TEXT, note TEXT NOT NULL,
                pinned BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW())''')
            # Moderation cases
            await c.execute('''CREATE TABLE IF NOT EXISTS mod_cases (
                id SERIAL PRIMARY KEY, target_user_id BIGINT NOT NULL,
                case_type TEXT NOT NULL, category TEXT, severity TEXT DEFAULT 'medium',
                reason TEXT, points INTEGER DEFAULT 0,
                staff_id BIGINT NOT NULL, staff_name TEXT,
                status TEXT DEFAULT 'active', resolution TEXT,
                resolved_by BIGINT, resolved_at TIMESTAMP,
                discord_synced BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS mod_evidence (
                id SERIAL PRIMARY KEY, case_id INTEGER REFERENCES mod_cases(id) ON DELETE CASCADE,
                evidence_type TEXT DEFAULT 'note', content TEXT NOT NULL,
                added_by BIGINT, added_by_name TEXT,
                created_at TIMESTAMP DEFAULT NOW())''')
            # Rank system
            await c.execute('''CREATE TABLE IF NOT EXISTS rank_ladder (
                id SERIAL PRIMARY KEY, rank_name TEXT NOT NULL, rank_order INTEGER DEFAULT 0,
                min_xp INTEGER DEFAULT 0, min_level INTEGER DEFAULT 0,
                discord_role_id BIGINT, perks TEXT DEFAULT '',
                auto_promote BOOLEAN DEFAULT FALSE, color TEXT DEFAULT '#888888',
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS rank_history (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                old_rank TEXT, new_rank TEXT, reason TEXT DEFAULT 'auto',
                changed_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
            # Events & raids scheduling
            await c.execute('''CREATE TABLE IF NOT EXISTS scheduled_events (
                id SERIAL PRIMARY KEY, title TEXT NOT NULL, event_type TEXT DEFAULT 'raid',
                description TEXT DEFAULT '', scheduled_at TIMESTAMP,
                duration_minutes INTEGER DEFAULT 60,
                max_participants INTEGER DEFAULT 0, min_level INTEGER DEFAULT 0,
                xp_reward INTEGER DEFAULT 0, coin_reward INTEGER DEFAULT 0,
                status TEXT DEFAULT 'scheduled', created_by BIGINT, created_by_name TEXT,
                started_at TIMESTAMP, completed_at TIMESTAMP,
                summary TEXT DEFAULT '', created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS event_signups (
                id SERIAL PRIMARY KEY, event_id INTEGER REFERENCES scheduled_events(id) ON DELETE CASCADE,
                user_id BIGINT NOT NULL, status TEXT DEFAULT 'signed_up',
                attended BOOLEAN DEFAULT FALSE, performance_score INTEGER DEFAULT 0,
                rewards_given BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(event_id, user_id))''')
            # Reward system
            await c.execute('''CREATE TABLE IF NOT EXISTS reward_mappings (
                id SERIAL PRIMARY KEY, trigger_type TEXT NOT NULL,
                trigger_value TEXT NOT NULL, reward_type TEXT NOT NULL,
                reward_value TEXT NOT NULL, description TEXT DEFAULT '',
                cooldown_hours INTEGER DEFAULT 0, active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS reward_claims (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                reward_id INTEGER REFERENCES reward_mappings(id),
                claimed_at TIMESTAMP DEFAULT NOW())''')
            # Embed manager
            await c.execute('''CREATE TABLE IF NOT EXISTS embed_store (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT DEFAULT 'general',
                embed_data JSONB NOT NULL, active BOOLEAN DEFAULT TRUE,
                channel_id BIGINT, message_id BIGINT,
                interactions JSONB DEFAULT '[]',
                last_pushed TIMESTAMP, created_by BIGINT,
                created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS embed_history (
                id SERIAL PRIMARY KEY, embed_id INTEGER REFERENCES embed_store(id) ON DELETE CASCADE,
                embed_data JSONB NOT NULL, version INTEGER DEFAULT 1,
                changed_by BIGINT, changed_by_name TEXT,
                created_at TIMESTAMP DEFAULT NOW())''')
            # Notifications
            await c.execute('''CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY, target_staff_id BIGINT,
                notif_type TEXT NOT NULL, title TEXT NOT NULL,
                message TEXT DEFAULT '', link TEXT DEFAULT '',
                is_read BOOLEAN DEFAULT FALSE, is_global BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW())''')
            # User preferences
            await c.execute('''CREATE TABLE IF NOT EXISTS user_preferences (
                user_id BIGINT PRIMARY KEY, theme TEXT DEFAULT 'dark',
                notifications_enabled BOOLEAN DEFAULT TRUE,
                data JSONB DEFAULT '{}', updated_at TIMESTAMP DEFAULT NOW())''')
            # Bot status
            await c.execute('''CREATE TABLE IF NOT EXISTS bot_status_log (
                id SERIAL PRIMARY KEY, status TEXT DEFAULT 'online',
                event TEXT NOT NULL, details TEXT DEFAULT '',
                latency_ms INTEGER DEFAULT 0, guild_count INTEGER DEFAULT 0,
                member_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())''')
            # Clan rules
            await c.execute('''CREATE TABLE IF NOT EXISTS clan_rules (
                id SERIAL PRIMARY KEY, section_title TEXT NOT NULL,
                section_order INTEGER DEFAULT 0, content TEXT NOT NULL,
                updated_by BIGINT, updated_at TIMESTAMP DEFAULT NOW())''')
            # Seasonal config
            await c.execute('''CREATE TABLE IF NOT EXISTS seasonal_config (
                id SERIAL PRIMARY KEY, season_name TEXT NOT NULL,
                season_number INTEGER DEFAULT 1,
                start_date TIMESTAMP, end_date TIMESTAMP,
                status TEXT DEFAULT 'upcoming',
                reset_xp BOOLEAN DEFAULT FALSE, reset_elo BOOLEAN DEFAULT FALSE,
                reset_coins BOOLEAN DEFAULT FALSE,
                rewards JSONB DEFAULT '{}', archive_data JSONB DEFAULT '{}',
                created_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
            # Recruitment votes
            await c.execute('''CREATE TABLE IF NOT EXISTS recruitment_votes (
                id SERIAL PRIMARY KEY, application_id INTEGER,
                staff_id BIGINT NOT NULL, vote TEXT NOT NULL,
                comment TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(application_id, staff_id))''')
            # Tournaments
            await c.execute('''CREATE TABLE IF NOT EXISTS dash_tournaments (
                id SERIAL PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
                status TEXT DEFAULT 'draft', game_mode TEXT DEFAULT 'TSB',
                match_format TEXT DEFAULT '1v1', is_ranked BOOLEAN DEFAULT FALSE,
                bracket_size INTEGER DEFAULT 8, best_of INTEGER DEFAULT 1,
                entry_requirement TEXT DEFAULT '', required_role TEXT DEFAULT '',
                min_clan_rank TEXT DEFAULT '', entry_type TEXT DEFAULT 'open',
                entry_fee INTEGER DEFAULT 0, prize_pool TEXT DEFAULT '',
                prize_robux INTEGER DEFAULT 0, prize_coins INTEGER DEFAULT 0,
                prize_winner TEXT DEFAULT '', prize_runner_up TEXT DEFAULT '',
                prize_semifinal TEXT DEFAULT '',
                match_rules TEXT DEFAULT '', timeout_minutes INTEGER DEFAULT 15,
                no_show_penalty INTEGER DEFAULT 0, screenshot_required BOOLEAN DEFAULT FALSE,
                rules_acknowledgment BOOLEAN DEFAULT FALSE,
                checkin_required BOOLEAN DEFAULT FALSE, checkin_minutes INTEGER DEFAULT 30,
                season_id INTEGER, bracket JSONB DEFAULT '[]',
                registration_close TIMESTAMP, start_time TIMESTAMP,
                embed_message_id BIGINT DEFAULT 0, embed_channel_id BIGINT DEFAULT 0,
                created_by BIGINT, created_at TIMESTAMP DEFAULT NOW(),
                started_at TIMESTAMP, completed_at TIMESTAMP)''')
            await c.execute('''CREATE TABLE IF NOT EXISTS dash_tournament_participants (
                id SERIAL PRIMARY KEY, tournament_id INTEGER REFERENCES dash_tournaments(id),
                user_id BIGINT NOT NULL, team_id INTEGER, seed INTEGER DEFAULT 0,
                checked_in BOOLEAN DEFAULT FALSE, checked_in_at TIMESTAMP,
                status TEXT DEFAULT 'active', ranking_points_change INTEGER DEFAULT 0,
                eliminated_at TIMESTAMP, created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(tournament_id, user_id))''')
            await c.execute('''CREATE TABLE IF NOT EXISTS tournament_teams (
                id SERIAL PRIMARY KEY, tournament_id INTEGER REFERENCES dash_tournaments(id),
                team_name TEXT NOT NULL, team_icon_url TEXT DEFAULT '',
                captain_user_id BIGINT NOT NULL, status TEXT DEFAULT 'active',
                seed INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS tournament_team_members (
                id SERIAL PRIMARY KEY, team_id INTEGER REFERENCES tournament_teams(id),
                user_id BIGINT NOT NULL, role TEXT DEFAULT 'member',
                UNIQUE(team_id, user_id))''')
            await c.execute('''CREATE TABLE IF NOT EXISTS tournament_matches (
                id SERIAL PRIMARY KEY, tournament_id INTEGER REFERENCES dash_tournaments(id),
                round_num INTEGER DEFAULT 1, match_num INTEGER DEFAULT 1,
                player1_id BIGINT, player2_id BIGINT,
                team1_id INTEGER, team2_id INTEGER,
                player1_score INTEGER DEFAULT 0, player2_score INTEGER DEFAULT 0,
                winner_id BIGINT, winner_team_id INTEGER,
                screenshot_url TEXT DEFAULT '', screenshot_url_2 TEXT DEFAULT '',
                reported_by BIGINT, confirmed_by BIGINT,
                status TEXT DEFAULT 'pending', dispute_reason TEXT DEFAULT '',
                staff_notes TEXT DEFAULT '', staff_override_by BIGINT,
                started_at TIMESTAMP, completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS tournament_disputes (
                id SERIAL PRIMARY KEY, tournament_id INTEGER REFERENCES dash_tournaments(id),
                match_id INTEGER REFERENCES tournament_matches(id),
                filed_by BIGINT NOT NULL, filed_by_name TEXT DEFAULT '',
                reason TEXT NOT NULL, evidence_url TEXT DEFAULT '',
                status TEXT DEFAULT 'open', resolution TEXT DEFAULT '',
                resolved_by BIGINT, resolved_by_name TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW(), resolved_at TIMESTAMP)''')
            await c.execute('''CREATE TABLE IF NOT EXISTS ranking_ladders (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                format TEXT DEFAULT '1v1', season_id INTEGER DEFAULT 0,
                points INTEGER DEFAULT 1000, peak_points INTEGER DEFAULT 1000,
                wins INTEGER DEFAULT 0, losses INTEGER DEFAULT 0,
                streak INTEGER DEFAULT 0, best_streak INTEGER DEFAULT 0,
                last_match_at TIMESTAMP, tier TEXT DEFAULT 'Unranked',
                UNIQUE(user_id, format, season_id))''')
            await c.execute('''CREATE TABLE IF NOT EXISTS ranking_history (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                format TEXT DEFAULT '1v1', season_id INTEGER DEFAULT 0,
                tournament_id INTEGER, match_id INTEGER,
                points_before INTEGER, points_after INTEGER,
                change INTEGER DEFAULT 0, reason TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS tournament_seasons (
                id SERIAL PRIMARY KEY, name TEXT NOT NULL,
                status TEXT DEFAULT 'active', start_date TIMESTAMP DEFAULT NOW(),
                end_date TIMESTAMP, rewards_description TEXT DEFAULT '',
                champion_role TEXT DEFAULT '', finalist_role TEXT DEFAULT '',
                created_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_ranking_format ON ranking_ladders(format, season_id, points DESC)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_ranking_user ON ranking_ladders(user_id)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_tmatch_tournament ON tournament_matches(tournament_id)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_tdispute_status ON tournament_disputes(status)')
            # Role history (Discord role changes)
            await c.execute('''CREATE TABLE IF NOT EXISTS discord_role_history (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                role_id BIGINT, role_name TEXT, action TEXT DEFAULT 'added',
                changed_by BIGINT, reason TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW())''')
            # Duel disputes
            await c.execute('''CREATE TABLE IF NOT EXISTS duel_disputes (
                id SERIAL PRIMARY KEY, duel_index INTEGER,
                challenger_id BIGINT NOT NULL, opponent_id BIGINT NOT NULL,
                filed_by BIGINT NOT NULL, filed_by_name TEXT,
                reason TEXT NOT NULL, evidence TEXT DEFAULT '',
                status TEXT DEFAULT 'open', resolution TEXT,
                reviewed_by BIGINT, reviewed_by_name TEXT,
                reviewed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW())''')
            # Interaction config (buttons, dropdowns for embeds)
            await c.execute('''CREATE TABLE IF NOT EXISTS interaction_config (
                id SERIAL PRIMARY KEY, embed_id INTEGER REFERENCES embed_store(id) ON DELETE CASCADE,
                interaction_type TEXT DEFAULT 'button',
                custom_id TEXT NOT NULL, label TEXT NOT NULL,
                style TEXT DEFAULT 'primary', emoji TEXT DEFAULT '',
                action_type TEXT DEFAULT 'role_toggle',
                action_value TEXT DEFAULT '', enabled BOOLEAN DEFAULT TRUE,
                required_role_id BIGINT,
                created_at TIMESTAMP DEFAULT NOW())''')
            # Recruitment positions & applications
            await c.execute('''CREATE TABLE IF NOT EXISTS recruitment_positions (
                id SERIAL PRIMARY KEY, title TEXT NOT NULL,
                description TEXT DEFAULT '', requirements TEXT DEFAULT '',
                max_applicants INTEGER DEFAULT 0, status TEXT DEFAULT 'open',
                created_by BIGINT, created_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS recruitment_applications (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                position_id INTEGER REFERENCES recruitment_positions(id),
                answers TEXT DEFAULT '', status TEXT DEFAULT 'applied',
                reviewed_by BIGINT, review_note TEXT,
                created_at TIMESTAMP DEFAULT NOW(), reviewed_at TIMESTAMP)''')
            # Session tokens for expiration
            await c.execute('''CREATE TABLE IF NOT EXISTS session_tokens (
                id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE, ip_address TEXT,
                expires_at TIMESTAMP NOT NULL, invalidated BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW())''')
            # Server config (multi-server future-proofing)
            await c.execute('''CREATE TABLE IF NOT EXISTS server_config (
                guild_id BIGINT PRIMARY KEY, guild_name TEXT DEFAULT '',
                config JSONB DEFAULT '{}', features JSONB DEFAULT '{}',
                embed_categories JSONB DEFAULT '[]',
                created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())''')
            # Indexes for performance
            await c.execute('CREATE INDEX IF NOT EXISTS idx_audit_created ON dashboard_audit_log(created_at DESC)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_cases_user ON mod_cases(target_user_id)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_cases_status ON mod_cases(status)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_notif_staff ON notifications(target_staff_id, is_read)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_events_status ON scheduled_events(status)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_sessions_staff ON staff_sessions(staff_id)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_disputes_status ON duel_disputes(status)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_role_hist_user ON discord_role_history(user_id)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_apps_status ON recruitment_applications(status)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_session_tokens ON session_tokens(token_hash)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_interactions ON interaction_config(embed_id)')
            # Allies system
            await c.execute('''CREATE TABLE IF NOT EXISTS allies (
                id SERIAL PRIMARY KEY, server_name TEXT NOT NULL,
                server_icon_url TEXT DEFAULT '', description TEXT DEFAULT '',
                invite_link TEXT DEFAULT '', ally_type TEXT DEFAULT 'friendly',
                tier TEXT DEFAULT 'bronze', status TEXT DEFAULT 'active',
                visibility TEXT DEFAULT 'public', display_order INTEGER DEFAULT 0,
                server_size INTEGER DEFAULT 0, contact_discord_id BIGINT DEFAULT 0,
                notes TEXT DEFAULT '', embed_message_id BIGINT DEFAULT 0,
                embed_channel_id BIGINT DEFAULT 0,
                allied_at TIMESTAMP DEFAULT NOW(), paused_at TIMESTAMP,
                removed_at TIMESTAMP, added_by BIGINT, last_validated TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(), updated_at TIMESTAMP DEFAULT NOW())''')
            await c.execute('''CREATE TABLE IF NOT EXISTS ally_applications (
                id SERIAL PRIMARY KEY, server_name TEXT NOT NULL,
                server_size INTEGER DEFAULT 0, invite_link TEXT DEFAULT '',
                reason TEXT DEFAULT '', offering TEXT DEFAULT '',
                contact_discord_id TEXT DEFAULT '', contact_name TEXT DEFAULT '',
                status TEXT DEFAULT 'pending', reviewer_id BIGINT,
                reviewer_name TEXT, review_notes TEXT DEFAULT '',
                ally_id INTEGER REFERENCES allies(id),
                created_at TIMESTAMP DEFAULT NOW(), reviewed_at TIMESTAMP)''')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_allies_status ON allies(status)')
            await c.execute('CREATE INDEX IF NOT EXISTS idx_ally_apps_status ON ally_applications(status)')
            # Seed rank ladder if empty
            count = await c.fetchval('SELECT COUNT(*) FROM rank_ladder')
            if count == 0:
                for i, r in enumerate(DEFAULT_RANKS):
                    await c.execute('INSERT INTO rank_ladder (rank_name, rank_order, min_xp, min_level, perks, auto_promote) VALUES ($1,$2,$3,$4,$5,$6)',
                        r["rank"], i, r["min_xp"], r["min_level"], r["perks"], r["auto_promote"])
        print("Dashboard DB connected (v5.1 - complete features)")

    async def close(self):
        if self.pool: await self.pool.close()

    # == HELPERS ==
    async def _blob(self, key: str) -> Dict:
        if not self.pool: return {}
        try:
            async with self.pool.acquire() as c:
                row = await c.fetchrow("SELECT data FROM json_data WHERE key = $1", key)
                if row and row["data"]:
                    d = row["data"]
                    return json.loads(d) if isinstance(d, str) else d
        except Exception as e: print(f"[DB] blob({key}): {e}")
        return {}
    async def _main(self) -> Dict: return await self._blob("main_data") or {"users": {}, "roster": []}
    async def _duels(self) -> Dict: return await self._blob("duels_data") or {"elo": {}, "duel_history": []}
    async def _warnings(self) -> Dict: return await self._blob("warnings_data") or {"users": {}, "recent_warnings": []}
    async def _users(self) -> Dict[str, Dict]: return (await self._main()).get("users", {})
    async def _qall(self, q, *a):
        if not self.pool: return []
        try:
            async with self.pool.acquire() as c: return [dict(r) for r in await c.fetch(q, *a)]
        except Exception as e: print(f"[DB] qall: {e}"); return []
    async def _qone(self, q, *a):
        if not self.pool: return None
        try:
            async with self.pool.acquire() as c:
                r = await c.fetchrow(q, *a); return dict(r) if r else None
        except Exception as e: print(f"[DB] qone: {e}"); return None
    async def _exec(self, q, *a):
        if not self.pool: return
        try:
            async with self.pool.acquire() as c: await c.execute(q, *a)
        except Exception as e: print(f"[DB] exec: {e}")
    async def _insert_ret(self, q, *a):
        if not self.pool: return None
        try:
            async with self.pool.acquire() as c:
                r = await c.fetchrow(q, *a)
                return dict(r) if r else None
        except Exception as e: print(f"[DB] insert: {e}"); return None

    def get_avatar_url(self, user: Dict) -> str:
        if user.get("avatar_url"): return user["avatar_url"]
        uid = user.get("user_id", 0)
        return f"https://cdn.discordapp.com/embed/avatars/{int(uid) % 5}.png"

    # == SERVER STATS ==
    async def get_server_stats(self):
        users = await self._users()
        now = datetime.datetime.now(datetime.timezone.utc)
        d1 = (now - datetime.timedelta(days=1)).isoformat()
        d7 = (now - datetime.timedelta(days=7)).isoformat()
        duels = await self._duels()
        return {
            "total_users": len(users),
            "active_24h": sum(1 for u in users.values() if (u.get("last_active") or "") > d1),
            "active_7d": sum(1 for u in users.values() if (u.get("last_active") or "") > d7),
            "total_duels": len(duels.get("duel_history", [])),
            "max_level": max((u.get("level", 0) or 0 for u in users.values()), default=0),
            "total_xp": sum(u.get("xp", 0) or 0 for u in users.values()),
            "verified_count": sum(1 for u in users.values() if u.get("verified")),
        }

    # == USER OPERATIONS ==
    async def get_user(self, user_id: int) -> Optional[Dict]:
        users = await self._users()
        u = users.get(str(user_id))
        if not u: return None
        u["user_id"] = user_id
        elo_map = (await self._duels()).get("elo", {})
        e = elo_map.get(str(user_id), {})
        u["elo_rating"] = e.get("elo", 1000) if isinstance(e, dict) else (e if isinstance(e, (int, float)) else 1000)
        u["wins"] = e.get("wins", 0) if isinstance(e, dict) else 0
        u["losses"] = e.get("losses", 0) if isinstance(e, dict) else 0
        warn = (await self._warnings()).get("users", {}).get(str(user_id), {})
        u["warning_points"] = warn.get("total_points", 0) if isinstance(warn, dict) else 0
        u["warnings"] = warn.get("warnings", []) if isinstance(warn, dict) else []
        u["avatar_url"] = u.get("avatar_url") or self.get_avatar_url(u)
        u["stage_rank"] = None
        for i, slot in enumerate(await self.get_roster()):
            if slot is not None and str(slot) == str(user_id):
                u["stage_rank"] = i + 1; break
        items = u.get("inventory", [])
        u["inventory_items"] = [SHOP_ITEMS.get(it, {"name": it, "type": "unknown"}) for it in items] if items else []
        return u

    async def get_user_rank(self, uid: int, sort_key: str) -> int:
        users = await self._users()
        if sort_key == "elo_rating":
            elo_map = (await self._duels()).get("elo", {})
            vals = [(k, (v.get("elo", 1000) if isinstance(v, dict) else v) if v else 1000) for k, v in elo_map.items()]
            vals.sort(key=lambda x: x[1], reverse=True)
            for i, (k, _) in enumerate(vals):
                if str(k) == str(uid): return i + 1
            return 0
        vals = [(k, u.get(sort_key, 0) or 0) for k, u in users.items()]
        vals.sort(key=lambda x: x[1], reverse=True)
        for i, (k, _) in enumerate(vals):
            if str(k) == str(uid): return i + 1
        return 0

    async def get_total_users(self) -> int: return len(await self._users())

    async def search_users(self, query: str) -> List[Dict]:
        users = await self._users()
        elo_map = (await self._duels()).get("elo", {})
        results = []
        q = query.lower()
        for uid, u in users.items():
            name = (u.get("roblox_username") or "").lower()
            if q in name or q in uid:
                e = elo_map.get(uid, {})
                u["user_id"] = int(uid)
                u["elo_rating"] = e.get("elo", 1000) if isinstance(e, dict) else 1000
                u["avatar_url"] = u.get("avatar_url") or self.get_avatar_url(u)
                results.append(u)
                if len(results) >= 50: break
        return results

    # == GLOBAL SEARCH ==
    async def global_search(self, query: str) -> Dict:
        results = {"users": [], "cases": [], "events": [], "embeds": []}
        results["users"] = (await self.search_users(query))[:20]
        if query.isdigit():
            cases = await self._qall("SELECT * FROM mod_cases WHERE target_user_id=$1 OR id=$2 ORDER BY created_at DESC LIMIT 10", int(query), int(query))
        else:
            cases = await self._qall("SELECT * FROM mod_cases WHERE reason ILIKE $1 OR staff_name ILIKE $1 ORDER BY created_at DESC LIMIT 10", f"%{query}%")
        results["cases"] = cases
        results["events"] = await self._qall("SELECT * FROM scheduled_events WHERE title ILIKE $1 ORDER BY created_at DESC LIMIT 10", f"%{query}%")
        results["embeds"] = await self._qall("SELECT * FROM embed_store WHERE name ILIKE $1 OR category ILIKE $1 ORDER BY updated_at DESC LIMIT 10", f"%{query}%")
        return results

    # == LEADERBOARDS ==
    async def get_leaderboard(self, sort_key: str = "xp", limit: int = 25, offset: int = 0) -> List[Dict]:
        users = await self._users()
        elo_map = (await self._duels()).get("elo", {})
        items = []
        for uid, u in users.items():
            e = elo_map.get(uid, {})
            u["user_id"] = int(uid)
            u["elo_rating"] = e.get("elo", 1000) if isinstance(e, dict) else (e if isinstance(e, (int, float)) else 1000)
            u["wins"] = e.get("wins", 0) if isinstance(e, dict) else 0
            u["losses"] = e.get("losses", 0) if isinstance(e, dict) else 0
            u["avatar_url"] = u.get("avatar_url") or self.get_avatar_url(u)
            items.append(u)
        items.sort(key=lambda x: x.get(sort_key, 0) or 0, reverse=True)
        return items[offset:offset+limit]

    async def get_leaderboard_stats(self):
        users = await self._users()
        elo_map = (await self._duels()).get("elo", {})
        return {
            "total_users": len(users),
            "users_with_elo": len(elo_map),
            "users_with_xp": sum(1 for u in users.values() if (u.get("xp", 0) or 0) > 0),
            "users_with_coins": sum(1 for u in users.values() if (u.get("coins", 0) or 0) > 0),
        }

    # == ROSTER ==
    async def get_roster(self) -> List: return (await self._main()).get("roster", [None] * 10)
    async def get_roster_with_names(self) -> List[Dict]:
        roster = await self.get_roster()
        users = await self._users()
        result = []
        for i, slot in enumerate(roster if roster else [None]*10):
            if slot is not None:
                uid = str(slot); u = users.get(uid, {})
                result.append({"slot": i+1, "user_id": uid, "name": u.get("roblox_username") or f"User {uid}", "filled": True})
            else:
                result.append({"slot": i+1, "user_id": None, "name": None, "filled": False})
        return result

    # == DUELS ==
    async def get_duel_history(self, limit: int = 50) -> List[Dict]:
        duels = await self._duels()
        history = duels.get("duel_history", [])
        users = await self._users()
        for d in history:
            for key in ["winner", "loser", "challenger", "opponent"]:
                uid = str(d.get(key, ""))
                if uid in users:
                    d[f"{key}_name"] = users[uid].get("roblox_username", "Unknown")
        return history[-limit:][::-1]

    async def get_user_duel_history(self, uid: int, limit: int = 10) -> List[Dict]:
        duels = await self._duels()
        history = duels.get("duel_history", [])
        users = await self._users()
        uid_s = str(uid)
        user_duels = [d for d in history if str(d.get("winner")) == uid_s or str(d.get("loser")) == uid_s or str(d.get("challenger")) == uid_s or str(d.get("opponent")) == uid_s]
        for d in user_duels:
            opp = str(d.get("opponent" if str(d.get("challenger")) == uid_s else "challenger", ""))
            d["opponent_name"] = users.get(opp, {}).get("roblox_username", "Unknown")
        return user_duels[-limit:][::-1]

    async def get_elo_distribution(self) -> Dict:
        elo_map = (await self._duels()).get("elo", {})
        dist = Counter()
        for e in elo_map.values():
            rating = e.get("elo", 1000) if isinstance(e, dict) else (e if isinstance(e, (int, float)) else 1000)
            bucket = (int(rating) // 200) * 200
            dist[f"{bucket}-{bucket+199}"] += 1
        return dict(sorted(dist.items()))

    # == WARNINGS ==
    async def get_recent_warnings(self, limit: int = 20) -> List[Dict]:
        data = await self._warnings()
        recent = data.get("recent_warnings", [])
        return recent[-limit:][::-1]

    async def get_user_warnings(self, uid: int) -> Dict:
        data = await self._warnings()
        uw = data.get("users", {}).get(str(uid), {})
        if not isinstance(uw, dict): return {"warnings": [], "total_points": 0}
        return {"warnings": uw.get("warnings", []), "total_points": uw.get("total_points", 0)}

    # == WARS & RAIDS (from json) ==
    async def get_war_record(self) -> Dict:
        main = await self._main()
        wars = main.get("wars", [])
        w = sum(1 for x in wars if x.get("result") == "win")
        l = sum(1 for x in wars if x.get("result") == "loss")
        d = sum(1 for x in wars if x.get("result") == "draw")
        return {"total": len(wars), "wins": w, "losses": l, "draws": d}
    async def get_wars(self, limit=10):
        return (await self._main()).get("wars", [])[-limit:][::-1]
    async def get_recent_raids(self, limit=15):
        return (await self._main()).get("raids", [])[-limit:][::-1]
    async def get_raid_leaderboard(self, limit=10):
        users = await self._users()
        items = [{"user_id": int(k), "name": v.get("roblox_username", "Unknown"),
                  "raids": v.get("raid_participation", 0) or 0, "wins": v.get("raid_wins", 0) or 0}
                 for k, v in users.items() if (v.get("raid_participation", 0) or 0) > 0]
        items.sort(key=lambda x: x["raids"], reverse=True)
        return items[:limit]

    # == ECONOMY ==
    async def get_economy_stats(self):
        users = await self._users()
        coins = [(int(k), u.get("coins", 0) or 0) for k, u in users.items()]
        coins.sort(key=lambda x: x[1], reverse=True)
        return {
            "total_coins_circulation": sum(c for _, c in coins),
            "avg_coins": sum(c for _, c in coins) // max(len(coins), 1),
            "richest": [{"user_id": uid, "name": users.get(str(uid), {}).get("roblox_username") or users.get(str(uid), {}).get("username") or "Unknown", "coins": c, "level": users.get(str(uid), {}).get("level", 0)} for uid, c in coins[:10]],
        }
    async def get_shop_catalog(self): return [{"key": k, **v} for k, v in SHOP_ITEMS.items()]

    # == ANALYTICS ==
    async def get_analytics(self):
        users = await self._users()
        now = datetime.datetime.now(datetime.timezone.utc)
        levels = [u.get("level", 0) or 0 for u in users.values()]
        level_dist = Counter()
        for lvl in levels:
            bucket = f"{(lvl//5)*5}-{(lvl//5)*5+4}"
            level_dist[bucket] += 1
        daily_active = {}
        for u in users.values():
            la = u.get("last_active", "")
            if la and len(la) >= 10:
                day = la[:10]
                daily_active[day] = daily_active.get(day, 0) + 1
        return {
            "total_users": len(users), "avg_level": sum(levels) // max(len(levels), 1),
            "max_level": max(levels, default=0), "level_distribution": dict(sorted(level_dist.items())),
            "daily_active": dict(sorted(daily_active.items())[-30:]),
            "verified_pct": round(sum(1 for u in users.values() if u.get("verified")) / max(len(users), 1) * 100, 1),
        }

    # == AUDIT LOG ==
    async def add_audit(self, staff_id, staff_name, action, target_id=None, details=None, ip=None):
        await self._exec("INSERT INTO dashboard_audit_log (staff_id, staff_name, action, target_id, details, ip_address) VALUES ($1,$2,$3,$4,$5,$6)",
            staff_id, staff_name, action, target_id, details, ip)
    async def get_audit_log(self, limit=100):
        return await self._qall("SELECT * FROM dashboard_audit_log ORDER BY created_at DESC LIMIT $1", limit)

    # == GUARDIAN ==
    async def get_guardian_stats(self):
        data = await self._blob("guardian_stats")
        return data or {"commands_today": 0, "errors_today": 0, "active_abuse_flags": 0,
                        "abuse_scores": {}, "top_users_today": [], "restricted_users": [], "updated_at": None}
    async def get_guardian_audit_events(self, limit=50):
        return await self._qall("SELECT * FROM dashboard_audit_log WHERE action LIKE 'guardian_%%' ORDER BY created_at DESC LIMIT $1", limit)

    # =============================================
    # STAFF MANAGEMENT (expanded)
    # =============================================
    async def get_staff_members(self):
        return await self._qall("SELECT * FROM staff_roles ORDER BY permission_tier DESC, created_at ASC")
    async def add_staff_member(self, uid, name, tier, added_by, section_perms=None):
        await self._exec('INSERT INTO staff_roles (discord_user_id, display_name, permission_tier, added_by, section_perms) VALUES ($1,$2,$3,$4,$5) ON CONFLICT (discord_user_id) DO UPDATE SET display_name=$2, permission_tier=$3, section_perms=$5',
            uid, name, tier, added_by, json.dumps(section_perms or {}))
    async def auto_register_staff(self, uid, name, tier):
        """Auto-register staff from Discord permissions. Won't downgrade existing manual tiers."""
        await self._exec('''INSERT INTO staff_roles (discord_user_id, display_name, permission_tier, added_by)
            VALUES ($1, $2, $3, $1)
            ON CONFLICT (discord_user_id) DO UPDATE SET
                display_name = $2,
                permission_tier = GREATEST(staff_roles.permission_tier, $3),
                last_login = NOW()''', uid, name, tier)
    async def remove_staff_member(self, uid):
        await self._exec("DELETE FROM staff_roles WHERE discord_user_id = $1", uid)
    async def is_db_staff(self, uid):
        r = await self._qone("SELECT permission_tier, section_perms FROM staff_roles WHERE discord_user_id = $1", uid)
        return (True, r["permission_tier"], r.get("section_perms", {})) if r else (False, 0, {})
    async def update_staff_activity(self, uid, action_desc=None):
        if action_desc:
            await self._exec("UPDATE staff_roles SET last_action=NOW(), last_action_desc=$2 WHERE discord_user_id=$1", uid, action_desc)
        else:
            await self._exec("UPDATE staff_roles SET last_login=NOW() WHERE discord_user_id=$1", uid)

    # == ROLE CONFIG ==
    async def get_role_configs(self):
        return await self._qall("SELECT * FROM role_config ORDER BY permission_tier DESC, created_at ASC")
    async def add_role_config(self, role_id, name, tier, added_by, section_perms=None):
        await self._exec('INSERT INTO role_config (discord_role_id, role_name, permission_tier, added_by, section_perms) VALUES ($1,$2,$3,$4,$5) ON CONFLICT (discord_role_id) DO UPDATE SET role_name=$2, permission_tier=$3, section_perms=$5',
            role_id, name, tier, added_by, json.dumps(section_perms or {}))
    async def remove_role_config(self, role_id):
        await self._exec("DELETE FROM role_config WHERE discord_role_id = $1", role_id)
    async def check_role_permissions(self, role_ids):
        if not role_ids or not self.pool: return False, 0
        try:
            async with self.pool.acquire() as c:
                rows = await c.fetch("SELECT permission_tier FROM role_config WHERE discord_role_id = ANY($1)", [int(r) for r in role_ids])
                return (True, max(r["permission_tier"] for r in rows)) if rows else (False, 0)
        except: return (False, 0)

    # == STAFF SESSIONS ==
    async def log_staff_session(self, staff_id, staff_name, ip, action="login"):
        await self._exec("INSERT INTO staff_sessions (staff_id, staff_name, ip_address, action) VALUES ($1,$2,$3,$4)", staff_id, staff_name, ip, action)
        await self.update_staff_activity(staff_id)
    async def get_staff_sessions(self, staff_id=None, limit=50):
        if staff_id: return await self._qall("SELECT * FROM staff_sessions WHERE staff_id=$1 ORDER BY created_at DESC LIMIT $2", staff_id, limit)
        return await self._qall("SELECT * FROM staff_sessions ORDER BY created_at DESC LIMIT $1", limit)

    # == STAFF NOTES ==
    async def add_note(self, target_id, staff_id, staff_name, note, pinned=False):
        return await self._insert_ret("INSERT INTO staff_notes (target_user_id, staff_id, staff_name, note, pinned) VALUES ($1,$2,$3,$4,$5) RETURNING id",
            target_id, staff_id, staff_name, note, pinned)
    async def get_notes(self, target_id, limit=50):
        return await self._qall("SELECT * FROM staff_notes WHERE target_user_id=$1 ORDER BY pinned DESC, created_at DESC LIMIT $2", target_id, limit)
    async def delete_note(self, note_id):
        await self._exec("DELETE FROM staff_notes WHERE id=$1", note_id)
    async def toggle_pin_note(self, note_id):
        await self._exec("UPDATE staff_notes SET pinned = NOT pinned WHERE id=$1", note_id)

    # =============================================
    # MOD CASES (full case management)
    # =============================================
    async def create_case(self, target_id, case_type, category, severity, reason, points, staff_id, staff_name):
        return await self._insert_ret(
            "INSERT INTO mod_cases (target_user_id, case_type, category, severity, reason, points, staff_id, staff_name) VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
            target_id, case_type, category, severity, reason, points, staff_id, staff_name)
    async def get_case(self, case_id):
        case = await self._qone("SELECT * FROM mod_cases WHERE id=$1", case_id)
        if case:
            case["evidence"] = await self._qall("SELECT * FROM mod_evidence WHERE case_id=$1 ORDER BY created_at ASC", case_id)
        return case
    async def get_cases(self, status=None, limit=50):
        if status: return await self._qall("SELECT * FROM mod_cases WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM mod_cases ORDER BY created_at DESC LIMIT $1", limit)
    async def get_user_cases(self, uid, limit=50):
        return await self._qall("SELECT * FROM mod_cases WHERE target_user_id=$1 ORDER BY created_at DESC LIMIT $2", uid, limit)
    async def resolve_case(self, case_id, resolution, resolved_by):
        await self._exec("UPDATE mod_cases SET status='resolved', resolution=$2, resolved_by=$3, resolved_at=NOW() WHERE id=$1", case_id, resolution, resolved_by)
    async def add_evidence(self, case_id, evidence_type, content, added_by, added_by_name):
        return await self._insert_ret("INSERT INTO mod_evidence (case_id, evidence_type, content, added_by, added_by_name) VALUES ($1,$2,$3,$4,$5) RETURNING *",
            case_id, evidence_type, content, added_by, added_by_name)
    async def get_mod_stats(self):
        total = await self._qone("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE status='active') as active, COUNT(*) FILTER (WHERE status='resolved') as resolved, COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '7 days') as week FROM mod_cases")
        return total or {"total": 0, "active": 0, "resolved": 0, "week": 0}

    # =============================================
    # RANK LADDER
    # =============================================
    async def get_rank_ladder(self):
        return await self._qall("SELECT * FROM rank_ladder ORDER BY rank_order ASC")
    async def update_rank(self, rank_id, rank_name, min_xp, min_level, perks, auto_promote, color=None, role_id=None):
        await self._exec("UPDATE rank_ladder SET rank_name=$2, min_xp=$3, min_level=$4, perks=$5, auto_promote=$6, color=COALESCE($7, color), discord_role_id=$8 WHERE id=$1",
            rank_id, rank_name, min_xp, min_level, perks, auto_promote, color, role_id)
    async def add_rank(self, rank_name, rank_order, min_xp, min_level, perks, auto_promote):
        return await self._insert_ret("INSERT INTO rank_ladder (rank_name, rank_order, min_xp, min_level, perks, auto_promote) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
            rank_name, rank_order, min_xp, min_level, perks, auto_promote)
    async def delete_rank(self, rank_id):
        await self._exec("DELETE FROM rank_ladder WHERE id=$1", rank_id)
    async def get_user_rank_name(self, uid):
        user = await self.get_user(uid)
        if not user: return "Unknown"
        ladder = await self.get_rank_ladder()
        current = "Unranked"
        for r in ladder:
            if (user.get("xp", 0) or 0) >= r["min_xp"] and (user.get("level", 0) or 0) >= r["min_level"]:
                current = r["rank_name"]
        return current

    # == RANK HISTORY ==
    async def add_rank_change(self, uid, old_rank, new_rank, reason, changed_by=None):
        await self._exec("INSERT INTO rank_history (user_id, old_rank, new_rank, reason, changed_by) VALUES ($1,$2,$3,$4,$5)", uid, old_rank, new_rank, reason, changed_by)
    async def get_rank_history(self, uid=None, limit=50):
        if uid: return await self._qall("SELECT * FROM rank_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2", uid, limit)
        return await self._qall("SELECT * FROM rank_history ORDER BY created_at DESC LIMIT $1", limit)

    # =============================================
    # ACTIVITY TRACKING
    # =============================================
    async def get_activity_stats(self):
        users = await self._users()
        now = datetime.datetime.now(datetime.timezone.utc)
        d7 = (now - datetime.timedelta(days=7)).isoformat()
        d30 = (now - datetime.timedelta(days=30)).isoformat()
        inactive_14d = (now - datetime.timedelta(days=14)).isoformat()
        msg_total = sum(u.get("messages", 0) or 0 for u in users.values())
        voice_total = sum(u.get("voice_time", 0) or 0 for u in users.values())
        inactive = [{"user_id": int(k), "name": u.get("roblox_username", "Unknown"), "last_active": u.get("last_active", "Never"), "level": u.get("level", 0)}
                    for k, u in users.items() if (u.get("last_active") or "") < inactive_14d and (u.get("level", 0) or 0) > 0]
        inactive.sort(key=lambda x: x.get("last_active", ""), reverse=False)
        top_msg = sorted(users.items(), key=lambda x: x[1].get("messages", 0) or 0, reverse=True)[:15]
        top_voice = sorted(users.items(), key=lambda x: x[1].get("voice_time", 0) or 0, reverse=True)[:15]
        return {
            "msg_total": msg_total, "voice_total": voice_total,
            "active_7d": sum(1 for u in users.values() if (u.get("last_active") or "") > d7),
            "active_30d": sum(1 for u in users.values() if (u.get("last_active") or "") > d30),
            "inactive_users": inactive[:50],
            "top_msg": [{"user_id": int(k), "name": v.get("roblox_username", "Unknown"), "messages": v.get("messages", 0) or 0} for k, v in top_msg],
            "top_voice": [{"user_id": int(k), "name": v.get("roblox_username", "Unknown"), "voice_time": v.get("voice_time", 0) or 0} for k, v in top_voice],
        }

    # =============================================
    # SCHEDULED EVENTS
    # =============================================
    async def create_event(self, title, event_type, description, scheduled_at, duration, max_p, min_level, xp_reward, coin_reward, created_by, created_by_name):
        return await self._insert_ret(
            "INSERT INTO scheduled_events (title, event_type, description, scheduled_at, duration_minutes, max_participants, min_level, xp_reward, coin_reward, created_by, created_by_name) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *",
            title, event_type, description, scheduled_at, duration, max_p, min_level, xp_reward, coin_reward, created_by, created_by_name)
    async def get_events(self, status=None, limit=20):
        if status: return await self._qall("SELECT * FROM scheduled_events WHERE status=$1 ORDER BY scheduled_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM scheduled_events ORDER BY scheduled_at DESC LIMIT $1", limit)
    async def get_event(self, eid):
        ev = await self._qone("SELECT * FROM scheduled_events WHERE id=$1", eid)
        if ev:
            ev["signups"] = await self._qall("SELECT * FROM event_signups WHERE event_id=$1 ORDER BY created_at ASC", eid)
            users = await self._users()
            for s in ev["signups"]:
                u = users.get(str(s["user_id"]), {})
                s["name"] = u.get("roblox_username", "Unknown")
                s["level"] = u.get("level", 0) or 0
        return ev
    async def update_event_status(self, eid, status, summary=None):
        if status == "active": await self._exec("UPDATE scheduled_events SET status=$2, started_at=NOW() WHERE id=$1", eid, status)
        elif status == "completed":
            await self._exec("UPDATE scheduled_events SET status=$2, completed_at=NOW(), summary=COALESCE($3, summary) WHERE id=$1", eid, status, summary)
        else: await self._exec("UPDATE scheduled_events SET status=$2 WHERE id=$1", eid, status)
    async def signup_event(self, eid, uid):
        await self._exec("INSERT INTO event_signups (event_id, user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", eid, uid)
    async def cancel_signup(self, eid, uid):
        await self._exec("DELETE FROM event_signups WHERE event_id=$1 AND user_id=$2", eid, uid)
    async def mark_attendance(self, eid, uid, attended, score=0):
        await self._exec("UPDATE event_signups SET attended=$3, performance_score=$4 WHERE event_id=$1 AND user_id=$2", eid, uid, attended, score)

    # =============================================
    # REWARD SYSTEM
    # =============================================
    async def get_reward_mappings(self):
        return await self._qall("SELECT * FROM reward_mappings ORDER BY trigger_type, trigger_value")
    async def add_reward_mapping(self, trigger_type, trigger_value, reward_type, reward_value, desc, cooldown):
        return await self._insert_ret("INSERT INTO reward_mappings (trigger_type, trigger_value, reward_type, reward_value, description, cooldown_hours) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
            trigger_type, trigger_value, reward_type, reward_value, desc, cooldown)
    async def delete_reward_mapping(self, rid):
        await self._exec("DELETE FROM reward_mappings WHERE id=$1", rid)
    async def toggle_reward(self, rid):
        await self._exec("UPDATE reward_mappings SET active = NOT active WHERE id=$1", rid)
    async def can_claim_reward(self, uid, rid):
        last = await self._qone("SELECT claimed_at FROM reward_claims WHERE user_id=$1 AND reward_id=$2 ORDER BY claimed_at DESC LIMIT 1", uid, rid)
        if not last: return True
        reward = await self._qone("SELECT cooldown_hours FROM reward_mappings WHERE id=$1", rid)
        if not reward or not reward.get("cooldown_hours"): return True
        diff = (datetime.datetime.now(datetime.timezone.utc) - last["claimed_at"]).total_seconds() / 3600
        return diff >= reward["cooldown_hours"]
    async def claim_reward(self, uid, rid):
        await self._exec("INSERT INTO reward_claims (user_id, reward_id) VALUES ($1,$2)", uid, rid)

    # =============================================
    # EMBED MANAGER
    # =============================================
    async def get_embeds(self, category=None):
        if category: return await self._qall("SELECT * FROM embed_store WHERE category=$1 ORDER BY updated_at DESC", category)
        return await self._qall("SELECT * FROM embed_store ORDER BY updated_at DESC")
    async def get_embed(self, eid):
        e = await self._qone("SELECT * FROM embed_store WHERE id=$1", eid)
        if e:
            e["history"] = await self._qall("SELECT * FROM embed_history WHERE embed_id=$1 ORDER BY version DESC LIMIT 20", eid)
        return e
    async def get_embed_by_name(self, name):
        return await self._qone("SELECT * FROM embed_store WHERE name=$1", name)
    async def save_embed(self, name, category, embed_data, interactions, created_by):
        existing = await self.get_embed_by_name(name)
        if existing:
            version = len(await self._qall("SELECT id FROM embed_history WHERE embed_id=$1", existing["id"])) + 1
            await self._exec("INSERT INTO embed_history (embed_id, embed_data, version, changed_by) VALUES ($1,$2,$3,$4)",
                existing["id"], json.dumps(existing["embed_data"]) if isinstance(existing["embed_data"], dict) else existing["embed_data"], version, created_by)
            await self._exec("UPDATE embed_store SET embed_data=$2, category=$3, interactions=$4, updated_at=NOW() WHERE id=$1",
                existing["id"], json.dumps(embed_data), category, json.dumps(interactions or []))
            return existing["id"]
        r = await self._insert_ret("INSERT INTO embed_store (name, category, embed_data, interactions, created_by) VALUES ($1,$2,$3,$4,$5) RETURNING id",
            name, category, json.dumps(embed_data), json.dumps(interactions or []), created_by)
        return r["id"] if r else 0
    async def delete_embed(self, eid):
        await self._exec("DELETE FROM embed_store WHERE id=$1", eid)
    async def mark_embed_pushed(self, eid, channel_id, message_id):
        await self._exec("UPDATE embed_store SET last_pushed=NOW(), channel_id=$2, message_id=$3 WHERE id=$1", eid, channel_id, message_id)
    async def rollback_embed(self, eid, version_id):
        hist = await self._qone("SELECT embed_data FROM embed_history WHERE id=$1 AND embed_id=$2", version_id, eid)
        if hist:
            data = hist["embed_data"]
            if isinstance(data, str): data = json.loads(data)
            await self._exec("UPDATE embed_store SET embed_data=$2, updated_at=NOW() WHERE id=$1", eid, json.dumps(data))
            return True
        return False
    async def get_embed_categories(self):
        rows = await self._qall("SELECT DISTINCT category FROM embed_store ORDER BY category")
        return [r["category"] for r in rows]

    # =============================================
    # NOTIFICATIONS
    # =============================================
    async def add_notification(self, target_staff_id, notif_type, title, message="", link="", is_global=False):
        await self._exec("INSERT INTO notifications (target_staff_id, notif_type, title, message, link, is_global) VALUES ($1,$2,$3,$4,$5,$6)",
            target_staff_id, notif_type, title, message, link, is_global)
    async def get_notifications(self, staff_id, unread_only=False, limit=30):
        if unread_only:
            return await self._qall("SELECT * FROM notifications WHERE (target_staff_id=$1 OR is_global=TRUE) AND is_read=FALSE ORDER BY created_at DESC LIMIT $2", staff_id, limit)
        return await self._qall("SELECT * FROM notifications WHERE target_staff_id=$1 OR is_global=TRUE ORDER BY created_at DESC LIMIT $2", staff_id, limit)
    async def mark_notification_read(self, nid):
        await self._exec("UPDATE notifications SET is_read=TRUE WHERE id=$1", nid)
    async def mark_all_read(self, staff_id):
        await self._exec("UPDATE notifications SET is_read=TRUE WHERE (target_staff_id=$1 OR is_global=TRUE) AND is_read=FALSE", staff_id)
    async def get_unread_count(self, staff_id):
        r = await self._qone("SELECT COUNT(*) as cnt FROM notifications WHERE (target_staff_id=$1 OR is_global=TRUE) AND is_read=FALSE", staff_id)
        return r["cnt"] if r else 0

    # =============================================
    # USER PREFERENCES
    # =============================================
    async def get_user_prefs(self, uid):
        r = await self._qone("SELECT * FROM user_preferences WHERE user_id=$1", uid)
        return r or {"user_id": uid, "theme": "dark", "notifications_enabled": True, "data": {}}
    async def set_user_prefs(self, uid, theme=None, notifs=None, data=None):
        existing = await self.get_user_prefs(uid)
        t = theme or existing.get("theme", "dark")
        n = notifs if notifs is not None else existing.get("notifications_enabled", True)
        d = json.dumps(data or existing.get("data", {}))
        await self._exec("INSERT INTO user_preferences (user_id, theme, notifications_enabled, data, updated_at) VALUES ($1,$2,$3,$4,NOW()) ON CONFLICT (user_id) DO UPDATE SET theme=$2, notifications_enabled=$3, data=$4, updated_at=NOW()",
            uid, t, n, d)

    # =============================================
    # BOT STATUS
    # =============================================
    async def log_bot_status(self, status, event, details="", latency=0, guilds=0, members=0):
        await self._exec("INSERT INTO bot_status_log (status, event, details, latency_ms, guild_count, member_count) VALUES ($1,$2,$3,$4,$5,$6)",
            status, event, details, latency, guilds, members)
    async def get_bot_status(self, limit=50):
        return await self._qall("SELECT * FROM bot_status_log ORDER BY created_at DESC LIMIT $1", limit)
    async def get_bot_current_status(self):
        return await self._qone("SELECT * FROM bot_status_log ORDER BY created_at DESC LIMIT 1")

    # =============================================
    # CLAN RULES
    # =============================================
    async def get_clan_rules(self):
        return await self._qall("SELECT * FROM clan_rules ORDER BY section_order ASC")
    async def save_clan_rule(self, rule_id, title, content, order, updated_by):
        if rule_id:
            await self._exec("UPDATE clan_rules SET section_title=$2, content=$3, section_order=$4, updated_by=$5, updated_at=NOW() WHERE id=$1",
                rule_id, title, content, order, updated_by)
        else:
            await self._exec("INSERT INTO clan_rules (section_title, content, section_order, updated_by) VALUES ($1,$2,$3,$4)",
                title, content, order, updated_by)
    async def delete_clan_rule(self, rule_id):
        await self._exec("DELETE FROM clan_rules WHERE id=$1", rule_id)

    # =============================================
    # SEASONAL SYSTEM
    # =============================================
    async def get_seasons(self):
        return await self._qall("SELECT * FROM seasonal_config ORDER BY season_number DESC")
    async def get_current_season(self):
        return await self._qone("SELECT * FROM seasonal_config WHERE status='active' ORDER BY season_number DESC LIMIT 1")
    async def create_season(self, name, number, start, end, reset_xp, reset_elo, reset_coins, rewards, created_by):
        return await self._insert_ret(
            "INSERT INTO seasonal_config (season_name, season_number, start_date, end_date, reset_xp, reset_elo, reset_coins, rewards, created_by) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *",
            name, number, start, end, reset_xp, reset_elo, reset_coins, json.dumps(rewards or {}), created_by)
    async def update_season_status(self, sid, status):
        await self._exec("UPDATE seasonal_config SET status=$2 WHERE id=$1", sid, status)

    # =============================================
    # TOURNAMENTS (Comprehensive System)
    # =============================================
    async def get_tournaments(self, status=None, limit=20):
        if status: return await self._qall("SELECT * FROM dash_tournaments WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM dash_tournaments ORDER BY created_at DESC LIMIT $1", limit)

    async def get_tournament(self, tid):
        t = await self._qone("SELECT * FROM dash_tournaments WHERE id=$1", tid)
        if t:
            t["participants"] = await self._qall("SELECT * FROM dash_tournament_participants WHERE tournament_id=$1 ORDER BY seed ASC", tid)
            t["teams"] = await self._qall("SELECT * FROM tournament_teams WHERE tournament_id=$1 ORDER BY seed ASC", tid)
            t["matches"] = await self._qall("SELECT * FROM tournament_matches WHERE tournament_id=$1 ORDER BY round_num ASC, match_num ASC", tid)
            users = await self._users()
            for p in t["participants"]:
                u = users.get(str(p["user_id"]), {})
                p["roblox_username"] = u.get("roblox_username") or u.get("username") or "Unknown"
                p["elo_rating"] = u.get("elo_rating", 1000)
                p["avatar_url"] = u.get("avatar_url") or self.get_avatar_url(u)
                p["clan_rank"] = u.get("rank", "")
            for team in t["teams"]:
                team["members"] = await self._qall("SELECT * FROM tournament_team_members WHERE team_id=$1", team["id"])
                for m in team["members"]:
                    u = users.get(str(m["user_id"]), {})
                    m["roblox_username"] = u.get("roblox_username") or u.get("username") or "Unknown"
            t["dispute_count"] = await self._qval("SELECT COUNT(*) FROM tournament_disputes WHERE tournament_id=$1 AND status='open'", tid) or 0
        return t

    async def create_tournament(self, **kwargs):
        # Support old-style call: create_tournament(title, bracket_size, ...) 
        if len(kwargs) == 0: return 0
        cols = list(kwargs.keys())
        vals = list(kwargs.values())
        placeholders = [f"${i+1}" for i in range(len(vals))]
        q = f"INSERT INTO dash_tournaments ({','.join(cols)}) VALUES ({','.join(placeholders)}) RETURNING *"
        r = await self._insert_ret(q, *vals)
        return r["id"] if r else 0

    async def update_tournament(self, tid, **kwargs):
        sets, args = [], []
        for i, (k, v) in enumerate(kwargs.items(), 1):
            sets.append(f"{k}=${i}"); args.append(v)
        if not sets: return
        args.append(tid)
        await self._exec(f"UPDATE dash_tournaments SET {', '.join(sets)} WHERE id=${len(args)}", *args)

    async def update_tournament_status(self, tid, status):
        if status == "active": await self._exec("UPDATE dash_tournaments SET status=$2, started_at=NOW() WHERE id=$1", tid, status)
        elif status == "completed": await self._exec("UPDATE dash_tournaments SET status=$2, completed_at=NOW() WHERE id=$1", tid, status)
        elif status == "open": await self._exec("UPDATE dash_tournaments SET status='open' WHERE id=$1", tid)
        else: await self._exec("UPDATE dash_tournaments SET status=$2 WHERE id=$1", tid, status)

    # Participants
    async def add_tournament_participant(self, tid, uid, team_id=None, seed=0):
        await self._exec("INSERT INTO dash_tournament_participants (tournament_id, user_id, team_id, seed) VALUES ($1,$2,$3,$4) ON CONFLICT DO NOTHING", tid, uid, team_id, seed)
    async def remove_tournament_participant(self, tid, uid):
        await self._exec("DELETE FROM dash_tournament_participants WHERE tournament_id=$1 AND user_id=$2", tid, uid)
    async def disqualify_participant(self, tid, uid):
        await self._exec("UPDATE dash_tournament_participants SET status='disqualified', eliminated_at=NOW() WHERE tournament_id=$1 AND user_id=$2", tid, uid)
    async def checkin_participant(self, tid, uid):
        await self._exec("UPDATE dash_tournament_participants SET checked_in=TRUE, checked_in_at=NOW() WHERE tournament_id=$1 AND user_id=$2", tid, uid)

    # Teams
    async def create_team(self, tid, team_name, captain_id, icon_url=""):
        return await self._insert_ret("INSERT INTO tournament_teams (tournament_id, team_name, captain_user_id, team_icon_url) VALUES ($1,$2,$3,$4) RETURNING *", tid, team_name, captain_id, icon_url)
    async def add_team_member(self, team_id, uid, role="member"):
        await self._exec("INSERT INTO tournament_team_members (team_id, user_id, role) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING", team_id, uid, role)

    # Matches
    async def create_match(self, tid, round_num, match_num, p1_id=None, p2_id=None, t1_id=None, t2_id=None):
        return await self._insert_ret(
            "INSERT INTO tournament_matches (tournament_id, round_num, match_num, player1_id, player2_id, team1_id, team2_id) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
            tid, round_num, match_num, p1_id, p2_id, t1_id, t2_id)
    async def submit_match_result(self, match_id, winner_id, p1_score=0, p2_score=0, screenshot="", reported_by=None):
        await self._exec("UPDATE tournament_matches SET winner_id=$2, player1_score=$3, player2_score=$4, screenshot_url=$5, reported_by=$6, status='submitted', completed_at=NOW() WHERE id=$1",
            match_id, winner_id, p1_score, p2_score, screenshot, reported_by)
    async def confirm_match_result(self, match_id, confirmed_by):
        await self._exec("UPDATE tournament_matches SET confirmed_by=$2, status='verified' WHERE id=$1", match_id, confirmed_by)
    async def staff_override_match(self, match_id, winner_id, staff_id, notes=""):
        await self._exec("UPDATE tournament_matches SET winner_id=$2, staff_override_by=$3, staff_notes=$4, status='verified', completed_at=NOW() WHERE id=$1",
            match_id, winner_id, staff_id, notes)

    # Disputes
    async def create_tournament_dispute(self, tid, match_id, filed_by, filed_by_name, reason, evidence=""):
        await self._exec("UPDATE tournament_matches SET status='disputed', dispute_reason=$2 WHERE id=$1", match_id, reason)
        return await self._insert_ret("INSERT INTO tournament_disputes (tournament_id, match_id, filed_by, filed_by_name, reason, evidence_url) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *",
            tid, match_id, filed_by, filed_by_name, reason, evidence)
    async def get_tournament_disputes(self, status=None, tid=None, limit=50):
        q = "SELECT td.*, t.title as tournament_title FROM tournament_disputes td LEFT JOIN dash_tournaments t ON td.tournament_id=t.id WHERE 1=1"
        args = []
        if status: args.append(status); q += f" AND td.status=${len(args)}"
        if tid: args.append(tid); q += f" AND td.tournament_id=${len(args)}"
        q += f" ORDER BY td.created_at DESC LIMIT ${len(args)+1}"; args.append(limit)
        return await self._qall(q, *args)
    async def resolve_tournament_dispute(self, dispute_id, resolution, winner_id, resolved_by, resolved_by_name):
        d = await self._qone("SELECT * FROM tournament_disputes WHERE id=$1", dispute_id)
        if d:
            await self._exec("UPDATE tournament_disputes SET status='resolved', resolution=$2, resolved_by=$3, resolved_by_name=$4, resolved_at=NOW() WHERE id=$1",
                dispute_id, resolution, resolved_by, resolved_by_name)
            if d["match_id"] and winner_id:
                await self.staff_override_match(d["match_id"], winner_id, resolved_by, f"Dispute #{dispute_id}: {resolution}")
        return d

    # Bracket
    async def update_bracket(self, tid, bracket_data):
        await self._exec("UPDATE dash_tournaments SET bracket=$2 WHERE id=$1", tid, json.dumps(bracket_data))

    async def generate_bracket(self, tid):
        t = await self.get_tournament(tid)
        if not t: return None
        participants = [p for p in (t.get("participants") or []) if p["status"] == "active"]
        if len(participants) < 2: return None
        random.shuffle(participants)
        size = t.get("bracket_size", 8)
        while size < len(participants): size *= 2
        bracket = {"rounds": [], "size": size, "entries": len(participants), "format": t.get("match_format","1v1")}
        # Round 1
        round1 = []
        padded = participants + [None] * (size - len(participants))
        for i in range(0, size, 2):
            p1 = padded[i]; p2 = padded[i+1] if i+1 < len(padded) else None
            match = {"match_id": len(round1)+1,
                "player1": {"user_id": p1["user_id"], "name": p1.get("roblox_username","Unknown"), "seed": i+1, "avatar_url": p1.get("avatar_url","")} if p1 else None,
                "player2": {"user_id": p2["user_id"], "name": p2.get("roblox_username","Unknown"), "seed": i+2, "avatar_url": p2.get("avatar_url","")} if p2 else None,
                "winner": None, "score": "", "p1_score": 0, "p2_score": 0}
            if p1 and not p2: match["winner"] = p1["user_id"]
            elif p2 and not p1: match["winner"] = p2["user_id"]
            round1.append(match)
            if p1 and p2:
                await self.create_match(tid, 1, len(round1), p1_id=p1["user_id"], p2_id=p2["user_id"])
        bracket["rounds"].append({"round_num": 1, "name": "Round 1", "matches": round1})
        prev = len(round1); rn = 2
        while prev > 1:
            nm = []
            for i in range(prev // 2):
                nm.append({"match_id": i+1, "player1": None, "player2": None, "winner": None, "score": "", "p1_score": 0, "p2_score": 0, "feeds_from": [i*2+1, i*2+2]})
            name = "Finals" if prev//2 == 1 else ("Semi-Finals" if prev//2 == 2 else f"Round {rn}")
            bracket["rounds"].append({"round_num": rn, "name": name, "matches": nm})
            prev = len(nm); rn += 1
        for i, p in enumerate(participants):
            await self._exec("UPDATE dash_tournament_participants SET seed=$3 WHERE tournament_id=$1 AND user_id=$2", tid, p["user_id"], i+1)
        await self.update_bracket(tid, bracket)
        return bracket

    async def update_match_result(self, tid, round_num, match_id, winner_id, score="", p1_score=0, p2_score=0):
        t = await self._qone("SELECT bracket, is_ranked, match_format, season_id FROM dash_tournaments WHERE id=$1", tid)
        if not t: return False
        bracket = t["bracket"]
        if isinstance(bracket, str): bracket = json.loads(bracket)
        for rnd in bracket.get("rounds", []):
            if rnd["round_num"] == round_num:
                for m in rnd["matches"]:
                    if m["match_id"] == match_id:
                        m["winner"] = winner_id; m["score"] = score
                        m["p1_score"] = p1_score; m["p2_score"] = p2_score; break
        # Advance winner
        next_round = None
        for rnd in bracket.get("rounds", []):
            if rnd["round_num"] == round_num + 1: next_round = rnd; break
        if next_round:
            si = (match_id - 1) // 2; sp = (match_id - 1) % 2
            if si < len(next_round["matches"]):
                users = await self._users()
                wn = users.get(str(winner_id), {}).get("roblox_username") or "Unknown"
                wa = users.get(str(winner_id), {}).get("avatar_url") or ""
                player = {"user_id": winner_id, "name": wn, "avatar_url": wa}
                if sp == 0: next_round["matches"][si]["player1"] = player
                else: next_round["matches"][si]["player2"] = player
        # Eliminate loser
        for rnd in bracket.get("rounds", []):
            if rnd["round_num"] == round_num:
                for m in rnd["matches"]:
                    if m["match_id"] == match_id:
                        loser = None
                        if m.get("player1") and m["player1"].get("user_id") != winner_id: loser = m["player1"]["user_id"]
                        elif m.get("player2") and m["player2"].get("user_id") != winner_id: loser = m["player2"]["user_id"]
                        if loser: await self.disqualify_participant(tid, loser)
        await self.update_bracket(tid, bracket)
        # Ranking points for ranked tournaments
        if t.get("is_ranked"):
            await self._update_rankings(tid, round_num, winner_id, bracket, t.get("match_format","1v1"), t.get("season_id") or 0)
        return True

    # =============================================
    # RANKING / TOP 10 SYSTEM
    # =============================================
    RANKING_TIERS = [
        (2000, "Champion", "#FFD700"), (1800, "Grand Master", "#E74C3C"),
        (1600, "Master", "#9B59B6"), (1400, "Diamond", "#3498DB"),
        (1200, "Platinum", "#BDC3C7"), (1000, "Gold", "#F39C12"),
        (800, "Silver", "#95A5A6"), (600, "Bronze", "#CD7F32"), (0, "Unranked", "#666")
    ]
    def _get_tier(self, points):
        for threshold, name, _ in self.RANKING_TIERS:
            if points >= threshold: return name
        return "Unranked"
    def _get_tier_color(self, points):
        for threshold, _, color in self.RANKING_TIERS:
            if points >= threshold: return color
        return "#666"
    def _get_tier_progress(self, points):
        for i, (threshold, name, _) in enumerate(self.RANKING_TIERS):
            if points >= threshold:
                next_t = self.RANKING_TIERS[i-1][0] if i > 0 else threshold + 200
                return {"tier": name, "points": points, "tier_min": threshold, "tier_max": next_t,
                    "progress": min(100, int((points - threshold) / max(1, next_t - threshold) * 100))}
        return {"tier": "Unranked", "points": points, "tier_min": 0, "tier_max": 600, "progress": int(points / 6)}

    async def _update_rankings(self, tid, round_num, winner_id, bracket, fmt, season_id):
        loser_id = None
        for rnd in bracket.get("rounds", []):
            if rnd["round_num"] == round_num:
                for m in rnd["matches"]:
                    if m.get("winner") == winner_id:
                        if m.get("player1") and m["player1"].get("user_id") != winner_id: loser_id = m["player1"]["user_id"]
                        elif m.get("player2") and m["player2"].get("user_id") != winner_id: loser_id = m["player2"]["user_id"]
        total_rounds = len(bracket.get("rounds", []))
        base_gain = 25 + (round_num * 5)
        if round_num == total_rounds: base_gain += 20
        # Winner
        await self._exec("""INSERT INTO ranking_ladders (user_id, format, season_id, points, peak_points, wins, streak, best_streak, last_match_at, tier)
            VALUES ($1,$2,$3,$4,$4,1,1,1,NOW(),$5) ON CONFLICT (user_id, format, season_id) DO UPDATE SET
            points = ranking_ladders.points + $6, peak_points = GREATEST(ranking_ladders.peak_points, ranking_ladders.points + $6),
            wins = ranking_ladders.wins + 1, streak = CASE WHEN ranking_ladders.streak >= 0 THEN ranking_ladders.streak + 1 ELSE 1 END,
            best_streak = GREATEST(ranking_ladders.best_streak, CASE WHEN ranking_ladders.streak >= 0 THEN ranking_ladders.streak + 1 ELSE 1 END),
            last_match_at = NOW()""", winner_id, fmt, season_id, 1000 + base_gain, self._get_tier(1000 + base_gain), base_gain)
        w = await self._qone("SELECT points FROM ranking_ladders WHERE user_id=$1 AND format=$2 AND season_id=$3", winner_id, fmt, season_id)
        if w: await self._exec("UPDATE ranking_ladders SET tier=$4 WHERE user_id=$1 AND format=$2 AND season_id=$3", winner_id, fmt, season_id, self._get_tier(w["points"]))
        await self._exec("INSERT INTO ranking_history (user_id, format, season_id, tournament_id, points_before, points_after, change, reason) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)",
            winner_id, fmt, season_id, tid, (w["points"] if w else 1000) - base_gain, w["points"] if w else 1000, base_gain, f"Win R{round_num}")
        await self._exec("UPDATE dash_tournament_participants SET ranking_points_change=ranking_points_change+$3 WHERE tournament_id=$1 AND user_id=$2", tid, winner_id, base_gain)
        # Loser
        if loser_id:
            loss = max(10, base_gain // 2)
            await self._exec("""INSERT INTO ranking_ladders (user_id, format, season_id, points, peak_points, losses, streak, last_match_at, tier)
                VALUES ($1,$2,$3,$4,$4,1,-1,NOW(),$5) ON CONFLICT (user_id, format, season_id) DO UPDATE SET
                points = GREATEST(0, ranking_ladders.points - $6), losses = ranking_ladders.losses + 1,
                streak = CASE WHEN ranking_ladders.streak <= 0 THEN ranking_ladders.streak - 1 ELSE -1 END, last_match_at = NOW()""",
                loser_id, fmt, season_id, max(0, 1000 - loss), self._get_tier(max(0, 1000 - loss)), loss)
            l = await self._qone("SELECT points FROM ranking_ladders WHERE user_id=$1 AND format=$2 AND season_id=$3", loser_id, fmt, season_id)
            if l:
                await self._exec("UPDATE ranking_ladders SET tier=$4 WHERE user_id=$1 AND format=$2 AND season_id=$3", loser_id, fmt, season_id, self._get_tier(l["points"]))
                await self._exec("INSERT INTO ranking_history (user_id, format, season_id, points_before, points_after, change, reason) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    loser_id, fmt, season_id, l["points"] + loss, l["points"], -loss, f"Loss R{round_num}")
            await self._exec("UPDATE dash_tournament_participants SET ranking_points_change=ranking_points_change-$3 WHERE tournament_id=$1 AND user_id=$2", tid, loser_id, loss)

    async def get_top_rankings(self, fmt="1v1", season_id=0, limit=10):
        rows = await self._qall("SELECT * FROM ranking_ladders WHERE format=$1 AND season_id=$2 AND points > 0 ORDER BY points DESC LIMIT $3", fmt, season_id, limit)
        users = await self._users()
        for r in rows:
            u = users.get(str(r["user_id"]), {})
            r["roblox_username"] = u.get("roblox_username") or u.get("username") or "Unknown"
            r["avatar_url"] = u.get("avatar_url") or self.get_avatar_url(u)
            r["clan_rank"] = u.get("rank") or ""; r["tier_color"] = self._get_tier_color(r["points"])
            r["progress"] = self._get_tier_progress(r["points"])
        return rows
    async def get_player_ranking(self, uid, fmt="1v1", season_id=0):
        r = await self._qone("SELECT * FROM ranking_ladders WHERE user_id=$1 AND format=$2 AND season_id=$3", uid, fmt, season_id)
        if r: r["progress"] = self._get_tier_progress(r["points"]); r["tier_color"] = self._get_tier_color(r["points"])
        return r
    async def get_ranking_history(self, uid, fmt="1v1", limit=20):
        return await self._qall("SELECT * FROM ranking_history WHERE user_id=$1 AND format=$2 ORDER BY created_at DESC LIMIT $3", uid, fmt, limit)
    async def adjust_ranking(self, uid, fmt, amount, reason, staff_id, season_id=0):
        await self._exec("""INSERT INTO ranking_ladders (user_id, format, season_id, points, peak_points, tier)
            VALUES ($1,$2,$3,GREATEST(0,1000+$4),GREATEST(1000,1000+$4),$5) ON CONFLICT (user_id, format, season_id) DO UPDATE SET
            points = GREATEST(0, ranking_ladders.points + $4), peak_points = GREATEST(ranking_ladders.peak_points, ranking_ladders.points + $4)""",
            uid, fmt, season_id, amount, self._get_tier(1000 + amount))
        r = await self._qone("SELECT points FROM ranking_ladders WHERE user_id=$1 AND format=$2 AND season_id=$3", uid, fmt, season_id)
        if r: await self._exec("UPDATE ranking_ladders SET tier=$4 WHERE user_id=$1 AND format=$2 AND season_id=$3", uid, fmt, season_id, self._get_tier(r["points"]))

    # Tournament Seasons
    async def get_tournament_seasons(self, limit=10):
        return await self._qall("SELECT * FROM tournament_seasons ORDER BY created_at DESC LIMIT $1", limit)
    async def get_active_tournament_season(self):
        return await self._qone("SELECT * FROM tournament_seasons WHERE status='active' ORDER BY created_at DESC LIMIT 1")
    async def create_tournament_season(self, name, rewards="", champion_role="", created_by=0):
        return await self._insert_ret("INSERT INTO tournament_seasons (name, rewards_description, champion_role, created_by) VALUES ($1,$2,$3,$4) RETURNING *", name, rewards, champion_role, created_by)
    async def end_tournament_season(self, sid):
        await self._exec("UPDATE tournament_seasons SET status='ended', end_date=NOW() WHERE id=$1", sid)

    # == PENDING ACTIONS ==
    async def queue_action(self, action_type, target_user_id, staff_id, staff_name, params=None):
        r = await self._insert_ret("INSERT INTO pending_dashboard_actions (action_type, target_user_id, staff_id, staff_name, params) VALUES ($1,$2,$3,$4,$5) RETURNING id",
            action_type, target_user_id, staff_id, staff_name, json.dumps(params or {}))
        return r["id"] if r else 0
    async def get_pending_actions(self, limit=50):
        return await self._qall("SELECT * FROM pending_dashboard_actions ORDER BY created_at DESC LIMIT $1", limit)
    async def get_action_history(self, target_id=None, limit=30):
        if target_id: return await self._qall("SELECT * FROM pending_dashboard_actions WHERE target_user_id=$1 ORDER BY created_at DESC LIMIT $2", target_id, limit)
        return await self._qall("SELECT * FROM pending_dashboard_actions ORDER BY created_at DESC LIMIT $1", limit)
    async def get_transactions(self, user_id=None, limit=50):
        return await self._qall("SELECT * FROM pending_dashboard_actions WHERE action_type IN ('add_coins','add_xp') ORDER BY created_at DESC LIMIT $1", limit)
    async def get_pending_actions_by_status(self, status="pending", limit=10):
        return await self._qall("SELECT * FROM pending_dashboard_actions WHERE status=$1 ORDER BY created_at ASC LIMIT $2", status, limit)
    async def update_action_status(self, action_id, status, result=""):
        await self._exec("UPDATE pending_dashboard_actions SET status=$2, result=$3, executed_at=NOW() WHERE id=$1", action_id, status, result)
    async def get_action_stats(self):
        rows = await self._qall("SELECT status, COUNT(*) as cnt FROM pending_dashboard_actions GROUP BY status")
        stats = {r["status"]: r["cnt"] for r in rows}
        total = sum(stats.values())
        return {"total": total, "pending": stats.get("pending", 0), "done": stats.get("done", 0), "failed": stats.get("failed", 0)}
    async def get_action_history_filtered(self, status=None, limit=50):
        if status:
            return await self._qall("SELECT * FROM pending_dashboard_actions WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM pending_dashboard_actions ORDER BY created_at DESC LIMIT $1", limit)

    # == LEVEL BG ==
    async def set_user_bg(self, user_id, bg_key):
        return await self.queue_action("set_bg", user_id, user_id, "web_dashboard", {"bg_key": bg_key})
    async def get_user_bg(self, user_id):
        u = await self.get_user(user_id)
        return u.get("custom_level_bg") if u else None

    # == XP STATS ==
    async def get_xp_stats(self):
        users = await self._users()
        total_xp = sum(u.get("xp", 0) or 0 for u in users.values())
        levels = [u.get("level", 0) or 0 for u in users.values()]
        level_dist = Counter()
        for lvl in levels:
            bucket = f"{(lvl//5)*5}-{(lvl//5)*5+4}"
            level_dist[bucket] += 1
        top_xp = sorted(users.items(), key=lambda x: x[1].get("xp", 0) or 0, reverse=True)[:10]
        return {
            "total_xp": total_xp, "avg_xp": total_xp // max(len(users), 1),
            "max_level": max(levels) if levels else 0,
            "avg_level": sum(levels) // max(len(levels), 1), "total_users": len(users),
            "level_distribution": dict(sorted(level_dist.items())),
            "top_xp": [{"user_id": int(uid), "name": u.get("roblox_username", "Unknown"),
                        "xp": u.get("xp", 0) or 0, "level": u.get("level", 0) or 0} for uid, u in top_xp],
        }

    # == STAFF PERFORMANCE ==
    async def get_staff_performance(self, days=30):
        cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)).isoformat()
        staff = await self.get_staff_members()
        result = []
        for s in staff:
            sid = s["discord_user_id"]
            actions = await self._qone("SELECT COUNT(*) as total FROM dashboard_audit_log WHERE staff_id=$1 AND created_at > $2", sid, cutoff)
            cases = await self._qone("SELECT COUNT(*) as total FROM mod_cases WHERE staff_id=$1 AND created_at > $2", sid, cutoff)
            sessions = await self._qone("SELECT COUNT(*) as total, MAX(created_at) as last FROM staff_sessions WHERE staff_id=$1 AND created_at > $2", sid, cutoff)
            result.append({
                "staff_id": sid, "name": s["display_name"], "tier": s["permission_tier"],
                "actions": actions["total"] if actions else 0,
                "cases": cases["total"] if cases else 0,
                "logins": sessions["total"] if sessions else 0,
                "last_login": s.get("last_login"),
                "last_action": s.get("last_action"),
            })
        result.sort(key=lambda x: x["actions"], reverse=True)
        return result
    # =============================================
    # DUEL DISPUTES
    # =============================================
    async def create_dispute(self, duel_index, challenger_id, opponent_id, filed_by, filed_by_name, reason, evidence=""):
        return await self._insert_ret(
            "INSERT INTO duel_disputes (duel_index, challenger_id, opponent_id, filed_by, filed_by_name, reason, evidence) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
            duel_index, challenger_id, opponent_id, filed_by, filed_by_name, reason, evidence)
    async def get_disputes(self, status=None, limit=50):
        if status: return await self._qall("SELECT * FROM duel_disputes WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM duel_disputes ORDER BY created_at DESC LIMIT $1", limit)
    async def get_dispute(self, did):
        return await self._qone("SELECT * FROM duel_disputes WHERE id=$1", did)
    async def resolve_dispute(self, did, resolution, reviewed_by, reviewed_by_name):
        await self._exec("UPDATE duel_disputes SET status='resolved', resolution=$2, reviewed_by=$3, reviewed_by_name=$4, reviewed_at=NOW() WHERE id=$1",
            did, resolution, reviewed_by, reviewed_by_name)
    async def reject_dispute(self, did, resolution, reviewed_by, reviewed_by_name):
        await self._exec("UPDATE duel_disputes SET status='rejected', resolution=$2, reviewed_by=$3, reviewed_by_name=$4, reviewed_at=NOW() WHERE id=$1",
            did, resolution, reviewed_by, reviewed_by_name)

    # =============================================
    # DISCORD ROLE HISTORY
    # =============================================
    async def add_role_history(self, user_id, role_id, role_name, action, changed_by=None, reason=""):
        await self._exec("INSERT INTO discord_role_history (user_id, role_id, role_name, action, changed_by, reason) VALUES ($1,$2,$3,$4,$5,$6)",
            user_id, role_id, role_name, action, changed_by, reason)
    async def get_role_history(self, user_id=None, limit=50):
        if user_id: return await self._qall("SELECT * FROM discord_role_history WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2", user_id, limit)
        return await self._qall("SELECT * FROM discord_role_history ORDER BY created_at DESC LIMIT $1", limit)

    # =============================================
    # AUTO-ESCALATION
    # =============================================
    async def check_auto_escalation(self, user_id, current_points, staff_id, staff_name):
        """Check if warning points trigger automatic punishment. Returns action taken or None."""
        for threshold in ESCALATION_THRESHOLDS:
            if current_points >= threshold["points"]:
                # Check if this escalation was already applied
                existing = await self._qone(
                    "SELECT id FROM pending_dashboard_actions WHERE target_user_id=$1 AND action_type=$2 AND params::text LIKE '%auto_escalation%' AND created_at > NOW() - INTERVAL '1 hour'",
                    user_id, threshold["action"])
                if existing: continue
                params = {"reason": threshold["reason"], "auto_escalation": True}
                if threshold["action"] == "timeout": params["duration_minutes"] = threshold.get("duration_minutes", 30)
                await self.queue_action(threshold["action"], user_id, staff_id, staff_name, params)
                # Create mod case for the auto action
                await self.create_case(user_id, threshold["action"], "auto_escalation", "high" if threshold["action"] == "ban" else "medium",
                    threshold["reason"], threshold["points"], staff_id, f"AUTO: {staff_name}")
                # Queue mod-log webhook
                await self.queue_action("mod_log_webhook", user_id, staff_id, staff_name, {
                    "action": threshold["action"], "reason": threshold["reason"],
                    "points": current_points, "auto": True})
                return threshold
        return None

    # =============================================
    # ACTIVITY SCORES
    # =============================================
    async def compute_activity_score(self, user_id) -> float:
        """Compute a weighted activity score for a user"""
        u = (await self._users()).get(str(user_id), {})
        msgs = u.get("messages", 0) or 0
        voice = (u.get("voice_time", 0) or 0) / 60  # convert seconds to minutes
        duels_data = await self._duels()
        elo_entry = duels_data.get("elo", {}).get(str(user_id), {})
        duel_count = (elo_entry.get("wins", 0) if isinstance(elo_entry, dict) else 0) + (elo_entry.get("losses", 0) if isinstance(elo_entry, dict) else 0)
        raids = u.get("raid_participation", 0) or 0
        score = (msgs * ACTIVITY_WEIGHTS["messages"] +
                 voice * ACTIVITY_WEIGHTS["voice_minutes"] +
                 duel_count * ACTIVITY_WEIGHTS["duels"] +
                 raids * ACTIVITY_WEIGHTS["raids"])
        return round(score, 1)

    async def get_activity_leaderboard(self, limit=25):
        users = await self._users()
        duels_data = await self._duels()
        items = []
        for uid_s, u in users.items():
            msgs = u.get("messages", 0) or 0
            voice = (u.get("voice_time", 0) or 0) / 60
            elo_entry = duels_data.get("elo", {}).get(uid_s, {})
            duel_count = (elo_entry.get("wins", 0) if isinstance(elo_entry, dict) else 0) + (elo_entry.get("losses", 0) if isinstance(elo_entry, dict) else 0)
            raids = u.get("raid_participation", 0) or 0
            score = (msgs * ACTIVITY_WEIGHTS["messages"] + voice * ACTIVITY_WEIGHTS["voice_minutes"] +
                     duel_count * ACTIVITY_WEIGHTS["duels"] + raids * ACTIVITY_WEIGHTS["raids"])
            items.append({"user_id": int(uid_s), "name": u.get("roblox_username", "Unknown"),
                          "score": round(score, 1), "messages": msgs, "voice_minutes": round(voice),
                          "duels": duel_count, "raids": raids, "level": u.get("level", 0) or 0})
        items.sort(key=lambda x: x["score"], reverse=True)
        return items[:limit]

    # =============================================
    # SEASONAL LEADERBOARDS
    # =============================================
    async def get_seasonal_leaderboard(self, season_id, sort_key="xp", limit=25):
        """Get leaderboard filtered by season (using archive data)"""
        season = await self._qone("SELECT * FROM seasonal_config WHERE id=$1", season_id)
        if not season or not season.get("archive_data"): return []
        archive = season["archive_data"]
        if isinstance(archive, str): archive = json.loads(archive)
        users = archive.get("users", {})
        items = []
        for uid_s, u in users.items():
            u["user_id"] = int(uid_s)
            u["avatar_url"] = u.get("avatar_url") or self.get_avatar_url(u)
            items.append(u)
        items.sort(key=lambda x: x.get(sort_key, 0) or 0, reverse=True)
        return items[:limit]

    async def archive_season_data(self, season_id):
        """Snapshot current user data into season archive"""
        users = await self._users()
        duels = await self._duels()
        archive = {"users": {}, "elo": duels.get("elo", {}), "archived_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        for uid, u in users.items():
            archive["users"][uid] = {"xp": u.get("xp", 0), "level": u.get("level", 0), "coins": u.get("coins", 0),
                "messages": u.get("messages", 0), "roblox_username": u.get("roblox_username", "Unknown")}
        await self._exec("UPDATE seasonal_config SET archive_data=$2 WHERE id=$1", season_id, json.dumps(archive))

    # =============================================
    # RECRUITMENT (full)
    # =============================================
    async def get_open_positions(self):
        return await self._qall("SELECT * FROM recruitment_positions WHERE status='open' ORDER BY created_at DESC")
    async def get_all_positions(self):
        return await self._qall("SELECT * FROM recruitment_positions ORDER BY created_at DESC")
    async def get_position(self, pid):
        return await self._qone("SELECT * FROM recruitment_positions WHERE id=$1", pid)
    async def create_position(self, title, description, requirements, max_applicants, created_by):
        return await self._insert_ret("INSERT INTO recruitment_positions (title, description, requirements, max_applicants, created_by) VALUES ($1,$2,$3,$4,$5) RETURNING *",
            title, description, requirements, max_applicants, created_by)
    async def close_position(self, pid):
        await self._exec("UPDATE recruitment_positions SET status='closed' WHERE id=$1", pid)
    async def reopen_position(self, pid):
        await self._exec("UPDATE recruitment_positions SET status='open' WHERE id=$1", pid)

    async def get_applications(self, status=None, limit=50):
        if status: return await self._qall(
            "SELECT a.*, p.title as position_title FROM recruitment_applications a LEFT JOIN recruitment_positions p ON a.position_id=p.id WHERE a.status=$1 ORDER BY a.created_at DESC LIMIT $2", status, limit)
        return await self._qall(
            "SELECT a.*, p.title as position_title FROM recruitment_applications a LEFT JOIN recruitment_positions p ON a.position_id=p.id ORDER BY a.created_at DESC LIMIT $1", limit)
    async def get_application(self, aid):
        app = await self._qone("SELECT a.*, p.title as position_title, p.requirements FROM recruitment_applications a LEFT JOIN recruitment_positions p ON a.position_id=p.id WHERE a.id=$1", aid)
        if app:
            app["votes"] = await self.get_votes(aid)
            users = await self._users()
            u = users.get(str(app["user_id"]), {})
            app["roblox_username"] = u.get("roblox_username", "Unknown")
            app["level"] = u.get("level", 0) or 0
            app["xp"] = u.get("xp", 0) or 0
        return app
    async def get_user_applications(self, user_id):
        return await self._qall("SELECT a.*, p.title as position_title FROM recruitment_applications a LEFT JOIN recruitment_positions p ON a.position_id=p.id WHERE a.user_id=$1 ORDER BY a.created_at DESC", user_id)
    async def submit_application(self, user_id, position_id, answers):
        if not self.pool: return False
        try:
            async with self.pool.acquire() as c:
                await c.execute("INSERT INTO recruitment_applications (user_id, position_id, answers, status) VALUES ($1, $2, $3, 'applied')", user_id, position_id, answers)
            return True
        except Exception as e: print(f"[DB] App submit: {e}"); return False
    async def update_application_status(self, aid, status, reviewed_by, review_note=""):
        await self._exec("UPDATE recruitment_applications SET status=$2, reviewed_by=$3, review_note=$4, reviewed_at=NOW() WHERE id=$1", aid, status, reviewed_by, review_note)

    async def add_vote(self, app_id, staff_id, vote, comment=""):
        await self._exec("INSERT INTO recruitment_votes (application_id, staff_id, vote, comment) VALUES ($1,$2,$3,$4) ON CONFLICT (application_id, staff_id) DO UPDATE SET vote=$3, comment=$4", app_id, staff_id, vote, comment)
    async def get_votes(self, app_id):
        return await self._qall("SELECT * FROM recruitment_votes WHERE application_id=$1 ORDER BY created_at", app_id)

    # =============================================
    # INTERACTION CONFIG (buttons/dropdowns for embeds)
    # =============================================
    async def get_interactions(self, embed_id):
        return await self._qall("SELECT * FROM interaction_config WHERE embed_id=$1 ORDER BY id ASC", embed_id)
    async def add_interaction(self, embed_id, itype, custom_id, label, style, emoji, action_type, action_value, required_role_id=None):
        return await self._insert_ret(
            "INSERT INTO interaction_config (embed_id, interaction_type, custom_id, label, style, emoji, action_type, action_value, required_role_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *",
            embed_id, itype, custom_id, label, style, emoji, action_type, action_value, required_role_id)
    async def update_interaction(self, iid, label, style, emoji, action_type, action_value, enabled, required_role_id):
        await self._exec("UPDATE interaction_config SET label=$2, style=$3, emoji=$4, action_type=$5, action_value=$6, enabled=$7, required_role_id=$8 WHERE id=$1",
            iid, label, style, emoji, action_type, action_value, enabled, required_role_id)
    async def delete_interaction(self, iid):
        await self._exec("DELETE FROM interaction_config WHERE id=$1", iid)
    async def toggle_interaction(self, iid):
        await self._exec("UPDATE interaction_config SET enabled = NOT enabled WHERE id=$1", iid)

    # =============================================
    # SESSION MANAGEMENT
    # =============================================
    async def create_session_token(self, user_id, ip, hours=24):
        token = hashlib.sha256(f"{user_id}{datetime.datetime.now().isoformat()}{random.random()}".encode()).hexdigest()
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
        await self._exec("INSERT INTO session_tokens (user_id, token_hash, ip_address, expires_at) VALUES ($1,$2,$3,$4)", user_id, token, ip, expires)
        return token
    async def validate_session_token(self, token):
        r = await self._qone("SELECT * FROM session_tokens WHERE token_hash=$1 AND invalidated=FALSE AND expires_at > NOW()", token)
        return r
    async def invalidate_user_sessions(self, user_id):
        """Force re-auth by invalidating all sessions for a user"""
        await self._exec("UPDATE session_tokens SET invalidated=TRUE WHERE user_id=$1", user_id)
    async def cleanup_expired_sessions(self):
        await self._exec("DELETE FROM session_tokens WHERE expires_at < NOW() - INTERVAL '7 days'")

    # =============================================
    # SERVER CONFIG (multi-server)
    # =============================================
    async def get_server_config(self, guild_id):
        r = await self._qone("SELECT * FROM server_config WHERE guild_id=$1", guild_id)
        return r or {"guild_id": guild_id, "config": {}, "features": {}, "embed_categories": EMBED_CATEGORIES}
    async def save_server_config(self, guild_id, guild_name, config, features):
        await self._exec("INSERT INTO server_config (guild_id, guild_name, config, features, updated_at) VALUES ($1,$2,$3,$4,NOW()) ON CONFLICT (guild_id) DO UPDATE SET guild_name=$2, config=$3, features=$4, updated_at=NOW()",
            guild_id, guild_name, json.dumps(config), json.dumps(features))
    async def get_embed_category_toggles(self, guild_id):
        sc = await self.get_server_config(guild_id)
        cats = sc.get("embed_categories", EMBED_CATEGORIES)
        if isinstance(cats, str): cats = json.loads(cats)
        return cats
    async def set_embed_category_toggles(self, guild_id, categories):
        await self._exec("UPDATE server_config SET embed_categories=$2, updated_at=NOW() WHERE guild_id=$1", guild_id, json.dumps(categories))

    # =============================================
    # MOD LOG WEBHOOK (sync to Discord)
    # =============================================
    async def queue_mod_log(self, user_id, staff_id, staff_name, action, reason, details=None):
        """Queue a mod-log webhook message for the bot to push to Discord"""
        await self.queue_action("mod_log_webhook", user_id, staff_id, staff_name, {
            "action": action, "reason": reason, "details": details or {}})

    # =============================================
    # BOT STATUS (extended with restart cooldown)
    # =============================================
    async def get_last_restart(self):
        return await self._qone("SELECT * FROM bot_status_log WHERE event='restart' ORDER BY created_at DESC LIMIT 1")
    async def can_restart(self, cooldown_minutes=5):
        last = await self.get_last_restart()
        if not last: return True
        diff = (datetime.datetime.now(datetime.timezone.utc) - last["created_at"]).total_seconds() / 60
        return diff >= cooldown_minutes
    async def request_restart(self, staff_id, staff_name, reason=""):
        if not await self.can_restart(): return False
        await self.queue_action("bot_restart", 0, staff_id, staff_name, {"reason": reason})
        await self.log_bot_status("restarting", "restart", f"Requested by {staff_name}: {reason}")
        return True

    # =============================================
    # ALLIES SYSTEM
    # =============================================
    async def get_allies(self, status=None, visibility=None):
        q = "SELECT * FROM allies WHERE 1=1"
        args = []
        if status: q += f" AND status=${len(args)+1}"; args.append(status)
        if visibility: q += f" AND visibility=${len(args)+1}"; args.append(visibility)
        q += " ORDER BY display_order ASC, allied_at DESC"
        return await self._qall(q, *args) if args else await self._qall(q)

    async def get_ally(self, aid):
        return await self._qone("SELECT * FROM allies WHERE id=$1", aid)

    async def create_ally(self, server_name, description, invite_link, ally_type, tier, server_icon_url="", server_size=0, contact_discord_id=0, notes="", added_by=0):
        return await self._insert_ret(
            """INSERT INTO allies (server_name, description, invite_link, ally_type, tier, server_icon_url, server_size, contact_discord_id, notes, added_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING *""",
            server_name, description, invite_link, ally_type, tier, server_icon_url, server_size, contact_discord_id, notes, added_by)

    async def update_ally(self, aid, **kwargs):
        sets = []
        args = []
        for i, (k, v) in enumerate(kwargs.items(), 1):
            sets.append(f"{k}=${i}")
            args.append(v)
        if not sets: return
        sets.append(f"updated_at=NOW()")
        args.append(aid)
        await self._exec(f"UPDATE allies SET {', '.join(sets)} WHERE id=${len(args)}", *args)

    async def pause_ally(self, aid):
        await self._exec("UPDATE allies SET status='paused', paused_at=NOW(), updated_at=NOW() WHERE id=$1", aid)

    async def remove_ally(self, aid):
        await self._exec("UPDATE allies SET status='removed', removed_at=NOW(), updated_at=NOW() WHERE id=$1", aid)

    async def reactivate_ally(self, aid):
        await self._exec("UPDATE allies SET status='active', paused_at=NULL, removed_at=NULL, updated_at=NOW() WHERE id=$1", aid)

    async def get_ally_stats(self):
        total = await self._qone("SELECT COUNT(*) as total, COUNT(*) FILTER (WHERE status='active') as active, COUNT(*) FILTER (WHERE status='paused') as paused, COUNT(*) FILTER (WHERE status='removed') as removed FROM allies")
        return total or {"total": 0, "active": 0, "paused": 0, "removed": 0}

    # Ally Applications
    async def get_ally_applications(self, status=None, limit=50):
        if status: return await self._qall("SELECT * FROM ally_applications WHERE status=$1 ORDER BY created_at DESC LIMIT $2", status, limit)
        return await self._qall("SELECT * FROM ally_applications ORDER BY created_at DESC LIMIT $1", limit)

    async def get_ally_application(self, app_id):
        return await self._qone("SELECT * FROM ally_applications WHERE id=$1", app_id)

    async def create_ally_application(self, server_name, server_size, invite_link, reason, offering, contact_discord_id, contact_name):
        return await self._insert_ret(
            "INSERT INTO ally_applications (server_name, server_size, invite_link, reason, offering, contact_discord_id, contact_name) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *",
            server_name, server_size, invite_link, reason, offering, contact_discord_id, contact_name)

    async def review_ally_application(self, app_id, status, reviewer_id, reviewer_name, notes=""):
        await self._exec(
            "UPDATE ally_applications SET status=$2, reviewer_id=$3, reviewer_name=$4, review_notes=$5, reviewed_at=NOW() WHERE id=$1",
            app_id, status, reviewer_id, reviewer_name, notes)
        return await self.get_ally_application(app_id)

    async def approve_ally_application(self, app_id, reviewer_id, reviewer_name, ally_type="friendly", tier="bronze", notes=""):
        app = await self.get_ally_application(app_id)
        if not app: return None
        ally = await self.create_ally(
            app["server_name"], app.get("reason", ""), app.get("invite_link", ""),
            ally_type, tier, server_size=app.get("server_size", 0),
            contact_discord_id=int(app.get("contact_discord_id", 0) or 0),
            notes=notes, added_by=reviewer_id)
        if ally:
            await self._exec("UPDATE ally_applications SET status='approved', reviewer_id=$2, reviewer_name=$3, review_notes=$4, reviewed_at=NOW(), ally_id=$5 WHERE id=$1",
                app_id, reviewer_id, reviewer_name, notes, ally["id"])
        return ally

    async def set_ally_embed_ids(self, aid, message_id, channel_id):
        await self._exec("UPDATE allies SET embed_message_id=$2, embed_channel_id=$3, updated_at=NOW() WHERE id=$1", aid, message_id, channel_id)

    async def validate_ally_invite(self, aid):
        await self._exec("UPDATE allies SET last_validated=NOW() WHERE id=$1", aid)

db = DashboardDB()
