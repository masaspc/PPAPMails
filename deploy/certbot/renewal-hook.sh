#!/bin/bash
# SSL証明書更新後フック
# /etc/letsencrypt/renewal-hooks/deploy/tbn-reload.sh

# Nginx再読み込み
systemctl reload nginx

# Postfix再読み込み（TLS証明書更新反映）
systemctl reload postfix

echo "$(date): SSL certificate renewed and services reloaded" >> /var/log/tbn-secure-download/certbot-renewal.log
