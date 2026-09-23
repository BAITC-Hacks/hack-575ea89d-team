#!/usr/bin/env bash
# Run on the Brev Ubuntu VM after installing backend/requirements.txt.
set -euo pipefail
project_dir=$(cd "$(dirname "$0")/../.." && pwd)
service_user=$(id -un)
demo_lines=""
if [[ "${1:-}" == "--demo" ]]; then
  demo_lines="Environment=NETWORK_DATA_DIR=$project_dir/backend/.demo-data
ExecStartPre=$project_dir/backend/.venv/bin/python $project_dir/scripts/generate_demo.py --output $project_dir/backend/.demo-data"
elif [[ -n "${1:-}" ]]; then
  echo 'Usage: install-services.sh [--demo]' >&2
  exit 1
fi
if [[ "$project_dir" == *[[:space:]]* ]]; then
  echo 'Use a project directory without spaces.' >&2
  exit 1
fi
test -x "$project_dir/backend/.venv/bin/uvicorn"
test -f "$project_dir/frontend/index.html" || {
  echo 'Dashboard is missing. Deploy the reviewed frontend revision first.' >&2
  exit 1
}
if [[ ! -e "$project_dir/backend/.env" ]]; then
  (umask 077; cp "$project_dir/backend/.env.example" "$project_dir/backend/.env")
fi
sudo tee /etc/systemd/system/network-intelligence-api.service >/dev/null <<EOF
[Unit]
Description=Network Intelligence FastAPI
After=network-online.target
Wants=network-online.target

[Service]
User=$service_user
WorkingDirectory=$project_dir/backend
$demo_lines
ExecStart=$project_dir/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo tee /etc/systemd/system/network-intelligence-ui.service >/dev/null <<EOF
[Unit]
Description=Network Intelligence demo dashboard
After=network.target

[Service]
User=$service_user
WorkingDirectory=$project_dir/frontend
ExecStart=$project_dir/backend/.venv/bin/python -m http.server 5173 --bind 127.0.0.1 --directory $project_dir/frontend
Restart=on-failure
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now network-intelligence-api network-intelligence-ui
sudo systemctl restart network-intelligence-api network-intelligence-ui
sudo systemctl is-active network-intelligence-api network-intelligence-ui
