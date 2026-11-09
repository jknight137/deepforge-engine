"""Schema additions for actor ownership, engine sessions and action receipts."""

AGENT_SCHEMA = (
    """CREATE TABLE agent_engines (world_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
        frame_id INTEGER NOT NULL, frame_hash TEXT NOT NULL, seen_ms INTEGER NOT NULL,
        FOREIGN KEY(world_id) REFERENCES worlds(world_id))""",
    """CREATE TABLE agent_boots (world_id TEXT NOT NULL, session_id TEXT NOT NULL,
        retired INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(world_id,session_id))""",
    """CREATE TABLE agents (world_id TEXT NOT NULL, actor_id TEXT NOT NULL,
        capabilities TEXT NOT NULL, observation TEXT NOT NULL, observed_ms INTEGER NOT NULL,
        active INTEGER NOT NULL, sequence INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(world_id,actor_id),
        FOREIGN KEY(world_id,actor_id) REFERENCES entities(world_id,entity_id))""",
    """CREATE TABLE agent_controls (world_id TEXT NOT NULL, actor_id TEXT NOT NULL,
        controller_id TEXT, generation INTEGER NOT NULL DEFAULT 0, token TEXT,
        expires_ms INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(world_id,actor_id),
        FOREIGN KEY(world_id,actor_id) REFERENCES agents(world_id,actor_id))""",
    """CREATE TABLE agent_actions (world_id TEXT NOT NULL, action_id TEXT NOT NULL,
        actor_id TEXT NOT NULL, controller_id TEXT NOT NULL, generation INTEGER NOT NULL,
        sequence INTEGER NOT NULL, operation TEXT NOT NULL, args TEXT NOT NULL,
        signature TEXT NOT NULL, status TEXT NOT NULL, result TEXT, engine_session TEXT,
        PRIMARY KEY(world_id,action_id), UNIQUE(world_id,actor_id,sequence),
        FOREIGN KEY(world_id,actor_id) REFERENCES agents(world_id,actor_id))""",
    """CREATE UNIQUE INDEX agent_action_active ON agent_actions(world_id,actor_id)
        WHERE status IN ('queued','dispatched')""",
    "CREATE INDEX agent_action_owner ON agent_actions(world_id,controller_id,action_id)",
)

AGENT_RECOVERY_SCHEMA = (
    """CREATE TABLE agent_rejections (world_id TEXT NOT NULL, session_id TEXT NOT NULL,
        frame_id INTEGER NOT NULL, kind TEXT NOT NULL, item_id TEXT NOT NULL,
        error_code TEXT NOT NULL, message TEXT NOT NULL, created_ms INTEGER NOT NULL,
        PRIMARY KEY(world_id,session_id,frame_id,kind,item_id))""",
)
