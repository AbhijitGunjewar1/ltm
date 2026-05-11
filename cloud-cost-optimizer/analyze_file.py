#!/usr/bin/env python3
"""
GCP Cloud Cost Optimizer — Deep Analysis Engine
Project: gcpopenshift

Drop your VM metrics file (CSV/Excel/JSON) in the same folder and run:
    python analyze_file.py
"""

import sys, os, json, csv, argparse
from datetime import datetime, timezone

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False

try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

try:
    from colorama import Fore, Style, init as colorama_init
    colorama_init(autoreset=True)
    HAS_COLOR = True
except ImportError:
    HAS_COLOR = False

# ─────────────────────────────────────────────────────────────────────────────
#  Constants & Pricing (us-central1 on-demand, USD)
# ─────────────────────────────────────────────────────────────────────────────

HOURS_PER_MONTH  = 730
HOURS_PER_YEAR   = 8760
MONTHS_PER_YEAR  = 12

# Committed Use Discount rates
CUD_1YR_DISCOUNT = 0.37    # 37% off on-demand
CUD_3YR_DISCOUNT = 0.57    # 57% off on-demand

# Sustained Use Discount (auto-applied for N1/N2 after 25% month usage)
SUD_MAX_DISCOUNT = 0.30

# Spot VM discount vs on-demand
SPOT_DISCOUNT    = 0.80    # up to 80% off

# Scheduled shutdown savings (e.g. off 14hrs/day on weekdays + weekends)
SCHEDULE_8HR_DAY   = 1 - (8  / 24)   # on 8hrs/day  → 67% saving
SCHEDULE_12HR_DAY  = 1 - (12 / 24)   # on 12hrs/day → 50% saving

# Thresholds
CPU_IDLE      = 5.0
CPU_LOW       = 20.0
CPU_HIGH      = 80.0
MEM_LOW       = 40.0
MEM_HIGH      = 85.0

# Machine catalog: name → (vcpus, ram_gb, cpu_price/hr, ram_price/gb/hr)
CATALOG = {
    # E2 — most cost-effective general purpose
    "e2-micro":        (2,   1,    0.0084, 0.0011),
    "e2-small":        (2,   2,    0.0168, 0.0023),
    "e2-medium":       (2,   4,    0.0335, 0.0045),
    "e2-standard-2":   (2,   8,    0.0210, 0.0028),
    "e2-standard-4":   (4,  16,    0.0210, 0.0028),
    "e2-standard-8":   (8,  32,    0.0210, 0.0028),
    "e2-standard-16":  (16, 64,    0.0210, 0.0028),
    "e2-standard-32":  (32, 128,   0.0210, 0.0028),
    "e2-highmem-2":    (2,  16,    0.0210, 0.0028),
    "e2-highmem-4":    (4,  32,    0.0210, 0.0028),
    "e2-highmem-8":    (8,  64,    0.0210, 0.0028),
    "e2-highmem-16":   (16, 128,   0.0210, 0.0028),
    "e2-highcpu-2":    (2,   2,    0.0210, 0.0028),
    "e2-highcpu-4":    (4,   4,    0.0210, 0.0028),
    "e2-highcpu-8":    (8,   8,    0.0210, 0.0028),
    "e2-highcpu-16":   (16, 16,    0.0210, 0.0028),
    "e2-highcpu-32":   (32, 32,    0.0210, 0.0028),
    # N2 — balanced performance
    "n2-standard-2":   (2,   8,    0.0334, 0.0045),
    "n2-standard-4":   (4,  16,    0.0334, 0.0045),
    "n2-standard-8":   (8,  32,    0.0334, 0.0045),
    "n2-standard-16":  (16, 64,    0.0334, 0.0045),
    "n2-standard-32":  (32, 128,   0.0334, 0.0045),
    "n2-standard-48":  (48, 192,   0.0334, 0.0045),
    "n2-standard-64":  (64, 256,   0.0334, 0.0045),
    "n2-highmem-2":    (2,  16,    0.0334, 0.0045),
    "n2-highmem-4":    (4,  32,    0.0334, 0.0045),
    "n2-highmem-8":    (8,  64,    0.0334, 0.0045),
    "n2-highmem-16":   (16, 128,   0.0334, 0.0045),
    "n2-highmem-32":   (32, 256,   0.0334, 0.0045),
    "n2-highcpu-4":    (4,   4,    0.0334, 0.0045),
    "n2-highcpu-8":    (8,   8,    0.0334, 0.0045),
    "n2-highcpu-16":   (16, 16,    0.0334, 0.0045),
    "n2-highcpu-32":   (32, 32,    0.0334, 0.0045),
    # N1 — older gen, still common
    "n1-standard-1":   (1,   3.75, 0.0475, 0.0066),
    "n1-standard-2":   (2,   7.5,  0.0475, 0.0066),
    "n1-standard-4":   (4,  15,    0.0475, 0.0066),
    "n1-standard-8":   (8,  30,    0.0475, 0.0066),
    "n1-standard-16":  (16, 60,    0.0475, 0.0066),
    "n1-standard-32":  (32, 120,   0.0475, 0.0066),
    "n1-standard-64":  (64, 240,   0.0475, 0.0066),
    "n1-highmem-2":    (2,  13,    0.0475, 0.0066),
    "n1-highmem-4":    (4,  26,    0.0475, 0.0066),
    "n1-highmem-8":    (8,  52,    0.0475, 0.0066),
    "n1-highmem-16":   (16, 104,   0.0475, 0.0066),
    "n1-highcpu-4":    (4,   3.6,  0.0475, 0.0066),
    "n1-highcpu-8":    (8,   7.2,  0.0475, 0.0066),
    "n1-highcpu-16":   (16, 14.4,  0.0475, 0.0066),
    "n1-highcpu-32":   (32, 28.8,  0.0475, 0.0066),
    # N2D — AMD, good price/perf
    "n2d-standard-2":  (2,   8,    0.0284, 0.0038),
    "n2d-standard-4":  (4,  16,    0.0284, 0.0038),
    "n2d-standard-8":  (8,  32,    0.0284, 0.0038),
    "n2d-standard-16": (16, 64,    0.0284, 0.0038),
    "n2d-standard-32": (32, 128,   0.0284, 0.0038),
    # C2 — compute optimized
    "c2-standard-4":   (4,  16,    0.0522, 0.0070),
    "c2-standard-8":   (8,  32,    0.0522, 0.0070),
    "c2-standard-16":  (16, 64,    0.0522, 0.0070),
    "c2-standard-30":  (30, 120,   0.0522, 0.0070),
    "c2-standard-60":  (60, 240,   0.0522, 0.0070),
}

