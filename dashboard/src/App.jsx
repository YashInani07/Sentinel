import React, { useState, useEffect } from 'react';

// Environment-aware URL resolver
// isLocalDev is true if running on localhost with custom development (5173/3000) or docker-compose (8080) ports.
// Otherwise (e.g. running on Kubernetes ingress), use relative paths.
const isLocalDev = 
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') &&
  (window.location.port === '8080' || window.location.port === '5173' || window.location.port === '3000');

const COLLECTOR_URL = isLocalDev ? 'http://localhost:8000' : '/api/collector';
const ALERT_URL = isLocalDev ? 'http://localhost:8001' : '/api/alerts';

const PRODUCER_URLS = {
  'producer-1': isLocalDev ? 'http://localhost:8011' : '/api/producer-1',
  'producer-2': isLocalDev ? 'http://localhost:8012' : '/api/producer-2',
  'producer-3': isLocalDev ? 'http://localhost:8013' : '/api/producer-3',
};

const PRODUCER_NAMES = ['producer-1', 'producer-2', 'producer-3'];

export default function App() {
  const [logs, setLogs] = useState([]);
  const [errorCounts, setErrorCounts] = useState({});
  const [alerts, setAlerts] = useState([]);
  const [spamming, setSpamming] = useState({
    'producer-1': false,
    'producer-2': false,
    'producer-3': false,
  });

  // Filters state
  const [filterService, setFilterService] = useState('');
  const [filterLevel, setFilterLevel] = useState('');

  // Fetch logs from collector
  const fetchLogs = async () => {
    try {
      let url = `${COLLECTOR_URL}/logs?limit=50`;
      if (filterService) {
        url += `&service_name=${filterService}`;
      }
      if (filterLevel) {
        url += `&level=${filterLevel}`;
      }
      const response = await fetch(url);
      if (response.ok) {
        const data = await response.json();
        setLogs(data);
      }
    } catch (err) {
      console.warn('Error fetching logs:', err);
    }
  };

  // Fetch sliding window error counts (window = 60s)
  const fetchErrorCounts = async () => {
    try {
      const response = await fetch(`${COLLECTOR_URL}/logs/error-counts?window_seconds=60`);
      if (response.ok) {
        const data = await response.json();
        setErrorCounts(data);
      }
    } catch (err) {
      console.warn('Error fetching error counts:', err);
    }
  };

  // Fetch active alerts
  const fetchAlerts = async () => {
    try {
      const response = await fetch(`${ALERT_URL}/alerts`);
      if (response.ok) {
        const data = await response.json();
        setAlerts(data);
      }
    } catch (err) {
      console.warn('Error fetching alerts:', err);
    }
  };

  // Fetch spam status of each producer
  const fetchSpamStatuses = async () => {
    const updatedSpamming = { ...spamming };
    for (const name of PRODUCER_NAMES) {
      try {
        const response = await fetch(`${PRODUCER_URLS[name]}/status`);
        if (response.ok) {
          const data = await response.json();
          updatedSpamming[name] = data.spamming_errors;
        }
      } catch (err) {
        // Log is fine, but don't break dashboard
        // E.g. service might not be up yet
      }
    }
    setSpamming(updatedSpamming);
  };

  // Toggle spam errors on/off
  const toggleSpam = async (serviceName) => {
    const isSpamming = spamming[serviceName];
    const endpoint = isSpamming ? '/spam-errors/stop' : '/spam-errors/start';
    try {
      const response = await fetch(`${PRODUCER_URLS[serviceName]}${endpoint}`, {
        method: 'POST',
      });
      if (response.ok) {
        setSpamming((prev) => ({
          ...prev,
          [serviceName]: !isSpamming,
        }));
      }
    } catch (err) {
      alert(`Failed to connect to ${serviceName} at ${PRODUCER_URLS[serviceName]}`);
    }
  };

  // Clear alerts helper
  const clearAlerts = async () => {
    try {
      await fetch(`${ALERT_URL}/alerts/clear`, { method: 'POST' });
      setAlerts([]);
    } catch (err) {
      console.error('Failed to clear alerts:', err);
    }
  };

  // Set up periodic polling
  useEffect(() => {
    fetchLogs();
    fetchErrorCounts();
    fetchAlerts();
    fetchSpamStatuses();

    const interval = setInterval(() => {
      fetchLogs();
      fetchErrorCounts();
      fetchAlerts();
      fetchSpamStatuses();
    }, 3000);

    return () => clearInterval(interval);
  }, [filterService, filterLevel]);

  return (
    <div className="container">
      {/* Header */}
      <header className="app-header glass">
        <div className="logo-section">
          <div className="logo-icon">S</div>
          <h1 className="app-title">Sentinel Distributed Logging</h1>
        </div>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
          Live Status: <span style={{ color: 'var(--accent-emerald)', fontWeight: 'bold' }}>● Connected</span>
        </div>
      </header>

      {/* Active Alerts Banner */}
      {alerts.length > 0 && (
        <div className="alerts-banner-container">
          <div className="glass" style={{ padding: '16px 20px', borderRadius: '12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <h2 style={{ fontSize: '1rem', color: 'var(--color-error)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                ⚠️ Active System Alerts ({alerts.length})
              </h2>
              <button className="btn btn-stop" onClick={clearAlerts}>Clear Alerts</button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {alerts.slice(0, 3).map((alert) => {
                const currentCount = errorCounts[alert.service_name] || 0;
                const isResolved = currentCount <= alert.threshold;
                return (
                  <div key={alert.id} className={`alert-card ${isResolved ? 'resolved' : ''}`}>
                    <div className="alert-icon">{isResolved ? '✅' : '🔥'}</div>
                    <div className="alert-content">
                      <div className="alert-msg">
                        {alert.message} {isResolved && <span style={{ color: 'var(--accent-emerald)', marginLeft: '8px', fontSize: '0.8rem', fontWeight: 'bold' }}>[RESOLVED]</span>}
                      </div>
                      <div className="alert-meta">
                        <span>Threshold: &gt; {alert.threshold}</span>
                        <span>Service: {alert.service_name}</span>
                        <span>Current Errors: {currentCount}</span>
                        <span>Fired: {new Date(alert.timestamp).toLocaleTimeString()}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
              {alerts.length > 3 && (
                <div style={{ textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  And {alerts.length - 3} more alert(s) below...
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Main Grid */}
      <main className="dashboard-grid">
        {/* Left column: Metrics and Controls */}
        <section className="sidebar">
          {/* Metrics Panel */}
          <div className="glass" style={{ padding: '20px' }}>
            <h2 className="panel-title">
              Error Metrics
              <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 'normal' }}>
                60s window
              </span>
            </h2>
            {PRODUCER_NAMES.map((name) => {
              const count = errorCounts[name] || 0;
              return (
                <div key={name} className="metric-row">
                  <span className="service-badge">{name}</span>
                  <span className={`error-count-badge ${count === 0 ? 'zero' : ''}`}>
                    {count} ERROR{count !== 1 ? 's' : ''}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Spam Controls */}
          <div className="glass" style={{ padding: '20px' }}>
            <h2 className="panel-title">Spam Error Injection</h2>
            {PRODUCER_NAMES.map((name) => (
              <div key={name} className="control-item">
                <span className="service-badge">{name}</span>
                <button
                  className={`btn ${spamming[name] ? 'btn-stop' : 'btn-start'}`}
                  onClick={() => toggleSpam(name)}
                >
                  {spamming[name] ? 'Stop Spam' : 'Spam Errors'}
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Right column: Live Logs */}
        <section className="glass logs-panel">
          <h2 className="panel-title">Live Logs</h2>
          
          {/* Filters */}
          <div className="filters-container">
            <div className="filter-group">
              <label className="filter-label">Service</label>
              <select
                className="select-input"
                value={filterService}
                onChange={(e) => setFilterService(e.target.value)}
              >
                <option value="">All Services</option>
                {PRODUCER_NAMES.map(name => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>

            <div className="filter-group">
              <label className="filter-label">Severity Level</label>
              <select
                className="select-input"
                value={filterLevel}
                onChange={(e) => setFilterLevel(e.target.value)}
              >
                <option value="">All Levels</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </div>
            
            <div style={{ marginLeft: 'auto', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
              Showing last {logs.length} logs
            </div>
          </div>

          {/* Table */}
          <div className="table-wrapper">
            <table className="logs-table">
              <thead>
                <tr>
                  <th style={{ width: '20%' }}>Timestamp</th>
                  <th style={{ width: '15%' }}>Service</th>
                  <th style={{ width: '15%' }}>Level</th>
                  <th>Message</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 ? (
                  <tr>
                    <td colSpan="4" style={{ textAlign: 'center', padding: '30px', color: 'var(--text-secondary)' }}>
                      No logs matching filters found. Wait for producers to start...
                    </td>
                  </tr>
                ) : (
                  logs.map((log) => (
                    <tr key={log.id} className="log-row">
                      <td className="time-col">{new Date(log.timestamp).toLocaleTimeString()}</td>
                      <td className="service-col" style={{ color: log.service_name === 'producer-1' ? '#38bdf8' : log.service_name === 'producer-2' ? '#a78bfa' : '#34d399' }}>
                        {log.service_name}
                      </td>
                      <td>
                        <span className={`badge badge-${log.level.toLowerCase()}`}>
                          {log.level}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>{log.message}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}
