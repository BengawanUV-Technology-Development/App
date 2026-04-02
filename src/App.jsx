import { useState, useEffect } from "react";
import reactLogo from "./assets/react.svg";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

function App() {
  const [coords, setCoords] = useState({ lat: 0, lng: 0, alt: 0 });
  const [status, setStatus] = useState("Connecting to Python...");

  // Fungsi untuk mengambil data dari Backend Python (Flask)
  const fetchPythonData = async () => {
    try {
      const response = await fetch('http://localhost:5001/get-coordinates');
      if (!response.ok) throw new Error("Network response was not ok");
      const data = await response.json();
      setCoords(data);
      setStatus("Connected to Python");
    } catch (error) {
      setStatus("Python Backend not reached yet...");
      console.error("Error fetching from Python:", error);
    }
  };

  // Jalankan polling data setiap 1 detik untuk Mission Planner
  useEffect(() => {
    const interval = setInterval(fetchPythonData, 1000);
    return () => clearInterval(interval); // Cleanup saat app ditutup
  }, []);

  return (
    <main className="container">
      <h1>Mission Planner Dashboard</h1>

      <div className="row">
        <img src="/tauri.svg" className="logo tauri" alt="Tauri logo" />
        <img src="/vite.svg" className="logo vite" alt="Vite logo" />
        <img src={reactLogo} className="logo react" alt="React logo" />
        {/* Tambahkan logo Python jika ada untuk visual */}
      </div>

      <div className="card">
        <h3>Backend Status: <span style={{ color: status.includes("Connected") ? "green" : "red" }}>{status}</span></h3>
        <div className="data-display">
          <p><strong>Latitude:</strong> {coords.lat}</p>
          <p><strong>Longitude:</strong> {coords.lng}</p>
          <p><strong>Altitude:</strong> {coords.alt} m</p>
        </div>
      </div>

      <button onClick={fetchPythonData}>Refresh Manual</button>

      <p className="read-the-docs">
        Integrasi Tauri (React) + Python Sidecar
      </p>
    </main>
  );
}

export default App;