COL_ALIASES = {
    "name":         ["name","instance name","vm name","instance_name","vm_name","hostname","server name"],
    "zone":         ["zone","location","region","availability zone"],
    "machine_type": ["machine type","machine_type","type","instance type","size","sku","vm size"],
    "status":       ["status","state","power state","vm status"],
    "cpu_avg":      ["cpu avg","cpu_avg","average cpu","cpu utilization","cpu util","cpu usage",
                     "avg cpu","avg cpu utilization","mean cpu","cpu (avg)","cpu utilization (avg)",
                     "average cpu utilization","cpu%","cpu % avg","cpu percent"],
    "cpu_max":      ["cpu max","cpu_max","max cpu","peak cpu","cpu (max)","maximum cpu","cpu % max"],
    "cpu_min":      ["cpu min","cpu_min","min cpu","minimum cpu","cpu (min)","cpu % min"],
    "cpu_p95":      ["cpu p95","cpu_p95","95th cpu","p95 cpu","cpu 95th percentile"],
    "mem_avg":      ["memory avg","mem avg","mem_avg","average memory","memory utilization",
                     "mem util","memory usage","avg memory","avg memory utilization",
                     "memory (avg)","ram usage","mem%","memory %","memory percent","ram %"],
    "mem_max":      ["memory max","mem max","mem_max","peak memory","memory (max)","maximum memory"],
    "vcpus":        ["vcpus","vcpu","cpus","cpu count","num cpus","cores","number of cpus","vcore"],
    "ram_gb":       ["ram gb","ram_gb","memory gb","memory (gb)","ram (gb)",
                     "total memory","memory size","total ram","memory gib"],
    "preemptible":  ["preemptible","spot","spot vm","preemptible vm"],
    "monthly_cost": ["monthly cost","cost per month","monthly price","current cost","est cost",
                     "cost (usd)","monthly cost usd"],
}

# ─────────────────────────────────────────────────────────────────────────────
#  File loading
# ─────────────────────────────────────────────────────────────────────────────

def load_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".json":
        with open(path) as f:
            data = json.load(f)
        rows = data if isinstance(data, list) else data.get("vms", data.get("instances", [data]))
    elif ext in (".xlsx", ".xls"):
        if not HAS_PANDAS:
            sys.exit("ERROR: Install pandas & openpyxl:  python -m pip install pandas openpyxl")
        df = pd.read_excel(path, dtype=str)
        df.columns = [c.strip() for c in df.columns]
        rows = df.fillna("").to_dict(orient="records")
    else:
        rows = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rows.append({k.strip(): v.strip() for k, v in row.items() if k})
    print(f"  Loaded {len(rows)} rows from: {os.path.basename(path)}")
    return rows


def map_columns(rows):
    if not rows:
        return rows
    raw = list(rows[0].keys())
    lower = {h.lower(): h for h in raw}
    mapping = {}
    for canon, aliases in COL_ALIASES.items():
        for a in aliases:
            if a in lower:
                mapping[canon] = lower[a]
                break
    if "name" not in mapping:
        print(f"\nWARNING: Could not detect VM Name column.")
        print(f"  Found columns: {raw}\n")

    out = []
    for row in rows:
        nr = {}
        for canon, raw_key in mapping.items():
            nr[canon] = row.get(raw_key, "")
        for k, v in row.items():
            if k not in mapping.values():
                nr[k] = v
        out.append(nr)
    return out

# ─────────────────────────────────────────────────────────────────────────────
#  Parsers
# ─────────────────────────────────────────────────────────────────────────────

def pct(v):
    if v is None or str(v).strip() in ("", "-", "N/A", "n/a", "nan"):
        return None
    s = str(v).strip().rstrip("%")
    try:
        f = float(s)
        return round(f * 100 if 0 < f <= 1.0 else f, 2)
    except ValueError:
        return None

