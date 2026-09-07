"""
backend/constants.py
Week 4 — Task 6/7: shared, framework-agnostic constants used across
process boundaries (FastAPI app process AND the standalone ai-worker process).

Single responsibility: hold values that both sides of a process boundary
need to agree on, with zero framework imports.
"""

# Redis pub/sub channel used for live WebSocket event broadcast.
# Publishers: ai-worker/ollama_worker.py (after a successful DB write, W4T6)
# Subscribers: backend/api/routes/ws_events.py (relays to connected clients)
EVENTS_CHANNEL: str = "surveillance:events:broadcast"

# Redis list key used for the Stage 1 → Stage 2 detection event queue.
# Publishers: ai-worker/redis_publisher.py (RPUSH, W2T5)
# Consumers: ai-worker/ollama_worker.py (BLPOP, W3T3)
# Read-only inspector: backend/services/health.py (LLEN, W4T7)
#
# NOTE — known duplication: ai-worker/config.py independently defines
# REDIS_QUEUE_KEY = "surveillance:detection_events" as its own constant,
# since config.py predates this shared-constants module (W2) and the
# worker's LLEN-consuming code never previously needed to cross the
# backend/ boundary. Both values must stay in sync manually for now.
# Flagging for a W6 polish-pass cleanup rather than touching config.py
# here — out of scope for W4T7.
REDIS_QUEUE_KEY: str = "surveillance:detection_events"