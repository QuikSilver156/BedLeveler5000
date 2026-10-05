#!/usr/bin/env python

from Common.Common import LOG_ALL
from Common.SerialPorts import describePort
from Common.SerialPorts import shouldAssertDtr
from PySide6 import QtCore
from PySide6 import QtSerialPort
import logging
import math

class SerialConnection(QtCore.QObject):
    # TODO: Determine if an errorOccurred signal is needed

    def __init__(self, printerInfo, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Get logger
        self.logger = logging.getLogger(self.__class__.__name__)

        # Serial port
        self._serialPort = QtSerialPort.QSerialPort()
        self._serialPort.readyRead.connect(self._readData)
        self._serialPort.errorOccurred.connect(self._handleSerialPortError)

        self.readBuffer = b''
        self.linesReceived = 0
        self._lastErrorMessage = None

        self._serialPort.setBaudRate(printerInfo.connection.baudRate)
        self._serialPort.setDataBits(printerInfo.connection.dataBits)
        self._serialPort.setParity(printerInfo.connection.parity)
        self._serialPort.setStopBits(printerInfo.connection.stopBits)
        self._serialPort.setFlowControl(printerInfo.connection.flowControl)

    def _handleSerialPortError(self, errorCode):
        match errorCode:
            case QtSerialPort.QSerialPort.SerialPortError.NoError:
                return
            case QtSerialPort.QSerialPort.SerialPortError.DeviceNotFoundError:
                message = f'{self._serialPort.portName()} was not found. The printer may be unplugged or on a different port (try Ports -> Auto-detect printer).'
            case QtSerialPort.QSerialPort.SerialPortError.PermissionError:
                message = f'{self._serialPort.portName()} is in use by another program. Close PuTTY, Cura, OctoPrint, Pronterface or any other Bed Leveler 5000 window, then try again.'
            case QtSerialPort.QSerialPort.SerialPortError.OpenError:
                message = 'An error occurred while attempting to open an already opened device in this object.'
            case QtSerialPort.QSerialPort.SerialPortError.NotOpenError:
                message = 'This error occurs when an operation is executed that can only be successfully performed if the device is open.'
            case QtSerialPort.QSerialPort.SerialPortError.WriteError:
                message = 'An I/O error occurred while writing data.'
            case QtSerialPort.QSerialPort.SerialPortError.ReadError:
                message = 'An I/O error occurred while reading data.'
            case QtSerialPort.QSerialPort.SerialPortError.ResourceError:
                message = f'Lost connection to {self._serialPort.portName()}. The printer may have been unplugged, powered off or reset.'
            case QtSerialPort.QSerialPort.SerialPortError.UnsupportedOperationError:
                message = 'The requested device operation is not supported or prohibited by the running operating system.'
            case QtSerialPort.QSerialPort.SerialPortError.TimeoutError:
                message = 'A timeout error occurred.'
            case QtSerialPort.QSerialPort.SerialPortError.UnknownError:
                message = 'An unknown error occured.'
            case _:
                message = 'An unidentified error occured.'

        self._lastErrorMessage = message

        # Errors raised while opening are reported by open() itself
        if not self._serialPort.isOpen():
            self.logger.error(f'Serial port error: {message}')
            return

        self._error(f'Serial port error: {message}')

    def connected(self):
        return self._serialPort.isOpen()

    def port(self):
        return self._serialPort.portName()

    def open(self, portName, *, clear=True):
        assert(not self._serialPort.isOpen())

        self._serialPort.setPortName(portName)

        self._lastErrorMessage = None
        if not self._serialPort.open(QtCore.QIODevice.ReadWrite):
            self._error(self._lastErrorMessage or f'Failed to open {portName}.')

        # Assert DTR so native-USB (CDC) boards send their replies. Without it,
        # some Marlin boards accept commands but stay silent. Skipped for
        # USB-serial bridge chips (CH340, FTDI, ...), where DTR resets the board.
        self.logger.info(f'Port details: {describePort(portName)}')
        if shouldAssertDtr(portName):
            if not self._serialPort.setDataTerminalReady(True):
                self.logger.warning(f'Failed to assert DTR on {portName}.')
            else:
                self.logger.info(f'Asserted DTR on {portName}')

        if clear and not self._serialPort.clear():
            self._error(f'Failed to clear {portName}.')

        self.linesReceived = 0
        self.logger.info(f'Opened {self._serialPort.portName()}')

    def close(self):
        if self._serialPort.isOpen():
            self._serialPort.close()
            self.logger.info(f'Closed {self._serialPort.portName()}')

    def write(self, string):
        self._serialPort.write((string + '\n').encode())

    def _readData(self):
        """ TODO: Improve error handling here """

        self.readBuffer += self._serialPort.readAll()

        # Log the read buffer
        self.logger.log(LOG_ALL, f'Read buffer: ')
        for batch in range(int(math.ceil(self.readBuffer.length() / 16))):
            startIndex = 16 * batch
            stopIndex = min(startIndex + 16, self.readBuffer.length())
            message = f'[0x{startIndex:02X}]:'
            for currentIndex in range(startIndex, stopIndex):
                message += f' {self.readBuffer[currentIndex].hex().upper()}'
            self.logger.log(LOG_ALL, message)

        while (index := self.readBuffer.indexOf(b'\n')) > -1:
            # Extract line
            try:
                lineEndIndex = index - 1 if index > 0 and self.readBuffer[index - 1] == b'\r' else index
                line = str(self.readBuffer[:lineEndIndex], 'ascii') # TODO: Verify the correct encoding
            except UnicodeDecodeError:
                self.logger.warn(f'Detected bad bytes: {self.readBuffer.data().hex()}.')
                self.readBuffer.clear()
                continue

            self.readBuffer = self.readBuffer[index+1:]

            self.logger.debug(f'Line: {line}')
            self.linesReceived += 1

            self._processLine(line)

    def _error(self, message):
        """ TODO: This needs to be fixed """
        self.logger.error(message)
        raise IOError(message)

if __name__ == '__main__':
    # Main only imports
    from Common import PrinterInfo
    import sys
    from PySide6 import QtCore
    from PySide6 import QtWidgets

    class TestConnection(SerialConnection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def sendCommand(self, command):
            self.logger.info(command)
            self.write(command)

        def _processLine(self, line):
            print(f'_processingLine: {line}')

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName('Serial Connection Test App')

    # Configure logging
    logging.basicConfig(level = logging.DEBUG)
    logger = logging.getLogger()

    connection = TestConnection(printerInfo = PrinterInfo.default(PrinterInfo.ConnectionMode.MARLIN_2))

    connection.open('COM8')

    connection.sendCommand('M114')

    widget = QtWidgets.QWidget()
    widget.show()

    sys.exit(app.exec())