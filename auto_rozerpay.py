# ============================================================
#   AUTO ROZERPAY CHECKER - FastAPI Web Service
#   Endpoints: /rz (GET & POST), /check, /mass-check, /health
#   Created by @MUMIRU_BRO
#   Free script — do NOT sell or claim as your own.
#   Telegram: @MUMIRU_BRO
# ============================================================

import os
import json
import time
from datetime import datetime
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

# Import the checker engine
from checker_engine import (
    REQUESTS_PROXY, PLAYWRIGHT_PROXY, setup_proxy,
    extract_merchant_data, get_dynamic_session_token,
    process_card, generate_device_fingerprint
)

# ============================================================
# App Initialization
# ============================================================
app = FastAPI(
    title="Auto Rozerpay Checker API",
    description="Check credit cards against Razorpay payment gateways. Main endpoint: /rz",
    version="2.1",
    docs_url="/docs",
    redoc_url="/redoc"
)

# ============================================================
# Global state (cached session token & merchant data)
# ============================================================
class GatewayCache:
    def __init__(self):
        self.site_url: str = ""
        self.kh: str = ""
        self.kid: str = ""
        self.plid: str = ""
        self.ppiid: str = ""
        self.amount_paise: int = 100
        self.stoken: str = ""
        self.token_uses: int = 0
        self.last_setup: float = 0
        self.setup_expiry: float = 300  # seconds before refreshing token

    def is_valid(self) -> bool:
        """Check if cached data is still usable."""
        return (self.kh and self.kid and self.plid and self.ppiid 
                and self.stoken and time.time() - self.last_setup < self.setup_expiry)

    def refresh_token(self) -> bool:
        """Refresh only the session token."""
        token, err = get_dynamic_session_token()
        if token:
            self.stoken = token
            self.token_uses = 0
            self.last_setup = time.time()
            return True
        return False

    def setup_gateway(self, site_url: str, amount_rupees: int = 1, proxy_string: str = "") -> Optional[str]:
        """Full setup: extract merchant data + get session token."""
        global REQUESTS_PROXY, PLAYWRIGHT_PROXY

        # Handle proxy
        if proxy_string:
            req_proxy, pw_proxy = setup_proxy(proxy_string)
            if req_proxy:
                REQUESTS_PROXY = req_proxy
                PLAYWRIGHT_PROXY = pw_proxy
            else:
                REQUESTS_PROXY = None
                PLAYWRIGHT_PROXY = None

        # Extract merchant data
        kh, kid, plid, ppiid, err = extract_merchant_data(site_url)
        if err:
            return f"Failed to extract merchant data: {err}"

        # Get session token
        stoken, err = get_dynamic_session_token()
        if err:
            return f"Failed to get session token: {err}"

        # Cache everything
        self.site_url = site_url
        self.kh = kh
        self.kid = kid
        self.plid = plid
        self.ppiid = ppiid
        self.amount_paise = amount_rupees * 100
        self.stoken = stoken
        self.token_uses = 0
        self.last_setup = time.time()

        return None  # No error

gateway = GatewayCache()

# ============================================================
# Pydantic Models
# ============================================================
class SingleCheckRequest(BaseModel):
    cc: str  # card|mm|yy|cvv
    site_url: Optional[str] = None
    amount: Optional[int] = 1
    proxy: Optional[str] = None

class MassCheckRequest(BaseModel):
    cards: List[str]  # list of "card|mm|yy|cvv"
    site_url: Optional[str] = None
    amount: Optional[int] = 1
    proxy: Optional[str] = None

class CheckResponse(BaseModel):
    status: str
    tag: str
    message: str
    elapsed: float
    masked_card: str
    payment_id: Optional[str] = None
    full_response: dict
    timestamp: str

class MassCheckResponse(BaseModel):
    total: int
    charged: int
    live: int
    declined: int
    errors: int
    results: List[CheckResponse]

# ============================================================
# Helper functions
# ============================================================
def mask_card(cc: str) -> str:
    """Mask card number for security."""
    parts = cc.strip().split('|')
    if len(parts) >= 1 and len(parts[0]) > 10:
        return f"{parts[0][:6]}****{parts[0][-4:]}"
    return cc[:10] + "****"

