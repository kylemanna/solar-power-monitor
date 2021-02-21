#!/bin/sh

# First argument is host, default to `rpi1`
host=${1:-rpi1}

while true; do 
    # Reads script via stdin so it's always up to date
    ssh $host python3 -u - < power-stream.py | \
        python3 -u bridge-influx.py | \
        jq -S .
    echo -e '\n\nRestarting\n\n'
    sleep 1
done 
