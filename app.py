import os
import re
import time
import json
import asyncio
import threading
import warnings
from datetime import datetime, timezone, timedelta
import requests
from flask import Flask, jsonify, render_template, request, send_file, send_from_directory, make_response

import database
from carelink_client import CareLinkClient, TOKEN_FILE

warnings.filterwarnings("ignore", category=UserWarning)

import matplotlib
matplotlib.use('Agg')
matplotlib.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'SimHei', 'DejaVu Sans', 'sans-serif']
matplotlib.rcParams['axes.unicode_minus'] = False
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from scipy.interpolate import make_interp_spline

app = Flask(__name__)
database.init_db()

client = CareLinkClient()

API_SECRET = os.environ.get("API_SECRET", "tigerlion2007")
LINE_ACCESS_TOKEN = os.environ.get("LINE_ACCESS_TOKEN", "").strip()
ENABLE_LINE_PUSH = os.environ.get("ENABLE_LINE_PUSH", "false").lower() in ("true", "1")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")

last_push_info = {"time": datetime.min.replace(tzinfo=timezone.utc), "val": 0, "type": "normal"}

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)

def ensure_https(url):
    if not url:
        return url
    if url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    return url

def get_direction_emoji(direction):
    mapping = {
        "DoubleUp": "⇈",
        "SingleUp": "↑",
        "FortyFiveUp": "↗",
        "Flat": "→",
        "FortyFiveDown": "↘",
        "SingleDown": "↓",
        "DoubleDown": "⇊",
        "RateOutOfRange": "!!",
        "NOT COMPUTABLE": "?",
        "NONE": "-"
    }
    return mapping.get(direction, direction or "-")

def send_line_message(text, image_url=None):
    if not ENABLE_LINE_PUSH or not LINE_ACCESS_TOKEN:
        return
    url = "https://api.line.me/v2/bot/message/broadcast"
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    
    image_url = ensure_https(image_url)
    messages = [{"type": "text", "text": text}]
    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })
        
    data = {"messages": messages}
    try:
        requests.post(url, headers=headers, json=data, timeout=10)
    except Exception as e:
        print(f"[LINE Broadcast Error] {e}")

def reply_line_message(reply_token, text, image_url=None):
    if not ENABLE_LINE_PUSH or not LINE_ACCESS_TOKEN:
        return
    url = "https://api.line.me/v2/bot/message/reply"
    headers = {"Authorization": f"Bearer {LINE_ACCESS_TOKEN}", "Content-Type": "application/json"}
    
    image_url = ensure_https(image_url)
    messages = [{"type": "text", "text": text}]
    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })
        
    data = {
        "replyToken": reply_token,
        "messages": messages
    }
    try:
        requests.post(url, headers=headers, json=data, timeout=10)
    except Exception as e:
        print(f"[LINE Reply Error] {e}")