# ============================================================
# Routes
# ============================================================
@app.get("/", include_in_schema=False)
async def root():
    """Root redirect to docs."""
    return {
        "service": "Auto Rozerpay Checker API",
        "version": "2.1",
        "docs": "/docs",
        "main_endpoint": "/rz?cc=card|mm|yy|cvv",
        "endpoints": {
            "single_check_GET": "/rz?cc=card|mm|yy|cvv",
            "single_check_POST": "/rz (JSON body)",
            "mass_check": "/mass-check (JSON body)",
            "health": "/health"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "gateway_ready": gateway.is_valid(),
        "timestamp": datetime.now().isoformat()
    }

# ============================================================
# PRIMARY ENDPOINT: /rz  (GET & POST)
# ============================================================
@app.get("/rz", response_model=CheckResponse)
async def rz_get(
    cc: str = Query(..., description="Card in format: card|mm|yy|cvv"),
    site_url: Optional[str] = Query(None, description="Razorpay payment page URL"),
    amount: Optional[int] = Query(1, description="Amount in Rupees"),
    proxy: Optional[str] = Query(None, description="Proxy in format: ip:port:user:pass")
):
    """
    Check a single card via GET request.
    
    Example:
        /rz?cc=4111111111111111|12|28|123&site_url=https://pages.razorpay.com/angroos&amount=1
    """
    return await _process_single(cc, site_url, amount, proxy)

@app.post("/rz", response_model=CheckResponse)
async def rz_post(request: SingleCheckRequest):
    """
    Check a single card via POST request.
    """
    return await _process_single(
        request.cc, request.site_url, request.amount, request.proxy
    )

# ============================================================
# Additional endpoints (backward compatible)
# ============================================================
@app.get("/check", response_model=CheckResponse)
async def check_single_get(
    cc: str = Query(..., description="Card in format: card|mm|yy|cvv"),
    site_url: Optional[str] = Query(None, description="Razorpay payment page URL"),
    amount: Optional[int] = Query(1, description="Amount in Rupees"),
    proxy: Optional[str] = Query(None, description="Proxy in format: ip:port:user:pass")
):
    """Alias for /rz – GET version."""
    return await rz_get(cc, site_url, amount, proxy)

@app.post("/check", response_model=CheckResponse)
async def check_single_post(request: SingleCheckRequest):
    """Alias for /rz – POST version."""
    return await rz_post(request)

@app.post("/mass-check", response_model=MassCheckResponse)
async def mass_check(request: MassCheckRequest):
    """
    Check multiple cards in one request.
    """
    # Setup gateway if needed
    if request.site_url and not gateway.is_valid():
        error = gateway.setup_gateway(
            request.site_url, request.amount, request.proxy or ""
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
    elif not request.site_url and not gateway.is_valid():
        raise HTTPException(
            status_code=400,
            detail="Gateway not initialized. Provide site_url in first request."
        )

    results = []
    charged = live = declined = errors = 0

    for cc in request.cards:
        # Refresh token periodically
        gateway.token_uses += 1
        if gateway.token_uses > 15:
            gateway.refresh_token()

        masked = mask_card(cc)

        try:
            tag, msg, elapsed, full_resp = process_card(
                cc, gateway.plid, gateway.ppiid, gateway.kid, gateway.kh,
                gateway.stoken, gateway.site_url, gateway.amount_paise
            )

            pid = full_resp.get("payment_id") or full_resp.get("razorpay_payment_id")

            result = CheckResponse(
                status="success",
                tag=tag,
                message=msg,
                elapsed=elapsed,
                masked_card=masked,
                payment_id=pid,
                full_response=full_resp,
                timestamp=datetime.now().isoformat()
            )
            results.append(result)

            if tag == "CHARGED":
                charged += 1
            elif tag == "LIVE":
                live += 1
            elif tag == "DECLINED":
                declined += 1
            else:
                errors += 1

        except Exception as e:
            result = CheckResponse(
                status="error",
                tag="ERROR",
                message=str(e)[:100],
                elapsed=0,
                masked_card=masked,
                full_response={"error": str(e)},
                timestamp=datetime.now().isoformat()
            )
            results.append(result)
            errors += 1

    return MassCheckResponse(
        total=len(request.cards),
        charged=charged,
        live=live,
        declined=declined,
        errors=errors,
        results=results
    )

# ============================================================
# Core processing function
# ============================================================
async def _process_single(
    cc: str,
    site_url: Optional[str] = None,
    amount: int = 1,
    proxy: Optional[str] = None
) -> CheckResponse:
    """Process a single card check."""
    # Validate card format
    if not cc or '|' not in cc:
        raise HTTPException(status_code=400, detail="Invalid card format. Use: card|mm|yy|cvv")

    # Setup gateway if needed
    if site_url:
        error = gateway.setup_gateway(site_url, amount, proxy or "")
        if error:
            raise HTTPException(status_code=400, detail=error)
    elif not gateway.is_valid():
        raise HTTPException(
            status_code=400,
            detail="Gateway not initialized. Provide site_url parameter."
        )

    # Refresh token periodically
    gateway.token_uses += 1
    if gateway.token_uses > 15:
        gateway.refresh_token()

    masked = mask_card(cc)
    start_time = time.time()

    try:
        tag, msg, elapsed, full_resp = process_card(
            cc, gateway.plid, gateway.ppiid, gateway.kid, gateway.kh,
            gateway.stoken, gateway.site_url, gateway.amount_paise
        )

        pid = full_resp.get("payment_id") or full_resp.get("razorpay_payment_id")

        return CheckResponse(
            status="success",
            tag=tag,
            message=msg,
            elapsed=elapsed,
            masked_card=masked,
            payment_id=pid,
            full_response=full_resp,
            timestamp=datetime.now().isoformat()
        )

    except Exception as e:
        return CheckResponse(
            status="error",
            tag="ERROR",
            message=str(e)[:100],
            elapsed=round(time.time() - start_time, 2),
            masked_card=masked,
            full_response={"error": str(e)},
            timestamp=datetime.now().isoformat()
        )

# ============================================================
# Run directly (development only)
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("api:app", host="0.0.0.0", port=port, reload=True)
