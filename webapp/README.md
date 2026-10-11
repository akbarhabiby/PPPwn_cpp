# PPPwn web control panel

A small web frontend to start/stop a PPPwn process, show its exact command, stream stdout, and display best-effort stage progress. Local development uses `.env` loaded by `python-dotenv`; no database is used.

## Local development with dotenv

From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your actual binary, payload paths, and interface
python webapp/server.py
```

The server loads `.env` from the repository root. Existing environment variables take precedence over `.env` values. The interface selector is populated dynamically from `pppwn list` on the local host. Open the configured `WEB_HOST` and `WEB_PORT` (defaults: `127.0.0.1:8080`).

## Docker and networking warning

Run this container on a **Linux host** with the PS4 connected to a physical network interface available to the container. Compose uses host networking and grants `NET_RAW` / `NET_ADMIN` capabilities for packet capture/injection. Docker Desktop on macOS/Windows runs containers inside a Linux VM and generally cannot expose the Mac's physical `en7` interface to libpcap; use a Linux machine or pass through a dedicated adapter to a Linux VM.

Place payloads at `payloads/stage1.bin` and `payloads/stage2.bin`. Configure your Linux interface (find it with `ip -br link`) and firmware in `.env`, then start:

```sh
docker compose up --build -d
```

Open `http://<linux-host-ip>:8080`. The interface selector is populated by running `pppwn list` inside the container, so it shows only interfaces visible to PPPwn there. Choose the PS4-connected interface and start the run. Stop with `docker compose down`; inspect server logs with `docker compose logs -f`.

Do not expose this unauthenticated control panel to an untrusted network. It can start the preconfigured PPPwn process with raw-network capabilities.
