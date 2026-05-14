# -*- coding: utf-8 -*-
"""Supabase client with a lightweight REST fallback.

The normal supabase-py package is used when available. In development machines
where the app is launched with a Python that does not have supabase installed,
the fallback keeps best-effort queue sync working through PostgREST.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote


SUPABASE_URL = "https://ljcauvdugccwhwiecbqw.supabase.co"
SUPABASE_KEY = "sb_publishable_Hn8Anfc5WhS8UwYqH3xbMA_GAvBPFwg"


@dataclass
class RestResponse:
    data: Any = None


class RestQuery:
    def __init__(self, client: "RestSupabaseClient", table_name: str):
        self.client = client
        self.table_name = table_name
        self._select = "*"
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None
        self._payload: dict[str, Any] | None = None
        self._on_conflict = "id"

    def select(self, columns: str):
        self._select = columns
        return self

    def eq(self, column: str, value: Any):
        self._filters.append((column, value))
        return self

    def limit(self, value: int):
        self._limit = int(value)
        return self

    def upsert(self, payload: dict[str, Any], on_conflict: str = "id"):
        self._payload = payload
        self._on_conflict = on_conflict
        return self

    def execute(self):
        if self._payload is not None:
            return self._execute_upsert()
        return self._execute_select()

    def _execute_select(self):
        params = [("select", self._select)]
        for column, value in self._filters:
            params.append((column, f"eq.{value}"))
        if self._limit is not None:
            params.append(("limit", str(self._limit)))
        response = self.client.request("GET", self.table_name, params=params)
        return RestResponse(response.json() if response.text else [])

    def _execute_upsert(self):
        params = [("on_conflict", self._on_conflict)]
        headers = {"Prefer": "resolution=merge-duplicates,return=representation"}
        response = self.client.request("POST", self.table_name, params=params, headers=headers, json=self._payload)
        return RestResponse(response.json() if response.text else None)


class RestSupabaseClient:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key

    def table(self, table_name: str):
        return RestQuery(self, table_name)

    def request(self, method: str, table_name: str, params=None, headers=None, json=None):
        import requests

        request_headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)
        query = ""
        if params:
            query = "?" + "&".join(f"{quote(str(k))}={quote(str(v), safe='*,.')}" for k, v in params)
        response = requests.request(
            method,
            f"{self.url}/rest/v1/{quote(table_name)}{query}",
            headers=request_headers,
            json=json,
            timeout=20,
        )
        if response.status_code >= 400:
            try:
                detail = response.json()
            except Exception:
                detail = response.text
            raise RuntimeError(detail)
        return response


try:
    from supabase import Client, create_client

    supabase: Client | RestSupabaseClient = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    supabase = RestSupabaseClient(SUPABASE_URL, SUPABASE_KEY)
