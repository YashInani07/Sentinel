from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
import os
import time
import logging

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("collector-service")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/sentinel")

# Database setup with retry logic
max_retries = 10
engine = None
for i in range(max_retries):
    try:
        logger.info(f"Connecting to database (attempt {i+1}/{max_retries})...")
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        # Force a connection check
        with engine.connect() as conn:
            pass
        logger.info("Database connection established successfully.")
        break
    except Exception as e:
        logger.warning(f"Database connection failed: {e}")
        if i == max_retries - 1:
            logger.critical("Could not connect to the database. Exiting.")
            raise e
        time.sleep(3)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database Model
class LogModel(Base):
    __tablename__ = "logs"
    
    id = Column(Integer, primary_key=True, index=True)
    service_name = Column(String, index=True, nullable=False)
    level = Column(String, index=True, nullable=False)  # e.g., INFO, WARNING, ERROR
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), index=True, nullable=False, default=lambda: datetime.now(timezone.utc))

# Create tables
Base.metadata.create_all(bind=engine)

# Pydantic Schemas
class LogCreate(BaseModel):
    service_name: str = Field(..., min_length=1, max_length=100)
    level: str = Field(..., pattern="^(INFO|WARNING|ERROR)$")
    message: str = Field(..., min_length=1)
    timestamp: Optional[datetime] = None

class LogResponse(BaseModel):
    id: int
    service_name: str
    level: str
    message: str
    timestamp: datetime

    class Config:
        from_attributes = True

# FastAPI App initialization
app = FastAPI(title="Sentinel Log Collector Service")

# CORS middleware to allow dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/logs", response_model=LogResponse, status_code=201)
def create_log(log_in: LogCreate, db: Session = Depends(get_db)):
    db_log = LogModel(
        service_name=log_in.service_name,
        level=log_in.level.upper(),
        message=log_in.message,
        timestamp=log_in.timestamp or datetime.now(timezone.utc)
    )
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log

@app.get("/logs", response_model=List[LogResponse])
def get_logs(
    service_name: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db)
):
    query = db.query(LogModel)
    
    if service_name:
        query = query.filter(LogModel.service_name == service_name)
    if level:
        query = query.filter(LogModel.level == level.upper())
    if start_time:
        query = query.filter(LogModel.timestamp >= start_time)
    if end_time:
        query = query.filter(LogModel.timestamp <= end_time)
        
    # Get latest logs first
    query = query.order_by(LogModel.timestamp.desc())
    return query.limit(limit).all()

@app.get("/logs/error-counts")
def get_error_counts(
    window_seconds: int = Query(60, ge=1),
    db: Session = Depends(get_db)
):
    """
    Returns the count of ERROR logs per service within a sliding time window.
    
    ===========================================================================
    INTERVIEW EXPLANATION: SLIDING TIME-WINDOW ERROR COUNTING
    ===========================================================================
    1. Single Source of Truth & Stateless App Design:
       Instead of keeping complex sliding window states or ring buffers in the 
       FastAPI application RAM (which is fragile, consumes server memory, and 
       breaks when multiple backend replicas run behind a load balancer), we 
       leverage PostgreSQL as our single source of truth. The application remains 
       completely stateless.
       
    2. Dynamic Time Cutoff Calculation:
       Every time this endpoint is queried, we calculate a dynamic timestamp threshold:
           cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
       This timestamp represents the start of our sliding window.
       
    3. Optimized Database Query & Aggregation:
       We run an SQL query equivalent to:
           SELECT service_name, COUNT(*) 
           FROM logs 
           WHERE level = 'ERROR' AND timestamp >= :cutoff 
           GROUP BY service_name;
       This aggregates only matching logs within the dynamic sliding window.
       
    4. Database Indexing strategy:
       We created a B-Tree composite or single-column index on the table:
       - `level` (String)
       - `timestamp` (DateTime with Timezone)
       - `service_name` (String)
       This ensures the query doesn't perform a slow Sequential Table Scan (O(N_total)). 
       Instead, the database performs index scans, filtering down directly to matching 
       rows in O(N_window) time, which makes the sliding-window query extremely fast.
    ===========================================================================
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    
    query = (
        db.query(LogModel.service_name, func.count(LogModel.id).label("error_count"))
        .filter(LogModel.level == "ERROR")
        .filter(LogModel.timestamp >= cutoff)
        .group_by(LogModel.service_name)
    )
    
    results = query.all()
    
    # Return mapping of service_name to count
    # E.g. {"service_a": 12, "service_b": 2}
    return {row.service_name: row.error_count for row in results}

@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "collector-service"}
