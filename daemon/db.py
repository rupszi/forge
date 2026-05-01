"""SQLite database with all memory tables. WAL mode for concurrent access."""

from __future__ import annotations

import atexit
import json
import os
import sqlite3
import weakref
from datetime import datetime, timezone

from .config import DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sprint_id TEXT,
    task_description TEXT NOT NULL,
    task_type TEXT,
    model TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    agent_role TEXT,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    error_category TEXT,
    resolution TEXT,
    evaluator_verdict TEXT,
    evaluator_feedback TEXT,
    revision_count INTEGER DEFAULT 0,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    duration_seconds REAL,
    files_changed TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    topic TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT,
    confidence REAL DEFAULT 0.5,
    times_applied INTEGER DEFAULT 0,
    times_helpful INTEGER DEFAULT 0,
    superseded_by INTEGER,
    created_at TEXT NOT NULL,
    last_used_at TEXT
);

CREATE TABLE IF NOT EXISTS procedures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_pattern TEXT NOT NULL,
    recommended_model TEXT NOT NULL,
    recommended_agent TEXT NOT NULL,
    success_rate REAL DEFAULT 0.0,
    avg_duration REAL DEFAULT 0.0,
    sample_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS research (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    url TEXT,
    title TEXT,
    extracted_content TEXT,
    relevance_score REAL DEFAULT 0.5,
    used_in_task TEXT,
    led_to_success INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS sprint_contracts (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    description TEXT NOT NULL,
    done_criteria TEXT NOT NULL,
    assigned_model TEXT,
    assigned_worktree TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    project_path TEXT NOT NULL,
    objective TEXT,
    detected_stack TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    total_sprints INTEGER DEFAULT 0,
    completed_sprints INTEGER DEFAULT 0,
    failed_sprints INTEGER DEFAULT 0,
    total_cost REAL DEFAULT 0.0,
    knowledge_items_created INTEGER DEFAULT 0,
    knowledge_items_applied INTEGER DEFAULT 0
);

-- Append-only audit log of plugin (skill / connector / LLM-adapter) invocations.
-- Layer 7 of the seven-layer security model (docs/SKILLS.md). Every dispatch
-- through daemon/skills/dispatch.py writes one row here BEFORE spawning the
-- subprocess and updates exit_code/duration via INSERT OR REPLACE — except
-- the schema itself blocks UPDATE / DELETE via the triggers below, so the
-- updater path is also INSERT (never modify a finalized row in place).
--
-- The triggers refuse any UPDATE / DELETE — once a row lands it's immutable.
-- This means the dispatcher writes a "started" row, then writes a "completed"
-- row with the same invocation_id; queries pick the most recent state via
-- ROWID DESC. Append-only by construction; no privileged role can rewrite history.
CREATE TABLE IF NOT EXISTS skill_invocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invocation_id TEXT NOT NULL,
    plugin_kind TEXT NOT NULL,           -- 'skill' | 'connector' | 'llm'
    plugin_name TEXT NOT NULL,
    plugin_version TEXT,
    manifest_sha256 TEXT NOT NULL,
    sprint_id TEXT,
    session_id TEXT,
    capabilities_json TEXT,              -- JSON snapshot of the network/fs/exec/secrets actually scoped
    args_json TEXT,                      -- JSON of args (redacted)
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_seconds REAL,
    exit_code INTEGER,
    ok INTEGER,                          -- 0 / 1
    error TEXT,
    capability_violations TEXT           -- JSON list of violations (egress / fs / exec)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(topic);
CREATE INDEX IF NOT EXISTS idx_knowledge_category ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_knowledge_confidence ON knowledge(confidence);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);
CREATE INDEX IF NOT EXISTS idx_episodes_type ON episodes(task_type);
CREATE INDEX IF NOT EXISTS idx_research_query ON research(query);
CREATE INDEX IF NOT EXISTS idx_procedures_pattern ON procedures(task_pattern);
CREATE INDEX IF NOT EXISTS idx_skill_invocations_id ON skill_invocations(invocation_id);
CREATE INDEX IF NOT EXISTS idx_skill_invocations_name ON skill_invocations(plugin_name);
CREATE INDEX IF NOT EXISTS idx_skill_invocations_sprint ON skill_invocations(sprint_id);

