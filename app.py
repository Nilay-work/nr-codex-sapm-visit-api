from flask import Flask, request, jsonify
import aiohttp
import asyncio
import json
import threading
import requests
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info  # Import the generated protobuf class

app = Flask(__name__)

# Token loading function for visit and spam (separate tokens)
def load_visit_tokens(server_name):
    try:
        if server_name == "IND":
            path = "token_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "token_br.json"
        else:
            path = "token_bd.json"

        with open(path, "r") as f:
            data = json.load(f)

        tokens = [item["token"] for item in data if "token" in item and item["token"] not in ["", "N/A"]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Visit token load error for {server_name}: {e}")
        return []

def load_spam_tokens(server_name):
    try:
        if server_name == "IND":
            path = "spam_ind.json"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            path = "spam_br.json"
        else:
            path = "spam_bd.json"

        with open(path, "r") as f:
            data = json.load(f)

        tokens = [item["token"] for item in data if "token" in item and item["token"] not in ["", "N/A"]]
        return tokens
    except Exception as e:
        app.logger.error(f"❌ Spam token load error for {server_name}: {e}")
        return []

# URL functions for different regions
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

# Protobuf parsing for visit response
def parse_protobuf_response(response_data):
    try:
        info = Info()
        info.ParseFromString(response_data)
        
        player_data = {
            "uid": info.AccountInfo.UID if info.AccountInfo.UID else 0,
            "nickname": info.AccountInfo.PlayerNickname if info.AccountInfo.PlayerNickname else "",
            "likes": info.AccountInfo.Likes if info.AccountInfo.Likes else 0,
            "region": info.AccountInfo.PlayerRegion if info.AccountInfo.PlayerRegion else "",
            "level": info.AccountInfo.Levels if info.AccountInfo.Levels else 0
        }
        return player_data
    except Exception as e:
        app.logger.error(f"❌ Protobuf parsing error: {e}")
        return None

# Visit functionality (async)
async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB51",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False, timeout=10) as resp:
            if resp.status == 200:
                response_data = await resp.read()
                return True, response_data
            else:
                return False, None
    except Exception as e:
        app.logger.error(f"❌ Visit error: {e}")
        return False, None

async def send_until_100_success(tokens, uid, server_name, target_success=100):
    url = get_visit_url(server_name)
    connector = aiohttp.TCPConnector(limit=0, ssl=False)
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
        data = bytes.fromhex(encrypted)

        while total_success < target_success:
            batch_size = min(target_success - total_success, 100)
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

            print(f"Batch sent: {batch_size}, Success: {batch_success}, Total: {total_success}/{target_success}")

    return total_success, total_sent, player_info

# Spam functionality (threading)
def send_friend_request(uid, token, server_name, results):
    try:
        encrypted_id = Encrypt_ID(str(uid))
        payload = f"08a7c4839f1e10{encrypted_id}1801"
        encrypted_payload = encrypt_api(payload)

        url = get_spam_url(server_name)
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

        response = requests.post(url, headers=headers, data=bytes.fromhex(encrypted_payload), timeout=10)

        if response.status_code == 200:
            results["success"] += 1
        else:
            results["fail"] += 1
    except Exception as e:
        app.logger.error(f"❌ Friend request error: {e}")
        results["fail"] += 1

# Get player info separately for spam endpoint
def get_player_info(uid, server_name):
    try:
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
        
        response = requests.post(url, headers=headers, data=data, timeout=10)
        if response.status_code == 200:
            return parse_protobuf_response(response.content)
        else:
            return None
    except Exception as e:
        app.logger.error(f"❌ Player info error: {e}")
        return None

# Routes
@app.route('/visit', methods=['GET'])
def visit_route():
    uid = request.args.get('uid')
    region = request.args.get('region', 'IND').upper()
    
    if not uid:
        return jsonify({"error": "UID parameter is required"}), 400
    
    try:
        uid = int(uid)
    except ValueError:
        return jsonify({"error": "UID must be a valid number"}), 400

    tokens = load_visit_tokens(region)
    if not tokens:
        return jsonify({"error": f"No valid visit tokens found for region {region}"}), 500

    print(f"🚀 Sending visits to UID: {uid} | Region: {region} | Tokens: {len(tokens)}")
    
    total_success, total_sent, player_info = asyncio.run(
        send_until_100_success(tokens, uid, region, target_success=100)
    )

    response_data = {
        "success": total_success,
        "fail": 100 - total_success,
        "total_sent": total_sent
    }

    if player_info:
        response_data.update({
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "uid": player_info.get("uid", 0)
        })
    else:
        response_data["error"] = "Could not fetch player info"

    return jsonify(response_data), 200

@app.route("/spam", methods=["GET"])
def spam_route():
    uid = request.args.get("uid")
    region = request.args.get("region", "IND").upper()

    if not uid:
        return jsonify({"error": "uid parameter is required"}), 400

    try:
        uid = int(uid)
    except ValueError:
        return jsonify({"error": "UID must be a valid number"}), 400

    tokens = load_spam_tokens(region)
    if not tokens:
        return jsonify({"error": f"No spam tokens found for region {region}"}), 500

    player_info = get_player_info(uid, region)
    results = {"success": 0, "fail": 0}
    threads = []

    for token in tokens[:100]:
        t = threading.Thread(target=send_friend_request, args=(uid, token, region, results))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    response_data = {
        "success": results["success"],
        "fail": results["fail"],
        "total": results["success"] + results["fail"]
    }

    if player_info:
        response_data.update({
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "uid": player_info.get("uid", 0)
        })
    else:
        response_data["error"] = "Could not fetch player information"

    return jsonify(response_data), 200

# Health check
@app.route('/')
def home():
    return jsonify({"status": "FF Visit & Spam API Running", "endpoints": ["/visit", "/spam"]}), 200

# Run with fixed port (use environment variable)
if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    print(f"[🚀] Starting Flask API on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
