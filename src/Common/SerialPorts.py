#!/usr/bin/env python
""" Serial port helpers shared by the printer connection and the auto-detect scanner. """

from PySide6 import QtSerialPort

# USB-to-serial bridge chips. On boards that use them, DTR is wired to the
# microcontroller's reset line, so asserting it reboots the printer.
USB_SERIAL_BRIDGE_VENDORS = {
    0x1A86, # WCH (CH340/CH341) - most Creality 8-bit and 4.2.x boards
    0x0403, # FTDI
    0x10C4, # Silicon Labs CP210x
    0x067B, # Prolific
    0x2341, # Arduino (Mega 2560 with 16U2)
    0x2A03, # Arduino.org
}

def shouldAssertDtr(portName):
    """ True for native-USB boards (e.g. STM32), which only send replies once
        DTR is asserted. False for USB-serial bridge chips, where DTR would reset the board. """
    for info in QtSerialPort.QSerialPortInfo.availablePorts():
        if info.portName() == portName:
            if info.hasVendorIdentifier() and info.vendorIdentifier() in USB_SERIAL_BRIDGE_VENDORS:
                return False
            return True
    return True

def describePort(portName):
    for info in QtSerialPort.QSerialPortInfo.availablePorts():
        if info.portName() == portName:
            vid = f'{info.vendorIdentifier():04X}' if info.hasVendorIdentifier() else '----'
            pid = f'{info.productIdentifier():04X}' if info.hasProductIdentifier() else '----'
            return f'{portName}: {info.description()} [{vid}:{pid}]'
    return f'{portName}: (not found)'
