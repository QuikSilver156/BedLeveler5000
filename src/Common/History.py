#!/usr/bin/env python
""" Saves every 'Probe all' run to a CSV file so runs can be compared over time. """

from PySide6 import QtCore
import csv
import datetime
import pathlib

FIELDS = ['timestamp', 'printer', 'point', 'x', 'y', 'z', 'samples', 'spread']

def historyDir():
    location = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation)
    path = pathlib.Path(location) if location else pathlib.Path.home() / '.BedLeveler5000'
    path.mkdir(parents=True, exist_ok=True)
    return path

def historyFile():
    return historyDir() / 'probe_history.csv'

def _readRows():
    path = historyFile()
    if not path.exists():
        return []
    with open(path, newline='') as file:
        return list(csv.DictReader(file))

def lastRun(printerName):
    """ Returns (timestamp, {point name: z}) for the most recent run, or None. """
    rows = [row for row in _readRows() if row.get('printer') == printerName]
    if not rows:
        return None

    timestamp = rows[-1]['timestamp']
    values = {}
    for row in rows:
        if row['timestamp'] == timestamp:
            try:
                values[row['point']] = float(row['z'])
            except (KeyError, ValueError):
                pass
    return timestamp, values

def appendRun(printerName, results, samples=1, spreads=None):
    """ results: list of NamedPoint3F. spreads: optional {point name: spread}. """
    path = historyFile()
    newFile = not path.exists()
    timestamp = datetime.datetime.now().isoformat(timespec='seconds')
    spreads = spreads or {}

    with open(path, 'a', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        if newFile:
            writer.writeheader()
        for point in results:
            writer.writerow({'timestamp': timestamp,
                             'printer': printerName,
                             'point': point.name,
                             'x': f'{point.x:.3f}',
                             'y': f'{point.y:.3f}',
                             'z': f'{point.z:.4f}',
                             'samples': samples,
                             'spread': f'{spreads.get(point.name, 0.0):.4f}'})
    return timestamp
