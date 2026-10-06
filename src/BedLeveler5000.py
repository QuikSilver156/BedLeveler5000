#!/usr/bin/env python

from Common import Common
from Common.Points import NamedPoint3F
from Common.CommonArgumentParser import CommonArgumentParser
from Widgets.BedLeveler5000.ManualWidget import ManualWidget
from Widgets.BedLeveler5000.MeshWidget import MeshWidget
from Common.PrinterInfo import ConnectionMode
from Printers.Marlin2.Marlin2Printer import Marlin2Printer
from Printers.Moonraker.MoonrakerPrinter import MoonrakerPrinter
from Widgets.BedLeveler5000.TemperatureControlsWidget import TemperatureControlsWidget
from Widgets.BedLeveler5000.StatusBar import StatusBar
from Widgets.PrinterConnectWidget import PrinterConnectWidget
from Dialogs.BedLeveler5000.CancellableStatusDialog import CancellableStatusDialog
from Dialogs.AboutDialog import AboutDialog
from Dialogs.WarningDialog import WarningDialog
from Dialogs.ErrorDialog import ErrorDialog
from Dialogs.FatalErrorDialog import FatalErrorDialog
from Common import Version
from Common import History
from Common import PortScanner
from Dialogs.OctoPrintSettingsDialog import OctoPrintSettingsDialog
from Dialogs.OctoPrintSettingsDialog import loadSettings as loadOctoPrintSettings
from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets
from PySide6 import QtSerialPort
import argparse
from enum import StrEnum
import json
import shutil
import statistics
import time
import logging
import pathlib
import signal
import sys

# Enable CTRL-C killing the application
signal.signal(signal.SIGINT, signal.SIG_DFL)

DESCRIPTION = 'A utility aiding in FDM printer bed leveling.'

