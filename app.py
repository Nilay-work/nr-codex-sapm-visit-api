from flask import Flask, jsonify
import aiohttp
import asyncio
import json
from byte import encrypt_api, Encrypt_ID
from visit_count_pb2 import Info  # Import the generated protobuf class

app = Flask(__name__)

def load_tokens(server_name, mode="visit"):
    try:
        if mode == "spam":
            if server_name == "IND":
                path = "spam_ind.json"
            elif server_name in {"BR", "US", "SAC", "NA"}:
                path = "spam_br.json"
            else:
                path = "spam_bd.json"
        else:  # visit mode
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
        app.logger.error(f"❌ Token load error for {server_name} ({mode}): {e}")
        return []

def get_url(server_name, mode="visit"):
    if mode == "spam":
        if server_name == "IND":
            return "https://client.ind.freefiremobile.com/RequestAddingFriend"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            return "https://client.us.freefiremobile.com/RequestAddingFriend"
        else:
            return "https://clientbp.ggblueshark.com/RequestAddingFriend"
    else:  # visit mode
        if server_name == "IND":
            return "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif server_name in {"BR", "US", "SAC", "NA"}:
            return "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            return "https://clientbp.ggblueshark.com/GetPlayerPersonalShow"

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

async def visit(session, url, token, uid, data):
    headers = {
        "ReleaseVersion": "OB51",
        "X-GA": "v1 1",
        "Authorization": f"Bearer {token}",
        "Host": url.replace("https://", "").split("/")[0]
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False) as resp:
            if resp.status == 200:
                response_data = await resp.read()
                return True, response_data
            else:
                return False, None
    except Exception as e:
        app.logger.error(f"❌ Visit error: {e}")
        return False, None

async def spam_friend_request(session, url, token, uid, data):
    headers = {
        "Expect": "100-continue",
        "Authorization": f"Bearer {token}",
        "X-Unity-Version": "2018.4.11f1",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB51",
        "Content-Type": "application/x-www-form-urlencoded",
        "Content-Length": "16",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; SM-N975F Build/PI)",
        "Host": url.replace("https://", "").split("/")[0],
        "Connection": "close",
        "Accept-Encoding": "gzip, deflate, br"
    }
    try:
        async with session.post(url, headers=headers, data=data, ssl=False) as resp:
            return resp.status == 200
    except Exception as e:
        app.logger.error(f"❌ Spam error: {e}")
        return False

async def send_until_1000_success(tokens, uid, server_name, target_success=1000):
    url = get_url(server_name, "visit")
    connector = aiohttp.TCPConnector(limit=0)
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None

    async with aiohttp.ClientSession(connector=connector) as session:
        encrypted = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
        data = bytes.fromhex(encrypted)

        while total_success < target_success:
            batch_size = min(target_success - total_success, 1000)
            tasks = [
                asyncio.create_task(visit(session, url, tokens[(total_sent + i) % len(tokens)], uid, data))
                for i in range(batch_size)
            ]
            results = await asyncio.gather(*tasks)
            
            if first_success_response is None:
                for success, response in results:
                    if success and response is not None:
                        first_success_response = response
                        player_info = parse_protobuf_response(response)
                        break
            
            batch_success = sum(1 for r, _ in results if r)
            total_success += batch_success
            total_sent += batch_size

            print(f"Batch sent: {batch_size}, Success in batch: {batch_success}, Total success so far: {total_success}")

    return total_success, total_sent, player_info

async def send_friend_requests(tokens, uid, server_name, target_success=1000):
    url = get_url(server_name, "spam")
    connector = aiohttp.TCPConnector(limit=0)
    total_success = 0
    total_sent = 0
    first_success_response = None
    player_info = None

    async with aiohttp.ClientSession(connector=connector) as session:
        encrypted_id = Encrypt_ID(str(uid))
        payload = f"08a7c4839f1e10{encrypted_id}1801"
        encrypted_payload = encrypt_api(payload)
        data = bytes.fromhex(encrypted_payload)

        # For spam, we need to get player info first using visit endpoint
        visit_url = get_url(server_name, "visit")
        visit_tokens = load_tokens(server_name, "visit")
        if visit_tokens:
            encrypted_visit = encrypt_api("08" + Encrypt_ID(str(uid)) + "1801")
            visit_data = bytes.fromhex(encrypted_visit)
            
            # Get player info using first token
            success, response = await visit(session, visit_url, visit_tokens[0], uid, visit_data)
            if success and response:
                player_info = parse_protobuf_response(response)

        while total_success < target_success:
            batch_size = min(target_success - total_success, 1000)
            tasks = [
                asyncio.create_task(spam_friend_request(session, url, tokens[(total_sent + i) % len(tokens)], uid, data))
                for i in range(batch_size)
            ]
            results = await asyncio.gather(*tasks)
            
            batch_success = sum(1 for r in results if r)
            total_success += batch_success
            total_sent += batch_size

            print(f"Spam batch sent: {batch_size}, Success in batch: {batch_success}, Total success so far: {total_success}")

    return total_success, total_sent, player_info

@app.route('/<string:server>/<int:uid>', methods=['GET'])
def send_visits(server, uid):
    server = server.upper()
    tokens = load_tokens(server, "visit")
    target_success = 1000

    if not tokens:
        return jsonify({"error": "❌ No valid tokens found"}), 500

    print(f"🚀 Sending visits to UID: {uid} using {len(tokens)} tokens")
    print(f"Waiting for total {target_success} successful visits...")

    total_success, total_sent, player_info = asyncio.run(send_until_1000_success(
        tokens, uid, server,
        target_success=target_success
    ))

    if player_info:
        player_info_response = {
            "fail": target_success - total_success,
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "success": total_success,
            "uid": player_info.get("uid", 0)
        }
        return jsonify(player_info_response), 200
    else:
        return jsonify({"error": "Could not decode player information"}), 500

@app.route('/spam/<string:server>/<int:uid>', methods=['GET'])
def send_spam(server, uid):
    server = server.upper()
    tokens = load_tokens(server, "spam")
    target_success = 1000

    if not tokens:
        return jsonify({"error": "❌ No valid tokens found"}), 500

    print(f"🚀 Sending friend requests to UID: {uid} using {len(tokens)} tokens")
    print(f"Waiting for total {target_success} successful requests...")

    total_success, total_sent, player_info = asyncio.run(send_friend_requests(
        tokens, uid, server,
        target_success=target_success
    ))

    if player_info:
        player_info_response = {
            "fail": target_success - total_success,
            "level": player_info.get("level", 0),
            "likes": player_info.get("likes", 0),
            "nickname": player_info.get("nickname", ""),
            "region": player_info.get("region", ""),
            "success": total_success,
            "uid": player_info.get("uid", 0)
        }
        return jsonify(player_info_response), 200
    else:
        # If we couldn't get player info, still return the spam results
        spam_response = {
            "fail": target_success - total_success,
            "level": 0,
            "likes": 0,
            "nickname": "",
            "region": "",
            "success": total_success,
            "uid": uid
        }
        return jsonify(spam_response), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
