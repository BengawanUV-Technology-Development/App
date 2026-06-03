import { useConnection } from "../../hooks/useConnection";
import Badge from "../common/Badge";

function parseAddress(address) {
  const match = /^serial:\/\/(.+):(\d+)$/.exec(address || "");
  if (!match) return { port: "-", baud: "-" };
  return { port: match[1], baud: match[2] };
}

function ConnectionPanel({ health, onChanged }) {
  const connection = useConnection(onChanged);
  const active = parseAddress(health.system_address);

  return (
    <article className="connection-panel">
      <div className="connection-left">
        <div>
          <p className="panel-label">Link</p>
          <h2>FC Connection</h2>
        </div>
        <Badge tone={health.connected ? "success" : health.status === "CONNECTING" ? "warning" : ""}>
          {health.status || "OFFLINE"}
        </Badge>
      </div>

      <div className="connection-controls">
        <label>
          <span>Port</span>
          <select value={connection.selectedPort} onChange={(event) => connection.setSelectedPort(event.target.value)}>
            {connection.portOptions.map((port) => (
              <option key={port.value} value={port.value}>
                {port.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Baud</span>
          <select value={connection.selectedBaud} onChange={(event) => connection.setSelectedBaud(event.target.value)}>
            {connection.bauds.map((baud) => (
              <option key={baud} value={baud}>{baud}</option>
            ))}
          </select>
        </label>

        <button type="button" className="toolbar-button" onClick={connection.refreshPorts} disabled={connection.loading} title="Scan serial ports">
          Ports
        </button>
        <button type="button" className="connect-button" onClick={connection.connect} disabled={connection.loading || !connection.selectedPort}>
          Connect
        </button>
        <button type="button" className="toolbar-button" onClick={connection.disconnect} disabled={connection.loading}>
          Disconnect
        </button>
      </div>

      <div className="connection-meta">
        <span>Target {health.system_address ? `${active.port} @ ${active.baud}` : "not selected"}</span>
        <span>gRPC {health.mavsdk_server_port || "auto"}</span>
        <span>{connection.status}</span>
      </div>
    </article>
  );
}

export default ConnectionPanel;
