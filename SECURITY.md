# SECURITY GUIDE

## 1) SSH hardening
- Create a non-root sudo user and disable direct root login (`PermitRootLogin no`).
- Disable password SSH auth and use keys only (`PasswordAuthentication no`).
- Change default SSH port only if your operations team can document it.
- Restart SSH carefully after validation to avoid lockout.

## 2) Firewall (UFW)
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
sudo ufw status
```

## 3) fail2ban
```bash
sudo apt update && sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban
sudo fail2ban-client status
```
- Keep default `sshd` jail enabled at minimum.

## 4) Admin password rules
- Minimum 12 characters (recommended 16+).
- Use a random password manager generated secret.
- Never reuse admin password across services.
- Rotate credentials immediately after suspected exposure.

## 5) API key protection
- Store keys only in `.env` on server (never commit).
- Restrict file permissions: `chmod 600 .env`.
- Rotate `OPENAI_API_KEY` and `PEXELS_API_KEY` if leaked.
- Do not print keys in logs or screenshots.

## 6) Backup rules
- Run DB backup at least daily and before updates.
- Keep 3-2-1 copies: local, separate disk/object store, offsite.
- Test restore monthly to verify backups are valid.
- Encrypt backup archives when moved off server.
