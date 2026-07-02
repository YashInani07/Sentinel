from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import httpx
import os
import random
import logging
from datetime import datetime, timezone

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("producer")

SERVICE_NAME = os.getenv("SERVICE_NAME", "producer-default")
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://collector-service:8000")

logger.info(f"Starting producer: {SERVICE_NAME} targeting collector: {COLLECTOR_URL}")

# State variables
spamming_errors = False
client = None

# Simulated messages
INFO_MSGS = [
    "Database connection pool initialized.",
    "User session validated successfully.",
    "Cache hit for key 'session_token:user_4823'.",
    "API request received: GET /v1/products.",
    "File uploaded to S3 bucket 'user-backups'.",
    "Heartbeat sent to main registry."
]

WARN_MSGS = [
    "Database connection taking longer than average (200ms).",
    "API rate limit approaching 80% capacity for user_12.",
    "Disk storage usage exceeds 75% on /data.",
    "Unusual request pattern detected from IP 10.0.2.15.",
    "Retry attempt 1 for email notification service."
]

ERROR_MSGS = [
    "Database connection failure: timeout occurred after 5000ms.",
    "Payment processing failed: insufficient funds response from stripe.",
    "Out of memory exception during image processing.",
    "Null pointer in auth middleware for key validation.",
    "Failed to bind to port 8080: Address already in use."
]

async def send_log(level: str, message: str):
    global client
    if client is None:
        return
    
    payload = {
        "service_name": SERVICE_NAME,
        "level": level,
        "message": message,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        response = await client.post("/logs", json=payload)
        if response.status_code == 201:
            logger.debug(f"Successfully sent log: [{level}] {message}")
        else:
            logger.error(f"Failed to send log. Status code: {response.status_code}, response: {response.text}")
    except httpx.RequestError as e:
        logger.warning(f"Failed to connect to collector: {e}")

async def log_generator_loop():
    logger.info("Log generator loop started.")
    while True:
        try:
            if spamming_errors:
                # Spam errors rapidly: every 0.2 seconds
                msg = random.choice(ERROR_MSGS)
                await send_log("ERROR", f"[SPAM] {msg}")
                await asyncio.sleep(0.2)
            else:
                # Normal log generation: every 3 seconds
                # Distribution: 70% INFO, 20% WARNING, 10% ERROR
                roll = random.random()
                if roll < 0.70:
                    level = "INFO"
                    msg = random.choice(INFO_MSGS)
                elif roll < 0.90:
                    level = "WARNING"
                    msg = random.choice(WARN_MSGS)
                else:
                    level = "ERROR"
                    msg = random.choice(ERROR_MSGS)
                
                await send_log(level, msg)
                await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            logger.info("Log generator loop task cancelled.")
            break
        except Exception as e:
            logger.error(f"Error in log generator loop: {e}")
            await asyncio.sleep(1.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    # Initialize HTTPX AsyncClient
    client = httpx.AsyncClient(base_url=COLLECTOR_URL, timeout=5.0)
    # Start background task
    bg_task = asyncio.create_task(log_generator_loop())
    yield
    # Shutdown
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass
    await client.aclose()

app = FastAPI(title=f"Sentinel Producer - {SERVICE_NAME}", lifespan=lifespan)

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/spam-errors/start")
def start_spam():
    global spamming_errors
    spamming_errors = True
    logger.info("Started spamming errors.")
    return {"status": "started", "service_name": SERVICE_NAME, "spamming": True}

@app.post("/spam-errors/stop")
def stop_spam():
    global spamming_errors
    spamming_errors = False
    logger.info("Stopped spamming errors.")
    return {"status": "stopped", "service_name": SERVICE_NAME, "spamming": False}

@app.get("/status")
def get_status():
    return {
        "service_name": SERVICE_NAME,
        "collector_url": COLLECTOR_URL,
        "spamming_errors": spamming_errors
    }
