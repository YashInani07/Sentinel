# Sentinel — Distributed Log Aggregation & Alerting System

Sentinel is a distributed, containerized, and stateless log aggregation pipeline that collects logs from simulated microservices, provides dynamic query capabilities with a real sliding-window error count database engine, alerts on critical conditions, and visualizes status in a dark glassmorphic React dashboard.

---

## Architecture Diagram

```
                              +---------------------------------------+
                              |          Kubernetes Ingress           |
                              |              (Port 80)                |
                              +---------------------------------------+
                                 |         |                    |
            /                    |         |                    |
            |                    v         |                    v
            |             +------------+   |              +------------+
            |  Ingress    |  React     |   |   Ingress    |  Collector |
            |  Routing    |  Dashboard |   |   Routing    |  Service   |
            |             +------------+   |              +------------+
            |                              v                    |
    Clients |                       +------------+              |  Read/Write
    Browser |                       |   Alert    |              v
            |                       |  Service   |        +------------+
            |                       +------------+        | PostgreSQL |
            \                             |               +------------+
                                          |                     ^
                                          | Polls counts        | Ingests logs
                                          v                     |
                              +---------------------------------+
                              |       Internal Cluster Net      |
                              +---------------------------------+
                                      ^        ^        ^
                                      |        |        | POST /logs
                                    +---+    +---+    +---+
                                    |P-1|    |P-2|    |P-3|  (Distributed Producers)
                                    +---+    +---+    +---+
```

---

## Setup & Running Guide

### 🐳 Run with Docker Compose (Local Development)

The easiest way to boot the entire system locally is using Docker Compose.

1. **Start all services**:
   ```bash
   docker compose up --build -d
   ```
2. **Access the web dashboard**:
   Go to [http://localhost:8080](http://localhost:8080) in your browser.
3. **Verify the services**:
   *   **Collector API**: `http://localhost:8000` (e.g. `curl http://localhost:8000/logs`)
   *   **Alert Service API**: `http://localhost:8001` (e.g. `curl http://localhost:8001/alerts`)
   *   **Producers status**:
       *   Producer-1: `http://localhost:8011/status`
       *   Producer-2: `http://localhost:8012/status`
       *   Producer-3: `http://localhost:8013/status`

---

### ☸️ Run in Kubernetes (Kind Cluster)

To run the system in Kubernetes, follow these steps to build the local containers and apply the manifests:

1. **Verify your local cluster is running**:
   Ensure `kind` and `kubectl` are pointing to your cluster context (e.g. `kind-sentinel-cluster`).
2. **Build and Tag the Docker images**:
   ```bash
   docker build -t sentinel-collector:latest ./collector-service
   docker build -t sentinel-alerts:latest ./alert-service
   docker build -t sentinel-producer:latest ./producer
   docker build -t sentinel-dashboard:latest ./dashboard
   ```
3. **Load the Docker images into Kind**:
   ```bash
   kind load docker-image sentinel-collector:latest --name sentinel-cluster
   kind load docker-image sentinel-alerts:latest --name sentinel-cluster
   kind load docker-image sentinel-producer:latest --name sentinel-cluster
   kind load docker-image sentinel-dashboard:latest --name sentinel-cluster
   ```
4. **Ensure Ingress-Nginx controller is installed**:
   If not already running, install it via the official Kind deployment manifest:
   ```bash
   kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
   ```
   Wait for the controller pods to become ready:
   ```bash
   kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s
   ```
5. **Apply Sentinel manifests**:
   ```bash
   kubectl apply -f k8s/
   ```
6. **Verify Pod Statuses**:
   ```bash
   kubectl get pods
   ```
7. **Access the Ingress Controller locally**:
   If you created the Kind cluster with direct port mapping, go to `http://localhost/`. Otherwise, port-forward the ingress-nginx controller:
   ```bash
   kubectl port-forward -n ingress-nginx service/ingress-nginx-controller 9000:80
   ```
   *   Access the Dashboard: [http://localhost:9000/](http://localhost:9000/)
   *   Access Logs: [http://localhost:9000/api/collector/logs](http://localhost:9000/api/collector/logs)

---

## Sliding-Window Alerting Design

### Ingress & Routing
*   The system routes traffic under a unified Ingress on port 80/443. 
*   Paths prefixing `/api/collector` map to the collector, `/api/alerts` map to the alert-service, and `/api/producer-X` map to the corresponding producer replicas, with rewrite target annotations stripping the prefixes before hitting the pods.

### Database Aggregation
*   To keep application backends 100% stateless and support horizontal replication without state fragmentation, Sentinel delegates the sliding-window error count to PostgreSQL.
*   Every query dynamically computes a database cutoff:
    `cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)`
*   Then aggregates logs with the SQL query:
    ```sql
    SELECT service_name, COUNT(*) 
    FROM logs 
    WHERE level = 'ERROR' AND timestamp >= :cutoff 
    GROUP BY service_name;
    ```
*   **Indexing Optimization**: B-Tree indices are built on `(level, timestamp, service_name)` to allow database index-range scans, achieving `O(N_window)` evaluation instead of table scans.

### Throttling & Escalation
*   **Alert Cooldown**: To prevent notification spam, a 30-second cooldown is enforced per service.
*   **Severity Tiers**: Immediately overrides the cooldown if the error count escalates to a higher severity tier:
    *   **Tier 1 (Warning)**: `> 5` errors
    *   **Tier 2 (High)**: `> 20` errors
    *   **Tier 3 (Critical)**: `> 50` errors
    *   **Tier 4 (Disaster)**: `> 100` errors
*   **Resolved Alerts**: Active alerts remain in the dashboard banner, but once a service's sliding-window error count drops back below the threshold, the alert status dynamically transitions to a greyed-out **"RESOLVED"** visual state showing the current live count of `0`.
