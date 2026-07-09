# 📧 SMTP Tunnel Proxy

> **A high-speed covert tunnel that disguises TCP traffic as SMTP email communication to bypass Deep Packet Inspection (DPI) firewalls.**

```
┌─────────────┐      ┌─────────────┐      ┌─────────────┐      ┌──────────────┐
│ Application │─────▶│   Client    │─────▶│   Server    │─────▶│  Destination │
│  (Browser)  │ TCP  │  Forward:   │ SMTP │  Port 587   │ TCP  │  port:2090   │
│             │◀─────│  port:2090  │◀─────│             │◀─────│              │
└─────────────┘      └─────────────┘      └─────────────┘      └──────────────┘
                            │                    │
                            │   Looks like       │
                            │   Email Traffic    │
                            ▼                    ▼
                     ┌────────────────────────────────┐
                     │     DPI Firewall               │
                     │  ✅ Sees: Normal SMTP Session  │
                     │  ❌ Cannot see: Tunnel Data    │
                     └────────────────────────────────┘
```

---

## 🎯 Features

| Feature | Description |
|---------|-------------|
| 🔒 **TLS Encryption** | All traffic encrypted with TLS 1.2+ after STARTTLS |
| 🎭 **DPI Evasion** | Initial handshake mimics real SMTP servers (Postfix) |
| ⚡ **High Speed** | Binary streaming protocol after handshake - minimal overhead |
| 👥 **Multi-User** | Per-user secrets, IP whitelists, and logging settings |
| 🔑 **Authentication** | Per-user pre-shared keys with HMAC-SHA256 |
| 🌐 **Port Forwarding** | Forward any local port through the tunnel to any destination |
| 📡 **Multiplexing** | Multiple connections over single tunnel |
| 🛡️ **IP Whitelist** | Per-user access control by IP address/CIDR |
| 📦 **Easy Install** | One-liner server installation with systemd service |
| 🎁 **Client Packages** | Auto-generated ZIP files for each user |
| 🔄 **Auto-Reconnect** | Client automatically reconnects on connection loss |

> 📚 For in-depth technical details, protocol specifications, and security analysis, see [TECHNICAL.md](TECHNICAL.md).

---

## ⚡ Quick Start

### 📋 Prerequisites

