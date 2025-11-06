import os
import json
import base64
import asyncio
import aiohttp
import traceback
from flask import Flask, request, jsonify
from byte import encrypt_api, Encrypt_ID  # Ensure byte.py is in api/ folder
from visit_count_pb2 import Info  # Ensure visit_count_pb2.py is in api/ folder

app = Flask(__name__)

# Token loading from env vars (base64 encoded JSON strings)
def load_visit_tokens(server_name):
    try:
        env_key = f"VISIT_TOKENS_{server_name}"
        encoded_data = os.environ.get(env_key)
        if not encoded_data:
            app.logger.warning(f"No {env_key} env var found")
            return []
        
        data = json.loads(base64.b64decode(encoded_data).decode('utf-8'))
        tokens = [item["token"] for item in data if "token" in item and item["token"] not in ["", "N/A"]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Visit token load error for {server_name}: {e}\n{traceback.format_exc()}")
        return []

def load_spam_tokens(server_name):
    try:
        env_key = f"SPAM_TOKENS_{server_name}"
        encoded_data = os.environ.get(env_key)
        if not encoded_data:
            app.logger.warning(f"No {env_key} env var found")
            return []
        
        data = json.loads(base64.b64decode(encoded_data).decode('utf-8'))
        tokens = [item["token"] for item in data if "token" in item and item["token"] not in ["", "N/A"]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Spam token load error for {server_name}: {e}\n{traceback.format_exc()}")
        return []

# URL functions (unchanged)
def get_visit_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
    else:
        return "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

def get_spam_url(server_name):
    if server_name == "IND":
        return "https://client.ind.freefiremobile.com/RequestAddingFriend"
    elif server_name in {"BR", "US", "SAC", "NA"}:
        return "https://client.us.freefiremobile.com/RequestAddingFriend"
    else:
        return "https://clientbp.ggblueshark.com/RequestAddingFriend"

# Protobuf parsing (unchanged)
def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        player_data = {
            "uid": info.AccountInfo.UID if hasattr(info.AccountInfo, 'UID') and info.AccountInfo.UID else 0,
            "nickname": info.AccountInfo.PlayerNickname if hasattr(info.AccountInfo, 'PlayerNickname') and info.AccountInfo.PlayerNickname else "",
            "likes": info.AccountInfo.Likes if hasattr(info.AccountInfo, 'Likes') and info.AccountInfo.Likes else 0,
            "region": info.AccountInfo.PlayerRegion if hasattr(info.AccountInfo, 'PlayerRegion') and info.AccountInfo.PlayerRegion else "",
            "level": info.AccountInfo.Levels if hasattr(info.AccountInfo, 'Levels') and info.AccountInfo.Levels else 0
        }
        return player_data
    except Exception as e:
        app.logger.error(f"❌ Protobuf parsing error: {e}\n{traceback.format_exc()}")
        return None

# Async visit (with timeout)
async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB51",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        timeout = aiohttp.ClientTimeout(total=5)  # Reduced for serverless
        async with session.post(url, headers=headers, data=data, ssl=False, timeout=timeout) as resp:
            if resp.status == 200:
                response_data = await resp.read()
                return True, response_data
            else:
                return False, None
    except Exception as e:
        app.logger.error(f"❌ Visit error: {e}")
        return False, None

# Main visit logic (unchanged but wrapped)
async def send_until_100_success(tokens, uid, server_name, target_success=100):
    if not tokens:
        return 0, 0, None
    
    url = get_visit_url(server_name)
    connector = aiohttp.TCPConnector(limit=50, ssl=False)  # Limited for serverless
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
        data = bytes.fromhex(encrypted)

        while total_success < target_success:
            batch_size = min(target_success - total_success, 20)  # Smaller batches for serverless
            tasks = [
                visit(session, url, tokens[(total_sent + i) % len(tokens)], uid, data)
                for i in range(batch_size)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            if first_success_response is None:
                for item in results:
                    if isinstance(item, tuple) and item[0] and item[1]:
                        first_success_response = item[1]
                        player_info = parse_protobuf_response(item[1])
                        break
            
            batch_success = sum(1 for r in results if isinstance(r, tuple) and r[0])
            total_success += batch_success
            total_sent += batch_size

            app.logger.info(f"Batch: {batch_size}, Success: {batch_success}, Total: {total_success}/{target_success}")

    return total_success, total_sent, player_info

# Async spam request (replaced threading with async)
async def send_spam_request(session, url, token, uid):
    try:
        encrypted_id = Encrypt_ID(str(uid))
        payload = f"08a7c4839f1e10{encrypted_id}1801"
        encrypted_payload = encrypt_api(payload)

        headers = {
            "Expect": "100-continue",
            "Authorization": f"Bearer {token}",
            "X-Unity-Version": "2018.4.11f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB51",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; SM-N975F Build/PI)",
            "Host": url.replace("https://", "").split("/")[0],
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip"
        }

        timeout = aiohttp.ClientTimeout(total=5)
        async with session.post(url, headers=headers, data=bytes.fromhex(encrypted_payload), timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        app.logger.error(f"❌ Spam request error: {e}")
        return False

async def send_spam_requests(tokens, uid, server_name, target_count=100):
    if not tokens:
        return 0, 0
    
    url = get_spam_url(server_name)
    connector = aiohttp.TCPConnector(limit=50, ssl=False)
    success_count = 0
    total_sent = 0

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        while total_sent < target_count and total_sent < len(tokens):
            batch_size = min(target_count - total_sent, 20)
            tasks = [
                send_spam_request(session, url, tokens[total_sent + i], uid)
                for i in range(batch_size)
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            batch_success = sum(1 for r in results if isinstance(r, bool) and r)
            success_count += batch_success
            total_sent += batch_size

            app.logger.info(f"Spam Batch: {batch_size}, Success: {batch_success}, Total: {success_count}")

    return success_count, total_sent

# Get player info (async version)
async def get_player_info_async(uid, server_name):
    tokens = load_visit_tokens(server_name)
    if not tokens:
        return None
    
    url = get_visit_url(server_name)
    token = tokens[0]
    
    encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
    data = bytes.fromhex(encrypted)
    
    headers = {
        "ReleaseVersion": "OB51",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    
    connector = aiohttp.TCPConnector(limit=1, ssl=False)
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        try:
            async with session.post(url, headers=headers, data=data, ssl=False) as resp:
                if resp.status == 200:
                    response_data = await resp.read()
                    return parse_protobuf_response(response_data)
                return None
        except Exception as e:
            app.logger.error(f"❌ Player info error: {e}\n{traceback.format_exc()}")
            return None

# Routes (wrapped in try-catch)
@app.route('/visit', methods=['GET'])
def visit_route():
    try:
        uid = request.args.get('uid')
        region = request.args.get('region', 'IND').upper()
        
        if not uid:
            return jsonify({"error": "UID parameter is required"}), 400
        
        uid = int(uid)
        tokens = load_visit_tokens(region)
        if not tokens:
            return jsonify({"error": f"No valid visit tokens for {region}"}), 500

        app.logger.info(f"🚀 Visit request: UID {uid}, Region {region}, Tokens {len(tokens)}")
        
        total_success, total_sent, player_info = asyncio.run(
            send_until_100_success(tokens, uid, region)
        )

        response_data = {
            "success": total_success,
            "fail": 100 - total_success,
            "total_sent": total_sent
        }

        if player_info:
            response_data.update(player_info)
        else:
            response_data["error"] = "Could not fetch player info"

        return jsonify(response_data), 200
    except Exception as e:
        app.logger.error(f"❌ Visit route error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/spam', methods=['GET'])
def spam_route():
    try:
        uid = request.args.get('uid')
        region = request.args.get('region', 'IND').upper()

        if not uid:
            return jsonify({"error": "UID parameter is required"}), 400

        uid = int(uid)
        tokens = load_spam_tokens(region)
        if not tokens:
            return jsonify({"error": f"No spam tokens for {region}"}), 500

        app.logger.info(f"🚀 Spam request: UID {uid}, Region {region}, Tokens {len(tokens)}")
        
        # Get player info async
        player_info = asyncio.run(get_player_info_async(uid, region))
        
        success, total = asyncio.run(send_spam_requests(tokens, uid, region))

        response_data = {
            "success": success,
            "fail": total - success,
            "total": total
        }

        if player_info:
            response_data.update(player_info)
        else:
            response_data["error"] = "Could not fetch player info"

        return jsonify(response_data), 200
    except Exception as e:
        app.logger.error(f"❌ Spam route error: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/')
def home():
    return jsonify({"status": "FF Visit & Spam API Running", "endpoints": ["/visit?uid=123&region=IND", "/spam?uid=123&region=IND"]}), 200

# Vercel requires this for Python
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
