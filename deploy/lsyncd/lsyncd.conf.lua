-- Secure Download - lsyncd双方向同期設定
-- /etc/lsyncd/lsyncd.conf.lua
--
-- 設定手順:
-- 1. 両VPS間でSSH鍵認証を設定（プライベートNW経由）
-- 2. このファイルを /etc/lsyncd/lsyncd.conf.lua に配置
-- 3. sudo systemctl enable --now lsyncd

settings {
    logfile = "/var/log/lsyncd/lsyncd.log",
    statusFile = "/var/log/lsyncd/lsyncd.status",
    statusInterval = 20,
    nodaemon = false,
    maxProcesses = 4,
}

-- ファイルストレージの同期（相手VPSへ）
-- ${PEER_PRIVATE_IP} を実際のプライベートIPに変更すること
sync {
    default.rsync,
    source = "/var/secure-download/files/",
    target = "app-user@${PEER_PRIVATE_IP}:/var/secure-download/files/",
    delay = 1,
    rsync = {
        binary = "/usr/bin/rsync",
        archive = true,
        compress = false,  -- プライベートNW内なので圧縮不要
        rsh = "/usr/bin/ssh -p 22 -i /home/app-user/.ssh/id_ed25519 -o StrictHostKeyChecking=no",
    },
}
