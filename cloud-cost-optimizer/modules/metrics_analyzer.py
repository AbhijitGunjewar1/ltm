"""
Pull CPU and memory metrics from Cloud Monitoring for all VMs
over the configured analysis window (default: last 10 months).
"""

import requests
from datetime import datetime, timezone
from typing import Any
from config import (
    PROJECT_ID,
    ANALYSIS_START,
    ANALYSIS_END,
    ALIGNMENT_PERIOD_SECONDS,
    CPU_LOW_THRESHOLD,
    CPU_HIGH_THRESHOLD,
    MEMORY_LOW_THRESHOLD,
    IDLE_CPU_THRESHOLD,
)


# ── Cloud Monitoring metric types ─────────────────────────────────────────────
CPU_METRIC    = "compute.googleapis.com/instance/cpu/utilization"
# Memory requires Ops Agent; falls back gracefully if missing
MEMORY_METRIC = "agent.googleapis.com/memory/percent_used"
UPTIME_METRIC = "compute.googleapis.com/instance/uptime"

MONITORING_BASE = "https://monitoring.googleapis.com/v3"


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch_timeseries(
    token: str,
    project_id: str,
    metric_type: str,
    extra_filter: str = "",
    reducer: str = "REDUCE_MEAN",
    groupby: list[str] | None = None,
) -> list[dict]:
    """Generic Cloud Monitoring timeSeries.list call."""
    url = f"{MONITORING_BASE}/projects/{project_id}/timeSeries"
    headers = {"Authorization": f"Bearer {token}"}

    metric_filter = f'metric.type="{metric_type}"'
    if extra_filter:
        metric_filter += f" AND {extra_filter}"

    params: dict[str, Any] = {
        "filter": metric_filter,
        "interval.startTime": _ts(ANALYSIS_START),
        "interval.endTime": _ts(ANALYSIS_END),
        "aggregation.alignmentPeriod": f"{ALIGNMENT_PERIOD_SECONDS}s",
        "aggregation.perSeriesAligner": "ALIGN_MEAN",
        "aggregation.crossSeriesReducer": reducer,
        "aggregation.groupByFields": groupby or [
            "metric.labels.instance_name",
            "resource.labels.zone",
        ],
    }

    series: list[dict] = []
    page_token = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code == 404:
            return []   # metric not available
        resp.raise_for_status()
        data = resp.json()
        series.extend(data.get("timeSeries", []))
        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return series


def _series_stats(points: list[dict]) -> dict:
    """Compute avg / max / min / p95 from a list of Monitoring points."""
    if not points:
        return {"avg": None, "max": None, "min": None, "p95": None, "samples": 0}

    values = sorted(
        float(p.get("value", {}).get("doubleValue", 0)) for p in points
    )
    n = len(values)
    avg = sum(values) / n
    p95_idx = max(0, int(n * 0.95) - 1)

    return {
        "avg": round(avg * 100, 2),          # convert 0-1 fraction → %
        "max": round(values[-1] * 100, 2),
        "min": round(values[0] * 100, 2),
        "p95": round(values[p95_idx] * 100, 2),
        "samples": n,
    }


def _memory_series_stats(points: list[dict]) -> dict:
    """Memory metric is already in %, no *100 conversion needed."""
    if not points:
        return {"avg": None, "max": None, "min": None, "p95": None, "samples": 0}

    values = sorted(float(p.get("value", {}).get("doubleValue", 0)) for p in points)
    n = len(values)
    avg = sum(values) / n
    p95_idx = max(0, int(n * 0.95) - 1)

    return {
        "avg": round(avg, 2),
        "max": round(values[-1], 2),
        "min": round(values[0], 2),
        "p95": round(values[p95_idx], 2),
        "samples": n,
    }


