"""
api.py
Production-grade REST API layer for the Website Automation Agent.
Provides async endpoints, health checks, and metrics for production deployment.
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

import agent
import config

# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
TASK_COUNT = Counter(
    "agent_tasks_total",
    "Total number of tasks processed",
    ["status", "provider"]
)
TASK_DURATION = Histogram(
    "agent_task_duration_seconds",
    "Time spent processing tasks",
    ["provider"]
)
BROWSER_OPERATIONS = Counter(
    "browser_operations_total",
    "Total browser operations",
    ["operation", "status"]
)

# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------
class TaskRequest(BaseModel):
    """Request model for running a task."""
    goal: str = Field(..., min_length=1, max_length=1000, description="Plain English task description")
    headless: Optional[bool] = Field(default=None, description="Override headless mode")


class TaskResponse(BaseModel):
    """Response model for task execution."""
    task_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    browser_connected: bool
    config_valid: bool


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logging.info("API server starting up")
    yield
    # Shutdown
    logging.info("API server shutting down")
    try:
        import browser_tools as bt
        bt.close_browser()
    except Exception:
        pass


app = FastAPI(
    title="Website Automation Agent API",
    version="1.0.0",
    lifespan=lifespan
)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to all requests for tracing."""
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for load balancers and monitoring."""
    import browser_tools as bt
    
    browser_connected = False
    try:
        if bt._browser is not None:
            browser_connected = bt._browser.is_connected()
    except Exception:
        pass
    
    return HealthResponse(
        status="healthy" if browser_connected else "degraded",
        browser_connected=browser_connected,
        config_valid=True
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@app.post("/tasks", response_model=TaskResponse)
async def run_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """Run a single task and return the result."""
    task_id = str(uuid.uuid4())
    
    try:
        # Build agent
        agt = agent.build_agent()
        
        # Run task with metrics
        with TASK_DURATION.labels(provider=config.config.llm.provider).time():
            result = await agent.run_task(agt, request.goal)
        
        TASK_COUNT.labels(status="success", provider=config.config.llm.provider).inc()
        
        return TaskResponse(
            task_id=task_id,
            status="completed",
            result=result
        )
    except Exception as e:
        TASK_COUNT.labels(status="error", provider=config.config.llm.provider).inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/browser/open")
async def open_browser_endpoint(headless: Optional[bool] = None):
    """Open the browser explicitly."""
    import browser_tools as bt
    
    try:
        result = bt.open_browser(headless=headless if headless is not None else config.HEADLESS)
        BROWSER_OPERATIONS.labels(operation="open", status="success").inc()
        return result
    except Exception as e:
        BROWSER_OPERATIONS.labels(operation="open", status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/browser/close")
async def close_browser_endpoint():
    """Close the browser explicitly."""
    import browser_tools as bt
    
    try:
        result = bt.close_browser()
        BROWSER_OPERATIONS.labels(operation="close", status="success").inc()
        return result
    except Exception as e:
        BROWSER_OPERATIONS.labels(operation="close", status="error").inc()
        raise HTTPException(status_code=500, detail=str(e))


# Need to import Response for metrics endpoint
from starlette.responses import Response