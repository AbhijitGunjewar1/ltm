"""
Cloud Cost Optimizer – Configuration
Project: gcpopenshift
"""

import os
from datetime import datetime, timezone, timedelta

# ── GCP Project ──────────────────────────────────────────────────────────────
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "gcpopenshift")

# Path to service-account JSON key (set env var or place file in credentials/)
CREDENTIALS_PATH = os.getenv(
    "GOOGLE_APPLICATION_CREDENTIALS",
    os.path.join(os.path.dirname(__file__), "credentials", "service-account.json"),
)

# ── Analysis window ───────────────────────────────────────────────────────────
MONTHS_BACK = 10          # how many months of history to pull
ANALYSIS_END   = datetime.now(timezone.utc)
ANALYSIS_START = ANALYSIS_END - timedelta(days=MONTHS_BACK * 30)

# Cloud Monitoring sample alignment period (seconds) – 1 day
ALIGNMENT_PERIOD_SECONDS = 86400

# ── Rightsizing thresholds ────────────────────────────────────────────────────
CPU_LOW_THRESHOLD    = 20.0   # avg CPU % below this → likely over-provisioned
CPU_HIGH_THRESHOLD   = 80.0   # avg CPU % above this → under-provisioned
MEMORY_LOW_THRESHOLD = 40.0   # avg memory % below this → likely over-provisioned
IDLE_CPU_THRESHOLD   = 5.0    # avg CPU % below this → consider shutdown

# ── GCE machine type families (price per vCPU-hour, USD, us-central1) ─────────
# Source: Google Cloud pricing (approximate, for relative comparison)
MACHINE_TYPE_PRICES = {
    "n1-standard":  {"vcpu": 0.0475, "ram_gb": 0.0066},
    "n1-highmem":   {"vcpu": 0.0475, "ram_gb": 0.0066},
    "n1-highcpu":   {"vcpu": 0.0475, "ram_gb": 0.0066},
    "n2-standard":  {"vcpu": 0.0334, "ram_gb": 0.0045},
    "n2-highmem":   {"vcpu": 0.0334, "ram_gb": 0.0045},
    "n2-highcpu":   {"vcpu": 0.0334, "ram_gb": 0.0045},
    "e2-standard":  {"vcpu": 0.0210, "ram_gb": 0.0028},
    "e2-highmem":   {"vcpu": 0.0210, "ram_gb": 0.0028},
    "e2-highcpu":   {"vcpu": 0.0210, "ram_gb": 0.0028},
    "n2d-standard": {"vcpu": 0.0284, "ram_gb": 0.0038},
    "c2-standard":  {"vcpu": 0.0522, "ram_gb": 0.0070},
    "m1-ultramem":  {"vcpu": 0.1428, "ram_gb": 0.0098},
    "default":      {"vcpu": 0.0334, "ram_gb": 0.0045},
}

# Machine-type catalog: common types → (vCPUs, RAM GB)
MACHINE_CATALOG = {
    "n1-standard-1":  (1, 3.75),   "n1-standard-2":  (2, 7.5),
    "n1-standard-4":  (4, 15),     "n1-standard-8":  (8, 30),
    "n1-standard-16": (16, 60),    "n1-standard-32": (32, 120),
    "n1-standard-64": (64, 240),
    "n1-highmem-2":   (2, 13),     "n1-highmem-4":   (4, 26),
    "n1-highmem-8":   (8, 52),     "n1-highmem-16":  (16, 104),
    "n1-highcpu-4":   (4, 3.6),    "n1-highcpu-8":   (8, 7.2),
    "n1-highcpu-16":  (16, 14.4),  "n1-highcpu-32":  (32, 28.8),
    "n2-standard-2":  (2, 8),      "n2-standard-4":  (4, 16),
    "n2-standard-8":  (8, 32),     "n2-standard-16": (16, 64),
    "n2-standard-32": (32, 128),   "n2-standard-48": (48, 192),
    "n2-highmem-2":   (2, 16),     "n2-highmem-4":   (4, 32),
    "n2-highmem-8":   (8, 64),     "n2-highmem-16":  (16, 128),
    "n2-highcpu-4":   (4, 4),      "n2-highcpu-8":   (8, 8),
    "n2-highcpu-16":  (16, 16),    "n2-highcpu-32":  (32, 32),
    "e2-standard-2":  (2, 8),      "e2-standard-4":  (4, 16),
    "e2-standard-8":  (8, 32),     "e2-standard-16": (16, 64),
    "e2-highmem-2":   (2, 16),     "e2-highmem-4":   (4, 32),
    "e2-highmem-8":   (8, 64),     "e2-highmem-16":  (16, 128),
    "e2-highcpu-4":   (4, 4),      "e2-highcpu-8":   (8, 8),
    "e2-highcpu-16":  (16, 16),    "e2-highcpu-32":  (32, 32),
    "e2-micro":       (2, 1),      "e2-small":       (2, 2),
    "e2-medium":      (2, 4),
    "n2d-standard-2": (2, 8),      "n2d-standard-4": (4, 16),
    "n2d-standard-8": (8, 32),     "n2d-standard-16":(16, 64),
    "c2-standard-4":  (4, 16),     "c2-standard-8":  (8, 32),
    "c2-standard-16": (16, 64),    "c2-standard-30": (30, 120),
    "c2-standard-60": (60, 240),
}

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")
