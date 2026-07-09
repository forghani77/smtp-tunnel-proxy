#!/bin/bash
#
# SMTP Tunnel Proxy - Uninstall Script
#
# Removes the server while preserving /etc/smtp-tunnel config.
# To also remove config: rm -rf /etc/smtp-tunnel
#
# Version: 1.4.0

set -e

echo "Stopping service..."
systemctl stop smtp-tunnel 2>/dev/null || true
systemctl disable smtp-tunnel 2>/dev/null || true

echo "Removing files..."
rm -f /etc/systemd/system/smtp-tunnel.service
rm -f /usr/local/bin/smtp-tunnel-adduser
rm -f /usr/local/bin/smtp-tunnel-deluser
rm -f /usr/local/bin/smtp-tunnel-listusers
rm -f /usr/local/bin/smtp-tunnel-update
rm -rf /opt/smtp-tunnel

systemctl daemon-reload

echo ""
echo "SMTP Tunnel Proxy uninstalled successfully."
echo ""
echo "Note: Configuration in /etc/smtp-tunnel was NOT removed."
echo "Remove manually if needed:"
echo "  rm -rf /etc/smtp-tunnel"
