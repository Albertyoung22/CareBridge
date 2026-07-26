import os
import re
import json
import time
import requests
from datetime import datetime, timezone

CARELINK_USERNAME = os.environ.get("CARELINK_USERNAME", "")
CARELINK_PASSWORD = os.environ.get("CARELINK_PASSWORD", "")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "logindata.json")
HOST = "carelink.minimed.eu"

class CareLinkClient:
    def __init__(self, username=CARELINK_USERNAME, password=CARELINK_PASSWORD):
        self.username = username
        self.password = password
        self.country = "TW"
        self.token_data = None
        self.last_fetch_time = None
        self.last_glucose = None
        self.last_trend = "Flat"
        self.last_status = "Initialized"
        self.patient_id = None
        self.session = requests.Session()
        self.headers = {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def login_with_credentials(self, username, password, country="TW"):
        self.username = username
        self.password = password
        self.country = country
        
        sso_url = f"https://{HOST}/patient/sso/login?country={country.lower()}&lang=zh"
        try:
            r1 = self.session.get(sso_url, timeout=15, allow_redirects=True)
            state_match = re.search(r'name="state" value="([^"]+)"', r1.text)
            if not state_match:
                print("[CareLink Login Error] Could not find state parameter in form HTML.")
                return False, "無法取得 CareLink 登入頁狀態碼"
            
            state_val = state_match.group(1)
            form_data = {
                'state': state_val,
                'username': username,
                'password': password,
                'action': 'default'
            }
            
            r2 = self.session.post(r1.url, data=form_data, timeout=15, allow_redirects=True)
            cookies = self.session.cookies.get_dict()
            
            auth_token = cookies.get("auth_tmp_token")
            if not auth_token:
                for cookie in self.session.cookies:
                    if cookie.name == 'auth_tmp_token':
                        auth_token = cookie.value
                        break
            
            if auth_token:
                self.token_data = {
                    "access_token": auth_token,
                    "refresh_token": "web_session_active",
                    "scope": "profile openid roles country",
                    "client_id": "4fb211b8-f130-4398-b51e-28900bf68527",
                    "client_secret": "",
                    "mag-identifier": "web-session",
                    "username": username,
                    "password": password,
                    "country": country,
                    "cookies": {
                        "auth_tmp_token": auth_token
                    }
                }
                with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.token_data, f, indent=4)
                
                self.headers["Authorization"] = f"Bearer {auth_token}"
                print(f"[CareLink Auto-Login] Successfully logged in! Token: {auth_token[:20]}...")
                return True, "登入成功"
            else:
                return False, "帳號或密碼錯誤，或是美敦力伺服器回應異常"
        except Exception as e:
            print(f"[CareLink Login Exception] {e}")
            return False, f"連線異常: {e}"

    def load_token(self):
        env_token = os.environ.get("CARELINK_TOKEN_JSON")
        if env_token:
            try:
                self.token_data = json.loads(env_token)
                with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
                    json.dump(self.token_data, f, indent=4)
            except Exception as e:
                print(f"[CareLink] Failed to load token from CARELINK_TOKEN_JSON env: {e}")

        if os.path.exists(TOKEN_FILE):
            try:
                with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
                    self.token_data = json.load(f)
                    
                    if "username" in self.token_data and self.token_data["username"]:
                        self.username = self.token_data["username"]
                    if "password" in self.token_data and self.token_data["password"]:
                        self.password = self.token_data["password"]
                    if "country" in self.token_data and self.token_data["country"]:
                        self.country = self.token_data["country"]

                    if "cookies" in self.token_data:
                        for k, v in self.token_data["cookies"].items():
                            self.session.cookies.set(k, v, domain=".minimed.eu")
                            self.session.cookies.set(k, v, domain="carelink.minimed.eu")
                            self.session.cookies.set(k, v, domain="carelink-login.minimed.eu")

                    token_val = self.token_data.get("access_token")
                    if token_val and token_val != "web_session_active":
                        self.headers["Authorization"] = f"Bearer {token_val}"
            except Exception as e:
                print(f"[CareLink Token Load Error] {e}")

    def discover_patient_id(self):
        if self.patient_id:
            return self.patient_id
        
        try:
            links_url = f"https://{HOST}/patient/m2m/links/patients"
            resp = self.session.get(links_url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                patients = resp.json()
                if isinstance(patients, list) and len(patients) > 0:
                    self.patient_id = patients[0].get("username") or patients[0].get("id") or "18624702"
                    print(f"[CareLink] Patient ID: {self.patient_id}")
                    return self.patient_id
        except Exception as e:
            print(f"[CareLink Patient Discovery Warning] {e}")
        
        self.patient_id = "18624702"
        return self.patient_id

    def get_recent_data(self, is_retry=False):
        self.load_token()
        if not self.token_data or "Authorization" not in self.headers:
            self.last_status = "No Valid Token (Please configure token at /setup)"
            return None

        patient_username = self.discover_patient_id()
        data_url = f"https://clcloud.minimed.eu/patient/m2m/connect/data/gc/patients/{patient_username}"

        try:
            resp = self.session.get(data_url, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                json_data = resp.json()
                sgs = json_data.get("sgs") or json_data.get("lastSG") or []
                
                latest_item = None
                if isinstance(sgs, list) and len(sgs) > 0:
                    latest_item = sgs[-1]
                elif isinstance(sgs, dict):
                    latest_item = sgs
                
                if latest_item:
                    sgv = latest_item.get("sg") or latest_item.get("sgv") or latest_item.get("value")
                    direction = latest_item.get("trend") or latest_item.get("direction") or "Flat"
                    dt_str = latest_item.get("datetime") or latest_item.get("dateString")
                    
                    if sgv:
                        try:
                            dt_obj = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                        except Exception:
                            dt_obj = datetime.now(timezone(timedelta(hours=8)))
                            dt_str = dt_obj.isoformat()
                        
                        ts_ms = int(dt_obj.timestamp() * 1000)
                        
                        self.last_glucose = sgv
                        self.last_trend = direction
                        self.last_fetch_time = dt_obj
                        self.last_status = "連線成功"
                        
                        return {
                            "sgv": int(sgv),
                            "direction": direction,
                            "dateString": dt_str,
                            "date": ts_ms,
                            "device": "MMT-7841QZW"
                        }
                
                self.last_status = "無連續血糖數據"
                return None

            elif resp.status_code in (401, 403):
                if not is_retry:
                    print(f"[CareLink Warning] Token expired ({resp.status_code}). Attempting auto-refresh...")
                    if self.auto_refresh_token():
                        return self.get_recent_data(is_retry=True)
                
                self.last_status = f"[CareLink Error] Token Expired ({resp.status_code}). Please login at /setup"
                return None
            else:
                self.last_status = f"API Error ({resp.status_code})"
                return None
        except Exception as e:
            self.last_status = f"Network Exception: {e}"
            print(f"[CareLink Exception] {e}")

        return None

    def auto_refresh_token(self):
        if self.username and self.password:
            print("[CareLink Auto-Refresh] Attempting re-authentication with stored credentials...")
            success, _ = self.login_with_credentials(self.username, self.password, self.country)
            if success:
                print("[CareLink Auto-Refresh] Successfully re-authenticated!")
                return True

        print("[CareLink Auto-Refresh] Re-authentication failed or credentials not provided.")
        return False
