#!/bin/sh
# ipp-usb normally relies on udev hotplug, whose events never reach a container. So: run it in
# standalone mode and restart it whenever the set of USB devices changes (printer plugged or
# unplugged). A restart is a few seconds; CUPS retries the job (ErrorPolicy retry-job).
set -u
snapshot() { ls -R /dev/bus/usb 2>/dev/null | md5sum; }

pid=""
stop() { [ -n "$pid" ] && kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null; exit 0; }
trap stop TERM INT

last="$(snapshot)"
while :; do
    ipp-usb debug &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
        sleep 3
        now="$(snapshot)"
        if [ "$now" != "$last" ]; then
            echo "[entrypoint] USB device set changed: restarting ipp-usb"
            last="$now"
            kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
            break
        fi
    done
    kill -0 "$pid" 2>/dev/null || { wait "$pid" 2>/dev/null; echo "[entrypoint] ipp-usb exited, restarting in 3s"; sleep 3; }
done
