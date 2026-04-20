import os
import hmac
import time
import threading
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app, origins=['https://genaroroustan.github.io'])

# Deduplicación: { key: timestamp_unix }
_dedup_cache: dict[str, float] = {}
_DEDUP_WINDOW = 60  # segundos

N8N_URL = os.environ.get('N8N_WEBHOOK_URL')
API_KEY = os.environ.get('N8N_API_KEY')
N8N_DASHBOARD_URL = os.environ.get('N8N_DASHBOARD_URL') or 'https://genaroroustan1.app.n8n.cloud/webhook/dashboard-data'
N8N_DASHBOARD_API_KEY = os.environ.get('N8N_DASHBOARD_API_KEY') or API_KEY
HR_USERNAME = os.environ.get('HR_USERNAME')
HR_PASSWORD = os.environ.get('HR_PASSWORD')

@app.route('/', methods=['GET'])
def status():
    return "🛡️ Proxy Listo", 200

# --- MANEJO DE LA API ---

@app.route('/enviar-prueba', methods=['POST'])
def proxy_n8n():
    try:
        data = request.json or {}
        # --- Deduplicación por cédula + ventana de 60s ---
        cedula = str(data.get('cedula') or '').strip()
        if cedula:
            minute_bucket = int(time.time() // _DEDUP_WINDOW)
            dedup_key = f"{cedula}:{minute_bucket}"
            now = time.time()
            expired = [k for k, t in _dedup_cache.items() if now - t > _DEDUP_WINDOW]
            for k in expired:
                del _dedup_cache[k]
            if dedup_key in _dedup_cache:
                return jsonify({"message": "duplicado ignorado"}), 200
            _dedup_cache[dedup_key] = now
        # -------------------------------------------------
        if not N8N_URL:
            return jsonify({"error": "Falta URL en Secrets"}), 500

        # Lanzar envío a n8n en background y responder 200 inmediatamente
        # Esto evita que Replit reenvíe la request si el worker muere esperando
        def enviar_a_n8n(payload: dict) -> None:
            try:
                print(f"[PROXY] Enviando a n8n - cedula: {payload.get('cedula','?')}", flush=True)
                requests.post(
                    N8N_URL,
                    json=payload,
                    headers={"Content-Type": "application/json", "x-api-key": API_KEY},
                    timeout=90,
                )
                print(f"[PROXY] n8n OK - cedula: {payload.get('cedula','?')}", flush=True)
            except Exception as e:
                print(f"[PROXY] n8n ERROR - cedula: {payload.get('cedula','?')} - {e}", flush=True)

        threading.Thread(target=enviar_a_n8n, args=(data,), daemon=False).start()
        return jsonify({"message": "✅ Recibido"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/dashboard-data', methods=['GET'])
def proxy_dashboard_data():
    try:
        token = request.args.get('token', '')

        if not N8N_DASHBOARD_API_KEY:
            return jsonify({"error": "Falta X-API-KEY en Secrets"}), 500

        url = N8N_DASHBOARD_URL
        if token:
            url = f"{url}?token={token}"

        headers = {
            "Accept": "application/json",
            "X-API-KEY": N8N_DASHBOARD_API_KEY,
        }

        response = requests.get(url, headers=headers, timeout=20)
        try:
            return jsonify(response.json()), response.status_code
        except:
            return jsonify({"error": "Respuesta inválida desde n8n"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/hr/login', methods=['POST'])
def hr_login():
    try:
        if not HR_USERNAME or not HR_PASSWORD:
            return jsonify({"error": "Faltan credenciales RRHH en Secrets"}), 500

        data = request.json or {}
        username = str(data.get('username') or '').strip()
        password = str(data.get('password') or '')

        ok_user = hmac.compare_digest(username, HR_USERNAME)
        ok_pass = hmac.compare_digest(password, HR_PASSWORD)
        if not (ok_user and ok_pass):
            return jsonify({"ok": False}), 401

        return jsonify({"ok": True, "user": username}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
