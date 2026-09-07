"""Service configuration values, carried forward verbatim from
Low-Level Design Section 3 — do not change without updating that
document first. Each value traces to a real, live-verified finding in
the singleSlide_demo proof of concept; see LLD Section 3 for the source
of each one.
"""

# Synthesis/Critique revision cap. Tied to the proof of concept's cost
# model — changing this silently invalidates that math.
MAX_REVISIONS = 1

# Feature Investigation turn budget. 5 was the original estimate; 6
# accounts for a mandatory tool-discovery step found only through live
# debugging in the proof of concept.
MAX_TURNS = 6

# Model call isolation flags, mandatory on every agentic call. This is
# the exact fix for a real, confirmed 10x cost anomaly found in the
# proof of concept's own observability trace — not optional, and not a
# per-call decision left to individual services.
AGENT_CALL_ISOLATION = {
    "setting_sources": [],
    "skills": [],
    "strict_mcp_config": True,
}

# On-demand trigger rate limit: 2 per Portfolio Lead per day, enforced
# at the API Gateway (Apigee), not application code. Recorded here for
# traceability only.
ON_DEMAND_RATE_LIMIT_PER_LEAD_PER_DAY = 2

# Minimum replica count per core service, spread across availability
# zones. A Kubernetes/Helm deployment concern, not application code;
# recorded here for traceability only.
MIN_SERVICE_REPLICAS = 3

# Content safety check is mandatory after Quality Assurance and before
# any content reaches Human Governance. There is no configuration flag
# to disable it — closing the confirmed gap that Foundry does not apply
# automatic content filtering to Claude models (NFR-8).
CONTENT_SAFETY_CHECK_MANDATORY = True
