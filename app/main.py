from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import balance_insights, bank_debt, health, lender_match, overview, profit_loss, underwriting
from app.config import settings
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.debug)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(overview.router)
app.include_router(bank_debt.router)
app.include_router(balance_insights.router)
app.include_router(profit_loss.router)
app.include_router(lender_match.router)
app.include_router(underwriting.router)
