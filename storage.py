import json
import sqlite3
from aiogram.fsm.storage.base import BaseStorage, StorageKey


class SQLiteFSMStorage(BaseStorage):
    def __init__(self, db_path: str = "fsm_states.db"):
        self.db_path = db_path
        self._init()

    def _init(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS fsm_states(
                key TEXT PRIMARY KEY,
                state TEXT,
                data TEXT
            )""")

    @staticmethod
    def _k(k: StorageKey) -> str:
        return f"{k.bot_id}:{k.chat_id}:{k.user_id}:{k.destiny}:{k.thread_id or ''}:{k.business_connection_id or ''}"

    async def set_state(self, key, state):
        k = self._k(key)
        state_str = state.state if hasattr(state, "state") else state
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO fsm_states(key, state, data) VALUES (?, ?, '{}') "
                "ON CONFLICT(key) DO UPDATE SET state = excluded.state",
                (k, state_str),
            )

    async def get_state(self, key):
        k = self._k(key)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT state FROM fsm_states WHERE key=?", (k,)).fetchone()
        return row[0] if row else None

    async def set_data(self, key, data):
        k = self._k(key)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO fsm_states(key, state, data) VALUES (?, NULL, ?) "
                "ON CONFLICT(key) DO UPDATE SET data = excluded.data",
                (k, json.dumps(data, default=str)),
            )

    async def get_data(self, key):
        k = self._k(key)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT data FROM fsm_states WHERE key=?", (k,)).fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return {}

    async def close(self):
        pass