"""Trading readiness API routes."""
from fastapi import APIRouter, Depends
from bahamut.auth.router import get_current_user

router = APIRouter()


@router.get("/check")
async def run_check(user=Depends(get_current_user)):
    """Run the 12-point trading readiness checklist."""
    from bahamut.readiness.checklist import run_readiness_check
    return run_readiness_check().to_dict()


@router.get("/health")
async def health():
    return {"status": "healthy", "service": "readiness-svc"}