def num(v):
    if v is None or str(v).strip() in ("", "-", "N/A"):
        return None
    try:
        return float(str(v).strip().replace(",", ""))
    except ValueError:
        return None

def detect_monthly_cols(rows):
    if not rows:
        return []
    months = []
    for col in rows[0].keys():
        c = str(col).strip()
        if len(c) == 7 and c[4] == "-":
            try:
                datetime.strptime(c, "%Y-%m")
                months.append(c)
            except ValueError:
                pass
    return sorted(months)

# ─────────────────────────────────────────────────────────────────────────────
#  Cost engine
# ─────────────────────────────────────────────────────────────────────────────

def machine_cost_per_month(vcpus, ram_gb, machine_type):
    mt = (machine_type or "").lower().strip()
    if mt in CATALOG:
        cv, cr, cp, rp = CATALOG[mt]
        return round(cv * cp * HOURS_PER_MONTH + cr * rp * HOURS_PER_MONTH, 2)
    if vcpus and ram_gb:
        return round(vcpus * 0.0334 * HOURS_PER_MONTH + ram_gb * 0.0045 * HOURS_PER_MONTH, 2)
    return None

def lookup_specs(machine_type):
    mt = (machine_type or "").lower().strip()
    if mt in CATALOG:
        cv, cr, _, _ = CATALOG[mt]
        return cv, cr
    return None, None

def get_machine_family(machine_type):
    mt = (machine_type or "").lower()
    for f in ["e2", "n2d", "n2", "n1", "c2", "m1", "m2", "a2"]:
        if mt.startswith(f):
            return f
    return "unknown"

def suggest_rightsize(machine_type, avg_cpu, avg_mem, vcpus, ram_gb):
    """Return list of rightsizing options sorted by monthly cost."""
    if avg_cpu is None or vcpus is None:
        return []

    # Need 30% headroom above actual usage
    need_cpu = max(1, vcpus * (avg_cpu / 100) * 1.30)
    need_ram = max(0.5, (ram_gb or 4) * ((avg_mem or 50) / 100) * 1.30)

    current_cost = machine_cost_per_month(vcpus, ram_gb, machine_type)
    options = []

    for mt, (cv, cr, cp, rp) in CATALOG.items():
        if cv < need_cpu or cr < need_ram:
            continue
        cost = round(cv * cp * HOURS_PER_MONTH + cr * rp * HOURS_PER_MONTH, 2)
        if current_cost and cost >= current_cost:
            continue
        saving = round(current_cost - cost, 2) if current_cost else 0
        saving_pct = round(saving / current_cost * 100, 1) if current_cost else 0
        options.append({
            "machine_type": mt, "vcpus": cv, "ram_gb": cr,
            "monthly_cost": cost, "saving_per_month": saving,
            "saving_pct": saving_pct,
        })

    return sorted(options, key=lambda x: x["monthly_cost"])


