"""Ownership models: an org-level site owner and a responsible person.

A ``SiteOwner`` is the org-level group accountable for one or more sites (e.g. a
content-manager security group). A ``Person`` is an individual; people belong to
owners many-to-many (the ``person_owner`` table). "Responsible people for a
site" are the members of that site's owner.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SiteOwner:
    id: int | None
    key: str
    label: str | None = None
    notes: str | None = None
    created_at: str | None = None


@dataclass
class Person:
    id: int | None
    employee_id: str
    full_name: str
    email: str | None = None
    is_manager: bool = False
    created_at: str | None = None
