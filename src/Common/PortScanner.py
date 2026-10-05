#!/usr/bin/env python
""" Finds which serial port a Marlin printer is on by asking each port for M115. """

from Common.SerialPorts import shouldAssertDtr
from PySide6 import QtCore
from PySide6 import QtSerialPort
from PySide6 import QtWidgets
import logging
import re
from typing import NamedTuple

COMMON_BAUD_RATES = [115_200, 250_000]

class ScanResult(NamedTuple):
    port: str
    baudRate: int
    firmware: str
    machine: str

def _query(portName, baudRate, isCancelled, timeoutMs=4000, resendMs=2000):
    """ Returns (status, data). status is 'ok', 'busy', 'silent' or 'cancelled'. """
    port = QtSerialPort.QSerialPort()
    port.setPortName(portName)
    port.setBaudRate(baudRate)
    port.setDataBits(QtSerialPort.QSerialPort.Data8)
    port.setParity(QtSerialPort.QSerialPort.NoParity)
    port.setStopBits(QtSerialPort.QSerialPort.OneStop)
    port.setFlowControl(QtSerialPort.QSerialPort.NoFlowControl)

    if not port.open(QtCore.QIODevice.ReadWrite):
        if port.error() == QtSerialPort.QSerialPort.SerialPortError.PermissionError:
            return 'busy', b''
        return 'silent', b''

    try:
        # Native-USB boards only reply with DTR asserted. M115 is also sent a
        # second time in case the board was still starting up.
        if shouldAssertDtr(portName):
            port.setDataTerminalReady(True)
        port.clear()

        data = b''
        timer = QtCore.QElapsedTimer()
        timer.start()
        sentAgain = False

        port.write(b'\nM115\n')
        port.flush()

        while timer.elapsed() < timeoutMs:
            if isCancelled():
                return 'cancelled', data

            if port.waitForReadyRead(100):
                data += bytes(port.readAll().data())
                index = data.find(b'FIRMWARE_NAME')
                if index >= 0 and (b'\nok' in data[index:] or len(data) > 8192):
                    return 'ok', data

            QtWidgets.QApplication.processEvents()

            if not sentAgain and timer.elapsed() > resendMs:
                sentAgain = True
                port.write(b'\nM115\n')
                port.flush()

        return ('ok' if b'FIRMWARE_NAME' in data else 'silent'), data
    finally:
        port.close()

def _parse(data):
    text = data.decode('ascii', errors='replace')
    firmware = re.search(r'FIRMWARE_NAME:(.+?)(?: SOURCE_CODE_URL| PROTOCOL_VERSION|$)', text, re.MULTILINE)
    machine = re.search(r'MACHINE_TYPE:(.+?)(?: EXTRUDER_COUNT|$)', text, re.MULTILINE)
    return (firmware.group(1).strip() if firmware else 'Marlin',
            machine.group(1).strip() if machine else '')

def scan(preferredBaudRate=None, parent=None):
    """ Scans all serial ports with a progress dialog.
        Returns (ScanResult or None, list of busy port names). """

    logger = logging.getLogger('PortScanner')
    portNames = [info.portName() for info in QtSerialPort.QSerialPortInfo.availablePorts()]

    baudRates = []
    for baudRate in [preferredBaudRate] + COMMON_BAUD_RATES:
        if baudRate is not None and int(baudRate) not in baudRates:
            baudRates.append(int(baudRate))

    progress = QtWidgets.QProgressDialog('Looking for the printer...', 'Cancel', 0,
                                         max(1, len(portNames) * len(baudRates)), parent)
    progress.setWindowTitle('Auto-detect printer')
    progress.setWindowModality(QtCore.Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    busyPorts = []
    step = 0
    try:
        for baudRate in baudRates:
            for portName in portNames:
                if progress.wasCanceled():
                    return None, busyPorts
                if portName in busyPorts:
                    step += 1
                    continue

                progress.setLabelText(f'Checking {portName} at {baudRate} baud...')
                progress.setValue(step)
                QtWidgets.QApplication.processEvents()

                status, data = _query(portName, baudRate, progress.wasCanceled)
                logger.info(f'Scan {portName} @ {baudRate}: {status}')
                step += 1

                if status == 'cancelled':
                    return None, busyPorts
                if status == 'busy':
                    busyPorts.append(portName)
                elif status == 'ok':
                    firmware, machine = _parse(data)
                    return ScanResult(portName, baudRate, firmware, machine), busyPorts
        return None, busyPorts
    finally:
        progress.close()

def describe(result, busyPorts, profileBaudRate=None):
    """ Human readable summary of a scan. """
    if result is None:
        message = 'No printer answered on any serial port.\n\n' \
                  'Check that the printer is powered on, has finished starting up, ' \
                  'and that its USB cable carries data (not a charge-only cable).'
        if busyPorts:
            message += f'\n\nThese ports are in use by another program and could not be checked: ' \
                       f'{", ".join(busyPorts)}. Close PuTTY, Cura, OctoPrint or Pronterface and try again.'
        return message

    message = f'Found {result.firmware}'
    if result.machine:
        message += f' ({result.machine})'
    message += f' on {result.port} at {result.baudRate} baud.'

    if profileBaudRate is not None and int(profileBaudRate) != result.baudRate:
        message += f'\n\nThe selected printer profile uses {int(profileBaudRate)} baud. ' \
                   f'Change its Baud Rate to {result.baudRate} in Printer Info Wizard so it matches.'
    return message
