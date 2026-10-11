# PPPwn web control panel

A small web frontend to start/stop a PPPwn process, show its exact command, stream stdout, and display best-effort stage progress. Local development uses `.env` loaded by `python-dotenv`; no database is used.

## Local development

From the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with local binary, payload paths, and interface
python webapp/server.py
```

The selector lists interfaces visible to PPPwn on that machine. Open `http://127.0.0.1:8080` by default.

## Build and export for a Linux x86_64 server

The Docker image must target `linux/amd64` even if you build it on an Apple Silicon Mac. From the repository root:

```sh
docker buildx build --platform linux/amd64 --load -t pppwn-web:linux-amd64 .
docker save pppwn-web:linux-amd64 -o pppwn-web-linux-amd64.tar
scp pppwn-web-linux-amd64.tar user@your-server:/tmp/
```

On the server, install/load the image:

```sh
sudo docker load -i /tmp/pppwn-web-linux-amd64.tar
```

Copy `docker-compose.yml` to a deployment directory on the server. Place the stage payloads there as `payloads/stage1.bin` and `payloads/stage2.bin`, then configure the interface name and firmware in a `.env` file:

```sh
mkdir -p ~/pppwn-deploy/payloads
# copy docker-compose.yml and the two payload files into ~/pppwn-deploy
cd ~/pppwn-deploy
cat > .env <<'EOF'
PPPWN_INTERFACE=enp3s0
PPPWN_FIRMWARE=1100
EOF
```

Set `PPPWN_INTERFACE` to the Linux interface connected to the PS4. Find candidate names with `ip -br link`. Start the already-loaded image:

```sh
sudo docker compose up -d
sudo docker compose logs -f
```

Compose uses `network_mode: host`, so on the Linux server the web UI listens on port 8080 and PPPwn can see host interfaces. Open `http://<server-ip>:8080`, then select the interface in the UI. Do not expose this unauthenticated control panel to an untrusted network.

Stop it with `sudo docker compose down`. The image is tagged `pppwn-web:linux-amd64`; Compose does not build or pull it on the server.

## Linux networking note

Docker host networking is necessary here so PPPwn can access the PS4-connected interface. Docker Desktop on macOS runs containers in a Linux VM and does not expose the Mac's physical Ethernet interface in the same way. Use the Mac for cross-building/exporting the image, and use the Linux x86_64 server for actual PPPwn runs.
