# Production Deployment Guide: Vercel + Railway

This guide walks you through deploying Project Sentinel in a production cloud environment, using **Vercel** for the React frontend, and **Railway** for the database, backend APIs, and background log producers.

---

## Step 1: Deploy Database & Backends on Railway

Railway is ideal for this project because it natively understands multi-service repositories and supports persistent background containers.

### 1. Create a Railway Account & Project
1. Go to [Railway.app](https://railway.app) and sign up with your GitHub account.
2. Click **New Project** -> **Deploy from GitHub repo** and select your Sentinel repository.

### 2. Add PostgreSQL Database
1. Inside your Railway project canvas, click **+ New** -> **Database** -> **Add PostgreSQL**.
2. Railway will spin up a Postgres instance and automatically generate a `DATABASE_URL` environment variable.

### 3. Deploy the Collector Service
1. Click **+ New** -> **GitHub Repo** -> select your Sentinel repository.
2. Rename this service to `collector-service` in the settings tab.
3. In the service **Settings** under *General*, set the **Root Directory** to `collector-service`.
4. In the service **Variables**, link the database:
   *   Add a variable named `DATABASE_URL` and select the value from your PostgreSQL database service reference (e.g. `${{ Postgres.DATABASE_URL }}`).
5. Under **Settings** -> **Public Networking**, click **Generate Domain**. Copy this URL (e.g., `https://collector-production.up.railway.app`).

### 4. Deploy the Alert Service
1. Click **+ New** -> **GitHub Repo** -> select your Sentinel repository.
2. Rename this service to `alert-service`.
3. In **Settings**, set the **Root Directory** to `alert-service`.
4. In **Variables**, add:
   *   `COLLECTOR_URL` = Your generated Collector domain (e.g., `https://collector-production.up.railway.app`)
   *   `ALERT_THRESHOLD` = `5`
   *   `POLL_INTERVAL` = `10`
5. Under **Settings** -> **Public Networking**, click **Generate Domain**. Copy this URL (e.g., `https://alerts-production.up.railway.app`).

### 5. Deploy the Producers (3 Replicas)
For each of the three producers (`producer-1`, `producer-2`, `producer-3`):
1. Click **+ New** -> **GitHub Repo** -> select your Sentinel repository.
2. Rename it (e.g. `sentinel-producer-1`).
3. In **Settings**, set the **Root Directory** to `producer`.
4. In **Variables**, add:
   *   `SERVICE_NAME` = `producer-1` (use `producer-2` and `producer-3` for the respective services)
   *   `COLLECTOR_URL` = Your generated Collector domain (e.g., `https://collector-production.up.railway.app`)
5. Under **Settings** -> **Public Networking**, click **Generate Domain**. You will need this domain to trigger spams from the dashboard. (e.g. `https://producer1-production.up.railway.app`).

---

## Step 2: Deploy Frontend on Vercel

### 1. Create a Vercel Project
1. Go to [Vercel.com](https://vercel.com) and log in with your GitHub account.
2. Click **Add New** -> **Project** and import your Sentinel repository.

### 2. Configure Build Settings
1. In the configuration page, set the **Root Directory** to `dashboard`.
2. Under **Framework Preset**, Vercel should automatically detect **Vite**.
3. Expand the **Environment Variables** section and add:
   *   `VITE_COLLECTOR_URL` = Your generated Railway Collector domain (e.g., `https://collector-production.up.railway.app`)
   *   `VITE_ALERT_URL` = Your generated Railway Alert domain (e.g., `https://alerts-production.up.railway.app`)
   *   `VITE_PRODUCER_1_URL` = Your generated Railway Producer 1 domain (e.g., `https://producer1-production.up.railway.app`)
   *   `VITE_PRODUCER_2_URL` = Your generated Railway Producer 2 domain (e.g., `https://producer2-production.up.railway.app`)
   *   `VITE_PRODUCER_3_URL` = Your generated Railway Producer 3 domain (e.g., `https://producer3-production.up.railway.app`)
4. Click **Deploy**.

Vercel will build the React static bundle with the production domains baked in, and serve it at a public `.vercel.app` URL.

---

## Step 3: Access and Test

1. Open your Vercel URL.
2. Verify that logs are flowing from the Railway producers into the dashboard table.
3. Test the spam injection by clicking **Spam Errors** on the UI. The request is routed to your Railway producer, which immediately spams your Railway collector, triggering Railway alert-service alerts live in your browser dashboard!
