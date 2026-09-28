from fastapi import APIRouter, Request, Header, HTTPException, Depends
from app.services.mobile_money_service import MobileMoneyService
from app.db.deps import get_db
from app.core.crypto import verify_hmac
from app.core.config import settings

router = APIRouter()

@router.post("/webhooks/mobile-money/wave")
async def wave_webhook(
    request: Request,
    x_wave_signature: str = Header(...),
    db=Depends(get_db),
):
    raw = await request.body()
    if not verify_hmac(raw, x_wave_signature, settings.WAVE_WEBHOOK_SECRET):
        raise HTTPException(401, "Signature invalide")

    payload = await request.json()
    service = MobileMoneyService(db)
    return await service.ingerer("wave", payload)
