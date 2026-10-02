#!/bin/bash
# Run on the Pi as brian. Uses sudo for mosquitto + systemd.
# If PasswordAuthentication is off for SSH, feed local sudo via:
#   printf '%s\n' "$SUDO_PASS" | sudo -S -v
# before invoking, or export SUDO_PASS for this script.
set -euo pipefail
FW="${FIELDWATCH_HOME:-/home/brian/fieldwatch}"
FARM="$FW/farm"
VENV="$FW/venv"
DATA="$FW/data"
PASSWD_FILE="${MOSQUITTO_PASSWD_FILE:-/etc/mosquitto/fieldwatch.passwd}"
MQTT_USER="${FIELDWATCH_MQTT_USER:-hub}"

sudo_cmd() {
  if sudo -n true 2>/dev/null; then
    sudo "$@"
  elif [ -n "${SUDO_PASS:-}" ]; then
    printf '%s\n' "$SUDO_PASS" | sudo -S "$@"
  else
    sudo "$@"
  fi
}

echo "== Fieldwatch hub install =="
mkdir -p "$DATA" "$FW/mosquitto"

if [ ! -f "$FW/allowlist.json" ]; then
  cat > "$FW/allowlist.json" <<'JSON'
{"v":1,"notes":"Pi-local allowlist — add family MACs/SSIDs here. Not in git.","radios":[]}
JSON
  chmod 600 "$FW/allowlist.json"
fi

# Catalog subset (large; fetch if missing — do not block hub)
CAT="$FARM/catalog/fieldwatch-signatures-farm.json"
if [ ! -s "$CAT" ]; then
  echo "Fetching farm catalog subset…"
  mkdir -p "$FARM/catalog"
  curl -fsSL -o "$CAT" \
    "https://raw.githubusercontent.com/OffGridPete/Fieldwatch/v1.1.16/dist/fieldwatch-signatures-v2.json" \
    || echo "WARN: catalog fetch failed — classifier will be empty until present"
fi

python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$FARM/hub/requirements.txt"

ENV_FILE="$FW/mqtt.passwd.env"
if [ ! -f "$ENV_FILE" ]; then
  MQTT_PW="$(openssl rand -base64 18 | tr -d '/+=' | head -c 20)"
  umask 077
  printf 'FIELDWATCH_MQTT_PASSWORD=%s\n' "$MQTT_PW" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "Wrote $ENV_FILE"
else
  MQTT_PW="$(sed -n 's/^FIELDWATCH_MQTT_PASSWORD=//p' "$ENV_FILE" | head -1)"
fi

CONF_SRC="$FARM/mosquitto/fieldwatch.conf.example"
if [ -f "$CONF_SRC" ]; then
  TMP=$(mktemp)
  sed "s|/etc/mosquitto/fieldwatch.passwd|$PASSWD_FILE|" "$CONF_SRC" > "$TMP"
  sudo_cmd cp "$TMP" /etc/mosquitto/conf.d/fieldwatch.conf
  rm -f "$TMP"
fi

echo "Ensuring MQTT user '$MQTT_USER' in $PASSWD_FILE"
if [ ! -f "$PASSWD_FILE" ] || [ ! -s "$PASSWD_FILE" ]; then
  sudo_cmd mosquitto_passwd -b -c "$PASSWD_FILE" "$MQTT_USER" "$MQTT_PW"
else
  sudo_cmd mosquitto_passwd -b "$PASSWD_FILE" "$MQTT_USER" "$MQTT_PW"
fi
sudo_cmd chown mosquitto:mosquitto "$PASSWD_FILE" || sudo_cmd chown root:root "$PASSWD_FILE"
sudo_cmd chmod 640 "$PASSWD_FILE"

if [ -f /etc/mosquitto/passwd ] && [ ! -s /etc/mosquitto/passwd ]; then
  sudo_cmd mosquitto_passwd -b -c /etc/mosquitto/passwd "$MQTT_USER" "$MQTT_PW"
  sudo_cmd chown mosquitto:mosquitto /etc/mosquitto/passwd
  sudo_cmd chmod 640 /etc/mosquitto/passwd
fi

sudo_cmd systemctl restart mosquitto || true

sudo_cmd cp "$FARM/systemd/fieldwatch-hub.service" /etc/systemd/system/fieldwatch-hub.service
sudo_cmd systemctl daemon-reload
sudo_cmd systemctl enable --now fieldwatch-hub.service
sleep 3
systemctl --no-pager --full status fieldwatch-hub.service | head -40 || true
echo "--- health ---"
curl -fsS "http://127.0.0.1:8080/health" || true
echo
echo "HUD: http://192.168.4.24:8080/ (or http://192.168.0.24:8080/)"
echo "Mosquitto password file: $PASSWD_FILE"
echo "Done."
