from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Query

from app.config.database import db

router = APIRouter()

BucketUnit = Literal["minute", "hour", "day"]


def _parse_iso_datetime(value: str) -> datetime:
    """Parse ISO-8601 datetime strings commonly produced by JS/clients.

    Accepts either:
    - 2026-04-10T15:20:30
    - 2026-04-10T15:20:30.123
    - 2026-04-10T15:20:30Z
    - 2026-04-10T15:20:30+00:00
    """
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    return datetime.fromisoformat(normalized)


def _date_trunc_unit(unit: BucketUnit) -> str:
    # Mongo expects 'minute'|'hour'|'day'
    return unit


@router.get("/metrics/materials_by_line")
def materials_by_line(
    start: str,
    end: str,
    bucket: BucketUnit = "minute",
):
    """Accepted materials per line over time.

    Output rows: {ts, line, material, count}
    """
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    pipeline = [
        {
            "$match": {
                "timestamp": {"$gte": start_dt, "$lte": end_dt},
                "type": "classification",
                "result": "accepted",
                "material": {"$in": ["plastic", "glass", "metal"]},
                "line": {"$ne": None},
            }
        },
        {
            "$project": {
                "ts": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": _date_trunc_unit(bucket),
                    }
                },
                "line": 1,
                "material": 1,
            }
        },
        {
            "$group": {
                "_id": {"ts": "$ts", "line": "$line", "material": "$material"},
                "count": {"$sum": 1},
            }
        },
        {
            "$project": {
                "_id": 0,
                "ts": "$_id.ts",
                "line": "$_id.line",
                "material": "$_id.material",
                "count": 1,
            }
        },
        {"$sort": {"ts": 1, "line": 1, "material": 1}},
    ]

    return list(db.events.aggregate(pipeline))


@router.get("/metrics/parking_occupancy")
def parking_occupancy(
    start: str,
    end: str,
    bucket: BucketUnit = "minute",
):
    """Parking occupancy over time.

    Output rows: {ts, occupied, total, occupancy_pct}
    """
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    pipeline = [
        {"$match": {"timestamp": {"$gte": start_dt, "$lte": end_dt}}},
        {"$sort": {"timestamp": 1}},
        {
            "$addFields": {
                "occupied": {
                    "$size": {
                        "$filter": {
                            "input": "$parking",
                            "as": "p",
                            "cond": {"$eq": ["$$p", True]},
                        }
                    }
                },
                "total": {"$size": "$parking"},
                "ts": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": _date_trunc_unit(bucket),
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$ts",
                "occupied": {"$last": "$occupied"},
                "total": {"$last": "$total"},
            }
        },
        {
            "$project": {
                "_id": 0,
                "ts": "$_id",
                "occupied": 1,
                "total": 1,
                "occupancy_pct": {
                    "$cond": [
                        {"$gt": ["$total", 0]},
                        {"$multiply": [{"$divide": ["$occupied", "$total"]}, 100]},
                        0,
                    ]
                },
            }
        },
        {"$sort": {"ts": 1}},
    ]

    return list(db.state.aggregate(pipeline))


@router.get("/metrics/throughput")
def throughput(
    start: str,
    end: str,
    bucket: BucketUnit = "minute",
):
    """System throughput (elements processed) over time.

    Derived from classification events.

    Output rows: {ts, processed, accepted, rejected}
    """
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    pipeline = [
        {
            "$match": {
                "timestamp": {"$gte": start_dt, "$lte": end_dt},
                "type": "classification",
            }
        },
        {
            "$project": {
                "ts": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": _date_trunc_unit(bucket),
                    }
                },
                "is_accepted": {"$eq": ["$result", "accepted"]},
                "is_rejected": {"$ne": ["$result", "accepted"]},
            }
        },
        {
            "$group": {
                "_id": "$ts",
                "processed": {"$sum": 1},
                "accepted": {"$sum": {"$cond": ["$is_accepted", 1, 0]}},
                "rejected": {"$sum": {"$cond": ["$is_rejected", 1, 0]}},
            }
        },
        {
            "$project": {
                "_id": 0,
                "ts": "$_id",
                "processed": 1,
                "accepted": 1,
                "rejected": 1,
            }
        },
        {"$sort": {"ts": 1}},
    ]

    return list(db.events.aggregate(pipeline))


