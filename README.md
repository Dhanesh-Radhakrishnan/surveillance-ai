# Local AI Privacy-First Video Surveillance Analytics

All inference runs locally on RTX 3050 (4GB VRAM).

## Architecture
Two-stage inference pipeline:
- **Stage 1 (lightweight trigger):** OpenCV + YOLO11n on CPU → Redis queue
- **Stage 2 (async AI analysis):** moondream2 via Ollama → PostgreSQL → WebSocket

## Hardware
| Machine | Role |
|---|---|
| Ryzen 5 6600H + RTX 3050 | Backend, AI worker, Ollama, DB |
| i5 14th gen (LAN) | React frontend / reserve camera node |
| i3 7th gen (LAN, reserve) | Multi-node capable |

