# src-tauri/src-python/main.py
from flask import Flask, jsonify
from flask_cors import CORS # Penting agar React bisa akses

app = Flask(__name__)
CORS(app) # Mengizinkan request dari frontend Tauri

@app.route('/get-coordinates', methods=['GET'])
def get_coordinates():
    # Simulasi data koordinat drone untuk Mission Planner
    data = {
        "lat": -7.5588,
        "lng": 110.8562,
        "alt": 100
    }
    return jsonify(data)

if __name__ == '__main__':
    # Jalankan di port 5001
    app.run(port=5001)