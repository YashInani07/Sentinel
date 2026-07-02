# Sentinel — Distributed Log Aggregation & Alerting System

Sentinel is a distributed, containerized, and stateless log aggregation pipeline that collects logs from simulated microservices, provides dynamic query capabilities with a real sliding-window error count database engine, alerts on critical conditions, and visualizes status in a dark glassmorphic React dashboard.

This repository is ready to be cloned and run locally. Follow the instructions below to get started.

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

## How to Run & Access Locally (GitHub Guide)

To clone this repository and run Sentinel on your machine, choose one of the two deployment methods below.

### Prerequisites
*   [Docker Desktop](https://www.docker.com/products/docker-desktop/) or [Colima](https://github.com/abiosoft/colima) installed and running.
*   *Optional (for Kubernetes deployment)*: [kubectl](https://kubernetes.io/docs/tasks/tools/) and [Kind](https://kind.sigs.k8s.io/) or [Minikube](https://minikube.sigs.k8s.io/docs/start/).

---

### 🐳 Method 1: Running with Docker Compose (Fastest)

This boots up the complete stack (Postgres Database, Collector, 3x Producers, Alert Service, and Dashboard) in containers on your local network.

1.  **Clone the repository**:
    ```bash
    git clone <your-repository-url>
    cd sentinel
    ```
2.  **Start all services**:
    ```bash
    docker compose up --build -d
    ```
3.  **Access the Dashboard**:
    Open [http://localhost:8080](http://localhost:8080) in your browser.
4.  **Local Endpoints**:
    *   **Logs Collector Service**: [http://localhost:8000/logs](http://localhost:8000/logs)
    *   **Alerting Service**: [http://localhost:8001/alerts](http://localhost:8001/alerts)
    *   **Producer 1 Status / Controls**: [http://localhost:8011/status](http://localhost:8011/status)
    *   **Producer 2 Status / Controls**: [http://localhost:8012/status](http://localhost:8012/status)
    *   **Producer 3 Status / Controls**: [http://localhost:8013/status](http://localhost:8013/status)

---

### ☸️ Method 2: Running in Kubernetes (Kind Cluster)

This deploys Sentinel inside a local Kubernetes cluster behind an Ingress Controller, exactly mimicking a production cloud environment.

1.  **Start your local cluster** (using Kind):
    ```bash
    kind create cluster --name sentinel-cluster
    ```
2.  **Build and Tag Docker images**:
    ```bash
    docker build -t sentinel-collector:latest ./collector-service
    docker build -t sentinel-alerts:latest ./alert-service
    docker build -t sentinel-producer:latest ./producer
    docker build -t sentinel-dashboard:latest ./dashboard
    ```
3.  **Load the images into your Kind cluster**:
    ```bash
    kind load docker-image sentinel-collector:latest --name sentinel-cluster
    kind load docker-image sentinel-alerts:latest --name sentinel-cluster
    kind load docker-image sentinel-producer:latest --name sentinel-cluster
    kind load docker-image sentinel-dashboard:latest --name sentinel-cluster
    ```
4.  **Install Ingress-Nginx Controller** (Kind-specific configuration):
    ```bash
    kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml
    ```
    Wait for the ingress pods to be fully ready:
    ```bash
    kubectl wait --namespace ingress-nginx --for=condition=ready pod --selector=app.kubernetes.io/component=controller --timeout=120s
    ```
5.  **Deploy Sentinel applications**:
    ```bash
    kubectl apply -f k8s/
    ```
6.  **Verify Pod Statuses**:
    Ensure all pods reach the `Running` state:
    ```bash
    kubectl get pods
    ```
7.  **Access the System**:
    Port-forward the Ingress Controller to your local machine:
    ```bash
    kubectl port-forward -n ingress-nginx service/ingress-nginx-controller 9000:80
    ```
    *   **React Dashboard**: [http://localhost:9000/](http://localhost:9000/)
    *   **Aggregated Logs**: [http://localhost:9000/api/collector/logs](http://localhost:9000/api/collector/logs)
    *   **Fired Alerts**: [http://localhost:9000/api/alerts/alerts](http://localhost:9000/api/alerts/alerts)

---

## Demo: Testing the Alerting Loop

Once the app is running (on port `8080` for Docker Compose or port `9000` via Kubernetes Ingress):

1.  Open the web dashboard in your browser.
2.  Locate the **Spam Error Injection** panel and click **Spam Errors** on `producer-1` (or run a curl to start the burst):
    *   *Docker Compose*: `curl -X POST http://localhost:8011/spam-errors/start`
    *   *Kubernetes Ingress*: `kubectl exec deploy/sentinel-dashboard -- curl -s -X POST http://sentinel-producer-1-service:8000/spam-errors/start`
3.  You will see live red `ERROR` logs stream in. The error count on the left will spike.
4.  As the count escalates, the Alert Service will immediately flag the service and post warnings to the **Active System Alerts** banner at the top of the dashboard.
5.  Click **Stop Spam** (or stop via curl).
6.  Once the 60-second sliding window passes, the error metric drops back to `0` and the alert banners automatically transition to a green, greyed-out **`[RESOLVED]`** state.

---

## Sliding-Window Alerting Design

### Ingress Routing & Path Rewrites
All services run behind an Ingress Controller. The Ingress routes path requests (e.g. `/api/collector`) and rewrites them dynamically to strip off prefixes before reaching the target backend microservices, allowing a single entry point.

### Database Aggregation
Sentinel aggregates error metrics using PostgreSQL instead of stateful RAM buffers. This keeps the application servers stateless and allows them to scale horizontally. The query dynamically computes a 60-second sliding window threshold:
```sql
SELECT service_name, COUNT(*) 
FROM logs 
WHERE level = 'ERROR' AND timestamp >= NOW() - INTERVAL '60 seconds' 
GROUP BY service_name;
```
Indices on `(level, timestamp, service_name)` optimize this aggregation to index-range scans.

### Cooldowns & Severity Escalation
To prevent alert fatigue, a **30-second cooldown** is enforced per service. However, if a surge climbs rapidly across severity tiers, the cooldown is bypassed to alert immediately:
*   **Tier 1 (Warning)**: `> 5` errors
*   **Tier 2 (High)**: `> 20` errors
*   **Tier 3 (Critical)**: `> 50` errors
*   **Tier 4 (Disaster)**: `> 100` errors
