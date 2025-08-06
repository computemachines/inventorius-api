#!/bin/sh
sentinel=/var/lib/sshport.once
[ -f "$sentinel" ] && exit 0

apk update
apk add git
git clone https://github.com/computemachines/inventorius.git /opt/inventorius

sed -i '/^#\?Port /d' /etc/ssh/sshd_config
sed -i '1iPort 48231' /etc/ssh/sshd_config
iptables -I INPUT -p tcp --dport 48231 -m conntrack --ctstate NEW -j ACCEPT
iptables -D INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null
rc-service iptables save
rc-service sshd restart
touch "$sentinel"