- **Server**: Linux VPS with Python 3.8+, port 587 open
- **Client**: Windows/macOS/Linux with Python 3.8+
- **Domain name**: Required for TLS certificate verification (free options: [DuckDNS](https://www.duckdns.org), [No-IP](https://www.noip.com), [FreeDNS](https://freedns.afraid.org))

---

## 🚀 Server Setup (VPS)

### Step 1️⃣: Get a Domain Name

Get a free domain pointing to your VPS:
- 🦆 **[DuckDNS](https://www.duckdns.org)** - Recommended, simple and free
- 🌐 **[No-IP](https://www.noip.com)** - Free tier available
- 🆓 **[FreeDNS](https://freedns.afraid.org)** - Many domain options

Example: `myserver.duckdns.org` → `203.0.113.50` (your VPS IP)

### Step 2️⃣: Run the Installer

```bash
curl -sSL https://raw.githubusercontent.com/forghani77/smtp-tunnel-proxy/main/install.sh | sudo bash
```

The installer will:
1. 📥 Download and install everything
2. ❓ Ask for your domain name
3. 🔐 Generate TLS certificates automatically
4. 👤 Offer to create your first user
5. 🔥 Configure firewall
6. 🚀 Start the service

**That's it!** Your server is ready.

### ➕ Add More Users Later

```bash
smtp-tunnel-adduser bob      # Add user + generate client ZIP
smtp-tunnel-listusers        # List all users
smtp-tunnel-deluser bob      # Remove a user
```

### 🔄 Update Server

```bash
smtp-tunnel-update           # Updates code, preserves config/certs/users
```

---

## 💻 Client Setup

### Option A: Easy Way (Recommended)

1. Get your `username.zip` file from the server admin
2. Extract the ZIP file
3. Run the launcher:

| Platform | How to Run |
|----------|------------|
| 🪟 **Windows** | Double-click `start.bat` |
| 🐧 **Linux** | Run `./start.sh` |
| 🍎 **macOS** | Run `./start.sh` |

The launcher will automatically install dependencies and start the client.

✅ You should see:
```
SMTP Tunnel Client - Port Forwarding Mode
User: alice

[INFO] Starting SMTP Tunnel...
Connecting to myserver.duckdns.org:587
Connected - binary mode active
Listening on 127.0.0.1:2090 -> 127.0.0.1:2090
```

### Option B: Manual Way

```bash
cd alice
pip install --break-system-packages -r requirements.txt
python client.py
```

### Option C: Custom Configuration

```bash
# Download files
scp root@myserver.duckdns.org:/etc/smtp-tunnel/ca.crt .

# Create config.yaml:
cat > config.yaml << EOF
client:
  server_host: "myserver.duckdns.org"
  server_port: 587
  listen_port: 2090
  forward_host: "127.0.0.1"
  forward_port: 2090
  username: "alice"
  secret: "your-secret-from-admin"
  ca_cert: "ca.crt"
EOF

# Run client
python client.py -c config.yaml
```

---

## 📖 Usage

### 🔀 Client Modes

The client supports two modes: **port forward** (fixed target) and **SOCKS5 proxy** (dynamic target).

#### Port Forward Mode

```bash
# Forward local port 2090 to a service on the server's localhost
python client.py --mode forward --listen-port 2090 --forward-host 127.0.0.1 --forward-port 2090

# Forward local port 8080 to an internal web server
python client.py --mode forward --listen-port 8080 --forward-host 10.0.0.5 --forward-port 80

# Expose on 0.0.0.0 so other machines on your LAN can connect
python client.py --mode forward --listen-host 0.0.0.0 --listen-port 2090 --forward-host 127.0.0.1 --forward-port 2090
```

#### SOCKS5 Proxy Mode

```bash
# Listen as SOCKS5 proxy on default port 1080
python client.py --mode socks

# Listen on a different port/interface
python client.py --mode socks --listen-host 0.0.0.0 --listen-port 8888
```

### ✅ Test Connection

```bash
# Connect to a service forwarded through the tunnel
curl http://127.0.0.1:8080
telnet 127.0.0.1 2090
```

---

## ⚙️ Configuration Reference

### 🖥️ Server Options (`config.yaml`)

| Option | Description | Default |
|--------|-------------|---------|
| `host` | Listen interface | `0.0.0.0` |
| `port` | Listen port | `587` |
| `hostname` | SMTP hostname (must match certificate) | `mail.example.com` |
| `cert_file` | TLS certificate path | `server.crt` |
| `key_file` | TLS private key path | `server.key` |
| `users_file` | Path to users configuration | `users.yaml` |
| `log_users` | Global logging setting | `true` |

### 👥 User Options (`users.yaml`)

Each user can have individual settings:

```yaml
users:
  alice:
    secret: "auto-generated-secret"
    # whitelist:              # Optional: restrict to specific IPs
    #   - "192.168.1.100"
    #   - "10.0.0.0/8"        # CIDR notation supported
    # logging: true           # Optional: disable to stop logging this user

  bob:
    secret: "another-secret"
    whitelist:
      - "203.0.113.50"        # Bob can only connect from this IP
    logging: false            # Don't log Bob's activity
```

| Option | Description | Default |
|--------|-------------|---------|
| `secret` | User's authentication secret | Required |
| `whitelist` | Allowed IPs for this user (CIDR supported) | All IPs |
| `logging` | Enable activity logging for this user | `true` |

### 💻 Client Options

| Option | Description | Default |
|--------|-------------|---------|
| `server_host` | Server domain name | Required |
| `server_port` | Server port | `587` |
| `mode` | Client mode: `forward` or `socks` | `forward` |
| `listen_port` | Local port to listen on | `1080` |
| `listen_host` | Local interface to bind to | `127.0.0.1` |
| `forward_host` | Destination host (forward mode, reachable from server) | Required |
| `forward_port` | Destination port (forward mode) | Required |
| `username` | Your username | Required |
| `secret` | Your authentication secret | Required |
| `ca_cert` | CA certificate for verification | Recommended |

---

## 📋 Service Management

```bash
# Check status
sudo systemctl status smtp-tunnel

# Restart after config changes
sudo systemctl restart smtp-tunnel

# View logs
sudo journalctl -u smtp-tunnel -n 100

# Uninstall
sudo /opt/smtp-tunnel/uninstall.sh
```

---

## 🔧 Command Line Options

### 🖥️ Server
```bash
python server.py [-c CONFIG] [-d]

  -c, --config    Config file (default: config.yaml)
  -d, --debug     Enable debug logging
```

### 💻 Client
```bash
python client.py [-c CONFIG] [--server HOST] [--server-port PORT]
                 [--mode forward|socks] [-p LISTEN_PORT]
                 [--listen-host HOST] [--forward-host HOST]
                 [--forward-port PORT] [-u USERNAME] [-s SECRET]
                 [--ca-cert FILE] [-d]

  -c, --config        Config file (default: config.yaml)
  --server            Override server domain
  --server-port       Override server port
  --mode              Client mode: forward or socks (default: forward)
  -p, --listen-port   Local port to listen on
  --listen-host       Local interface to bind to
  --forward-host      Forward destination host (forward mode)
  --forward-port      Forward destination port (forward mode)
  -u, --username      Your username
  -s, --secret        Override secret
  --ca-cert           CA certificate path
  -d, --debug         Enable debug logging
```

### 👥 User Management
```bash
smtp-tunnel-adduser <username> [-u USERS_FILE] [-c CONFIG]
                     [--mode forward|socks] [--listen-host HOST]
                     [--forward-host HOST] [--forward-port PORT]
                     [--no-package]
    Add a new user and generate client package

smtp-tunnel-deluser <username> [-u USERS_FILE] [-f]
    Remove a user (use -f to skip confirmation)

smtp-tunnel-listusers [-u USERS_FILE] [-v]
    List all users (use -v for detailed info)

smtp-tunnel-update
    Update server to latest version (preserves config/certs/users)
```

---

## 📁 File Structure

```
smtp_proxy/
├── 📄 server.py               # Server (runs on VPS)
├── 📄 client.py               # Client (runs locally)
├── 📄 common.py               # Shared utilities
├── 📄 generate_certs.py       # Certificate generator
├── 📄 config.yaml             # Server/client configuration
├── 📄 users.yaml              # User database
├── 📄 requirements.txt        # Python dependencies
├── 📄 install.sh              # One-liner server installer
├── 📄 smtp-tunnel.service     # Systemd unit file
├── 🔧 smtp-tunnel-adduser     # Add user script
├── 🔧 smtp-tunnel-deluser     # Remove user script
├── 🔧 smtp-tunnel-listusers   # List users script
├── 🔧 smtp-tunnel-update      # Update server script
├── 🔧 uninstall.sh            # Uninstall script
├── 📄 README.md               # This file
└── 📄 TECHNICAL.md            # Technical documentation
```

### 📦 Installation Paths (after install.sh)

```
/opt/smtp-tunnel/              # Application files
  ├── server.py
  ├── client.py
  ├── common.py
  ├── uninstall.sh
/etc/smtp-tunnel/              # Configuration files
  ├── config.yaml
  ├── users.yaml
  ├── server.crt
  ├── server.key
  └── ca.crt
/usr/local/bin/                # Management commands
  ├── smtp-tunnel-adduser
  ├── smtp-tunnel-deluser
  ├── smtp-tunnel-listusers
  └── smtp-tunnel-update
```

---

## 🔧 Troubleshooting

### ❌ "Connection refused"
- Check server is running: `systemctl status smtp-tunnel` or `ps aux | grep server.py`
- Check port is open: `netstat -tlnp | grep 587`
- Check firewall: `ufw status`

### ❌ "Auth failed"
- Verify `username` and `secret` match in users.yaml
- Check server time is accurate (within 5 minutes)
- Run `smtp-tunnel-listusers -v` to verify user exists

### ❌ "IP not whitelisted"
- Check user's whitelist in users.yaml
- Your current IP must match a whitelist entry
- CIDR notation is supported (e.g., `10.0.0.0/8`)

### ❌ "Certificate verify failed"
- Ensure you're using a domain name, not IP address
- Verify `server_host` matches the certificate hostname
- Ensure you have the correct `ca.crt` from the server

### 🐛 Debug Mode

```bash
# Enable detailed logging
python server.py -d
python client.py -d

# View systemd logs
journalctl -u smtp-tunnel -f
```

---

## 🔐 Security Notes

- ✅ **Always use a domain name** for proper TLS verification
- ✅ **Always use `ca_cert`** to prevent man-in-the-middle attacks
- ✅ **Use `smtp-tunnel-adduser`** to generate strong secrets automatically
- ✅ **Use per-user IP whitelists** if you know client IPs
- ✅ **Protect `users.yaml`** - contains all user secrets (chmod 600)
- ✅ **Disable logging** for sensitive users with `logging: false`

> 📚 For detailed security analysis and threat model, see [TECHNICAL.md](TECHNICAL.md).

---

## 📄 License

This project is provided for educational and authorized use only. Use responsibly and in accordance with applicable laws.

---

## ⚠️ Disclaimer

This tool is designed for legitimate privacy and censorship circumvention purposes. Users are responsible for ensuring their use complies with applicable laws and regulations.

---

*Made with ❤️ for internet freedom*
