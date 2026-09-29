"""
Worker batch — Livraison des webhooks en attente + nettoyage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and
