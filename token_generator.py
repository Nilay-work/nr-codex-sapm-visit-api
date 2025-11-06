#!/usr/bin/env python3
# token_generator.py

import json
import asyncio
import httpx
import os
import base64
from typing import Optional, List, Dict

# ================= CONFIG =================
JWT_API_URL = "https://api.freefireservice.dnc.su/oauth/account:login"
ACCOUNTS_FILE = "acc_ind.txt"
OUTPUT_FILE = "token_ind.json"
MAX_RETRIES = 3
RETRY_DELAY = 15
BATCH_SIZE = 100
MAX_CONCURRENT = 100

# =========================================

def load_accounts() -> List[Dict[str, str]]:
    """Load UID:PASS from acc_ind.txt"""
    accounts = []
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"[ERROR] File not found: {ACCOUNTS_FILE}")
        return accounts

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or ":" not in line:
                continue
            parts = line.split(":", 1)
            uid = parts[0].strip()
            password = parts[1].strip()
            if uid.isdigit() and password:
                accounts.append({"uid": uid, "password": password})
            else:
                print(f"[SKIP] Invalid line {line_num}: {line}")
    print(f"[LOADED] {len(accounts)} valid accounts from {ACCOUNTS_FILE}")
    return accounts

def extract_jwt_from_response(data: dict) -> Optional[str]:
    """Extract JWT string starting with 'ey' from API response"""
    if not isinstance(data, dict):
        return None
    # Try common keys
    for key in ["8", "token", "access_token", "jwt", "data"]:
        value = data.get(key)
        if isinstance(value, str) and value.startswith("ey"):
            return value
    # Fallback: search in all string values
    for val in data.values():
        if isinstance(val, str) and val.startswith("ey"):
            return val
    return None

def decode_jwt_region(token: str) -> str:
    """Extract noti_region from JWT payload"""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("noti_region", "UNKNOWN")
    except Exception:
        return "UNKNOWN"

async def generate_token(client: httpx.AsyncClient, uid: str, password: str) -> Optional[str]:
    """Call API and return JWT if valid"""
    try:
        params = {"data": f"{uid}:{password}"}
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)",
            "Accept": "application/json"
        }
        resp = await client.get(JWT_API_URL, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None
        
        data = resp.json()
        token = extract_jwt_from_response(data)
        return token
    except Exception as e:
        print(f"[{uid}] Request error: {e}")
        return None

async def process_account(client: httpx.AsyncClient, acc: Dict[str, str]) -> Optional[Dict[str, str]]:
    uid = acc["uid"]
    password = acc["password"]

    for attempt in range(1, MAX_RETRIES + 1):
        token = await generate_token(client, uid, password)
        
        if not token:
            print(f"[{uid}] No response (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            continue

        region = decode_jwt_region(token)
        if region == "IND":
            print(f"[{uid}] Valid IND token generated!")
            return {"uid": uid, "token": token}
        else:
            print(f"[{uid}] Wrong region: {region} (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    print(f"[{uid}] All attempts failed.")
    return None

async def main():
    print("FreeFire IND Token Generator (Fixed JWT Extractor)")
    accounts = load_accounts()
    if not accounts:
        print("No valid accounts to process.")
        return

    valid_tokens = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def bounded_process(acc):
        async with semaphore:
            result = await process_account(client, acc)
            if result:
                valid_tokens.append(result)

    async with httpx.AsyncClient() as client:
        tasks = [bounded_process(acc) for acc in accounts[:BATCH_SIZE]]
        await asyncio.gather(*tasks)

    # Save output
    if valid_tokens:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(valid_tokens, f, indent=2)
        print(f"[SUCCESS] {len(valid_tokens)} IND tokens saved to {OUTPUT_FILE}")
    else:
        print("[FAILED] No valid IND tokens generated.")
        # Create empty file to avoid missing file errors
        open(OUTPUT_FILE, "w").close()

if __name__ == "__main__":
    asyncio.run(main())