class MainWindow(QtWidgets.QMainWindow):
    class State(StrEnum):
        DISCONNECTED = 'Disconnected'
        INITIALIZING = 'Initializing'
        INITIALIZING_MESH = 'Initializing mesh'
        CONNECTED = 'Connected'
        HOMING = 'Homing'
        MANUAL_PROBE = 'Manually probing point'
        UPDATING_MESH = 'Updating mesh'
        LIVE_ADJUST = 'Live adjust'
        HEAT_SOAK = 'Heat soaking bed'

    NO_RESPONSE_TIMEOUT_MS = 10_000
    SAMPLE_CHOICES = [1, 2, 3, 5]
    SOAK_CHOICES = [0, 2, 5, 10, 15]
    SOAK_TOLERANCE_C = 1.0

    class Dialog(StrEnum):
        INITIALIZING = 'Initializing'
        HOMING = 'Homing'
        PROBE = 'Probe'
        LIVE = 'Live'
        SOAK = 'Soak'

    def __init__(self, *args, printersDir, printer=None, host=None, port=None, noTemperatureReporting=False, **kwargs):
        super().__init__(*args, **kwargs)

        self.setWindowTitle(f'{QtCore.QCoreApplication.applicationName()} {QtCore.QCoreApplication.applicationVersion()}')
        self.logger = logging.getLogger(QtCore.QCoreApplication.applicationName())
        self.settings = QtCore.QSettings('QuikSilver', 'BedLeveler5000')
        self.liveContext = None
        self.soakContext = None
        self.lastTemperatures = None
        self.bedAtTempSince = None

        self.__createWidgets()
        self.__layoutWidgets()
        self.__createMenus()
        self.__createStatusBar()
        self.__createDialogs()
        self.__createTimers()

        self.currentId = -1
        self.printer = None
        self.printerInfo = None
        self.meshCoordinates = None
        self.printerQtConnections = []
        self.noTemperatureReporting = noTemperatureReporting
        self.printerConnectWidget.loadPrinters(printersDir, desiredPrinter=printer, desiredHost=host, desiredPort=port)
        self.printerConnectWidget.setOctoPrintMode(self.octoPrintEnabled())
        if printer is None:
            self._restoreLastConnection()
        self.updateState(self.State.DISCONNECTED)

    def __createWidgets(self):
        # Printer connect widget
        self.printerConnectWidget = PrinterConnectWidget()
        self.printerConnectWidget.printerChanged.connect(self.switchPrinter)
        self.printerConnectWidget.connectRequested.connect(self.connectToPrinter)
        self.printerConnectWidget.disconnectRequested.connect(self.disconnectFromPrinter)
        self.printerConnectWidget.homeRequested.connect(self.home)

        # Temperature Controls Widget
        self.temperatureControlsWidget = TemperatureControlsWidget()
        self.temperatureControlsWidget.bedHeaterChanged.connect(self.setBedTemperature)
        self.temperatureControlsWidget.nozzleHeaterChanged.connect(self.setNozzleTemperature)

        # Manual widget
        self.manualWidget = ManualWidget()
        self.manualWidget.probe.connect(
            lambda command, pointList: self._withHeatSoak(lambda: self.manualProbe(command, pointList)))
        self.manualWidget.liveAdjust.connect(
            lambda point, name, z: self._withHeatSoak(lambda: self.startLiveAdjust(point, name, z)))

        # Mesh widget
        self.meshWidget = MeshWidget()
        self.meshWidget.updateMesh.connect(lambda: self._withHeatSoak(lambda: self.updateMesh(0, 0)))

        # Tab widget
        self.tabWidget = QtWidgets.QTabWidget()
        self.tabWidget.addTab(self.manualWidget, 'Manual')
        self.tabWidget.addTab(self.meshWidget, 'Mesh')

    def __layoutWidgets(self):
        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.printerConnectWidget)
        layout.addWidget(self.temperatureControlsWidget)
        layout.addWidget(self.tabWidget)

        widget = QtWidgets.QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def __createMenus(self):
        # File menu
        self.fileMenu = QtWidgets.QMenu('File', self)
        self.exportHistoryAction = QtGui.QAction('Export probe history (CSV)...', self)
        self.exportHistoryAction.setStatusTip('Save every "Probe all" run to a CSV file')
        self.exportHistoryAction.triggered.connect(self.exportHistory)
        self.fileMenu.addAction(self.exportHistoryAction)
        self.openHistoryFolderAction = QtGui.QAction('Open history folder', self)
        self.openHistoryFolderAction.triggered.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(History.historyDir()))))
        self.fileMenu.addAction(self.openHistoryFolderAction)
        self.fileMenu.addSeparator()
        self.exitAction = QtGui.QAction('Exit', self)
        self.exitAction.setStatusTip('Exit the application')
        self.exitAction.triggered.connect(self.close)
        self.fileMenu.addAction(self.exitAction)
        self.menuBar().addMenu(self.fileMenu)

        # Ports
        self.portsMenu = QtWidgets.QMenu('Ports', self)
        self.enumeratePortsAction = QtGui.QAction('Enumerate', self)
        self.enumeratePortsAction.setStatusTip('Reenumerate COM ports')
        self.enumeratePortsAction.triggered.connect(self.printerConnectWidget.enumeratePorts)
        self.portsMenu.addAction(self.enumeratePortsAction)
        self.autoDetectAction = QtGui.QAction('Auto-detect printer', self)
        self.autoDetectAction.setStatusTip('Ask each COM port for M115 and select the one the printer answers on')
        self.autoDetectAction.triggered.connect(self.autoDetectPrinter)
        self.portsMenu.addAction(self.autoDetectAction)
        self.portsMenu.addSeparator()
        self.useOctoPrintAction = QtGui.QAction('Connect through OctoPrint', self)
        self.useOctoPrintAction.setCheckable(True)
        self.useOctoPrintAction.setChecked(self.octoPrintEnabled())
        self.useOctoPrintAction.setStatusTip('Send commands through OctoPrint so it can stay connected to the printer')
        self.useOctoPrintAction.toggled.connect(self.setOctoPrintEnabled)
        self.portsMenu.addAction(self.useOctoPrintAction)
        self.octoPrintSettingsAction = QtGui.QAction('OctoPrint settings...', self)
        self.octoPrintSettingsAction.triggered.connect(self.editOctoPrintSettings)
        self.portsMenu.addAction(self.octoPrintSettingsAction)
        self.menuBar().addMenu(self.portsMenu)

        self.settingsMenu = QtWidgets.QMenu('Settings', self)
        self.samplesMenu = self.settingsMenu.addMenu('Samples per point')
        self.samplesActionGroup = QtGui.QActionGroup(self)
        self.samplesActionGroup.setExclusive(True)
        currentSamples = self.samplesPerPoint()
        for count in self.SAMPLE_CHOICES:
            action = QtGui.QAction(f'{count}' + (' (no averaging)' if count == 1 else ' (average)'), self)
            action.setCheckable(True)
            action.setChecked(count == currentSamples)
            action.setData(count)
            action.triggered.connect(lambda checked=False, count=count: self.settings.setValue('samplesPerPoint', count))
            self.samplesActionGroup.addAction(action)
            self.samplesMenu.addAction(action)

        self.soakMenu = self.settingsMenu.addMenu('Heat soak before probing')
        self.soakActionGroup = QtGui.QActionGroup(self)
        self.soakActionGroup.setExclusive(True)
        currentSoak = self.heatSoakMinutes()
        for minutes in self.SOAK_CHOICES:
            action = QtGui.QAction('Off' if minutes == 0 else f'{minutes} minutes', self)
            action.setCheckable(True)
            action.setChecked(minutes == currentSoak)
            action.triggered.connect(lambda checked=False, minutes=minutes: self.settings.setValue('heatSoakMinutes', minutes))
            self.soakActionGroup.addAction(action)
            self.soakMenu.addAction(action)
        self.menuBar().addMenu(self.settingsMenu)

        self.helpMenu = QtWidgets.QMenu('Help', self)
        self.aboutAction = QtGui.QAction('About', self)
        self.aboutAction.triggered.connect(lambda : AboutDialog(DESCRIPTION).exec())
        self.helpMenu.addAction(self.aboutAction)
        self.aboutQtAction = QtGui.QAction('About Qt', self)
        self.aboutQtAction.triggered.connect(qApp.aboutQt)
        self.helpMenu.addAction(self.aboutQtAction)
        self.menuBar().addMenu(self.helpMenu)

    def __createStatusBar(self):
        self.setStatusBar(StatusBar())

    def __createDialogs(self):
        self.dialogs = {self.Dialog.INITIALIZING: CancellableStatusDialog(text='Initializing printer', parent=self),
                        self.Dialog.HOMING: CancellableStatusDialog(text='Homing', parent=self),
                        self.Dialog.PROBE: CancellableStatusDialog(text='Manually probing (x, y)', parent=self)}

        self.dialogs[self.Dialog.INITIALIZING].rejected.connect(self.disconnectFromPrinter)
        self.dialogs[self.Dialog.HOMING].rejected.connect(self._cancel)
        self.dialogs[self.Dialog.PROBE].rejected.connect(self._cancel)

        self.dialogs[self.Dialog.LIVE] = CancellableStatusDialog(text='Live adjust', parent=self)
        self.dialogs[self.Dialog.LIVE].setStandardButtons(QtWidgets.QMessageBox.Cancel)
        self.dialogs[self.Dialog.LIVE].button(QtWidgets.QMessageBox.Cancel).setText('Done')
        self.dialogs[self.Dialog.LIVE].rejected.connect(self._cancel)

        self.dialogs[self.Dialog.SOAK] = CancellableStatusDialog(text='Heat soak', parent=self)
        self.soakStartNowButton = self.dialogs[self.Dialog.SOAK].addButton('Start now', QtWidgets.QMessageBox.AcceptRole)
        self.soakStartNowButton.clicked.connect(self._soakStartNow)
        self.dialogs[self.Dialog.SOAK].rejected.connect(self._soakCancelled)

    def __createTimers(self):
        self.temperatureJobPending = False
        self.temperatureTimer = QtCore.QTimer()
        self.temperatureTimer.setInterval(1000) # TODO: Make the interval configurable
        self.temperatureTimer.timeout.connect(self.getTemperatures)

        self.noResponseTimer = QtCore.QTimer()
        self.noResponseTimer.setSingleShot(True)
        self.noResponseTimer.setInterval(self.NO_RESPONSE_TIMEOUT_MS)
        self.noResponseTimer.timeout.connect(self._checkPrinterResponding)

        self.soakTimer = QtCore.QTimer()
        self.soakTimer.setInterval(1000)
        self.soakTimer.timeout.connect(self._soakTick)

    def _createId(self, base):
        self.currentId += 1
        return f'{base}-{self.currentId}'

    def connectToPrinter(self):
        assert self.printerInfo == self.printerConnectWidget.printerInfo()
        assert self.printerConnectWidget.connectionMode() in ConnectionMode

        # Create the printer and determine open arguments
        if self.printerConnectWidget.connectionMode() == ConnectionMode.MARLIN_2:
            if self.printerConnectWidget.port() == PrinterConnectWidget.OCTOPRINT_PORT:
                octoPrintSettings = loadOctoPrintSettings(self.settings)
                if octoPrintSettings is None:
                    self._warning('Enter your OctoPrint address and API key first (Ports -> OctoPrint settings).')
                    self.editOctoPrintSettings()
                    return
                self.printer = Marlin2Printer(self.printerConnectWidget.printerInfo(), parent=self,
                                             octoPrintSettings=octoPrintSettings)
            else:
                self.printer = Marlin2Printer(self.printerConnectWidget.printerInfo(), parent=self)
            kwargs = {'port': self.printerConnectWidget.port()}
        elif self.printerConnectWidget.connectionMode() == ConnectionMode.MOONRAKER:
            self.printer = MoonrakerPrinter(self.printerConnectWidget.printerInfo(), parent=self)
            kwargs = {'host': self.printerConnectWidget.host()}
        else:
            raise RuntimeError('Invalid connection mode')

        # Make connections
        self.printerQtConnections = []
        self.printerQtConnections.append(self.printer.errorOccurred.connect(self.reportPrinterError))
        self.printerQtConnections.append(self.printer.inited.connect(self._processInitResults))
        self.printerQtConnections.append(self.printer.homed.connect(self._finishHoming))
        self.printerQtConnections.append(self.printer.gotTemperatures.connect(self.updateTemperatures))
        self.printerQtConnections.append(self.printer.gotMeshCoordinates.connect(self._initializeMesh))
        self.printerQtConnections.append(self.printer.probed.connect(self._processProbe))

        # Open the printer
        try:
            self.printer.open(**kwargs)
        except IOError as exception:
            for qtConnection in self.printerQtConnections:
                self.printer.disconnect(qtConnection)
            self.printerQtConnections = []
            self.printer = None
            self.updateState(self.State.DISCONNECTED)
            self.logger.error(str(exception))
            ErrorDialog(self, str(exception))
            return
        self.printerConnectWidget.setConnected()
        self.meshCoordinates = None

        # Set the temperature controls to off
        self.temperatureControlsWidget.resetButtons()

        # Start the temperature timer
        self.temperatureJobPending = False
        if not self.noTemperatureReporting:
            self.temperatureTimer.start()

        # Initialize the printer
        self.updateState(self.State.INITIALIZING)
        self.printer.init(self._createId('init'))
        self.dialogs[self.Dialog.INITIALIZING].show()

        # Watch for a printer that never answers (wrong port, wrong baud, ...)
        if self.printerConnectWidget.connectionMode() == ConnectionMode.MARLIN_2:
            self.noResponseTimer.start()

    def disconnectFromPrinter(self):
        assert(self.printerInfo == self.printerConnectWidget.printerInfo())

        # Stop the timers
        self.temperatureJobPending = False
        self.temperatureTimer.stop()
        self.noResponseTimer.stop()
        self.soakTimer.stop()
        self.soakContext = None
        self.liveContext = None
        self.lastTemperatures = None
        self.bedAtTempSince = None

        if self.printer is None:
            self.updateState(self.State.DISCONNECTED)
            return

        # Close the printer
        self.printerConnectWidget.setDisconnected()
        self.printer.close()
        self.meshCoordinates = None
        self.updateState(self.State.DISCONNECTED)

        # Break connections
        for qtConnection in self.printerQtConnections:
            self.printer.disconnect(qtConnection)
        self.printerQtConnections = []

        self.printer = None

    def switchPrinter(self):
        assert(self.printerInfo != self.printerConnectWidget.printerInfo())
        self.printerInfo = self.printerConnectWidget.printerInfo()

        try:
            self.manualWidget.setPrinter(self.printerInfo)
            self.meshWidget.resizeMesh(0, 0)
        except ValueError as valueError:
            self._fatalError(valueError.args[0])

    def updateState(self, state=None):
        if state is not None:
            self.state = state

        connected = self.printer is not None and self.printer.connected()
        busy = self.state != self.State.CONNECTED

        if not connected:
            self.printerConnectWidget.setDisconnected()
        elif busy:
            self.printerConnectWidget.setBusy()
        else:
            self.printerConnectWidget.setConnected()

        self.enumeratePortsAction.setEnabled(not connected)
        self.autoDetectAction.setEnabled(not connected and not self.octoPrintEnabled())
        self.useOctoPrintAction.setEnabled(not connected)

        self.temperatureControlsWidget.setEnabled(connected and not busy)
        self.manualWidget.setEnabled(connected and not busy)
        self.meshWidget.setEnabled(connected and not busy)

        self.statusBar().setState(self.state)

    def getTemperatures(self):
        if not self.temperatureJobPending:
            self.temperatureJobPending = True
            self.printer.getTemperatures(self._createId('getTemperatures'))

    def updateTemperatures(self, id_, context, result):
        self.temperatureJobPending = False
        self._trackBedTemperature(result)
        self.statusBar().setBedTemp(actual=result.bedActual, desired=result.bedDesired, power=result.bedPower)
        self.statusBar().setNozzleTemp(actual=result.toolActual, desired=result.toolDesired, power=result.toolPower)

    def _processInitResults(self, id_, context):
        for point in self.printerInfo.manualProbePoints:
            if not self.printer.isProbeable(x=point.x, y=point.y):
                probeBounds = self.printer.probeBounds()
                probeArea = f'({probeBounds.minX}, {probeBounds.minY}), ({probeBounds.maxX}, {probeBounds.maxY})'

                self._error(f'Manual probe point ({point.x}, {point.y}) is outside the probeable area of {probeArea}.'
                                 f' Either the probe point coordinates are wrong or the printer\'s X or Y'
                                 f' axis bounds are set incorrectly.')
                return

        self.printer.getMeshCoordinates(self._createId('getMeshCoordinates'))
        self.updateState(self.State.INITIALIZING_MESH)

    def _initializeMesh(self, id_, context, result):
        self.meshCoordinates = result.meshCoordinates
        corners = [self.meshCoordinates[0][0],
                   self.meshCoordinates[0][result.columnCount-1],
                   self.meshCoordinates[result.rowCount-1][0],
                   self.meshCoordinates[result.rowCount-1][result.columnCount-1]]

        for corner in corners:
            if not self.printer.isProbeable(x=corner.x, y=corner.y):
                probeBounds = self.printer.probeBounds()
                probeArea = f'({probeBounds.minX}, {probeBounds.minY}), ({probeBounds.maxX}, {probeBounds.maxY})'

                self._error(f'Mesh corner point ({corner.x}, {corner.y}) is outside the probeable area of {probeArea}.'
                                 f' Either the mesh is misconfigured or the printer\'s X or Y'
                                 f' axis bounds are set incorrectly.')
                return

        self.meshWidget.resizeMesh(result.rowCount,
                                   result.columnCount)
        self.updateState(self.State.CONNECTED)
        self.dialogs[self.Dialog.INITIALIZING].accept()
        self._saveLastConnection()

    def home(self):
        self.printer.home(self._createId('home'))
        self.updateState(self.State.HOMING)
        self.dialogs[self.Dialog.HOMING].show()

    def _finishHoming(self, id_, context):
        if not id_.startswith('home'):
            self._error('An error occurred while homing.')
        else:
            self.updateState(self.State.CONNECTED)
            self.dialogs[self.Dialog.HOMING].accept()

    def manualProbe(self, command, pointList):
        assert(len(pointList) > 0)
        context={'type': self.State.MANUAL_PROBE,
                 'command': command,
                 'pointList': list(pointList),
                 'resultList': [],
                 'samples': self.samplesPerPoint(),
                 'currentSamples': [],
                 'spreads': {}}

        point = pointList[0]
        self.printer.probe(self._createId(f'probe_{point.x}_{point.y}'), context=context, x=point.x, y=point.y)
        self.dialogs[self.Dialog.PROBE].setText(f'Manually probing at ({point.x}, {point.y})')
        self.updateState(self.State.MANUAL_PROBE)
        self.dialogs[self.Dialog.PROBE].show()

    def updateMesh(self, row=0, column=0):
        if row == 0 and column == 0:
            self.meshWidget.clear()

        coordinate = self.meshCoordinates[row][column]
        self.printer.probe(self._createId('updateMesh'),
                           context = {'type': self.State.UPDATING_MESH,
                                      'row': row,
                                      'column': column},
                           x=coordinate.x,
                           y=coordinate.y)

        self.updateState(self.State.UPDATING_MESH)
        self.dialogs[self.Dialog.PROBE].setText(f'Probing mesh at row: {row}, column: {column} (x: {coordinate.x:.3f}, y: {coordinate.y:.3f})')
        self.dialogs[self.Dialog.PROBE].show()

    def _processProbe(self, id_, context, response):
        assert isinstance(context, dict), 'context must be a dict.'
        if'type' not in context:
            self._error('Detected a printer response mismatch.')
        elif context['type'] == self.State.LIVE_ADJUST:
            self._processLiveProbe(context, response)
        elif context['type'] == self.State.MANUAL_PROBE:
            assert(self.state == self.State.MANUAL_PROBE)

            # Collect samples for the current point
            point = context['pointList'][0]
            context['currentSamples'].append(response.z)
            sampleCount = len(context['currentSamples'])
            if sampleCount < context['samples']:
                self.printer.probe(self._createId(f'probe_{point.x}_{point.y}'), context=context, x=point.x, y=point.y)
                self.dialogs[self.Dialog.PROBE].setText(f'Manually probing at ({point.x}, {point.y}) '
                                                        f'- sample {sampleCount + 1} of {context["samples"]}')
                return

            # Move the current point from the point list to the result list
            samples = context['currentSamples']
            context['currentSamples'] = []
            context['spreads'][point.name] = max(samples) - min(samples)
            context['pointList'].pop(0)
            context['resultList'].append(NamedPoint3F(point.name, response.x, response.y, statistics.fmean(samples)))

            if len(context['pointList']) > 0:
                point = context['pointList'][0]
                self.printer.probe(self._createId(f'probe_{point.x}_{point.y}'), context=context, x=point.x, y=point.y)
                self.dialogs[self.Dialog.PROBE].setText(f'Manually probing at ({point.x}, {point.y})')
            else:
                self.manualWidget.reportProbe(context['command'], context['resultList'])
                self._reportSamples(context)
                if context['command'] == ManualWidget.Command.ALL:
                    self._recordHistory(context)
                self.dialogs[self.Dialog.PROBE].accept()
                self.updateState(self.State.CONNECTED)
        else:
            assert(context['type'] == self.State.UPDATING_MESH and self.state == self.State.UPDATING_MESH)
            row = context['row']
            column = context['column']

            self.meshWidget.setPoint(row=row,
                                     column=column,
                                     z=response.z)

            if row % 2 == 0:
                column += 1
                if column >= len(self.meshCoordinates[0]):
                    column = len(self.meshCoordinates[0]) - 1
                    row += 1
            else:
                column -= 1
                if column < 0:
                    column = 0
                    row += 1

            if row >= len(self.meshCoordinates):
                self.dialogs[self.Dialog.PROBE].accept()
                self.updateState(self.State.CONNECTED)
            else:
                self.updateMesh(row, column)

    # ----- Live adjust -----
    def startLiveAdjust(self, point, referenceName, referenceZ):
        self.liveContext = {'type': self.State.LIVE_ADJUST,
                            'point': point,
                            'referenceName': referenceName,
                            'referenceZ': referenceZ,
                            'count': 0,
                            'lastText': None}
        self.updateState(self.State.LIVE_ADJUST)
        self.dialogs[self.Dialog.LIVE].setText(f'Live adjust: point {point.name}\n\nTaking the first reading...')
        self.dialogs[self.Dialog.LIVE].show()
        self._liveProbe()

    def _liveProbe(self):
        point = self.liveContext['point']
        self.printer.probe(self._createId(f'live_{point.x}_{point.y}'), context=self.liveContext, x=point.x, y=point.y)

    def _processLiveProbe(self, context, response):
        if self.state != self.State.LIVE_ADJUST or context is not self.liveContext:
            return # Stale result after Done was pressed

        context['count'] += 1
        point = context['point']
        text = self.manualWidget.liveReadingText(point.name, response.z, context['referenceName'], context['referenceZ'])
        context['lastText'] = text
        self.dialogs[self.Dialog.LIVE].setText(f'Live adjust: point {point.name} (reading {context["count"]})\n\n'
                                               f'{text}\n\n'
                                               f'Turn the knob for point {point.name} now. The next reading starts '
                                               f'automatically. Press Done when it reads close to +0.000.')
        self._liveProbe()

    # ----- Heat soak -----
    def heatSoakMinutes(self):
        try:
            value = int(self.settings.value('heatSoakMinutes', 0))
        except (TypeError, ValueError):
            value = 0
        return value if value in self.SOAK_CHOICES else 0

    def _trackBedTemperature(self, result):
        previous = self.lastTemperatures
        self.lastTemperatures = result

        if result.bedDesired <= 0:
            self.bedAtTempSince = None
            return

        # A new target restarts the soak
        if previous is not None and abs(previous.bedDesired - result.bedDesired) > 0.5:
            self.bedAtTempSince = None

        if abs(result.bedActual - result.bedDesired) <= self.SOAK_TOLERANCE_C:
            if self.bedAtTempSince is None:
                self.bedAtTempSince = time.monotonic()
        elif result.bedActual < result.bedDesired - 2 * self.SOAK_TOLERANCE_C:
            self.bedAtTempSince = None

    def _withHeatSoak(self, action):
        """ Runs action now, or after the bed has been at temperature for the heat soak time. """
        minutes = self.heatSoakMinutes()
        if minutes <= 0 or self.printer is None:
            action()
            return

        temperatures = self.lastTemperatures
        if temperatures is None or temperatures.bedDesired <= 0:
            self.manualWidget.appendNote('Heat soak is on, but the bed heater is off, so probing started right away. '
                                         'Turn the bed heater on to soak first.')
            action()
            return

        self.soakContext = {'action': action, 'seconds': minutes * 60}
        self.updateState(self.State.HEAT_SOAK)
        self._soakTick()
        if self.soakContext is not None:
            self.dialogs[self.Dialog.SOAK].show()
            self.soakTimer.start()

    def _soakTick(self):
        if self.soakContext is None:
            self.soakTimer.stop()
            return

        temperatures = self.lastTemperatures
        target = temperatures.bedDesired if temperatures is not None else 0
        actual = temperatures.bedActual if temperatures is not None else 0

        if self.bedAtTempSince is None:
            self.dialogs[self.Dialog.SOAK].setText(f'Waiting for the bed to reach {target:.0f}\u00B0C '
                                                   f'(now {actual:.1f}\u00B0C).\n\n'
                                                   f'Then it will soak for {self.soakContext["seconds"] // 60} minutes '
                                                   f'before probing.')
            return

        remaining = self.soakContext['seconds'] - (time.monotonic() - self.bedAtTempSince)
        if remaining <= 0:
            self._finishSoak()
            return

        minutes, seconds = divmod(int(remaining + 0.999), 60)
        self.dialogs[self.Dialog.SOAK].setText(f'Bed is at {actual:.1f}\u00B0C. Letting it soak so the '
                                               f'readings settle.\n\nProbing starts in {minutes}:{seconds:02d}.')

    def _finishSoak(self):
        context = self.soakContext
        self.soakContext = None
        self.soakTimer.stop()

        dialog = self.dialogs[self.Dialog.SOAK]
        dialog.blockSignals(True)
        dialog.hide()
        dialog.blockSignals(False)

        if context is None or self.printer is None:
            return
        self.updateState(self.State.CONNECTED)
        context['action']()

    def _soakStartNow(self):
        self._finishSoak()

    def _soakCancelled(self):
        if self.soakContext is None:
            return # Already finished (e.g. "Start now")
        self.soakContext = None
        self.soakTimer.stop()
        if self.printer is not None:
            self.updateState(self.State.CONNECTED)

    # ----- OctoPrint -----
    def octoPrintEnabled(self):
        value = self.settings.value('octoPrint/enabled', False)
        return value in (True, 'true', '1', 1)

    def setOctoPrintEnabled(self, enabled):
        if enabled and loadOctoPrintSettings(self.settings) is None:
            if not self.editOctoPrintSettings():
                self.useOctoPrintAction.blockSignals(True)
                self.useOctoPrintAction.setChecked(False)
                self.useOctoPrintAction.blockSignals(False)
                return
        self.settings.setValue('octoPrint/enabled', bool(enabled))
        self.printerConnectWidget.setOctoPrintMode(bool(enabled))
        self.updateState()

    def editOctoPrintSettings(self):
        return OctoPrintSettingsDialog(self.settings, self).exec() == QtWidgets.QDialog.Accepted

    # ----- Sampling, history -----
    def samplesPerPoint(self):
        try:
            value = int(self.settings.value('samplesPerPoint', 1))
        except (TypeError, ValueError):
            value = 1
        return value if value in self.SAMPLE_CHOICES else 1

    def _reportSamples(self, context):
        if context['samples'] <= 1 or not context['spreads']:
            return
        worstName = max(context['spreads'], key=context['spreads'].get)
        worst = context['spreads'][worstName]
        note = f'Averaged {context["samples"]} samples per point. Largest spread: {worst:.3f} mm (point {worstName}).'
        if worst > 0.03:
            note += ' That is a lot of scatter; check the probe and that the nozzle is clean.'
        self.manualWidget.appendNote(note)

    def _recordHistory(self, context):
        printerName = self.printerInfo.displayName
        try:
            previous = History.lastRun(printerName)
            History.appendRun(printerName, context['resultList'], context['samples'], context['spreads'])
        except (OSError, ValueError) as exception:
            self.logger.warning(f'Failed to update probe history: {exception}')
            return

        if previous is None:
            return
        timestamp, values = previous
        changes = []
        for point in context['resultList']:
            if point.name in values:
                changes.append(f'{point.name} {point.z - values[point.name]:+.3f}')
        if changes:
            when = timestamp.replace('T', ' ')
            self.manualWidget.appendNote(f'Change since last run ({when}): ' + ', '.join(changes))

    def exportHistory(self):
        source = History.historyFile()
        if not source.exists():
            self._warning('No probe history yet. Run "Probe all" at least once.')
            return
        filePath = QtWidgets.QFileDialog.getSaveFileName(self, 'Export probe history', 'probe_history.csv',
                                                         'CSV files (*.csv)')[0]
        if filePath:
            try:
                shutil.copyfile(source, filePath)
            except OSError as exception:
                self._warning(f'Failed to export history: {exception}')

    # ----- Connection helpers -----
    def autoDetectPrinter(self):
        if self.printer is not None or self.printerConnectWidget.printerCount() == 0:
            return
        if self.printerConnectWidget.connectionMode() != ConnectionMode.MARLIN_2:
            self._warning('Auto-detect only works with USB (Marlin) printers.')
            return

        profileBaudRate = int(self.printerInfo.connection.baudRate)
        result, busyPorts = PortScanner.scan(profileBaudRate, parent=self)
        if result is not None:
            self.printerConnectWidget.selectPort(result.port)
        QtWidgets.QMessageBox.information(self, 'Auto-detect printer',
                                          PortScanner.describe(result, busyPorts, profileBaudRate))

    def _checkPrinterResponding(self):
        if self.printer is None or not isinstance(self.printer, Marlin2Printer):
            return
        if self.printer.commandConnection.linesReceived > 0:
            return

        port = self.printerConnectWidget.port()
        if port == PrinterConnectWidget.OCTOPRINT_PORT:
            self._error(f'The printer has not responded through OctoPrint after {self.NO_RESPONSE_TIMEOUT_MS // 1000} seconds.\n\n'
                        'Check that OctoPrint shows the printer as Operational and is not printing, and look at '
                        'OctoPrint\'s Terminal tab for errors.')
            return
        self._error(f'The printer has not responded on {port} after {self.NO_RESPONSE_TIMEOUT_MS // 1000} seconds.\n\n'
                    'Things to check:\n'
                    '- The right port is selected (try Ports -> Auto-detect printer)\n'
                    '- The profile\'s baud rate matches the printer firmware (usually 115200 or 250000)\n'
                    '- The printer is powered on and has finished starting up\n'
                    '- No other program (PuTTY, Cura, OctoPrint) is connected to the printer')

    def _saveLastConnection(self):
        self.settings.setValue('lastPrinter', self.printerInfo.displayName)
        if self.printerConnectWidget.connectionMode() == ConnectionMode.MARLIN_2:
            self.settings.setValue('lastPort', self.printerConnectWidget.port())

    def _restoreLastConnection(self):
        lastPrinter = self.settings.value('lastPrinter')
        if lastPrinter and self.printerConnectWidget.selectPrinter(str(lastPrinter)):
            if self.printerInfo is None or self.printerInfo != self.printerConnectWidget.printerInfo():
                self.switchPrinter()
            lastPort = self.settings.value('lastPort')
            if lastPort:
                self.printerConnectWidget.selectPort(str(lastPort))

    def setBedTemperature(self, state, temp):
        self.printer.setBedTemperature(self._createId('setBedTemperature'), temperature=temp if state else 0)

    def setNozzleTemperature(self, state, temp):
        self.printer.setNozzleTemperature(self._createId('setNozzleTemperature'), temperature=temp if state else 0)

    def _cancel(self):
        """ Cancel operations that are safe to cancel """

        for dialog in self.dialogs.values():
            dialog.blockSignals(True)
            dialog.reject()
            dialog.blockSignals(False)

        if self.state == self.State.LIVE_ADJUST and self.liveContext is not None and self.liveContext.get('lastText'):
            self.manualWidget.logLiveReading(self.liveContext['lastText'])
        self.liveContext = None

        if self.printer is not None:
            self.printer.abort()
        self.updateState(self.State.CONNECTED)

    def reportPrinterError(self, type_, id_, context, message):
        self._error(message)

    def _fatalError(self, message):
        self.logger.critical(message)
        self.disconnectFromPrinter()
        for dialog in self.dialogs.values():
            dialog.blockSignals(True)
            dialog.reject()
            dialog.blockSignals(False)
        FatalErrorDialog(self, message)

    def _error(self, message):
        self.logger.error(message)
        self.disconnectFromPrinter()
        for dialog in self.dialogs.values():
            dialog.blockSignals(True)
            dialog.reject()
            dialog.blockSignals(False)
        ErrorDialog(self, message)

    def _warning(self, message):
        self.logger.warning(message)
        WarningDialog(self, message)

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon((Common.resourcesDir() / 'Icon-128x128.png').as_posix()))
    app.setApplicationName('Bed Leveler 5000')
    app.setApplicationVersion(Version.displayVersion())

    # Windows only, configure icon settings
    try:
        from ctypes import windll
        myappid = f'com.sandmmakers.bedleveler5000.{QtCore.QCoreApplication.applicationVersion()}'
        windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except ImportError:
        pass

    # Parse command line arguments
    parser = CommonArgumentParser(description=DESCRIPTION)
    parser.add_argument('--no-temperature-reporting', action='store_true', help='disable temperature reporting')
    args = parser.parse_args()

    # Configure logging
    Common.configureLogging(level=args.log_level, console=args.log_console, file=args.log_file)
    logging.getLogger(QtCore.QCoreApplication.applicationName()).info(f'Starting {app.applicationName()}')

    # Verify the printers directory exists
    if args.printers_dir is not None and not args.printers_dir.exists():
        FatalErrorDialog(None, f'Failed to find printer directory: {args.printers_dir}.')

    try:
        mainWindow = MainWindow(printersDir=args.printers_dir,
                                printer=args.printer,
                                host=args.host,
                                port=args.port,
                                noTemperatureReporting=args.no_temperature_reporting)
        mainWindow.show()
        sys.exit(app.exec())
    except KeyboardInterrupt:
        sys.exit(1)
    except Exception as exception:
        FatalErrorDialog(None, str(exception))