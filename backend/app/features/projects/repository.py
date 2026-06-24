from __future__ import annotations

import logging
import uuid

from app.db import get_pool

logger = logging.getLogger("projects.repo")

_PLACEHOLDER = "placeholder://not-configured"


async def create_project(
    user_id: str, name: str, description: str,
    kind: str = "internal", db_url: str | None = None,
) -> dict:
    """Create a project row. Internal projects start with the placeholder db_url (a SQLite file is
    provisioned by the service layer); external projects pass their probed DSN directly as db_url."""
    logger.info("→ create_project(user_id=%r name=%r kind=%r)", user_id, name, kind)  # autolog
    pool = get_pool()
    pid = str(uuid.uuid4())
    row = await pool.fetchrow(
        """
        INSERT INTO projects (id, name, description, user_id, db_url, kind)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, name, description, db_url, kind
        """,
        pid, name, description, user_id, db_url or _PLACEHOLDER, kind,
    )
    return dict(row)


async def list_projects(user_id: str) -> list[dict]:
    logger.info("→ list_projects(user_id=%r)", user_id)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, name, description, db_url, kind FROM projects WHERE user_id = $1 ORDER BY created_at DESC",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_project(project_id: str, user_id: str) -> dict | None:
    logger.info("→ get_project(project_id=%r user_id=%r)", project_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, name, description, db_url, kind FROM projects WHERE id = $1 AND user_id = $2",
        project_id, user_id,
    )
    return dict(row) if row else None


async def get_description_any(project_id: str) -> str | None:
    """Project description by id only (NO owner filter) — used as the database-level context
    for SQL generation. Returns None for synthetic/external scopes with no project row."""
    pool = get_pool()
    row = await pool.fetchrow("SELECT description FROM projects WHERE id = $1", project_id)
    return (row["description"] or None) if row else None


async def set_db_url(project_id: str, user_id: str, db_url: str) -> None:
    logger.info("→ set_db_url(project_id=%r user_id=%r db_url=***)", project_id, user_id)  # autolog
    pool = get_pool()
    await pool.execute(
        "UPDATE projects SET db_url = $3 WHERE id = $1 AND user_id = $2",
        project_id, user_id, db_url,
    )


async def delete_project(project_id: str, user_id: str) -> dict | None:
    logger.info("→ delete_project(project_id=%r user_id=%r)", project_id, user_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM projects WHERE id = $1 AND user_id = $2 RETURNING id, db_url",
        project_id, user_id,
    )
    return dict(row) if row else None


# --------------------------------------------------------------------- sharing

async def get_accessible_project(project_id: str, user_id: str) -> dict | None:
    """Project row if the user OWNS it OR it's SHARED with them — used by chat to resolve the
    data source for both owners (read/write) and viewers (read-only, enforced separately)."""
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, name, description, db_url, kind FROM projects
        WHERE id = $1 AND (
            user_id = $2
            OR EXISTS (SELECT 1 FROM project_shares WHERE project_id = $1 AND user_id = $2)
        )
        """,
        project_id, user_id,
    )
    return dict(row) if row else None


async def add_share(project_id: str, viewer_id: str, shared_by: str, permission: str = "view") -> None:
    logger.info("→ add_share(project_id=%r viewer_id=%r perm=%r)", project_id, viewer_id, permission)  # autolog
    pool = get_pool()
    await pool.execute(
        "INSERT INTO project_shares (project_id, user_id, shared_by, permission) VALUES ($1,$2,$3,$4) "
        "ON CONFLICT (project_id, user_id) DO UPDATE SET permission = EXCLUDED.permission",
        project_id, viewer_id, shared_by, permission,
    )


async def set_share_permission(project_id: str, viewer_id: str, permission: str) -> bool:
    pool = get_pool()
    row = await pool.fetchrow(
        "UPDATE project_shares SET permission=$3 WHERE project_id=$1 AND user_id=$2 RETURNING user_id",
        project_id, viewer_id, permission,
    )
    return row is not None


async def get_share_permission(project_id: str, user_id: str) -> str | None:
    """The share's permission ('view'|'edit') for this user, or None if not shared."""
    pool = get_pool()
    return await pool.fetchval(
        "SELECT permission FROM project_shares WHERE project_id=$1 AND user_id=$2",
        project_id, user_id,
    )


async def remove_share(project_id: str, viewer_id: str) -> bool:
    logger.info("→ remove_share(project_id=%r viewer_id=%r)", project_id, viewer_id)  # autolog
    pool = get_pool()
    row = await pool.fetchrow(
        "DELETE FROM project_shares WHERE project_id=$1 AND user_id=$2 RETURNING user_id",
        project_id, viewer_id,
    )
    return row is not None


async def list_shares(project_id: str) -> list[dict]:
    """People a project is shared with (name/email/role)."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT ps.user_id, u.name, u.email, u.role, ps.permission, ps.created_at
        FROM project_shares ps JOIN users u ON u.google_sub = ps.user_id
        WHERE ps.project_id = $1 ORDER BY ps.created_at ASC
        """,
        project_id,
    )
    return [dict(r) for r in rows]


async def list_shareable_users(project_id: str, owner_id: str) -> list[dict]:
    """Active users a project can still be shared with: everyone except the owner and the people
    it's already shared with. Used by the share modal to pick a teammate without typing."""
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT u.google_sub AS user_id, u.name, u.email, u.role
        FROM users u
        WHERE u.google_sub <> $2
          AND u.disabled_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM project_shares ps WHERE ps.project_id = $1 AND ps.user_id = u.google_sub
          )
        ORDER BY lower(COALESCE(NULLIF(u.name, ''), u.email))
        """,
        project_id, owner_id,
    )
    return [dict(r) for r in rows]


async def list_shared_with(user_id: str) -> list[dict]:
    """Projects shared WITH this user (for the viewer home), with owner info."""
    logger.info("→ list_shared_with(user_id=%r)", user_id)  # autolog
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT p.id, p.name, p.description,
               ou.name AS owner_name, ou.email AS owner_email,
               ps.created_at AS shared_at
        FROM project_shares ps
        JOIN projects p ON p.id = ps.project_id
        JOIN users ou ON ou.google_sub = p.user_id
        WHERE ps.user_id = $1
        ORDER BY ps.created_at DESC
        """,
        user_id,
    )
    return [dict(r) for r in rows]
