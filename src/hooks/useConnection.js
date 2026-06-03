import { useEffect, useState } from "react";
import { apiGet, apiPost } from "../services/api";

const defaultBauds = [57600, 115200, 230400, 460800, 921600];
const networkPorts = ["TCP", "UDP", "UDPCI", "WS"];
const fallbackPorts = ["AUTO", ...Array.from({ length: 30 }, (_, index) => `COM${index + 1}`), ...networkPorts];

function optionLabel(port) {
  if (port === "AUTO") return "AUTO";
  if (networkPorts.includes(port)) return port;
  return port;
}

function buildPortOptions(detectedPorts, candidates) {
  const detectedOptions = detectedPorts.map((port) => ({
    value: port.device,
    label: port.description ? `${port.device} ${port.description}` : port.device,
  }));
  const detectedValues = new Set(detectedOptions.map((option) => option.value));
  const candidateOptions = candidates
    .filter((port) => !detectedValues.has(port))
    .map((port) => ({ value: port, label: optionLabel(port) }));

  return [...detectedOptions, ...candidateOptions];
}

export function useConnection(onChanged) {
  const [ports, setPorts] = useState([]);
  const [candidates, setCandidates] = useState([]);
  const [portOptions, setPortOptions] = useState(buildPortOptions([], fallbackPorts));
  const [bauds, setBauds] = useState(defaultBauds);
  const [selectedPort, setSelectedPort] = useState("AUTO");
  const [selectedBaud, setSelectedBaud] = useState(115200);
  const [status, setStatus] = useState("-");
  const [loading, setLoading] = useState(false);

  const refreshPorts = async () => {
    setLoading(true);
    const result = await apiGet("/connection/ports");
    setLoading(false);

    if (!result.ok) {
      setCandidates(fallbackPorts);
      setPortOptions(buildPortOptions([], fallbackPorts));
      setSelectedPort((current) => current || "AUTO");
      setStatus(result.error === "TypeError: Failed to fetch" ? "Backend offline" : result.error);
      return result;
    }

    const nextPorts = result.data?.ports || [];
    const nextCandidates = result.data?.candidates || nextPorts.map((port) => port.device);
    setPorts(nextPorts);
    setCandidates(nextCandidates);
    setPortOptions(buildPortOptions(nextPorts, nextCandidates));
    setBauds(result.data?.bauds || defaultBauds);
    setSelectedPort((current) => {
      if (current && current !== "AUTO") return current;
      const ardupilotPort = nextPorts.find((port) => /ardupilot|pixhawk|cube|mavlink/i.test(`${port.description} ${port.hwid}`));
      return ardupilotPort?.device || current || "AUTO";
    });
    setStatus(nextPorts.length ? `${nextPorts.length} detected` : "Manual COM entry");
    return result;
  };

  const connect = async () => {
    setLoading(true);
    setStatus("Connecting...");
    let portToConnect = selectedPort;
    let availablePorts = ports;

    if (selectedPort === "AUTO" && availablePorts.length === 0) {
      const scanResult = await apiGet("/connection/ports");
      if (scanResult.ok) {
        availablePorts = scanResult.data?.ports || [];
        const nextCandidates = scanResult.data?.candidates || availablePorts.map((port) => port.device);
        setPorts(availablePorts);
        setCandidates(nextCandidates);
        setPortOptions(buildPortOptions(availablePorts, nextCandidates));
        setBauds(scanResult.data?.bauds || defaultBauds);
      } else {
        setLoading(false);
        setStatus(scanResult.error === "TypeError: Failed to fetch" ? "Backend offline" : scanResult.error);
        return scanResult;
      }
    }

    if (selectedPort === "AUTO") {
      const ardupilotPort = availablePorts.find((port) => /ardupilot|pixhawk|cube|mavlink/i.test(`${port.description} ${port.hwid}`));
      portToConnect = ardupilotPort?.device || availablePorts[0]?.device || "";
    }

    if (!portToConnect) {
      setLoading(false);
      setStatus("No detected COM port for AUTO");
      return { ok: false, error: "No detected COM port for AUTO" };
    }

    const result = await apiPost("/connection/connect", { port: portToConnect, baud: Number(selectedBaud) });
    setLoading(false);

    if (!result.ok) {
      setStatus(result.error);
      return result;
    }

    setStatus(result.data?.message || "Connection requested");
    await onChanged?.();
    return result;
  };

  const disconnect = async () => {
    setLoading(true);
    setStatus("Disconnecting...");
    const result = await apiPost("/connection/disconnect");
    setLoading(false);

    if (!result.ok) {
      setStatus(result.error);
      return result;
    }

    setStatus(result.data?.message || "Disconnected");
    await onChanged?.();
    return result;
  };

  useEffect(() => {
    refreshPorts();
  }, []);

  return {
    ports,
    candidates,
    portOptions,
    bauds,
    selectedPort,
    setSelectedPort,
    selectedBaud,
    setSelectedBaud,
    status,
    loading,
    refreshPorts,
    connect,
    disconnect,
  };
}
