#!/usr/bin/env bash
set -euo pipefail

# Run as the ubuntu user on the OCI Ampere VM with sudo access.
repo_dir=/home/ubuntu/meridian-bank
backend_dir="$repo_dir/backend"
container_name=meridian-api

deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ ! -r "$deploy_dir/nginx-meridian.conf" ]]; then
    printf 'Keep nginx-meridian.conf alongside this script.\n' >&2
    exit 1
fi

# 1. Install the host dependencies and start Docker.
sudo apt-get update
sudo apt-get install -y docker.io nginx git curl
sudo systemctl enable --now docker

# 2. Clone the repository on first run. Reuse the checkout on subsequent runs.
if [[ ! -d "$repo_dir/.git" ]]; then
    git clone https://github.com/nvadde/meridian-bank.git "$repo_dir"
fi

# 3. Stage the real .env and extracted wallet on the VM, then rerun.
# Use the deployment .env.example as a template. Keep WALLET_LOC and CONFIG_DIR
# set to /app/wallet. Keep the real .env and wallet outside Git.
if [[ ! -r "$backend_dir/.env" || ! -r "$backend_dir/wallet/tnsnames.ora" || ! -r "$backend_dir/wallet/ewallet.pem" ]]; then
    printf 'Place the real .env and extracted Oracle wallet in %s, then rerun.\n' "$backend_dir" >&2
    exit 1
fi
sudo chmod 600 "$backend_dir/.env"

# 4. Build the image on the VM using backend/ as the build context.
cd "$backend_dir"
sudo docker build -t meridian-backend .

# 5. Start the API on the VM loopback interface. Keep TCP 8000 out of OCI ingress rules.
if sudo docker container inspect "$container_name" >/dev/null 2>&1; then
    printf 'Container %s already exists. Verify it before replacing it.\n' "$container_name" >&2
    exit 1
fi
sudo docker run -d --name meridian-api --restart always \
    -p 127.0.0.1:8000:8000 \
    -v /home/ubuntu/meridian-bank/backend/wallet:/app/wallet:ro \
    -v /home/ubuntu/meridian-bank/backend/.env:/opt/meridian/backend/.env:ro \
    --env-file /home/ubuntu/meridian-bank/backend/.env \
    meridian-backend

# 6. Verify Oracle connectivity before enabling the reverse proxy.
curl --fail --silent --show-error --retry 10 --retry-connrefused \
    --max-time 10 http://127.0.0.1:8000/health
printf '\n'

# 7. Enable the Nginx site from the deployment files beside this script.
sudo install -m 0644 "$deploy_dir/nginx-meridian.conf" /etc/nginx/sites-available/meridian
sudo ln -sfn /etc/nginx/sites-available/meridian /etc/nginx/sites-enabled/meridian
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
