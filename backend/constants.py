"""
backend/constants.py
Week 4 — Task 6 refactor: shared, framework-agnostic constants used across
process boundaries (FastAPI app process AND the standalone ai-worker process).

Single responsibility: hold values that both sides of a process boundary
need to agree on, with zero framework imports. This file must NEVER import
fastapi, sqlalchemy, redis, or anything else — its only job is to be safely
importable from a bare Python process that doesn't have those frameworks
wired up the same way.

WHY this exists (vs. defining EVENTS_CHANNEL in ws_events.py):
  ws_events.py imports fastapi (APIRouter, WebSocket, WebSocketDisconnect).
  ollama_worker.py is a plain asyncio script with no FastAPI app — it should
  never need `import fastapi` transitively just to read one channel name
  string. Splitting this out means the worker's dependency graph stays
  exactly what its docstring already claims: Redis + Ollama, nothing else.
"""

# Redis pub/sub channel used for live WebSocket event broadcast.
# Publishers: ai-worker/ollama_worker.py (after a successful DB write, W4T6)
# Subscribers: backend/api/routes/ws_events.py (relays to connected clients)
EVENTS_CHANNEL: str = "surveillance:events:broadcast"