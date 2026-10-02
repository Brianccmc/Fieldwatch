# Mosquitto (LAN-only)

- Bind LAN/localhost only — **no public MQTT broker**.
- `allow_anonymous false`
- Password file on Pi only:
  - Preferred: `/etc/mosquitto/fieldwatch.passwd`
  - Also OK: `/home/brian/fieldwatch/mosquitto/fieldwatch.passwd`
- Create hub user (on Pi, not in git):

```bash
sudo mosquitto_passwd -c /etc/mosquitto/fieldwatch.passwd hub
sudo chown mosquitto:mosquitto /etc/mosquitto/fieldwatch.passwd
sudo chmod 640 /etc/mosquitto/fieldwatch.passwd
# point conf password_file at that path, then:
sudo systemctl restart mosquitto
```

Mirror the password into `/home/brian/fieldwatch/mqtt.passwd.env` for the hub service:

```
FIELDWATCH_MQTT_PASSWORD=...
```

chmod 600 that env file. Never commit it.
