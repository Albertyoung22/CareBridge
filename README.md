# 🩸 CareBridge - 美敦力 CareLink 轉 Nightscout / xDrip+ 自動橋接服務

`CareBridge` 是一個極簡、現代化的開源 Web 服務，能自動抓取 **美敦力 CareLink (MiniMed Guardian)** 連續血糖數據，並轉換為 **Nightscout API** 格式，讓您在 **xDrip+** 等 App 中 24 小時無縫監控血糖。

---

## 🌟 特點與優勢

1. **傻瓜式網頁設定 (`/setup`)**：不懂程式的病友或家屬，只需開啟網頁填入 Token，一鍵生成專屬 xDrip+ 網址。
2. **全自動背景續約**：具備 Auth0 跨網域 Cookie 自動續約機制，解決每 1 小時 Token 過期中斷的問題。
3. **MongoDB Cloud 支援**：數據自動儲存至 MongoDB Atlas 雲端資料庫。
4. **即時圖表與統計**：內建 TIR (範圍內比例)、GMI (預估 HbA1c) 與 Matplotlib 血糖趨勢圖。

---

## 🚀 部署指南 (Render 1-Click)

1. 將本專案 Fork 或 Push 到您自己的 **GitHub 儲存庫**。
2. 開啟 [Render.com](https://render.com/)，點選 **New +** ➔ **Web Service**。
3. 連結您的 GitHub 專案，設定如下：
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
4. 點擊 **Create Web Service** 部署。

---

## 📱 病友/使用者操作指南（3 步驟設定）

1. 開啟您的部署網址（例如 `https://your-app.onrender.com/setup`）。
2. 貼入 CareLink 的 `auth_tmp_token` 並點擊 **「一鍵驗證並生成專屬網址」**。
3. 點擊 **「一鍵複製專屬網址」**，打開手機 **xDrip+** ➔ 設定 ➔ 數據來源選擇 **Nightscout Follower** 貼上即可！

---

## 📄 開源授權
MIT License. 歡迎自由推廣與共享給需要的糖尿病友與家屬！
