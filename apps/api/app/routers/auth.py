from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import User
from ..schemas import LoginRequest, LoginResponse
from ..security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/bootstrap-status")
def bootstrap_status(db: Session = Depends(get_db)):
    """
    Diagnóstico do primeiro acesso (sem expor senha).
    Útil quando o login falha após deploy no EasyPanel.
    """
    configured = bool(settings.bootstrap_superadmin_email and settings.bootstrap_superadmin_password)
    email = settings.bootstrap_superadmin_email
    superadmin_exists = False
    if email:
        superadmin_exists = (
            db.scalar(select(User).where(func.lower(User.email) == email)) is not None
        )
    return {
        "bootstrap_env_configured": configured,
        "bootstrap_email": email,
        "superadmin_exists_for_bootstrap_email": superadmin_exists,
        "bootstrap_sync_password_enabled": settings.bootstrap_superadmin_sync_password,
        "hint": (
            "Se bootstrap_env_configured é false, defina BOOTSTRAP_SUPERADMIN_EMAIL e "
            "BOOTSTRAP_SUPERADMIN_PASSWORD na API e reinicie. "
            "Se superadmin_exists é false, reinicie a API uma vez com essas variáveis. "
            "Se o usuário existe mas a senha não confere, defina BOOTSTRAP_SUPERADMIN_SYNC_PASSWORD=true, "
            "reinicie, faça login e depois volte SYNC para false."
        ),
    }


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email_norm = str(payload.email).strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email_norm))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciais inválidas")

    token = create_access_token(subject=user.email, role=user.role.value)
    return LoginResponse(access_token=token, role=user.role, name=user.name)
