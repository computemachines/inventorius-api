#!/bin/sh

sentinel=/var/lib/sshport.once
[ -f "$sentinel" ] && exit 0

# --- Install system packages ---
apk update
apk add git nodejs npm py3-pip uwsgi uwsgi-python3 nginx

# --- Clone application repo ---
git clone https://github.com/computemachines/inventorius.git /opt/inventorius

# --- Backend setup ---
python3 -m pip install -r /opt/inventorius/inventorius-api/requirements.txt || true

# --- Frontend setup ---
cd /opt/inventorius/inventorius-frontend || exit 1
npm install || true

# --- Start backend via uWSGI ---
uwsgi --plugin python3 \
      --socket /var/run/uwsgi-inventorius-api.sock \
      --chdir /opt/inventorius/inventorius-api/src \
      --module inventorius:app \
      --chmod-socket=666 \
      --daemonize /var/log/uwsgi-inventorius.log

# --- Configure and start nginx ---
cp /opt/inventorius/inventorius_api.nginx.conf /etc/nginx/http.d/inventorius_api.conf
rm /etc/nginx/http.d/default.conf 2>/dev/null || true
nginx

# --- Start frontend dev server ---
cd /opt/inventorius/inventorius-frontend || exit 1
npm start &

# --- Configure SSH ---
sed -i '/^#\?Port /d' /etc/ssh/sshd_config
sed -i '1iPort 48231' /etc/ssh/sshd_config
iptables -I INPUT -p tcp --dport 48231 -m conntrack --ctstate NEW -j ACCEPT
iptables -D INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null
rc-service iptables save
rc-service sshd restart

touch "$sentinel"