def generate_line_chart():
    try:
        entries = database.get_nightscout_entries(limit=144)
        if not entries:
            return False
        
        entries.reverse()
        times = []
        vals = []
        tz_tw = timezone(timedelta(hours=8))
        for e in entries:
            try:
                dt = datetime.fromisoformat(e['dateString'].replace('Z', '+00:00'))
                times.append(dt.astimezone(tz_tw))
                vals.append(e.get('sgv', 0))
            except Exception:
                pass

        if not times or not vals:
            return False

        # 僅保留與最新一筆資料相差 24 小時內的紀錄，避免跨越過長停頓期導致圖表軸過度擠壓
        latest_time = times[-1]
        cutoff_time = latest_time - timedelta(hours=24)
        filtered = [(t, v) for t, v in zip(times, vals) if t >= cutoff_time]
        if len(filtered) >= 2:
            times, vals = zip(*filtered)
            times = list(times)
            vals = list(vals)

        BG_COLOR = '#121212'
        GRID_COLOR = '#2A2A2A'
        TEXT_COLOR = '#E0E0E0'
        NORMAL_COLOR = '#00E676'
        HIGH_COLOR = '#FF9100'
        LOW_COLOR = '#FF5252'
        LINE_COLOR = '#FFFFFF'
        
        plt.figure(figsize=(10, 5), facecolor=BG_COLOR, dpi=120)
        ax = plt.gca()
        ax.set_facecolor(BG_COLOR)
        
        plt.axhspan(70, 180, color=NORMAL_COLOR, alpha=0.03)
        plt.axhline(y=180, color=HIGH_COLOR, linestyle='--', linewidth=1, alpha=0.3)
        plt.axhline(y=70, color=LOW_COLOR, linestyle='--', linewidth=1, alpha=0.3)
        
        if len(times) > 10:
            try:
                x = np.array([t.timestamp() for t in times])
                y = np.array(vals)
                x, unique_idx = np.unique(x, return_index=True)
                y = y[unique_idx]
                
                if len(x) > 3:
                    x_new = np.linspace(x.min(), x.max(), 300)
                    spl = make_interp_spline(x, y, k=3)
                    y_smooth = spl(x_new)
                    
                    plt.plot([datetime.fromtimestamp(ts, tz=tz_tw) for ts in x_new], 
                             y_smooth, color=LINE_COLOR, linewidth=2, alpha=0.7, zorder=3)
                    plt.fill_between([datetime.fromtimestamp(ts, tz=tz_tw) for ts in x_new], 
                                    y_smooth, 40, color=LINE_COLOR, alpha=0.05, zorder=2)
                else:
                    plt.plot(times, vals, color=LINE_COLOR, linewidth=2, alpha=0.6, zorder=3)
            except Exception:
                plt.plot(times, vals, color=LINE_COLOR, linewidth=2, alpha=0.6, zorder=3)
        else:
            plt.plot(times, vals, color=LINE_COLOR, linewidth=2, alpha=0.6, zorder=3)
        
        colors = []
        for v in vals:
            if v >= 180: colors.append(HIGH_COLOR)
            elif v <= 70: colors.append(LOW_COLOR)
            else: colors.append(NORMAL_COLOR)
        
        plt.scatter(times, vals, c=colors, s=25, edgecolors=BG_COLOR, linewidth=0.5, zorder=4)
        
        latest_time = times[-1]
        latest_val = vals[-1]
        latest_color = colors[-1]
        
        plt.scatter(latest_time, latest_val, color=latest_color, s=120, edgecolors='white', linewidth=2, zorder=5)
        
        plt.annotate(f"{latest_val}", 
                     (latest_time, latest_val),
                     textcoords="offset points", 
                     xytext=(0, 15), 
                     ha='center', 
                     fontsize=14, 
                     fontweight='bold', 
                     color='white',
                     bbox=dict(boxstyle='round,pad=0.3', fc=latest_color, alpha=0.9, ec='white', lw=1))

        plt.ylim(40, 300 if max(vals) < 280 else max(vals) + 20)
        ax.tick_params(colors=TEXT_COLOR, labelsize=10)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID_COLOR)
        
        total_seconds = (times[-1] - times[0]).total_seconds() if len(times) > 1 else 0
        locator = mdates.AutoDateLocator(minticks=4, maxticks=8)
        ax.xaxis.set_major_locator(locator)
        if total_seconds <= 24 * 3600:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz_tw))
        else:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M', tz=tz_tw))
        
        plt.grid(color=GRID_COLOR, linestyle='-', linewidth=0.5, alpha=0.8)
        
        last_update = latest_time.strftime('%m/%d %H:%M')
        plt.title(f"Glucose Trend ({last_update})", color=TEXT_COLOR, fontsize=12, pad=15, fontweight='bold')
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        plt.tight_layout()
        
        output_path = os.path.join(STATIC_DIR, "line_chart.png")
        plt.savefig(output_path, facecolor='black')
        plt.close()
        return True
    except Exception as e:
        print(f"[Generate Line Chart Error] {e}")
        return False

