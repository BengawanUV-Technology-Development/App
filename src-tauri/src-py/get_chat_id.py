import os
import urllib.request
import json
import ssl
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN or TOKEN == "token_anda":
    print("❌ TELEGRAM_BOT_TOKEN belum diset di file .env!")
    exit()

url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
print("Menghubungi Telegram...")

ctx = ssl.create_default_context()

try:
    with urllib.request.urlopen(url, context=ctx) as response:
        data = json.loads(response.read().decode())
        if data.get("ok") and data.get("result"):
            for update in data["result"]:
                if "message" in update:
                    chat_id = update["message"]["chat"]["id"]
                    first_name = update["message"]["from"].get("first_name", "User")
                    print("\n" + "="*40)
                    print(f"✅ Pesan dari {first_name} terdeteksi!")
                    print(f"👉 CHAT_ID ANDA ADALAH: {chat_id}")
                    print(f"Tambahkan baris ini ke file .env:\nTELEGRAM_CHAT_ID={chat_id}")
                    print("="*40 + "\n")
                    exit()
            print("Belum ada pesan baru. Silakan kirim pesan 'Halo' ke Bot Anda di Telegram, lalu jalankan ulang skrip ini.")
        else:
            print("Belum ada pesan. Buka Telegram, cari bot Anda, tekan Start/kirim pesan, lalu coba lagi.")
except Exception as e:
    print(f"Error: {e}. Pastikan token benar.")
