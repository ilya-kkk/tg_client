#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 'vless://...'" >&2
  exit 1
fi

VLESS_URL="$1"
OUT_FILE="${2:-config.json}"

python3 - "$VLESS_URL" "$OUT_FILE" <<'PY'
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse, unquote

vless_url = sys.argv[1]
out_file = Path(sys.argv[2])

parsed = urlparse(vless_url)
if parsed.scheme.lower() != "vless":
    raise SystemExit("Error: link must start with vless://")

if not parsed.username:
    raise SystemExit("Error: UUID is missing in VLESS URL")
if not parsed.hostname:
    raise SystemExit("Error: host is missing in VLESS URL")

params = {k: v[-1] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
uuid = parsed.username
server = parsed.hostname
port = parsed.port or 443

security = params.get("security", "tls")
transport_type = params.get("type", "tcp")
flow = params.get("flow", "")
sni = params.get("sni") or params.get("host") or server
fingerprint = params.get("fp", "chrome")
public_key = params.get("pbk", "")
short_id = params.get("sid", "")
path = unquote(params.get("path", ""))
host = params.get("host", "")
header_type = params.get("headerType", "")

outbound = {
    "type": "vless",
    "tag": "proxy",
    "server": server,
    "server_port": port,
    "uuid": uuid,
    "packet_encoding": "xudp",
}

if flow:
    outbound["flow"] = flow

tls = {"enabled": security in ("tls", "reality"), "server_name": sni}
if fingerprint:
    tls["utls"] = {"enabled": True, "fingerprint": fingerprint}
if security == "reality":
    tls["reality"] = {
        "enabled": True,
        "public_key": public_key,
        "short_id": short_id,
    }
outbound["tls"] = tls

if transport_type in ("ws", "grpc", "http"):
    transport = {"type": transport_type}
    if path:
        transport["path"] = path
    if host:
        transport["host"] = [host] if transport_type == "http" else host
    if header_type:
        transport["headers"] = {"type": header_type}
    outbound["transport"] = transport

config = {
    "log": {"level": "info"},
    "dns": {
        "servers": [
            {"tag": "cloudflare", "address": "https://1.1.1.1/dns-query", "detour": "proxy"},
            {"tag": "local", "address": "local"},
        ],
        "final": "cloudflare",
    },
    "inbounds": [
        {
            "type": "mixed",
            "tag": "mixed-in",
            "listen": "0.0.0.0",
            "listen_port": 1080,
        }
    ],
    "outbounds": [
        outbound,
        {"type": "direct", "tag": "direct"},
        {"type": "block", "tag": "block"},
    ],
    "route": {"auto_detect_interface": True, "final": "proxy"},
}

out_file.parent.mkdir(parents=True, exist_ok=True)
out_file.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

name = unquote(parsed.fragment) if parsed.fragment else "-"
print(f"Config updated: {out_file}")
print(f"Endpoint: {server}:{port}")
print(f"Name: {name}")
PY
