from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import httpx
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("alert-service")

COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://collector-service:8000")
ALERT_THRESHOLD = int(os.getenv("ALERT_THRESHOLD", "5"))
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "10"))
WINDOW_SECONDS = int(os.getenv("WINDOW_SECONDS", "60"))

logger.info(f"Alert service initialized: COLLECTOR_URL={COLLECTOR_URL}, THRESHOLD={ALERT_THRESHOLD}, POLL_INTERVAL={POLL_INTERVAL}s")

# In-memory alert store
alerts: List[Dict[str, Any]] = []
alert_id_counter = 1

# Deduplication state: service_name -> {"count": int, "timestamp": datetime}
last_alerted: Dict[str, Dict[str, Any]] = {}

async def check_alerts():
    global alert_id_counter, alerts, last_alerted
    
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            url = f"{COLLECTOR_URL}/logs/error-counts?window_seconds={WINDOW_SECONDS}"
            response = await client.get(url)
            if response.status_code != 200:
                logger.error(f"Error fetching error counts: Status {response.status_code}")
                return
            
            error_counts = response.json()
            current_time = datetime.now(timezone.utc)
            
            # Keep track of active services in this poll
            polled_services = set(error_counts.keys())
            
            def get_severity_tier(err_count: int) -> int:
                if err_count > 100:
                    return 4  # Disaster
                if err_count > 50:
                    return 3  # Critical
                if err_count > 20:
                    return 2  # High
                if err_count > 5:
                    return 1  # Warning
                return 0

            # Evaluate threshold for all services returned
            for service_name, count in error_counts.items():
                if count > ALERT_THRESHOLD:
                    should_alert = False
                    current_tier = get_severity_tier(count)
                    
                    if service_name not in last_alerted:
                        # First time seeing this service exceed threshold
                        should_alert = True
                    else:
                        prev_state = last_alerted[service_name]
                        prev_tier = prev_state.get("tier", 1)
                        time_since_last_alert = current_time - prev_state["timestamp"]
                        
                        # Alert immediately if we cross into a higher severity tier
                        if current_tier > prev_tier:
                            logger.info(f"Severity tier escalated for {service_name}: Tier {prev_tier} -> Tier {current_tier}. Bypassing cooldown.")
                            should_alert = True
                        # Otherwise, respect the 30-second cooldown and alert only if count changed
                        elif time_since_last_alert >= timedelta(seconds=30):
                            if count != prev_state["count"]:
                                should_alert = True
                    
                    if should_alert:
                        new_alert = {
                            "id": alert_id_counter,
                            "service_name": service_name,
                            "error_count": count,
                            "threshold": ALERT_THRESHOLD,
                            "severity_tier": current_tier,
                            "timestamp": current_time.isoformat(),
                            "message": f"Service '{service_name}' has generated {count} errors in the last {WINDOW_SECONDS} seconds."
                        }
                        alert_id_counter += 1
                        
                        # Keep memory bounded: retain last 200 alerts
                        alerts.insert(0, new_alert)
                        if len(alerts) > 200:
                            alerts = alerts[:200]
                            
                        logger.warning(f"ALERT FIRED: {new_alert['message']}")
                        
                        # Update deduplication state
                        last_alerted[service_name] = {
                            "count": count,
                            "timestamp": current_time,
                            "tier": current_tier
                        }
                    else:
                        # Even if we don't fire an alert notification, we keep the underlying
                        # error count updated in our state as requested
                        last_alerted[service_name]["count"] = count
                else:
                    # Service is below threshold, reset its alert history if it exists
                    # This ensures that if the count drops and spikes again to the same value, it alerts.
                    if service_name in last_alerted:
                        logger.info(f"Service '{service_name}' error count dropped below threshold ({count} <= {ALERT_THRESHOLD}). Resetting alert state.")
                        del last_alerted[service_name]
            
            # Clean up old last_alerted entries for services not seen in the current window
            # (which means they have 0 errors and are thus below threshold)
            for service_name in list(last_alerted.keys()):
                if service_name not in polled_services:
                    logger.info(f"Service '{service_name}' has no active errors. Resetting alert state.")
                    del last_alerted[service_name]
                    
        except httpx.RequestError as e:
            logger.warning(f"Failed to connect to collector service at {COLLECTOR_URL}: {e}")
        except Exception as e:
            logger.error(f"Error in alert check job: {e}", exc_info=True)

async def alert_polling_loop():
    logger.info("Alert polling loop started.")
    while True:
        try:
            await check_alerts()
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            logger.info("Alert polling loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Alert polling loop encountered error: {e}")
            await asyncio.sleep(POLL_INTERVAL)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the background task
    bg_task = asyncio.create_task(alert_polling_loop())
    yield
    # Cleanup background task
    bg_task.cancel()
    try:
        await bg_task
    except asyncio.CancelledError:
        pass

app = FastAPI(title="Sentinel Alerting Service", lifespan=lifespan)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/alerts")
def get_alerts():
    return alerts

@app.post("/alerts/clear")
def clear_alerts():
    global alerts, last_alerted
    alerts.clear()
    last_alerted.clear()
    logger.info("Alert store and deduplication state cleared manually.")
    return {"status": "cleared"}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "alert-service"}
