"""
core.storage

Persistence for the queue: `job_manager` owns one session's SQLite database and
the `Job` dataclass, and `sessions` is the registry (`data/sessions.json`) that
maps each session id to its database file.
"""
