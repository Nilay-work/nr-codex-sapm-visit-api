#!/usr/bin/env python3
# token_generator.py

import json
import time
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
BATCH_SIZE = 50
MAX_CONCURRENT = 100

# =========================================

def load_accounts() -> List[Dict[str, str]]:
    """Load UID:PASS from acc_ind.txt"""
    accounts = []
    if not os.path.exists(ACCOUNTS_FILE):
        print(f"Account file {ACCOUNTS_FILE} not found!")
        return accounts

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            uid, password = line.split(":", 1)
            accounts.append({"uid": uid.strip(), "password": password.strip()})
    print(f"Loaded {len(accounts)} accounts from {ACCOUNTS_FILE}")
    return accounts

def decode_jwt_payload(token: str) -> dict:
    """Extract noti_region from JWT without verification"""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}

async def generate_token(client: httpx.AsyncClient, uid: str, password: str) -> Optional[str]:
    """Call API and extract JWT from field '8'"""
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
        token = data.get("8", "")
        if token and token.startswith("ey"):
            return token
    except Exception as e:
        print(f"[{uid}] Request failed: {e}")
    return None

async def process_account(client: httpx.AsyncClient, acc: Dict[str, str]) -> Optional[Dict[str, str]]:
    uid = acc["uid"]
    password = acc["password"]

    for attempt in range(1, MAX_RETRIES + 1):
        token = await generate_token(client, uid, password)
        if not token:
            print(f"[{uid}] Failed (attempt {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)
            continue

        payload = decode_jwt_payload(token)
        region = payload.get("noti_region", "UNKNOWN")

        if region == "IND":
            print(f"[{uid}] IND Token Generated!")
            return {"uid": uid, "token": token}
        else:
            print(f"[{uid}] Wrong region: {region} (retry {attempt}/{MAX_RETRIES})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

    print(f"[{uid}] All attempts failed.")
    return None

async def main():
    print("Starting FreeFire IND Token Generator...")
    accounts = load_accounts()
    if not accounts:
        print("No accounts to process.")
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

    # Save results
    if valid_tokens:
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(valid_tokens, f, indent=2)
        print(f"Saved {len(valid_tokens)} valid IND tokens to {OUTPUT_FILE}")
    else:
        print("No valid IND tokens generated.")
        # Keep old file if exists
        if not os.path.exists(OUTPUT_FILE):
            open(OUTPUT_FILE, "w").close()

if __name__ == "__main__":
    asyncio.run(main())
