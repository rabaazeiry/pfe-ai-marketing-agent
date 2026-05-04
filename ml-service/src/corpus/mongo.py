"""Read-only MongoDB queries for the master-corpus loader.

Only `find()` calls are made; nothing in this module writes to the database.
"""
from __future__ import annotations

from typing import Any, List

from pymongo import MongoClient
from pymongo.uri_parser import parse_uri

from .config import MONGODB_URI

DEFAULT_DB_NAME = "battouta_db"


def get_client() -> MongoClient:
    return MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)


def get_database(client: MongoClient):
    parsed = parse_uri(MONGODB_URI)
    db_name = parsed.get("database") or DEFAULT_DB_NAME
    return client[db_name]


def fetch_pfe_projects(db) -> List[dict]:
    """Projects whose name starts with 'PFE Analysis -'."""
    return list(db.projects.find({"name": {"$regex": r"^PFE Analysis -"}}))


def fetch_active_competitors(db, project_ids: List[Any]) -> List[dict]:
    return list(
        db.competitors.find(
            {"projectId": {"$in": project_ids}, "isActive": True}
        )
    )


def fetch_instagram_analyses(db, competitor_ids: List[Any]) -> List[dict]:
    return list(
        db.socialanalyses.find(
            {"competitorId": {"$in": competitor_ids}, "platform": "instagram"}
        )
    )
