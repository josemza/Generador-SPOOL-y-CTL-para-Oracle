# app/api/v1/router.py
from fastapi import APIRouter

from app.api.v1.spool import router as spool_router
from app.api.v1.ctl import router as ctl_router
from app.api.v1.fs import router as fs_router

api_router = APIRouter()
api_router.include_router(spool_router)
api_router.include_router(ctl_router)
api_router.include_router(fs_router)