-- Write-once triggers — refuse UPDATE / DELETE. Even an attacker with
-- direct sqlite3 access (e.g. via a malicious plugin that loaded sqlite3
-- and bypassed our API) cannot scrub their tracks without leaving an
-- error trail.
CREATE TRIGGER IF NOT EXISTS skill_invocations_no_update
BEFORE UPDATE ON skill_invocations
BEGIN
    SELECT RAISE(ABORT, 'skill_invocations is append-only — UPDATE refused (Layer 7 audit log)');
END;

CREATE TRIGGER IF NOT EXISTS skill_invocations_no_delete
BEFORE DELETE ON skill_invocations
BEGIN
    SELECT RAISE(ABORT, 'skill_invocations is append-only — DELETE refused (Layer 7 audit log)');
END;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ForgeDB:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

        # Defense in depth (Task 1.3): register an atexit handler so SIGINT/
        # SIGTERM paths that bypass an explicit ``.close()`` still flush WAL.
        # We hold a weakref so the registered closure does not extend the
        # DB's lifetime past normal scope; if the instance is GC'd before
        # interpreter shutdown the closure becomes a no-op.
        self._closed = False
        ref = weakref.ref(self)
        atexit.register(lambda: ForgeDB._safe_close(ref))

        # Optional sqlite-vec extension for episodic vector recall (ADR-012).
        # Gated by FORGE_VECTOR_EPISODES=1; silently skipped if the extension
        # isn't installed. The virtual table holds (episode_id, embedding)
        # pairs; on retrieval we cosine-similarity match against the live
        # query embedding (see daemon/memory/embeddings.py).
        self._vec_enabled = False
        self._init_vec_extension()

    @staticmethod
    def _safe_close(ref: weakref.ref) -> None:
        """atexit-safe close — swallow exceptions so interpreter shutdown
        proceeds cleanly even on a partially-constructed instance."""
        instance = ref()
        if instance is not None and not instance._closed:
            try:
                instance.close()
            except Exception:  # interpreter shutdown context — must not raise
                pass

    def __del__(self):
        """Best-effort close on garbage collection.

        atexit is the primary mechanism; ``__del__`` is a backstop for the
        rare case where instances outlive the atexit firing window (e.g.,
        long-running tests that explicitly drop their references). Failures
        are swallowed because there's no useful surface to report from
        ``__del__`` during shutdown.
        """
        try:
            if not getattr(self, "_closed", True):
                self._conn.close()
        except Exception:  # destructor must not raise
            pass

    def _init_vec_extension(self) -> None:
        """Load sqlite-vec and create the episode-embeddings virtual table.

        No-ops cleanly when the user hasn't opted in or when sqlite-vec
        isn't installed. Failures are logged once at INFO level.
        """
        try:
            from .memory.embeddings import (
                DEFAULT_EMBED_DIMS,
                has_sqlite_vec,
                is_enabled,
            )
        except ImportError:
            return

        if not is_enabled() or not has_sqlite_vec():
            return

        try:
            import sqlite_vec  # type: ignore[import-not-found]

            self._conn.enable_load_extension(True)
            sqlite_vec.load(self._conn)
            self._conn.enable_load_extension(False)
            # Virtual table — one row per episode, one float[] vector.
            # We use vec0() with a fixed dimension; if the user changes
            # embedding model and the dim differs they need to wipe the
            # table (documented).
            self._conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS episode_embeddings
                USING vec0(episode_id TEXT PRIMARY KEY, embedding float[{DEFAULT_EMBED_DIMS}])
                """
            )
            self._vec_enabled = True
        except (ImportError, sqlite3.OperationalError) as e:
            import logging

            logging.getLogger(__name__).info(
                "sqlite-vec extension not loaded (FORGE_VECTOR_EPISODES set but %s); "
                "episodic vector recall disabled",
                e,
            )

    # --- Sessions ---

    def save_session(self, session) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO sessions
                   (id, project_path, objective, detected_stack, started_at, ended_at,
                    total_sprints, completed_sprints, failed_sprints, total_cost,
                    knowledge_items_created, knowledge_items_applied)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    session.id,
                    session.project_path,
                    session.objective,
                    json.dumps(session.detected_stack) if session.detected_stack else None,
                    session.started_at,
                    session.ended_at,
                    session.total_sprints,
                    session.completed_sprints,
                    session.failed_sprints,
                    session.total_cost,
                    session.knowledge_items_created,
                    session.knowledge_items_applied,
                ),
            )

    def get_session(self, session_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Sprint contracts ---

    def save_sprint(self, sprint) -> None:
        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO sprint_contracts
                   (id, session_id, description, done_criteria, assigned_model,
                    assigned_worktree, status, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    sprint.id,
                    sprint.session_id,
                    sprint.description,
                    json.dumps(sprint.done_criteria),
                    sprint.assigned_model,
                    sprint.assigned_worktree,
                    sprint.status,
                    sprint.created_at,
                ),
            )

    def get_sprint(self, sprint_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM sprint_contracts WHERE id = ?", (sprint_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_sprints_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM sprint_contracts WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Episodes ---

    def save_episode(
        self,
        episode_id: str,
        session_id: str,
        sprint_id: str,
        task_description: str,
        model: str,
        agent_type: str,
        agent_role: str,
        status: str,
        **kwargs,
    ) -> None:
        """Persist one episode (sprint execution record).

        Free-text columns (``error``, ``resolution``, ``result``,
        ``evaluator_feedback``) often carry subprocess stderr or LLM
        output that may contain credentials echoed from the prompt
        environment. We redact them at write time so the SQLite file on
        disk never sees raw secrets, even if the runtime did. See ADR-017.

        When ``FORGE_VECTOR_EPISODES=1`` is set and ``sqlite-vec`` is
        installed, an embedding of the (task_description + error)
        composite is computed via Ollama and stored in the
        ``episode_embeddings`` virtual table for later cosine-similarity
        recall. Embedding failures degrade gracefully — the episode row
        is still persisted, just without a vector entry.
        """
        from .redact import redact

        def _r(value):
            if isinstance(value, str):
                return redact(value)
            return value

        with self._conn:
            self._conn.execute(
                """INSERT OR REPLACE INTO episodes
                   (id, session_id, sprint_id, task_description, task_type, model,
                    agent_type, agent_role, status, result, error, error_category,
                    resolution, evaluator_verdict, evaluator_feedback, revision_count,
                    tokens_in, tokens_out, cost_usd, duration_seconds, files_changed,
                    created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    episode_id,
                    session_id,
                    sprint_id,
                    _r(task_description),
                    kwargs.get("task_type"),
                    model,
                    agent_type,
                    agent_role,
                    status,
                    _r(kwargs.get("result")),
                    _r(kwargs.get("error")),
                    kwargs.get("error_category"),
                    _r(kwargs.get("resolution")),
                    kwargs.get("evaluator_verdict"),
                    _r(kwargs.get("evaluator_feedback")),
                    kwargs.get("revision_count", 0),
                    kwargs.get("tokens_in", 0),
                    kwargs.get("tokens_out", 0),
                    kwargs.get("cost_usd", 0.0),
                    kwargs.get("duration_seconds"),
                    json.dumps(kwargs.get("files_changed"))
                    if kwargs.get("files_changed")
                    else None,
                    _now(),
                ),
            )

    def get_episodes_for_session(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodes WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_failures(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM episodes WHERE status = 'failed' ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_failure_resolution_pairs(self, session_id: str) -> list[tuple[dict, dict]]:
        """Get pairs of (failed episode, subsequent completed episode) for the same sprint."""
        episodes = self.get_episodes_for_session(session_id)
        pairs = []
        failed = {}
        for ep in episodes:
            if ep["status"] == "failed" and ep["sprint_id"]:
                failed[ep["sprint_id"]] = ep
            elif ep["status"] == "completed" and ep["sprint_id"] and ep["sprint_id"] in failed:
                pairs.append((failed.pop(ep["sprint_id"]), ep))
        return pairs

    # --- Knowledge ---

    def add_knowledge(
        self, category: str, topic: str, content: str, source: str = "", confidence: float = 0.5
    ) -> int | None:
        """Insert a knowledge item, dedup'ing against existing content.

        Refuses to persist content that contains obvious credentials —
        agents calling ``forge_kb_add`` via MCP shouldn't be able to write
        secrets into the KB and have them surface in every future
        ``forge_kb_search`` answer (including across users if the KB is
        ever shared via the MCP server). The ``contains_secret`` check
        uses the same regex catalog as the trace-redaction layer.

        See ADR-017 + daemon/redact.py.
        """
        # Defense-in-depth: refuse to persist credentials. Better to drop
        # the write than learn to surface keys.
        from .redact import contains_secret

        if contains_secret(content) or contains_secret(topic):
            import logging

            logging.getLogger(__name__).warning(
                "add_knowledge: refused write — content matches a credential pattern "
                "(category=%s topic=%r len=%d). See daemon/redact.py.",
                category,
                topic[:40],
                len(content),
            )
            return None

        # Deduplicate: check for similar content on same topic
        existing = self._conn.execute(
            "SELECT id FROM knowledge WHERE topic = ? AND content = ?",
            (topic, content),
        ).fetchone()
        if existing:
            return existing["id"]
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO knowledge (category, topic, content, source, confidence,
                   created_at, last_used_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (category, topic, content, source, confidence, _now(), _now()),
            )
            return cur.lastrowid

    def search_knowledge(
        self, query: str = "", topic: str = "", category: str = "", limit: int = 10
    ) -> list[dict]:
        conditions = ["superseded_by IS NULL"]
        params = []
        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        if topic:
            conditions.append("topic = ?")
            params.append(topic)
        if category:
            conditions.append("category = ?")
            params.append(category)
        where = " AND ".join(conditions)
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM knowledge WHERE {where} ORDER BY confidence DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_knowledge_for_task(self, task_description: str, limit: int = 5) -> list[dict]:
        """Get relevant knowledge items for a task. Uses word matching."""
        words = [w.lower() for w in task_description.split() if len(w) > 3]
        if not words:
            return []
        conditions = " OR ".join(["content LIKE ?" for _ in words])
        params = [f"%{w}%" for w in words[:10]]
        params.append(limit)
        rows = self._conn.execute(
            f"""SELECT * FROM knowledge WHERE superseded_by IS NULL
                AND ({conditions})
                ORDER BY confidence DESC, times_helpful DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_knowledge_helpful(self, item_id: int) -> None:
        with self._conn:
            self._conn.execute(
                """UPDATE knowledge SET times_helpful = times_helpful + 1,
                   times_applied = times_applied + 1, last_used_at = ?,
                   confidence = MIN(1.0, confidence + 0.05)
                   WHERE id = ?""",
                (_now(), item_id),
            )

    def mark_knowledge_unhelpful(self, item_id: int) -> None:
        with self._conn:
            self._conn.execute(
                """UPDATE knowledge SET times_applied = times_applied + 1,
                   last_used_at = ?,
                   confidence = MAX(0.0, confidence - 0.1)
                   WHERE id = ?""",
                (_now(), item_id),
            )

    def delete_knowledge(self, item_id: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM knowledge WHERE id = ?", (item_id,))

    def prune_knowledge(
        self, max_items: int = 200, min_confidence: float = 0.2, max_age_days: int = 90
    ) -> int:
        """Remove low-confidence and stale items. Returns count deleted."""
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        with self._conn:
            # Delete low confidence
            r1 = self._conn.execute(
                "DELETE FROM knowledge WHERE confidence < ? AND superseded_by IS NULL",
                (min_confidence,),
            )
            # Delete stale (unused for max_age_days)
            r2 = self._conn.execute(
                "DELETE FROM knowledge WHERE last_used_at < ? AND superseded_by IS NULL",
                (cutoff,),
            )
            # If still over max, delete lowest confidence
            count = self._conn.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]
            r3_count = 0
            if count > max_items:
                excess = count - max_items
                self._conn.execute(
                    """DELETE FROM knowledge WHERE id IN (
                       SELECT id FROM knowledge ORDER BY confidence ASC, last_used_at ASC
                       LIMIT ?)""",
                    (excess,),
                )
                r3_count = excess
            return r1.rowcount + r2.rowcount + r3_count

    def knowledge_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) as c FROM knowledge").fetchone()["c"]

    def get_all_knowledge(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM knowledge WHERE superseded_by IS NULL ORDER BY confidence DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Procedures ---

    def save_procedure(
        self, task_pattern: str, model: str, agent: str, success: bool, duration: float
    ) -> None:
        existing = self._conn.execute(
            "SELECT * FROM procedures WHERE task_pattern = ?", (task_pattern,)
        ).fetchone()
        now = _now()
        with self._conn:
            if existing:
                sc = existing["sample_count"] + 1
                old_rate = existing["success_rate"]
                new_rate = ((old_rate * (sc - 1)) + (1.0 if success else 0.0)) / sc
                old_dur = existing["avg_duration"]
                new_dur = ((old_dur * (sc - 1)) + duration) / sc
                self._conn.execute(
                    """UPDATE procedures SET success_rate=?, avg_duration=?,
                       sample_count=?, updated_at=? WHERE id=?""",
                    (new_rate, new_dur, sc, now, existing["id"]),
                )
            else:
                self._conn.execute(
                    """INSERT INTO procedures
                       (task_pattern, recommended_model, recommended_agent,
                        success_rate, avg_duration, sample_count, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (task_pattern, model, agent, 1.0 if success else 0.0, duration, 1, now, now),
                )

    def get_procedure(self, task_pattern: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM procedures WHERE task_pattern = ?", (task_pattern,)
        ).fetchone()
        return dict(row) if row else None

    # --- Research ---

    def save_research(
        self,
        query: str,
        url: str = "",
        title: str = "",
        extracted_content: str = "",
        relevance_score: float = 0.5,
        expires_days: int = 30,
    ) -> int:
        from datetime import timedelta

        expires = (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat()
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO research
                   (query, url, title, extracted_content, relevance_score,
                    created_at, expires_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (query, url, title, extracted_content, relevance_score, _now(), expires),
            )
            return cur.lastrowid

    def search_research(self, query: str, max_age_days: int = 30, limit: int = 5) -> list[dict]:
        from datetime import timedelta

        cutoff = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
        # Search both directions: query in stored OR stored in query
        # Also search extracted_content
        words = [w for w in query.lower().split() if len(w) > 3][:5]
        if not words:
            words = [query[:30]]
        conditions = " OR ".join(
            ["query LIKE ?" for _ in words] + ["extracted_content LIKE ?" for _ in words]
        )
        params = [f"%{w}%" for w in words] * 2
        params.extend([cutoff, limit])
        rows = self._conn.execute(
            f"""SELECT * FROM research WHERE ({conditions}) AND created_at > ?
               ORDER BY relevance_score DESC LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_research_used(self, research_id: int, task_id: str, success: bool) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE research SET used_in_task=?, led_to_success=? WHERE id=?",
                (task_id, 1 if success else 0, research_id),
            )

    # --- Skill / connector / LLM-adapter invocation audit log ---
    #
    # Append-only by construction: the table-level triggers refuse UPDATE
    # and DELETE. The dispatcher inserts a "start" row before spawn and a
    # "finish" row after completion (or kill on timeout). Queries that
    # need the latest state of an invocation read the most recent row by
    # ROWID DESC. See daemon/skills/dispatch.py.

    def record_invocation_start(
        self,
        *,
        invocation_id: str,
        plugin_kind: str,
        plugin_name: str,
        plugin_version: str,
        manifest_sha256: str,
        sprint_id: str | None,
        session_id: str | None,
        capabilities: dict | None,
        args: list | None,
    ) -> int:
        """Write the 'started' row for an invocation. Returns the rowid.

        ``capabilities`` is the dict of network / filesystem / exec /
        secrets_read scopes the runtime granted *for this run* (not the
        full manifest — this is the live scope, including any narrowing
        the dispatcher applied).
        """
        from .redact import redact

        caps_redacted = json.dumps(capabilities) if capabilities else None
        args_redacted = json.dumps([redact(a) if isinstance(a, str) else a for a in (args or [])])
        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO skill_invocations
                   (invocation_id, plugin_kind, plugin_name, plugin_version,
                    manifest_sha256, sprint_id, session_id, capabilities_json,
                    args_json, started_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    invocation_id,
                    plugin_kind,
                    plugin_name,
                    plugin_version,
                    manifest_sha256,
                    sprint_id,
                    session_id,
                    caps_redacted,
                    args_redacted,
                    _now(),
                ),
            )
            return cur.lastrowid

    def record_invocation_finish(
        self,
        *,
        invocation_id: str,
        plugin_kind: str,
        plugin_name: str,
        plugin_version: str,
        manifest_sha256: str,
        sprint_id: str | None,
        session_id: str | None,
        capabilities: dict | None,
        duration_seconds: float,
        exit_code: int | None,
        ok: bool,
        error: str | None = None,
        capability_violations: list[str] | None = None,
    ) -> int:
        """Write the 'finished' row. Always an INSERT — the original
        'started' row stays intact, so the audit trail shows both the
        spawn and the outcome with their own timestamps.

        ``error`` is redacted before persistence (subprocess stderr can
        echo credentials passed in env or args).
        """
        from .redact import redact

        with self._conn:
            cur = self._conn.execute(
                """INSERT INTO skill_invocations
                   (invocation_id, plugin_kind, plugin_name, plugin_version,
                    manifest_sha256, sprint_id, session_id, capabilities_json,
                    started_at, finished_at, duration_seconds, exit_code, ok,
                    error, capability_violations)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    invocation_id,
                    plugin_kind,
                    plugin_name,
                    plugin_version,
                    manifest_sha256,
                    sprint_id,
                    session_id,
                    json.dumps(capabilities) if capabilities else None,
                    _now(),  # started_at on the 'finish' row = its own write time
                    _now(),
                    duration_seconds,
                    exit_code,
                    1 if ok else 0,
                    redact(error) if error else None,
                    json.dumps(capability_violations) if capability_violations else None,
                ),
            )
            return cur.lastrowid

    def list_invocations(
        self,
        plugin_name: str | None = None,
        sprint_id: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Read invocations newest first. Returns the raw rows; the
        dispatcher / CLI is responsible for de-duping start+finish pairs
        if the caller wants only one row per invocation_id.
        """
        conditions = []
        params: list = []
        if plugin_name:
            conditions.append("plugin_name = ?")
            params.append(plugin_name)
        if sprint_id:
            conditions.append("sprint_id = ?")
            params.append(sprint_id)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM skill_invocations{where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Utility ---

    def close(self) -> None:
        """Close the underlying connection. Idempotent — calling twice is safe.

        The atexit-registered :func:`_safe_close` and :meth:`__del__` both
        check ``_closed`` before touching the connection, so explicit close
        in tests / app code does not race with interpreter shutdown.
        """
        if self._closed:
            return
        try:
            self._conn.close()
        finally:
            self._closed = True

    def table_counts(self) -> dict:
        tables = [
            "episodes",
            "knowledge",
            "procedures",
            "research",
            "sprint_contracts",
            "sessions",
            "skill_invocations",
        ]
        counts = {}
        for t in tables:
            counts[t] = self._conn.execute(f"SELECT COUNT(*) as c FROM {t}").fetchone()["c"]
        return counts

    # --- MCP-friendly summary helpers (Phase 1 Week 6) ---
    #
    # These return human-readable strings suitable for direct injection into
    # an MCP-aware client's context. The MCP server (daemon/mcp_server.py)
    # uses these for the ``forge://stats`` and ``forge://session/{id}/summary``
    # resources and for the ``forge_session_summary`` tool.

    def store_episode_embedding(self, episode_id: str, vector: list[float]) -> None:
        """Persist an episode's text embedding into the optional vec0 table.

        No-op when ``FORGE_VECTOR_EPISODES`` is unset or sqlite-vec isn't
        loaded. Caller (typically the scheduler post-evaluator) is
        responsible for computing the vector via
        ``daemon.memory.embeddings.embed`` before passing it here.
        """
        if not self._vec_enabled:
            return
        from .memory.embeddings import serialize_vector

        try:
            with self._conn:
                self._conn.execute(
                    "INSERT OR REPLACE INTO episode_embeddings(episode_id, embedding) VALUES (?, ?)",
                    (episode_id, serialize_vector(vector)),
                )
        except sqlite3.OperationalError as e:
            import logging

            logging.getLogger(__name__).warning(
                "store_episode_embedding failed for %s: %s", episode_id, e
            )

    def find_similar_episodes(self, vector: list[float], limit: int = 5) -> list[dict]:
        """Return the k-nearest episodes to a query embedding.

        Returns dicts with the standard episode columns merged with a
        ``distance`` field (smaller = closer in cosine terms). Empty list
        when vec is disabled or no embeddings exist yet.
        """
        if not self._vec_enabled:
            return []
        from .memory.embeddings import serialize_vector

        try:
            rows = self._conn.execute(
                """
                SELECT e.*, v.distance
                FROM episode_embeddings v
                JOIN episodes e ON e.id = v.episode_id
                WHERE v.embedding MATCH ?
                ORDER BY v.distance
                LIMIT ?
                """,
                (serialize_vector(vector), limit),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            import logging

            logging.getLogger(__name__).warning("find_similar_episodes failed: %s", e)
            return []

    def search_episodes(self, error_pattern: str, limit: int = 5) -> list[dict]:
        """Search the episodic store for past failures matching ``error_pattern``.

        Substring match against ``error`` and ``task_description`` columns,
        case-insensitive. Newest matches first. Used by the MCP server's
        ``forge_episode_search`` tool to surface "how did Forge resolve this
        before" answers.
        """
        rows = self._conn.execute(
            """
            SELECT * FROM episodes
            WHERE LOWER(error) LIKE LOWER(?) OR LOWER(task_description) LIKE LOWER(?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"%{error_pattern}%", f"%{error_pattern}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def kb_summary_text(self) -> str:
        """Return a markdown-ish summary of the knowledge base.

        Used by the ``forge://stats`` MCP resource so other agents can read
        Forge's KB shape without paginating through every item.
        """
        counts = self._conn.execute(
            """
            SELECT category, COUNT(*) as c
            FROM knowledge
            GROUP BY category
            """
        ).fetchall()
        by_cat = {r["category"]: r["c"] for r in counts}

        topics = self._conn.execute(
            """
            SELECT topic, COUNT(*) as c
            FROM knowledge
            GROUP BY topic
            ORDER BY c DESC
            LIMIT 10
            """
        ).fetchall()
        top_topics = [f"{r['topic']} ({r['c']})" for r in topics]

        recent = self._conn.execute(
            """
            SELECT topic, content
            FROM knowledge
            ORDER BY created_at DESC
            LIMIT 5
            """
        ).fetchall()

        total = sum(by_cat.values())
        lines = [
            "# Forge knowledge base summary",
            f"Total items: {total}",
        ]
        if by_cat:
            lines.append("")
            lines.append("## By category")
            for cat in ("gotcha", "solution", "pattern", "rule", "preference"):
                if cat in by_cat:
                    lines.append(f"  {cat}: {by_cat[cat]}")
        if top_topics:
            lines.append("")
            lines.append("## Top topics")
            lines.append(", ".join(top_topics))
        if recent:
            lines.append("")
            lines.append("## Recent additions")
            for r in recent:
                lines.append(f"  [{r['topic']}] {r['content']}")
        return "\n".join(lines)

    def session_summary_text(self, session_id: str) -> str:
        """Return a markdown-ish per-session summary (objective, sprint
        outcomes, totals, knowledge created)."""
        session = self.get_session(session_id)
        if not session:
            return f"No session with id {session_id!r} found."

        sprints = self.get_sprints_for_session(session_id)
        episodes = self.get_episodes_for_session(session_id)

        lines = [
            f"# Session {session_id}",
            f"Objective: {session.get('objective', '(none)')}",
            f"Project: {session.get('project_path', '(none)')}",
            f"Started: {session.get('started_at', '?')}",
        ]
        if session.get("ended_at"):
            lines.append(f"Ended: {session['ended_at']}")

        lines.append("")
        lines.append(f"## Sprints ({len(sprints)})")
        for s in sprints:
            lines.append(
                f"  - [{s.get('status', '?')}] {s.get('description', '?')[:80]} "
                f"(model={s.get('assigned_model', '?')}, revs={s.get('revision_count', 0)})"
            )

        lines.append("")
        lines.append(f"## Cost: ${session.get('total_cost', 0):.2f}")
        lines.append(f"## Episodes: {len(episodes)}")
        lines.append(f"## Knowledge created: {session.get('knowledge_items_created', 0)}")
        return "\n".join(lines)
