from __future__ import annotations

import sqlite3

from pdfscan.db.repositories.base import BaseRepository
from pdfscan.models import Person, SiteOwner


def _row_to_owner(row: sqlite3.Row) -> SiteOwner:
    return SiteOwner(
        id=row["id"],
        key=row["key"],
        label=row["label"],
        notes=row["notes"],
        created_at=row["created_at"],
    )


def _row_to_person(row: sqlite3.Row) -> Person:
    return Person(
        id=row["id"],
        employee_id=row["employee_id"],
        full_name=row["full_name"],
        email=row["email"],
        is_manager=bool(row["is_manager"]),
        created_at=row["created_at"],
    )


class SiteOwnerRepository(BaseRepository):
    def upsert(self, owner: SiteOwner) -> int:
        """Insert, or update label/notes if the key already exists. Returns the id."""
        cur = self.conn.execute(
            """
            INSERT INTO site_owner (key, label, notes)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                label = excluded.label,
                notes = excluded.notes
            RETURNING id
            """,
            (owner.key, owner.label, owner.notes),
        )
        return int(cur.fetchone()[0])

    def get_by_id(self, owner_id: int) -> SiteOwner | None:
        row = self.conn.execute(
            "SELECT * FROM site_owner WHERE id = ?", (owner_id,)
        ).fetchone()
        return _row_to_owner(row) if row else None

    def get_by_key(self, key: str) -> SiteOwner | None:
        row = self.conn.execute(
            "SELECT * FROM site_owner WHERE key = ?", (key,)
        ).fetchone()
        return _row_to_owner(row) if row else None

    def list(self) -> list[SiteOwner]:
        rows = self.conn.execute("SELECT * FROM site_owner ORDER BY key").fetchall()
        return [_row_to_owner(r) for r in rows]

    def remove(self, key: str) -> bool:
        """Delete an owner. Sites referencing it have owner_id set NULL (FK action),
        and person_owner memberships cascade-delete."""
        cur = self.conn.execute("DELETE FROM site_owner WHERE key = ?", (key,))
        return cur.rowcount > 0

    def site_names(self, owner_id: int) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM site WHERE owner_id = ? ORDER BY name", (owner_id,)
        ).fetchall()
        return [r["name"] for r in rows]


class PersonRepository(BaseRepository):
    def upsert(self, person: Person) -> int:
        """Insert, or update name/email if the employee_id already exists.

        ``is_manager`` is intentionally not overwritten on conflict (it is managed
        separately via :meth:`set_manager` / the managers import), so re-importing
        a roster does not clear manager flags.
        """
        cur = self.conn.execute(
            """
            INSERT INTO person (employee_id, full_name, email, is_manager)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(employee_id) DO UPDATE SET
                full_name = excluded.full_name,
                email = excluded.email
            RETURNING id
            """,
            (person.employee_id, person.full_name, person.email, int(person.is_manager)),
        )
        return int(cur.fetchone()[0])

    def get_by_id(self, person_id: int) -> Person | None:
        row = self.conn.execute(
            "SELECT * FROM person WHERE id = ?", (person_id,)
        ).fetchone()
        return _row_to_person(row) if row else None

    def get_by_employee_id(self, employee_id: str) -> Person | None:
        row = self.conn.execute(
            "SELECT * FROM person WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        return _row_to_person(row) if row else None

    def list(self) -> list[Person]:
        rows = self.conn.execute("SELECT * FROM person ORDER BY full_name").fetchall()
        return [_row_to_person(r) for r in rows]

    def set_manager(self, employee_id: str, is_manager: bool) -> bool:
        cur = self.conn.execute(
            "UPDATE person SET is_manager = ? WHERE employee_id = ?",
            (int(is_manager), employee_id),
        )
        return cur.rowcount > 0

    def remove(self, employee_id: str) -> bool:
        """Delete a person; person_owner memberships cascade-delete."""
        cur = self.conn.execute("DELETE FROM person WHERE employee_id = ?", (employee_id,))
        return cur.rowcount > 0

    # -- membership (person <-> owner, many-to-many) ----------------------------
    def add_membership(self, person_id: int, owner_id: int) -> bool:
        """Link a person to an owner. Idempotent (dedups person-in-many-orgs).

        Returns ``True`` if a new membership row was inserted, ``False`` if it
        already existed.
        """
        cur = self.conn.execute(
            """
            INSERT INTO person_owner (person_id, owner_id) VALUES (?, ?)
            ON CONFLICT(person_id, owner_id) DO NOTHING
            """,
            (person_id, owner_id),
        )
        return cur.rowcount > 0

    def remove_membership(self, person_id: int, owner_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM person_owner WHERE person_id = ? AND owner_id = ?",
            (person_id, owner_id),
        )
        return cur.rowcount > 0

    def members_of(self, owner_id: int) -> list[Person]:
        """People belonging to an owner (managers first, then by name)."""
        rows = self.conn.execute(
            """
            SELECT p.* FROM person p
            JOIN person_owner po ON po.person_id = p.id
            WHERE po.owner_id = ?
            ORDER BY p.is_manager DESC, p.full_name
            """,
            (owner_id,),
        ).fetchall()
        return [_row_to_person(r) for r in rows]
