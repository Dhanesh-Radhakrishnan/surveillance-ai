import asyncio
import logging
import asyncpg
import redis.asyncio as aioredis
from ollama import AsyncClient

# --- CONFIGURATION (Adjust to your infrastructure) ---
POSTGRES_HOST = "localhost"
POSTGRES_PORT = 5432
POSTGRES_USER = "surveillance"
POSTGRES_PASSWORD = "2@2serveillance"   # Special chars safe here — no URL encoding needed
POSTGRES_DB = "surveillance_db"

REDIS_URL = "redis://localhost:6379/0"
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "moondream:latest"          # Run `ollama list` to confirm exact name

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Surveillance_Check")


async def test_postgres():
    """Verify Postgres connection and read version."""
    try:
        logger.info("Connecting to PostgreSQL...")
        conn = await asyncpg.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            database=POSTGRES_DB,
        )
        version = await conn.fetchval("SELECT version();")
        await conn.close()
        # FIX: logger.info() takes a string, not a bool as first argument
        logger.info(f"PostgreSQL connected. Version: {version[:60]}...")
        return "PostgreSQL", True
    except Exception as e:
        logger.error(f"PostgreSQL connection failed: {e}")
        return "PostgreSQL", False


async def test_redis():
    """Verify Redis connection by setting and getting a test key."""
    try:
        logger.info("Connecting to Redis...")
        r = aioredis.from_url(REDIS_URL, socket_timeout=5.0)
        await r.set("surveillance_health_test", "active", ex=10)
        value = await r.get("surveillance_health_test")
        await r.aclose()

        if value and value.decode("utf-8") == "active":
            logger.info("Redis connected. Read/write successful.")
            return "Redis", True
        raise ValueError("Redis data mismatch — possible corruption.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        return "Redis", False


async def test_ollama():
    """Verify Ollama VLM connection by sending a dummy frame to moondream2."""
    try:
        logger.info(f"Connecting to Ollama at {OLLAMA_HOST}...")
        client = AsyncClient(host=OLLAMA_HOST)

        # Minimal valid 1x1 black pixel JPEG (base64) — simulates a surveillance snapshot
        dummy_jpeg_b64 = (
            b"/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////"
            b"////////////////////////////////////////////////////////////"
            b"wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
        )

        logger.info(f"Sending dummy frame to {OLLAMA_MODEL}...")
        response = await client.generate(
            model=OLLAMA_MODEL,
            prompt="Describe this image in one word.",
        images=[dummy_jpeg_b64.decode("utf-8")],
        )

        # FIX: ollama Python library returns a typed object, not a dict — use attribute access
        reply = response.response.strip()
        logger.info(f"Ollama/moondream2 connected. Vision response: '{reply}'")
        return "Ollama (moondream2)", True

    except Exception as e:
        logger.error(f"Ollama/moondream2 connection failed: {e}")
        logger.error("Tip: run  `ollama pull moondream2`  then  `ollama serve`  before testing.")
        return "Ollama (moondream2)", False


async def main():
    logger.info("Starting simultaneous backend service validation...")

    results = await asyncio.gather(
        test_postgres(),
        test_redis(),
        test_ollama(),
        return_exceptions=False,
    )

    print("\n" + "=" * 42)
    print("         HEALTH CHECK SUMMARY")
    print("=" * 42)
    all_passed = True
    for service, status in results:
        status_str = "PASSED" if status else "FAILED"
        print(f"  {service:<22} : {status_str}")
        if not status:
            all_passed = False
    print("=" * 42)

    if all_passed:
        print("  All systems go. Ready for Week 2.")
    else:
        print("  One or more services failed. Check logs above.")
    print()


if __name__ == "__main__":
    asyncio.run(main())