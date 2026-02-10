#!/usr/bin/env bash
set -euo pipefail

mkdir -p /root/tset
cd /root/tset

apt update
apt install -y python3 python3-venv python3-pip

python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt

echo "[OK] Installed dependencies."
echo "Next: cp .env.example .env && edit TENANT_ID/CLIENT_ID"
