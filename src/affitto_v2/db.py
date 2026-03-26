from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS listings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT NOT NULL,
  search_hash TEXT NOT NULL,
  ad_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  price TEXT,
  location TEXT,
  agency TEXT,
  dedup_key TEXT NOT NULL UNIQUE,
  first_seen_ts INTEGER NOT NULL,
  last_seen_ts INTEGER NOT NULL,
  notified_telegram INTEGER NOT NULL DEFAULT 0,
  notified_email INTEGER NOT NULL DEFAULT 0,
  payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_listings_site_search_time ON listings(site, search_hash, first_seen_ts);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen_ts);

CREATE TABLE IF NOT EXISTS blocked_agency_patterns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  pattern TEXT NOT NULL UNIQUE,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS private_only_agency_cache (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  site TEXT NOT NULL,
  search_hash TEXT NOT NULL,
  ad_id TEXT NOT NULL,
  agency TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  first_seen_ts INTEGER NOT NULL,
  last_seen_ts INTEGER NOT NULL,
  UNIQUE(site, search_hash, ad_id)
);

CREATE INDEX IF NOT EXISTS idx_private_only_agency_cache_lookup
  ON private_only_agency_cache(site, search_hash, ad_id, last_seen_ts);

CREATE TABLE IF NOT EXISTS app_kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_ts INTEGER NOT NULL
);
"""


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_search_hash(search_url: str) -> str:
    return _hash_text(search_url.strip())


def build_dedup_key(site: str, search_url: str, ad_id: str, url: str, title: str, price: str, location: str) -> str:
    normalized = "|".join(
        [
            _normalize(site),
            _hash_text(search_url.strip()),
            _normalize(ad_id),
            _normalize(url),
            _normalize(title),
            _normalize(price),
            _normalize(location),
        ]
    )
    return _hash_text(normalized)


@dataclass(frozen=True)
class ListingRecord:
    site: str
    search_url: str
    ad_id: str
    url: str
    title: str = ""
    price: str = ""
    location: str = ""
    agency: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    def search_hash(self) -> str:
        return build_search_hash(self.search_url)

    def dedup_key(self) -> str:
        return build_dedup_key(
            site=self.site,
            search_url=self.search_url,
            ad_id=self.ad_id,
            url=self.url,
            title=self.title,
            price=self.price,
            location=self.location,
        )


class Database:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
        con.execute("PRAGMA busy_timeout=5000;")
        return con

    def init_schema(self) -> None:
        with self._connect() as con:
            for stmt in _SCHEMA.strip().split(";"):
                chunk = stmt.strip()
                if chunk:
                    con.execute(chunk)
            con.commit()

    def upsert_listing(self, record: ListingRecord) -> bool:
        now = int(time.time())
        payload = json.dumps(record.payload or {}, ensure_ascii=False)
        dedup_key = record.dedup_key()
        with self._connect() as con:
            cur = con.execute(
                """
                INSERT OR IGNORE INTO listings (
                    site, search_hash, ad_id, url, title, price, location, agency,
                    dedup_key, first_seen_ts, last_seen_ts, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.site.strip().lower(),
                    record.search_hash(),
                    record.ad_id.strip(),
                    record.url.strip(),
                    record.title.strip(),
                    record.price.strip(),
                    record.location.strip(),
                    record.agency.strip(),
                    dedup_key,
                    now,
                    now,
                    payload,
                ),
            )
            is_new = cur.rowcount == 1
            if not is_new:
                con.execute(
                    """
                    UPDATE listings
                    SET last_seen_ts = ?, payload_json = ?, title = ?, price = ?, location = ?, agency = ?
                    WHERE dedup_key = ?
                    """,
                    (
                        now,
                        payload,
                        record.title.strip(),
                        record.price.strip(),
                        record.location.strip(),
                        record.agency.strip(),
                        dedup_key,
                    ),
                )
            con.commit()
            return is_new

    def purge_old_listings(self, retention_days: int = 15) -> int:
        threshold = int(time.time()) - int(retention_days * 24 * 3600)
        with self._connect() as con:
            cur = con.execute("DELETE FROM listings WHERE first_seen_ts < ?", (threshold,))
            con.commit()
            return int(cur.rowcount or 0)

    def listing_count(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT COUNT(*) AS n FROM listings").fetchone()
            return int(row["n"])

    def reset_listings(self) -> int:
        with self._connect() as con:
            row = con.execute("SELECT COUNT(*) AS n FROM listings").fetchone()
            removed = int(row["n"]) if row else 0
            con.execute("DELETE FROM listings")
            con.commit()
            return removed

    def set_blocked_agency_patterns(self, patterns: list[str]) -> None:
        now = int(time.time())
        cleaned = sorted({p.strip() for p in patterns if p and p.strip()})
        with self._connect() as con:
            con.execute("DELETE FROM blocked_agency_patterns")
            con.executemany(
                "INSERT INTO blocked_agency_patterns(pattern, enabled, created_ts) VALUES (?, 1, ?)",
                [(pattern, now) for pattern in cleaned],
            )
            con.commit()

    def get_blocked_agency_patterns(self) -> list[str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT pattern FROM blocked_agency_patterns WHERE enabled = 1 ORDER BY pattern"
            ).fetchall()
            return [str(r["pattern"]) for r in rows]

    def get_listing_agencies_by_ad_ids(self, *, site: str, search_url: str, ad_ids: list[str]) -> dict[str, str]:
        cleaned_ids = sorted({str(ad_id).strip() for ad_id in ad_ids if str(ad_id).strip()})
        if not cleaned_ids:
            return {}
        placeholders = ",".join("?" for _ in cleaned_ids)
        normalized_site = site.strip().lower()
        search_hash = build_search_hash(search_url)
        params: list[Any] = [normalized_site, search_hash, *cleaned_ids]
        listing_query = f"""
            SELECT ad_id, agency, last_seen_ts
            FROM listings
            WHERE site = ?
              AND search_hash = ?
              AND ad_id IN ({placeholders})
            ORDER BY last_seen_ts DESC, id DESC
        """
        cache_query = f"""
            SELECT ad_id, agency, last_seen_ts
            FROM private_only_agency_cache
            WHERE site = ?
              AND search_hash = ?
              AND ad_id IN ({placeholders})
            ORDER BY last_seen_ts DESC, id DESC
        """
        out: dict[str, str] = {}
        seen_ts: dict[str, int] = {}
        with self._connect() as con:
            for query in (listing_query, cache_query):
                rows = con.execute(query, params).fetchall()
                for row in rows:
                    ad_id = str(row["ad_id"] or "").strip()
                    if not ad_id:
                        continue
                    ts = int(row["last_seen_ts"] or 0)
                    if ad_id in seen_ts and seen_ts[ad_id] >= ts:
                        continue
                    seen_ts[ad_id] = ts
                    out[ad_id] = str(row["agency"] or "").strip()
        return out

    def upsert_private_only_agency(
        self,
        *,
        site: str,
        search_url: str,
        ad_id: str,
        agency: str,
        source: str = "",
    ) -> None:
        normalized_site = site.strip().lower()
        normalized_ad_id = str(ad_id).strip()
        normalized_agency = str(agency).strip()
        if not normalized_site or not normalized_ad_id or not normalized_agency:
            return
        now = int(time.time())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO private_only_agency_cache(
                    site, search_hash, ad_id, agency, source, first_seen_ts, last_seen_ts
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site, search_hash, ad_id) DO UPDATE
                  SET agency = excluded.agency,
                      source = excluded.source,
                      last_seen_ts = excluded.last_seen_ts
                """,
                (
                    normalized_site,
                    build_search_hash(search_url),
                    normalized_ad_id,
                    normalized_agency,
                    source.strip(),
                    now,
                    now,
                ),
            )
            con.commit()

    def agency_is_blocked(self, agency_name: str) -> tuple[bool, str]:
        value = agency_name or ""
        if not value.strip():
            return False, ""
        for pattern in self.get_blocked_agency_patterns():
            try:
                if re.search(pattern, value, flags=re.IGNORECASE):
                    return True, pattern
            except re.error:
                continue
        return False, ""

    def set_state(self, key: str, value: str) -> None:
        now = int(time.time())
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO app_kv(key, value, updated_ts)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE
                  SET value = excluded.value,
                      updated_ts = excluded.updated_ts
                """,
                (key, value, now),
            )
            con.commit()

    def get_state(self, key: str, default: str = "") -> str:
        with self._connect() as con:
            row = con.execute("SELECT value FROM app_kv WHERE key = ?", (key,)).fetchone()
            if not row:
                return default
            return str(row["value"])

    def mark_notified(self, dedup_key: str, channel: str) -> None:
        field = ""
        if channel == "email":
            field = "notified_email"
        elif channel == "telegram":
            field = "notified_telegram"
        else:
            raise ValueError(f"Unsupported channel: {channel}")
        with self._connect() as con:
            con.execute(f"UPDATE listings SET {field} = 1 WHERE dedup_key = ?", (dedup_key,))
            con.commit()
