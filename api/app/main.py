from fastapi import FastAPI

from app.routes import health, trace

# All routes live under /api so nginx (prod) and Vite (dev) proxy the path through unchanged.
app = FastAPI(title="KoLife API", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.include_router(health.router, prefix="/api")
app.include_router(trace.router, prefix="/api")
