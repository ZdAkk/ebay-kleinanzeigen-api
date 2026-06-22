from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from routers import (
    inserate_ultra as inserate,
    inserat,
    inserate_detailed_ultra as inserate_detailed,
    inserate_batch,
    convert_url,
    inserate_by_url,
)
from utils.browser import OptimizedPlaywrightManager
from utils.asyncio_optimizations import EventLoopOptimizer
from utils.auth import verify_token

# Global browser manager instance for sharing across all endpoints
browser_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - startup and shutdown events"""
    global browser_manager

    # Setup uvloop for maximum performance (2-4x improvement)
    uvloop_enabled = EventLoopOptimizer.setup_uvloop()

    # Optimize event loop settings
    EventLoopOptimizer.optimize_event_loop()

    # Startup: Initialize shared browser manager with optimized settings
    browser_manager = OptimizedPlaywrightManager(max_contexts=20, max_concurrent=10)
    await browser_manager.start()

    # Store browser manager in app state for access by routers
    app.state.browser_manager = browser_manager
    app.state.uvloop_enabled = uvloop_enabled

    yield

    # Shutdown: Clean up browser resources
    if browser_manager:
        await browser_manager.close()


app = FastAPI(version="1.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {
        "message": "Welcome to the Kleinanzeigen API",
        "endpoints": ["/inserate", "/inserat/{id}", "/inserate-detailed"],
        "status": "operational",
        "authentication": "All data endpoints require an 'x-token' header",
    }


# All data routers require x-token header authentication
app.include_router(inserate.router, dependencies=[Depends(verify_token)])
app.include_router(inserat.router, dependencies=[Depends(verify_token)])
app.include_router(inserate_detailed.router, dependencies=[Depends(verify_token)])
app.include_router(inserate_batch.router, dependencies=[Depends(verify_token)])
app.include_router(convert_url.router, dependencies=[Depends(verify_token)])
app.include_router(inserate_by_url.router, dependencies=[Depends(verify_token)])