@app.after_request
def add_no_cache_headers(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/setup')
@app.route('/setup/')
def setup_page():
    return render_template('setup.html')

@app.route('/setup/auto-login', methods=['POST'])
def setup_auto_login():
    body = request.get_json(silent=True) or {}
    username = body.get('username', '').strip()
    password = body.get('password', '').strip()
    country = body.get('country', 'TW')

    if not username or not password:
        return jsonify({"status": "error", "message": "帳號與密碼不能為空"}), 400

    success, msg = client.login_with_credentials(username, password, country)
    if success:
        data = client.get_recent_data()
        if data:
            database.save_entry(
                sgv=data['sgv'],
                direction=data['direction'],
                date_string=data['dateString'],
                timestamp=data['date'],
                device=data['device']
            )
            generate_line_chart()
        return jsonify({"status": "success", "message": "自動登入成功！已自動取得金鑰並啟用同步", "data": data})
    else:
        return jsonify({"status": "error", "message": msg}), 400

@app.route('/setup/save', methods=['POST'])
def setup_save():
    body = request.get_json(silent=True) or {}
    raw_input = body.get('token', '').strip()
    country = body.get('country', 'TW')
    
    if not raw_input:
        return jsonify({"status": "error", "message": "Token 不能為空"}), 400

    # 自動解析並擷取 auth_tmp_token (支援純 Token、Cookie 字串或 URL)
    token_match = re.search(r'auth_tmp_token=([a-zA-Z0-9%\._\-]+)', raw_input)
    if token_match:
        raw_token = token_match.group(1)
    else:
        raw_token = raw_input.split(';')[0].replace('Bearer ', '').strip('"\'; ')

    token_data = {
        "access_token": raw_token,
        "refresh_token": "web_session_active",
        "scope": "profile openid roles country",
        "client_id": "4fb211b8-f130-4398-b51e-28900bf68527",
        "client_secret": "",
        "mag-identifier": "web-session",
        "cookies": {
            "auth_tmp_token": raw_token
        }
    }
    
    try:
        with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(token_data, f, indent=4)
        
        client.country = country
        data = client.get_recent_data()
        if data:
            database.save_entry(
                sgv=data['sgv'],
                direction=data['direction'],
                date_string=data['dateString'],
                timestamp=data['date'],
                device=data['device']
            )
            generate_line_chart()
            return jsonify({"status": "success", "data": data})
        else:
            return jsonify({"status": "warning", "message": client.last_status or "已保存，待伺服器回應"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/v1', methods=['GET', 'POST'])
@app.route('/api/v1/', methods=['GET', 'POST'])
@app.route('/api/v1/entries', methods=['GET', 'POST'])
@app.route('/api/v1/entries/', methods=['GET', 'POST'])
@app.route('/api/v1/entries.json', methods=['GET', 'POST'])
def get_entries():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        items = [data] if isinstance(data, dict) else data
        for entry in items:
            val = entry.get('sgv') or entry.get('mbg') or entry.get('glucose')
            if val:
                database.save_entry(
                    sgv=int(val),
                    direction=entry.get('direction', 'Flat'),
                    date_string=entry.get('dateString', datetime.now(timezone(timedelta(hours=8))).isoformat()),
                    timestamp=entry.get('date', int(time.time() * 1000)),
                    device=entry.get('device', 'App')
                )
        return jsonify({"status": "success"}), 200

    if 'count' in request.args or (request.headers.get('Accept') == 'application/json' and not request.args.get('dashboard')):
        count = request.args.get('count', default=10, type=int)
        ns_entries = database.get_nightscout_entries(count)
        return jsonify(ns_entries)
        
    latest = database.get_latest_entry()
    history = database.get_recent_entries(288)
    stats = database.get_daily_stats(24)
    return jsonify({
        "status": "success",
        "latest": latest,
        "history": history,
        "stats": stats
    })

@app.route('/api/v1/sync', methods=['POST', 'GET'])
def trigger_sync():
    data = client.get_recent_data()
    if data:
        saved = database.save_entry(
            sgv=data['sgv'],
            direction=data['direction'],
            date_string=data['dateString'],
            timestamp=data['date'],
            device=data['device']
        )
        generate_line_chart()
        return jsonify({"status": "success", "data": data, "saved": saved})
    return jsonify({
        "status": "warning",
        "message": client.last_status or "CareLink 伺服器尚未回應或 Token 需更新"
    })

@app.route('/api/v1/status', methods=['GET'])
@app.route('/api/v1/status.json', methods=['GET'])
def get_status():
    now = datetime.now(timezone.utc)
    return jsonify({
        "status": "ok",
        "name": "CareBridge",
        "version": "1.0.0",
        "account": client.username,
        "country": client.country,
        "last_status": client.last_status,
        "last_glucose": client.last_glucose,
        "last_fetch_time": client.last_fetch_time.isoformat() if client.last_fetch_time else None,
        "has_token": bool(client.token_data),
        "serverTime": now.strftime('%Y-%m-%dT%H:%M:%S.000Z'),
        "serverTimeEpoch": int(now.timestamp() * 1000),
        "authorized": True,
        "apiEnabled": True,
        "settings": {
            "units": "mg/dL",
            "timeFormat": 24,
            "thresholds": {"bgHigh": 260, "bgTargetTop": 180, "bgTargetBottom": 80, "bgLow": 55},
            "enable": ["careportal", "rawbg", "iob"]
        }
    })

@app.route("/callback", methods=['POST'])
def line_callback():
    if not ENABLE_LINE_PUSH:
        return 'LINE Push Disabled', 200
    body = request.get_json(silent=True) or {}
    base_host = ensure_https(PUBLIC_URL or request.host_url.rstrip('/'))
    try:
        for event in body.get('events', []):
            if event.get('type') == 'message' and event.get('message', {}).get('type') == 'text':
                user_msg = event['message']['text'].strip()
                reply_token = event['replyToken']
                
                if "血糖" in user_msg or "bg" in user_msg.lower():
                    latest = database.get_latest_entry()
                    if latest:
                        try:
                            dt_in = datetime.fromisoformat(latest['dateString'].replace('Z', '+00:00'))
                            local_time = dt_in.astimezone(timezone(timedelta(hours=8))).strftime('%H:%M')
                        except Exception:
                            local_time = latest['dateString']
                        
                        chart_url = None
                        if generate_line_chart():
                            now_ts = int(time.time())
                            chart_url = f"{base_host}/static/line_chart.png?t={now_ts}"
                            
                        dir_emoji = get_direction_emoji(latest.get('direction'))
                        msg = f"【即時查詢】\n🩸 數值: {latest['sgv']}\n📈 趨勢: {dir_emoji} ({latest.get('direction', 'Flat')})\n⏰ 時間: {local_time}"
                        reply_line_message(reply_token, msg, chart_url)
                    else:
                        reply_line_message(reply_token, "資料庫目前沒有任何血糖紀錄。")
    except Exception as e:
        print(f"[LINE Callback Exception] {e}")
    return 'OK', 200

def start_background_loop():
    def loop():
        print("[CareBridge Thread] 美敦力 CareLink 背景同步任務已啟動 (每 5 分鐘自動執行)...")
        while True:
            try:
                data = client.get_recent_data()
                if data:
                    database.save_entry(
                        sgv=data['sgv'],
                        direction=data['direction'],
                        date_string=data['dateString'],
                        timestamp=data['date'],
                        device=data['device']
                    )
                    generate_line_chart()
            except Exception as e:
                print(f"[CareBridge Loop Exception] {e}")
            time.sleep(300)

    t = threading.Thread(target=loop, daemon=True)
    t.start()

start_background_loop()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"CareBridge Service Starting: http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
