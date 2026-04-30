"""Static reference tables of common AWS values.

Used by the `infrapilot lookup` commands so users can paste valid values
into prompts without leaving the CLI.
"""

# (code, human-readable name)
REGIONS = [
    ("us-east-1",      "US East (N. Virginia)"),
    ("us-east-2",      "US East (Ohio)"),
    ("us-west-1",      "US West (N. California)"),
    ("us-west-2",      "US West (Oregon)"),
    ("ca-central-1",   "Canada (Central)"),
    ("sa-east-1",      "South America (São Paulo)"),
    ("eu-west-1",      "Europe (Ireland)"),
    ("eu-west-2",      "Europe (London)"),
    ("eu-west-3",      "Europe (Paris)"),
    ("eu-central-1",   "Europe (Frankfurt)"),
    ("eu-north-1",     "Europe (Stockholm)"),
    ("eu-south-1",     "Europe (Milan)"),
    ("ap-south-1",     "Asia Pacific (Mumbai)"),
    ("ap-northeast-1", "Asia Pacific (Tokyo)"),
    ("ap-northeast-2", "Asia Pacific (Seoul)"),
    ("ap-northeast-3", "Asia Pacific (Osaka)"),
    ("ap-southeast-1", "Asia Pacific (Singapore)"),
    ("ap-southeast-2", "Asia Pacific (Sydney)"),
    ("ap-east-1",      "Asia Pacific (Hong Kong)"),
    ("me-south-1",     "Middle East (Bahrain)"),
    ("af-south-1",     "Africa (Cape Town)"),
]


# Instance families with one-line summaries.
INSTANCE_FAMILIES = [
    ("t3",  "burstable general purpose (Intel)"),
    ("t3a", "burstable general purpose (AMD)"),
    ("t4g", "burstable general purpose (Graviton/ARM)"),
    ("m5",  "general purpose (Intel)"),
    ("m5a", "general purpose (AMD)"),
    ("m6i", "general purpose (Intel, current gen)"),
    ("m7g", "general purpose (Graviton3/ARM)"),
    ("c5",  "compute optimized (Intel)"),
    ("c6i", "compute optimized (Intel, current gen)"),
    ("c7g", "compute optimized (Graviton3/ARM)"),
    ("r5",  "memory optimized (Intel)"),
    ("r6i", "memory optimized (Intel, current gen)"),
    ("r7g", "memory optimized (Graviton3/ARM)"),
    ("i3",  "storage optimized (NVMe SSD)"),
    ("g4dn","GPU (NVIDIA T4)"),
    ("p4d", "GPU (NVIDIA A100)"),
]


# (code, vCPU/memory summary).  A small curated list — not exhaustive.
INSTANCE_TYPES = [
    # t3 burstable (Intel) — most common for small services
    ("t3.nano",     "2 vCPU / 0.5 GiB"),
    ("t3.micro",    "2 vCPU / 1 GiB"),
    ("t3.small",    "2 vCPU / 2 GiB"),
    ("t3.medium",   "2 vCPU / 4 GiB"),
    ("t3.large",    "2 vCPU / 8 GiB"),
    ("t3.xlarge",   "4 vCPU / 16 GiB"),
    ("t3.2xlarge",  "8 vCPU / 32 GiB"),
    # t4g (Graviton/ARM) — cheaper, ARM-based
    ("t4g.nano",    "2 vCPU / 0.5 GiB (ARM)"),
    ("t4g.micro",   "2 vCPU / 1 GiB (ARM)"),
    ("t4g.small",   "2 vCPU / 2 GiB (ARM)"),
    ("t4g.medium",  "2 vCPU / 4 GiB (ARM)"),
    ("t4g.large",   "2 vCPU / 8 GiB (ARM)"),
    # m5 general purpose
    ("m5.large",    "2 vCPU / 8 GiB"),
    ("m5.xlarge",   "4 vCPU / 16 GiB"),
    ("m5.2xlarge",  "8 vCPU / 32 GiB"),
    ("m5.4xlarge",  "16 vCPU / 64 GiB"),
    # m6i (current-gen general purpose)
    ("m6i.large",   "2 vCPU / 8 GiB"),
    ("m6i.xlarge",  "4 vCPU / 16 GiB"),
    ("m6i.2xlarge", "8 vCPU / 32 GiB"),
    # c5 compute optimized
    ("c5.large",    "2 vCPU / 4 GiB"),
    ("c5.xlarge",   "4 vCPU / 8 GiB"),
    ("c5.2xlarge",  "8 vCPU / 16 GiB"),
    ("c5.4xlarge",  "16 vCPU / 32 GiB"),
    # c6i (current-gen compute optimized)
    ("c6i.large",   "2 vCPU / 4 GiB"),
    ("c6i.xlarge",  "4 vCPU / 8 GiB"),
    ("c6i.2xlarge", "8 vCPU / 16 GiB"),
    # r5 memory optimized
    ("r5.large",    "2 vCPU / 16 GiB"),
    ("r5.xlarge",   "4 vCPU / 32 GiB"),
    ("r5.2xlarge",  "8 vCPU / 64 GiB"),
    # GPU
    ("g4dn.xlarge", "4 vCPU / 16 GiB / 1x NVIDIA T4"),
    ("p4d.24xlarge","96 vCPU / 1.1 TiB / 8x NVIDIA A100"),
]
