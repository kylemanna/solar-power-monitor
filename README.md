# README

Early proof of concept for a Solar Power Monitor

    ssh $h python3 -u power-stream.py | python3 -u bridge-influx.py | jq -S .

