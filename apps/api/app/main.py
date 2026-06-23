from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from .config import settings
from .db import Base, SessionLocal, engine
from .models import User, UserRole
from .routers.auth import router as auth_router
from .routers.geo import router as geo_router
from .routers.cras import router as cras_router
from .routers.creas import router as creas_router
from .routers.sisc import router as sisc_router
from .routers.ingestion import router as ingestion_router
from .routers.users import router as users_router
from .routers.vigilance import router as vigilance_router
from .routers.assist import router as assist_router
from .routers.municipio import router as municipio_router
from .routers.caracterizacao import router as caracterizacao_router
from .routers.rma import router as rma_router
from .security import hash_password

app = FastAPI(title="VigSocial API", version="0.1.0")


def _cors_allow_origins() -> list[str]:
    raw = settings.cors_origins.strip()
    if raw == "*":
        return ["*"]
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def bootstrap_superadmin() -> None:
    if not settings.bootstrap_superadmin_email or not settings.bootstrap_superadmin_password:
        return

    email = settings.bootstrap_superadmin_email

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(func.lower(User.email) == email))
        if existing:
            if settings.bootstrap_superadmin_sync_password:
                existing.email = email
                existing.password_hash = hash_password(settings.bootstrap_superadmin_password)
                existing.role = UserRole.SUPERADMIN
                if settings.bootstrap_superadmin_name:
                    existing.name = settings.bootstrap_superadmin_name
                db.commit()
            return

        user = User(
            name=settings.bootstrap_superadmin_name,
            email=email,
            password_hash=hash_password(settings.bootstrap_superadmin_password),
            role=UserRole.SUPERADMIN,
        )
        db.add(user)
        db.commit()


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    bootstrap_superadmin()


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api/v1")
app.include_router(users_router, prefix="/api/v1")
app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(vigilance_router, prefix="/api/v1")
app.include_router(geo_router, prefix="/api/v1")
app.include_router(sisc_router, prefix="/api/v1")
app.include_router(cras_router, prefix="/api/v1")
app.include_router(creas_router, prefix="/api/v1")
app.include_router(assist_router, prefix="/api/v1")
app.include_router(municipio_router, prefix="/api/v1")
app.include_router(caracterizacao_router, prefix="/api/v1")
app.include_router(rma_router, prefix="/api/v1")