def fetch_cpu_metrics(token: str, project_id: str = PROJECT_ID) -> dict[str, dict]:
    """Return {instance_name: cpu_stats_dict} for all VMs."""
    print("  [metrics] Fetching CPU utilization (this may take a moment)...")
    series = _fetch_timeseries(token, project_id, CPU_METRIC)
    result: dict[str, dict] = {}
    for ts in series:
        name = ts.get("metric", {}).get("labels", {}).get("instance_name", "unknown")
        zone = ts.get("resource", {}).get("labels", {}).get("zone", "")
        stats = _series_stats(ts.get("points", []))
        result[name] = {**stats, "zone": zone}
    print(f"  [metrics] CPU data received for {len(result)} instances.")
    return result


def fetch_memory_metrics(token: str, project_id: str = PROJECT_ID) -> dict[str, dict]:
    """Return {instance_name: memory_stats_dict}. Empty if Ops Agent not installed."""
    print("  [metrics] Fetching memory utilization (requires Ops Agent)...")
    series = _fetch_timeseries(token, project_id, MEMORY_METRIC)
    result: dict[str, dict] = {}
    for ts in series:
        name = ts.get("metric", {}).get("labels", {}).get("instance_name", "unknown")
        zone = ts.get("resource", {}).get("labels", {}).get("zone", "")
        # filter out non-memory states
        state = ts.get("metric", {}).get("labels", {}).get("state", "used")
        if state != "used":
            continue
        stats = _memory_series_stats(ts.get("points", []))
        result[name] = {**stats, "zone": zone}

    if not result:
        print("  [metrics] No memory data — Ops Agent may not be installed on VMs.")
    else:
        print(f"  [metrics] Memory data received for {len(result)} instances.")
    return result


def build_monthly_breakdown(token: str, project_id: str = PROJECT_ID) -> dict[str, list]:
    """
    Return per-VM monthly CPU avg for last 10 months.
    Shape: {instance_name: [{"month": "2024-08", "avg_cpu": 12.3}, ...]}
    """
    print("  [metrics] Building monthly CPU breakdown...")
    series = _fetch_timeseries(
        token, project_id, CPU_METRIC,
        reducer="REDUCE_MEAN",
    )

    monthly: dict[str, list] = {}
    for ts in series:
        name = ts.get("metric", {}).get("labels", {}).get("instance_name", "unknown")
        by_month: dict[str, list] = {}
        for pt in ts.get("points", []):
            ts_str = pt.get("interval", {}).get("startTime", "")
            if not ts_str:
                continue
            month_key = ts_str[:7]   # "YYYY-MM"
            val = float(pt.get("value", {}).get("doubleValue", 0)) * 100
            by_month.setdefault(month_key, []).append(val)

        monthly[name] = sorted(
            [
                {"month": m, "avg_cpu": round(sum(v) / len(v), 2)}
                for m, v in by_month.items()
            ],
            key=lambda x: x["month"],
        )

    return monthly


def classify_vm(cpu_stats: dict, mem_stats: dict | None) -> tuple[str, str]:
    """
    Return (classification, reason).
    Classifications: IDLE, OVER_PROVISIONED, OPTIMAL, UNDER_PROVISIONED, NO_DATA
    """
    avg_cpu = cpu_stats.get("avg")
    avg_mem = mem_stats.get("avg") if mem_stats else None

    if avg_cpu is None:
        return "NO_DATA", "No CPU metrics available"

    if avg_cpu < IDLE_CPU_THRESHOLD:
        return "IDLE", f"Avg CPU {avg_cpu}% — candidate for shutdown or rightsizing to e2-micro"

    if avg_cpu < CPU_LOW_THRESHOLD:
        if avg_mem is not None and avg_mem < MEMORY_LOW_THRESHOLD:
            return (
                "OVER_PROVISIONED",
                f"Avg CPU {avg_cpu}%, Avg Mem {avg_mem}% — both low, downsize machine type",
            )
        return (
            "OVER_PROVISIONED",
            f"Avg CPU {avg_cpu}% — consider smaller machine type",
        )

    if avg_cpu > CPU_HIGH_THRESHOLD:
        return (
            "UNDER_PROVISIONED",
            f"Avg CPU {avg_cpu}% — consistently high, consider upsizing",
        )

    return "OPTIMAL", f"Avg CPU {avg_cpu}% — within normal range"