@router.get("/metrics/rejects_by_line")
def rejects_by_line(
    start: str,
    end: str,
    bucket: BucketUnit = "minute",
):
    """Rejected elements per line over time.

    NOTE: The backend does not currently store the *cause* of rejection, only result/material.

    Output rows: {ts, line, rejects}
    """
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    accepted_materials = ["plastic", "glass", "metal"]

    pipeline = [
        {
            "$match": {
                "timestamp": {"$gte": start_dt, "$lte": end_dt},
                "type": "classification",
                "line": {"$ne": None},
            }
        },
        {
            "$project": {
                "ts": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": _date_trunc_unit(bucket),
                    }
                },
                "line": 1,
                "is_reject": {
                    "$not": {
                        "$and": [
                            {"$eq": ["$result", "accepted"]},
                            {"$in": ["$material", accepted_materials]},
                        ]
                    }
                },
            }
        },
        {
            "$group": {
                "_id": {"ts": "$ts", "line": "$line"},
                "rejects": {"$sum": {"$cond": ["$is_reject", 1, 0]}},
            }
        },
        {
            "$project": {
                "_id": 0,
                "ts": "$_id.ts",
                "line": "$_id.line",
                "rejects": 1,
            }
        },
        {"$sort": {"ts": 1, "line": 1}},
    ]

    return list(db.events.aggregate(pipeline))


@router.get("/metrics/alerts")
def alerts_over_time(
    start: str,
    end: str,
    bucket: BucketUnit = "minute",
    types: Optional[str] = Query(default=None, description="Comma-separated alert types to include"),
):
    """Alert events over time, grouped by alert type.

    Output rows: {ts, type, count}
    """
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    match: dict = {"timestamp": {"$gte": start_dt, "$lte": end_dt}}
    if types:
        allowed = [t.strip() for t in types.split(",") if t.strip()]
        if allowed:
            match["type"] = {"$in": allowed}

    pipeline = [
        {"$match": match},
        {
            "$project": {
                "ts": {
                    "$dateTrunc": {
                        "date": "$timestamp",
                        "unit": _date_trunc_unit(bucket),
                    }
                },
                "type": 1,
            }
        },
        {"$group": {"_id": {"ts": "$ts", "type": "$type"}, "count": {"$sum": 1}}},
        {"$project": {"_id": 0, "ts": "$_id.ts", "type": "$_id.type", "count": 1}},
        {"$sort": {"ts": 1, "type": 1}},
    ]

    return list(db.alerts.aggregate(pipeline))


@router.get("/metrics/kpis_daily")
def kpis_daily(start: str, end: str):
    """Daily KPIs from the `kpis` collection.

    Output rows include a time field `ts` so Grafana can plot them.
    """
    start_dt = _parse_iso_datetime(start)
    end_dt = _parse_iso_datetime(end)

    pipeline = [
        {
            "$addFields": {
                "ts": {
                    "$dateFromString": {
                        "dateString": "$date",
                        "format": "%Y-%m-%d",
                    }
                }
            }
        },
        {"$match": {"ts": {"$gte": start_dt, "$lte": end_dt}}},
        {
            "$project": {
                "_id": 0,
                "ts": 1,
                "date": 1,
                "plastic": 1,
                "glass": 1,
                "metal": 1,
                "rejects": 1,
                "throughput": 1,
                "alerts": 1,
            }
        },
        {"$sort": {"ts": 1}},
    ]

    return list(db.kpis.aggregate(pipeline))
