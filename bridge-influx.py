#!/usr/bin/env python3

import datetime
import fileinput
import influxdb
import json

def make_measurement(timestamp, name, fields):
    d = {
        'measurement': 'power',
        'tags': { 'entity_id': name, 'domain': 'sensor', 'sensor': 'ina3221' },
        'time': str(timestamp),
        'fields': fields
    }
    return d

def send_measurement(client, name, raw_data, timestamp, verbose = True):
    data = []
    for ch, fields in raw_data.items():
        if ch.startswith('@'): continue
        data += [make_measurement(timestamp, f"{name}.{ch}", fields)]

    if verbose:
        print(json.dumps(data))

    return client.write_points(data)

if __name__ == '__main__':
    # Load configuration
    with open('config.json', 'r') as fp:
        config = json.load(fp)

    name = config['name']
    client = influxdb.InfluxDBClient(**config['influx'])

    for line in fileinput.input():
        raw_data = json.loads(line)
        sample_time = datetime.datetime.fromisoformat(raw_data['@time'])
        names = tuple(filter(lambda x: not x.startswith('@'), raw_data.keys()))
        result = send_measurement(client, name, raw_data, sample_time, verbose=True)
