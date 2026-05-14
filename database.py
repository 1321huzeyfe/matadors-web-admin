# -*- coding: utf-8 -*-
"""Compatibility exports for the database layer.

The implementation lives in the db package so auth, main kasa data,
and per-cashier data access can evolve independently while old imports
continue to work.
"""
from db import AuthDatabase, CashierDatabase, Database, KasaDatabase, DEFAULT_PRODUCTS

__all__ = ["Database", "AuthDatabase", "KasaDatabase", "CashierDatabase", "DEFAULT_PRODUCTS"]