def calc_discount_scenarios(monthly_cost):
    if not monthly_cost:
        return {}
    annual = monthly_cost * 12
    return {
        "on_demand_annual":        round(annual, 2),
        "sud_annual":              round(annual * (1 - SUD_MAX_DISCOUNT), 2),
        "cud_1yr_annual":          round(annual * (1 - CUD_1YR_DISCOUNT), 2),
        "cud_3yr_annual":          round(annual * (1 - CUD_3YR_DISCOUNT), 2),
        "spot_annual":             round(annual * (1 - SPOT_DISCOUNT), 2),
        "scheduled_12hr_annual":   round(annual * (1 - SCHEDULE_12HR_DAY), 2),
        "scheduled_8hr_annual":    round(annual * (1 - SCHEDULE_8HR_DAY), 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Classification
# ─────────────────────────────────────────────────────────────────────────────

def classify(avg_cpu, avg_mem, cpu_max=None):
    if avg_cpu is None:
        return "NO_DATA", "No CPU metrics available"
    if avg_cpu < CPU_IDLE:
        return "IDLE", f"Avg CPU {avg_cpu:.1f}% — VM is essentially unused"
    if avg_cpu < CPU_LOW:
        if avg_mem is not None and avg_mem < MEM_LOW:
            return "OVER_PROVISIONED", f"CPU {avg_cpu:.1f}% avg, Mem {avg_mem:.1f}% avg — both underutilized"
        return "OVER_PROVISIONED", f"CPU {avg_cpu:.1f}% avg — low utilization, oversized machine"
    if avg_cpu > CPU_HIGH:
        return "UNDER_PROVISIONED", f"CPU {avg_cpu:.1f}% avg — consistently high, risk of degradation"
    if avg_mem is not None and avg_mem > MEM_HIGH:
        return "MEMORY_PRESSURE", f"Memory {avg_mem:.1f}% avg — high memory usage, consider highmem type"
    return "OPTIMAL", f"CPU {avg_cpu:.1f}% — within healthy range"


STATUS_LABEL = {
    "IDLE":             "IDLE (Shutdown candidate)",
    "OVER_PROVISIONED": "OVER-PROVISIONED (Rightsize)",
    "UNDER_PROVISIONED":"UNDER-PROVISIONED (Upsize)",
    "MEMORY_PRESSURE":  "MEMORY PRESSURE (Switch to highmem)",
    "OPTIMAL":          "OPTIMAL",
    "NO_DATA":          "NO DATA",
}

def _c(text, cls):
    if not HAS_COLOR:
        return str(text)
    colors = {
        "IDLE":             Fore.RED,
        "OVER_PROVISIONED": Fore.YELLOW,
        "UNDER_PROVISIONED":Fore.MAGENTA,
        "MEMORY_PRESSURE":  Fore.CYAN,
        "OPTIMAL":          Fore.GREEN,
        "NO_DATA":          Fore.WHITE,
    }
    return f"{colors.get(cls,'')}{text}{Style.RESET_ALL}"

def _tab(rows, headers, fmt="github"):
    if HAS_TABULATE:
        return tabulate(rows, headers=headers, tablefmt=fmt)
    widths = [max(len(str(h)), max((len(str(r[i])) for r in rows), default=0))
              for i, h in enumerate(headers)]
    lines = ["  ".join(str(h).ljust(w) for h, w in zip(headers, widths)),
             "  ".join("-"*w for w in widths)]
    for row in rows:
        lines.append("  ".join(str(c).ljust(w) for c, w in zip(row, widths)))
    return "\n".join(lines)

def div(title=""):
    print(f"\n{'═'*80}")
    if title:
        print(f"  {title}")
        print(f"{'═'*80}")

def sec(title):
    print(f"\n{'─'*80}")
    print(f"  {title}")
    print(f"{'─'*80}\n")

# ─────────────────────────────────────────────────────────────────────────────
#  Main Analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze(rows):
    monthly_cols = detect_monthly_cols(rows)
    last10_months = sorted(monthly_cols)[-10:]

    vms = []
    for row in rows:
        name         = (row.get("name") or "").strip() or "unknown"
        zone         = (row.get("zone") or "").strip()
        machine_type = (row.get("machine_type") or "").strip()
        status       = (row.get("status") or "UNKNOWN").strip().upper()

        avg_cpu = pct(row.get("cpu_avg"))
        max_cpu = pct(row.get("cpu_max"))
        min_cpu = pct(row.get("cpu_min"))
        p95_cpu = pct(row.get("cpu_p95"))
        avg_mem = pct(row.get("mem_avg"))
        max_mem = pct(row.get("mem_max"))

        vcpus  = num(row.get("vcpus"))
        ram_gb = num(row.get("ram_gb"))
        if vcpus is None and machine_type:
            vcpus, ram_gb = lookup_specs(machine_type)

        monthly_data = {}
        for mc in last10_months:
            v = pct(row.get(mc))
            if v is not None:
                monthly_data[mc] = v

        monthly_cost = machine_cost_per_month(vcpus, ram_gb, machine_type)
        cls, reason  = classify(avg_cpu, avg_mem, max_cpu)
        options      = suggest_rightsize(machine_type, avg_cpu, avg_mem, vcpus, ram_gb)
        best_option  = options[0] if options else None
        discounts    = calc_discount_scenarios(monthly_cost)
        family       = get_machine_family(machine_type)

        vms.append({
            "name": name, "zone": zone, "machine_type": machine_type,
            "status": status, "vcpus": vcpus, "ram_gb": ram_gb,
            "family": family,
            "avg_cpu": avg_cpu, "max_cpu": max_cpu, "min_cpu": min_cpu,
            "p95_cpu": p95_cpu, "avg_mem": avg_mem, "max_mem": max_mem,
            "monthly_cost": monthly_cost,
            "annual_cost": round(monthly_cost * 12, 2) if monthly_cost else None,
            "classification": cls, "reason": reason,
            "rightsize_options": options,
            "best_option": best_option,
            "discounts": discounts,
            "monthly_data": monthly_data,
        })

    # ── Header ────────────────────────────────────────────────────────────────
    div("GCP CLOUD COST OPTIMIZATION — DEEP ANALYSIS REPORT")
    print(f"  Project        : gcpopenshift")
    print(f"  Generated      : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Total VMs      : {len(vms)}")
    running = sum(1 for v in vms if v["status"] in ("RUNNING","ACTIVE","ON"))
    print(f"  Running VMs    : {running}")
    print(f"  Monthly period : {last10_months[0] if last10_months else 'N/A'} → {last10_months[-1] if last10_months else 'N/A'}")
    print(f"{'═'*80}")

    # ── Section 1: VM Inventory + Utilization ─────────────────────────────────
    sec("SECTION 1 — VM INVENTORY & UTILIZATION OVERVIEW")
    rows1 = []
    for v in vms:
        cls = v["classification"]
        rows1.append([
            _c(v["name"][:28], cls),
            (v["zone"] or "")[-12:],
            v["machine_type"] or "—",
            f'{int(v["vcpus"])}' if v["vcpus"] else "?",
            f'{v["ram_gb"]:.0f}GB' if v["ram_gb"] else "?",
            f'{v["avg_cpu"]:.1f}%' if v["avg_cpu"] is not None else "N/A",
            f'{v["max_cpu"]:.1f}%' if v["max_cpu"] is not None else "N/A",
            f'{v["avg_mem"]:.1f}%' if v["avg_mem"] is not None else "N/A",
            f'${v["monthly_cost"]:,.2f}' if v["monthly_cost"] else "N/A",
            f'${v["annual_cost"]:,.2f}' if v["annual_cost"] else "N/A",
            _c(STATUS_LABEL.get(cls, cls), cls),
        ])
    print(_tab(rows1, [
        "VM Name","Zone","Machine Type","vCPU","RAM",
        "CPU Avg","CPU Max","Mem Avg","$/Month","$/Year","Status"
    ]))

    # ── Section 2: Monthly CPU Breakdown ─────────────────────────────────────
    if last10_months:
        sec(f"SECTION 2 — MONTHLY CPU UTILIZATION BREAKDOWN (last {len(last10_months)} months)")
        rows2 = []
        for v in vms:
            cls = v["classification"]
            row = [_c(v["name"][:26], cls), v["machine_type"] or "—"]
            vals = []
            for m in last10_months:
                val = v["monthly_data"].get(m)
                vals.append(val)
                row.append(f"{val:.1f}%" if val is not None else "—")
            # trend
            filled = [x for x in vals if x is not None]
            if len(filled) >= 2:
                trend = "↑ Rising" if filled[-1] > filled[0] * 1.1 else \
                        "↓ Falling" if filled[-1] < filled[0] * 0.9 else "→ Stable"
            else:
                trend = "—"
            row.append(trend)
            rows2.append(row)
        print(_tab(rows2, ["VM Name","Machine Type"] + last10_months + ["Trend"]))
    else:
        sec("SECTION 2 — MONTHLY BREAKDOWN")
        print("  No monthly columns found in your file.")
        print("  Add columns named '2024-08', '2024-09' ... with CPU% per month for this view.\n")

    # ── Section 3: Rightsizing Detail ─────────────────────────────────────────
    sec("SECTION 3 — RIGHTSIZING RECOMMENDATIONS (per VM)")
    for v in vms:
        cls = v["classification"]
        if cls in ("OPTIMAL", "NO_DATA") and not v["rightsize_options"]:
            continue
        print(f"  {'─'*76}")
        print(f"  VM   : {_c(v['name'], cls)}")
        print(f"  Now  : {v['machine_type']}  ({v['vcpus']} vCPUs, {v['ram_gb']} GB RAM)  ${v['monthly_cost']:,.2f}/mo  ${v['annual_cost']:,.2f}/yr" if v['monthly_cost'] else f"  Now  : {v['machine_type']}")
        print(f"  Usage: CPU avg {v['avg_cpu']:.1f}%  max {v['max_cpu']:.1f}%  p95 {v['p95_cpu']:.1f}%  |  Mem avg {v['avg_mem']:.1f}%" if all(x is not None for x in [v['avg_cpu'],v['max_cpu'],v['p95_cpu'],v['avg_mem']]) else f"  Usage: CPU avg {v['avg_cpu']:.1f}%" if v['avg_cpu'] is not None else "  Usage: No data")
        print(f"  Verdict: {_c(STATUS_LABEL.get(cls,cls), cls)}")
        print(f"  Reason : {v['reason']}")

        if cls == "IDLE":
            saving = v["monthly_cost"] or 0
            print(f"\n  ACTION: SHUT DOWN this VM")
            print(f"          Saving: ${saving:,.2f}/month  |  ${saving*12:,.2f}/year")
            print(f"          If kept for DR/standby: convert to a Spot VM or schedule shutdown")

        elif cls == "OVER_PROVISIONED" and v["rightsize_options"]:
            print(f"\n  RIGHTSIZE OPTIONS (top 3):")
            opts = v["rightsize_options"][:3]
            rrows = []
            for o in opts:
                rrows.append([
                    o["machine_type"],
                    f'{o["vcpus"]} vCPU',
                    f'{o["ram_gb"]} GB',
                    f'${o["monthly_cost"]:,.2f}/mo',
                    f'${o["monthly_cost"]*12:,.2f}/yr',
                    f'Save ${o["saving_per_month"]:,.2f}/mo',
                    f'{o["saving_pct"]}% cheaper',
                ])
            print(_tab(rrows, ["Machine Type","vCPUs","RAM","$/Month","$/Year","Monthly Saving","% Saving"]))
            best = opts[0]
            print(f"\n  RECOMMENDED → {best['machine_type']}  (saves ${best['saving_per_month']:,.2f}/mo = ${best['saving_per_month']*12:,.2f}/yr)")

        elif cls == "UNDER_PROVISIONED":
            print(f"\n  ACTION: UPSIZE machine or distribute load")
            print(f"          Consider: {v['machine_type'].replace('standard','highmem') if 'standard' in (v['machine_type'] or '') else 'next size up'}")
            print(f"          Or: add a second VM + load balancer for high availability")

        elif cls == "MEMORY_PRESSURE":
            mt = v["machine_type"] or ""
            suggested = mt.replace("standard", "highmem") if "standard" in mt else mt
            print(f"\n  ACTION: Switch to highmem variant: {suggested}")
            print(f"          Highmem gives 2× RAM per vCPU at similar price")
        print()

    # ── Section 4: Discount Scenarios ────────────────────────────────────────
    sec("SECTION 4 — DISCOUNT & COMMITMENT SCENARIOS (per VM annual cost)")
    rows4 = []
    for v in vms:
        d = v["discounts"]
        if not d:
            continue
        rows4.append([
            v["name"][:24],
            v["machine_type"] or "—",
            f'${d["on_demand_annual"]:,.0f}',
            f'${d["sud_annual"]:,.0f}',
            f'${d["cud_1yr_annual"]:,.0f}',
            f'${d["cud_3yr_annual"]:,.0f}',
            f'${d["spot_annual"]:,.0f}',
            f'${d["scheduled_12hr_annual"]:,.0f}',
        ])
    print("  Prices shown are ANNUAL (USD). Apply applicable discount for your workload.\n")
    print(_tab(rows4, [
        "VM Name","Machine Type",
        "On-Demand","SUD (30%)","CUD 1yr (37%)","CUD 3yr (57%)",
        "Spot (80%)","Scheduled 12hr"
    ]))
    print("""
  DISCOUNT GUIDE:
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ SUD  — Sustained Use Discount: auto-applied when VM runs >25% of month │
  │ CUD  — Committed Use Discount: commit 1yr or 3yr, best for stable VMs  │
  │ Spot — Preemptible/Spot VMs: up to 80% off, can be interrupted         │
  │ Sched— Shut down outside office hours (12hrs on = 50% saving)          │
  └─────────────────────────────────────────────────────────────────────────┘""")

    # ── Section 5: Family Migration ───────────────────────────────────────────
    sec("SECTION 5 — MACHINE FAMILY MIGRATION OPPORTUNITIES")
    print("""  Older machine families cost significantly more than newer ones:
  ┌──────────────┬────────────────────────────────────────────────────────┐
  │ Current      │ Recommended Migration                                  │
  ├──────────────┼────────────────────────────────────────────────────────┤
  │ N1 (gen 1)   │ → E2 (up to 31% cheaper, same workloads)              │
  │ N1 (gen 1)   │ → N2 (up to 27% cheaper, better performance)          │
  │ N2 standard  │ → E2 (up to 37% cheaper, if CPU is not a bottleneck)  │
  │ Any standard │ → N2D (AMD EPYC, ~15% cheaper than N2)                │
  │ C2           │ → C2D (AMD, up to 10% cheaper for compute workloads)  │
  └──────────────┴────────────────────────────────────────────────────────┘\n""")

    family_vms = {}
    for v in vms:
        family_vms.setdefault(v["family"], []).append(v)

    for family, fvms in sorted(family_vms.items()):
        total_annual = sum(v["annual_cost"] or 0 for v in fvms)
        migration_map = {"n1": ("e2", 0.31), "n2": ("e2", 0.37)}
        if family in migration_map:
            new_fam, saving_pct = migration_map[family]
            potential = round(total_annual * saving_pct, 2)
            print(f"  {len(fvms)} × {family.upper()} VMs  →  migrate to {new_fam.upper()}")
            print(f"    Current annual cost : ${total_annual:,.2f}")
            print(f"    Potential saving    : ${potential:,.2f}/year ({int(saving_pct*100)}% saving)")
            print()

    # ── Section 6: Infrastructure Optimization Techniques ─────────────────────
    sec("SECTION 6 — INFRASTRUCTURE OPTIMIZATION TECHNIQUES")
    print("""  1. RIGHTSIZING
     Reduce vCPUs and RAM to match actual usage (with 30% headroom).
     Best for: VMs with avg CPU < 20% or avg Memory < 40%.
     Action  : Change machine type in GCP Console → Edit → Machine Type.
     Impact  : 30–60% cost reduction per affected VM.

  2. COMMITTED USE DISCOUNTS (CUDs)
     Pre-commit to 1 or 3 years of usage for a specific machine family.
     Best for: Production VMs running 24/7 with predictable load.
     Action  : GCP Console → Committed Use Discounts → Purchase.
     Impact  : 37% (1yr) or 57% (3yr) saving on committed resources.

  3. SUSTAINED USE DISCOUNTS (SUDs)
     GCP auto-applies up to 30% discount when VM runs >25% of the month.
     Best for: VMs already running continuously (no action needed).
     Impact  : Up to 30% automatic discount.

  4. SPOT / PREEMPTIBLE VMs
     Use low-priority VMs that GCP can reclaim with 30s notice.
     Best for: Batch jobs, CI/CD pipelines, dev/test, fault-tolerant workloads.
     Action  : Edit VM → Availability policy → Spot.
     Impact  : Up to 80% cost reduction.

  5. SCHEDULED SHUTDOWN (Dev/Test VMs)
     Automatically stop non-production VMs outside working hours.
     Best for: Dev, test, staging VMs not needed 24/7.
     Action  : Cloud Scheduler + Cloud Functions, or Instance Schedules in GCP.
     Example : 8hrs/day on weekdays only = ~83% saving on that VM.
     Impact  : 50–83% saving on dev/test VMs.

  6. MACHINE FAMILY MIGRATION (N1 → E2 / N2)
     E2 is Google's latest cost-optimized family, up to 37% cheaper than N1.
     Best for: General-purpose workloads not requiring premium performance.
     Action  : Stop VM → Edit → Change Machine Type → Start.
     Impact  : 20–37% saving.

  7. IDLE VM CLEANUP
     VMs with near-zero CPU usage are paying full price for nothing.
     Best for: Forgotten dev VMs, decommissioned services.
     Action  : Verify with team, then delete or snapshot-and-delete.
     Impact  : 100% saving on those VMs.

  8. STORAGE OPTIMIZATION
     Unattached persistent disks still incur charges after VM deletion.
     Action  : GCP Console → Disks → filter "Not attached" → delete unused.
     Impact  : Eliminates orphaned disk charges ($0.04–$0.17/GB/month).

  9. CUSTOM MACHINE TYPES
     Dial in exact vCPU + RAM needed instead of nearest standard size.
     Best for: Workloads with unusual CPU:RAM ratios.
     Action  : GCP Console → Edit VM → Custom machine type.
     Impact  : 10–20% saving over nearest standard type.

  10. AUTOSCALING (Managed Instance Groups)
      Scale horizontally instead of over-provisioning a single large VM.
      Best for: Web servers, APIs with variable load patterns.
      Action  : Migrate workload to MIG with autoscaler.
      Impact  : Pay only for capacity actually in use.\n""")

    # ── Section 7: Savings Summary ────────────────────────────────────────────
    sec("SECTION 7 — TOTAL SAVINGS POTENTIAL SUMMARY")

    total_monthly   = sum(v["monthly_cost"] or 0 for v in vms)
    total_annual    = total_monthly * 12

    idle_vms        = [v for v in vms if v["classification"] == "IDLE"]
    overp_vms       = [v for v in vms if v["classification"] == "OVER_PROVISIONED"]
    underp_vms      = [v for v in vms if v["classification"] == "UNDER_PROVISIONED"]
    mempres_vms     = [v for v in vms if v["classification"] == "MEMORY_PRESSURE"]
    optimal_vms     = [v for v in vms if v["classification"] == "OPTIMAL"]
    nodata_vms      = [v for v in vms if v["classification"] == "NO_DATA"]

    idle_save_mo    = sum(v["monthly_cost"] or 0 for v in idle_vms)
    rightsize_save  = sum(
        v["best_option"]["saving_per_month"] for v in overp_vms
        if v.get("best_option")
    )
    n1_vms          = [v for v in vms if v["family"] == "n1"]
    n1_migration_save = sum((v["annual_cost"] or 0) * 0.31 for v in n1_vms) / 12

    cud_eligible_mo = sum(v["monthly_cost"] or 0 for v in vms
                          if v["classification"] in ("OPTIMAL","UNDER_PROVISIONED"))
    cud_save_mo     = cud_eligible_mo * CUD_1YR_DISCOUNT

    total_save_mo   = idle_save_mo + rightsize_save + n1_migration_save + cud_save_mo
    total_save_yr   = total_save_mo * 12
    optimized_mo    = total_monthly - total_save_mo
    savings_pct     = round(total_save_mo / total_monthly * 100, 1) if total_monthly else 0

    print(f"  {'─'*76}")
    print(f"  {'CURRENT SPEND':50} {'MONTHLY':>10}  {'ANNUAL':>10}")
    print(f"  {'─'*76}")
    print(f"  {'Total current cost (all VMs)':50} ${total_monthly:>9,.2f}  ${total_annual:>9,.2f}")
    print(f"  {'─'*76}")
    print(f"  {'SAVINGS BREAKDOWN':50} {'MONTHLY':>10}  {'ANNUAL':>10}")
    print(f"  {'─'*76}")
    print(f"  {_c(f'[S1] Shut down IDLE VMs ({len(idle_vms)} VMs)','IDLE'):65} ${idle_save_mo:>9,.2f}  ${idle_save_mo*12:>9,.2f}")
    print(f"  {_c(f'[S2] Rightsize OVER-PROVISIONED VMs ({len(overp_vms)} VMs)','OVER_PROVISIONED'):65} ${rightsize_save:>9,.2f}  ${rightsize_save*12:>9,.2f}")
    print(f"  {'[S3] Migrate N1 → E2 machine family ({} VMs)'.format(len(n1_vms)):50} ${n1_migration_save:>9,.2f}  ${n1_migration_save*12:>9,.2f}")
    print(f"  {'[S4] CUD 1yr on stable/optimal VMs':50} ${cud_save_mo:>9,.2f}  ${cud_save_mo*12:>9,.2f}")
    print(f"  {'─'*76}")
    print(f"  {'TOTAL POTENTIAL SAVINGS':50} ${total_save_mo:>9,.2f}  ${total_save_yr:>9,.2f}")
    print(f"  {'Optimized monthly spend':50} ${optimized_mo:>9,.2f}  ${optimized_mo*12:>9,.2f}")
    print(f"  {'Savings %':50} {savings_pct:>9.1f}%")
    print(f"  {'─'*76}")

    # VM breakdown by classification
    print(f"\n  VM BREAKDOWN:")
    print(f"    IDLE             : {len(idle_vms):3} VMs  — shut down → 100% saving on these")
    print(f"    OVER-PROVISIONED : {len(overp_vms):3} VMs  — rightsize → 30–60% saving each")
    print(f"    OPTIMAL          : {len(optimal_vms):3} VMs  — apply CUDs for 37% saving")
    print(f"    UNDER-PROVISIONED: {len(underp_vms):3} VMs  — upsize needed (cost will increase)")
    print(f"    MEMORY PRESSURE  : {len(mempres_vms):3} VMs  — switch to highmem type")
    print(f"    NO DATA          : {len(nodata_vms):3} VMs  — check monitoring setup")

    # ── Section 8: Priority Action Plan ───────────────────────────────────────
    sec("SECTION 8 — PRIORITY ACTION PLAN")
    print(f"  Execute in this order for fastest ROI:\n")
    action_num = 1
    if idle_vms:
        print(f"  [{action_num}] IMMEDIATELY — Shut down IDLE VMs")
        for v in idle_vms:
            print(f"       • {v['name']}  ({v['machine_type']})  saving ${v['monthly_cost']:,.2f}/mo")
        print(f"       Total: ${idle_save_mo:,.2f}/mo  |  ${idle_save_mo*12:,.2f}/yr\n")
        action_num += 1

    if overp_vms:
        print(f"  [{action_num}] THIS WEEK — Rightsize over-provisioned VMs")
        for v in overp_vms:
            if v.get("best_option"):
                b = v["best_option"]
                print(f"       • {v['name']}  {v['machine_type']} → {b['machine_type']}  "
                      f"saving ${b['saving_per_month']:,.2f}/mo")
        print(f"       Total: ${rightsize_save:,.2f}/mo  |  ${rightsize_save*12:,.2f}/yr\n")
        action_num += 1

    if n1_vms:
        print(f"  [{action_num}] THIS MONTH — Migrate {len(n1_vms)} N1 VMs → E2 machine family")
        for v in n1_vms:
            print(f"       • {v['name']}  ({v['machine_type']})")
        print(f"       Estimated saving: ${n1_migration_save:,.2f}/mo  |  ${n1_migration_save*12:,.2f}/yr\n")
        action_num += 1

    print(f"  [{action_num}] THIS QUARTER — Purchase Committed Use Discounts (CUDs)")
    print(f"       Apply 1yr CUDs to all stable, optimal VMs")
    print(f"       Saving: ${cud_save_mo:,.2f}/mo  |  ${cud_save_mo*12:,.2f}/yr\n")
    action_num += 1

    print(f"  [{action_num}] ONGOING — Enable Budget Alerts")
    print(f"       GCP Console → Billing → Budgets & Alerts")
    print(f"       Set alert at 80% of current spend to catch overruns early\n")

    # ── Export CSV ────────────────────────────────────────────────────────────
    os.makedirs("reports", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    out = f"reports/deep_analysis_{ts}.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "VM Name","Zone","Machine Type","vCPUs","RAM GB","Status",
            "CPU Avg%","CPU Max%","CPU P95%","Mem Avg%",
            "Monthly Cost USD","Annual Cost USD",
            "Classification","Reason",
            "Best Suggested Type","Best Suggested $/mo","Saving $/mo","Saving %",
            "On-Demand Annual","SUD Annual","CUD 1yr Annual","CUD 3yr Annual","Spot Annual",
        ] + last10_months)
        for v in vms:
            b = v.get("best_option") or {}
            d = v.get("discounts") or {}
            w.writerow([
                v["name"], v["zone"], v["machine_type"], v["vcpus"], v["ram_gb"], v["status"],
                v["avg_cpu"], v["max_cpu"], v["p95_cpu"], v["avg_mem"],
                v["monthly_cost"], v["annual_cost"],
                v["classification"], v["reason"],
                b.get("machine_type",""), b.get("monthly_cost",""),
                b.get("saving_per_month",""), b.get("saving_pct",""),
                d.get("on_demand_annual",""), d.get("sud_annual",""),
                d.get("cud_1yr_annual",""), d.get("cud_3yr_annual",""), d.get("spot_annual",""),
            ] + [v["monthly_data"].get(m,"") for m in last10_months])

    div()
    print(f"  Report saved → {out}")
    print(f"{'═'*80}\n")


# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="GCP VM Deep Cost Analyzer")
    parser.add_argument("file", nargs="?", help="VM metrics file (CSV/Excel/JSON)")
    args = parser.parse_args()

    filepath = args.file
    if not filepath:
        candidates = [
            f for f in os.listdir(".")
            if f.lower().endswith((".csv",".json",".xlsx",".xls"))
            and not f.startswith(".")
            and "analysis_" not in f
        ]
        if len(candidates) == 1:
            filepath = candidates[0]
            print(f"  Auto-detected: {filepath}")
        elif len(candidates) > 1:
            print("Multiple files found — specify one:")
            for c in candidates:
                print(f"  python analyze_file.py {c}")
            sys.exit(1)
        else:
            print("No input file found.\nUsage: python analyze_file.py your-file.csv")
            sys.exit(1)

    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        sys.exit(1)

    raw = load_file(filepath)
    if not raw:
        print("File is empty or could not be parsed.")
        sys.exit(1)

    rows = map_columns(raw)
    analyze(rows)


if __name__ == "__main__":
    main()
