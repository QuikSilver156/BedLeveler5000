#!/usr/bin/env python

from Common.Points import NamedPoint2F
from Common.Points import NamedPoint3F
from .ManualProbeButtonArea import ManualProbeButtonArea
from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets
import enum
import math

class ManualWidget(QtWidgets.QWidget):
    probe = QtCore.Signal(str, list)
    liveAdjust = QtCore.Signal(object, str, float) # point, reference name, reference z

    class Command(enum.StrEnum):
        SINGLE = 'Single'
        ALL = 'All'

    @enum.verify(enum.UNIQUE)
    class Direction(enum.StrEnum):
        ANY = 'Any'
        CW = 'CW'
        CCW = 'CCW'

    @enum.verify(enum.UNIQUE)
    class Output(enum.StrEnum):
        NONE = 'None'
        DELTA = 'Delta'
        TIME = 'Time'
        TURNS = 'Turns'
        DEGREES = 'Degrees'
        RADIANS = 'Radians'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fixedMap = None
        self.lastResults = None
        self.lastReferenceName = None

        self.__createWidgets()
        self.__layoutWidgets()
        self._updateState()
        self.clear()

    def __createWidgets(self):
        # Test button area
        self.manualProbeButtonArea = ManualProbeButtonArea()
        self.manualProbeButtonArea.probe.connect(self._probeSingle)

        # Reference combo box
        self.referenceComboBox = QtWidgets.QComboBox()

        # Direction combo box
        self.directionComboBox = QtWidgets.QComboBox()
        for direction in self.Direction:
            self.directionComboBox.addItem(str(direction), direction)
        self.directionComboBox.setCurrentText(str(self.Direction.ANY))
        self.directionComboBox.currentIndexChanged.connect(self._updateState)

        # Output combo box
        self.outputComboBox = QtWidgets.QComboBox()
        for output in self.Output:
            self.outputComboBox.addItem(str(output), output)
        self.outputComboBox.setCurrentText(str(self.Output.TURNS))

        # Log
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QtGui.QFont('Cascadia Mono'))

        # Probe all button
        self.probeAllButton = QtWidgets.QPushButton('Probe all')
        self.probeAllButton.clicked.connect(self._probeAll)

        # Live adjust button
        self.liveAdjustButton = QtWidgets.QPushButton('Live adjust')
        self.liveAdjustButton.setToolTip('Probe one point over and over while you turn its knob')
        self.liveAdjustButton.clicked.connect(self._startLiveAdjust)

        # Clear button
        self.clearButton = QtWidgets.QPushButton('Clear')
        self.clearButton.clicked.connect(self.clear)

    def __layoutWidgets(self):
        buttonLayout = QtWidgets.QHBoxLayout()
        buttonLayout.addStretch()
        buttonLayout.addWidget(self.probeAllButton)
        buttonLayout.addWidget(self.liveAdjustButton)
        buttonLayout.addWidget(self.clearButton)
        buttonLayout.addStretch()

        optionsLayout = QtWidgets.QFormLayout()
        optionsLayout.addRow('Reference:', self.referenceComboBox)
        optionsLayout.addRow('Direction:', self.directionComboBox)
        optionsLayout.addRow('Output:', self.outputComboBox)

        optionsGroupBox = QtWidgets.QGroupBox('Options')
        optionsGroupBox.setLayout(optionsLayout)

        topLayout = QtWidgets.QHBoxLayout()
        topLayout.addWidget(self.manualProbeButtonArea)
        topLayout.addWidget(optionsGroupBox)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(topLayout)
        layout.addWidget(self.log, stretch=100)
        layout.addLayout(buttonLayout)

        self.setLayout(layout)

    def setPrinter(self, printerInfo):
        self.printerInfo = printerInfo
        self.manualProbeButtonArea.configure(printerInfo)
        self.fixedMap = {}
        self.lastResults = None
        self.lastReferenceName = None

        # Set reference combo box items
        defaultReference = None
        self.referenceComboBox.clear()
        for point in printerInfo.manualProbePoints:
            self.referenceComboBox.addItem(point.name, point)
            self.fixedMap[point.name] = point.fixed
            if defaultReference is None and point.fixed:
                defaultReference = point
        if defaultReference is None:
            defaultReference = printerInfo.manualProbePoints[0]
        self.referenceComboBox.setCurrentText(defaultReference.name)

    def clear(self):
        self.previousCommand = None
        self.log.clear()

    def _updateState(self):
        self.referenceComboBox.setEnabled(self.directionComboBox.currentData() == self.Direction.ANY)

    def _probeSingle(self, point):
        self.probe.emit(self.Command.SINGLE, [point])

    def _probeAll(self):
        self.probe.emit(self.Command.ALL,
                        [NamedPoint2F(p.name, p.x, p.y) for p in self.printerInfo.manualProbePoints])

    def reportProbe(self, command, resultList):
        if command == self.Command.SINGLE:
            assert(len(resultList) == 1)
            self._reportSingleProbe(resultList[0])

        elif command == self.Command.ALL:
            assert(len(resultList) > 1)
            self._reportAllProbe(resultList)

    def _reportSingleProbe(self, result):
        if self.previousCommand is self.Command.ALL:
            self.log.append('--------------------------------------------------')

        self.log.append(f'Probed {result.name} ({result.x}, {result.y}): {result.z:.3f}')
        self.previousCommand = self.Command.SINGLE

    def _reportAllProbe(self, resultList):
        referenceName, relativeDistanceList = self._relativeDistances(resultList,
                                                                      self.referenceComboBox.currentText(),
                                                                      self.directionComboBox.currentData(),
                                                                      self.printerInfo.screwType.clockwise)

        if self.previousCommand is not None:
            self.log.append('--------------------------------------------------')

        for raw, relative in zip(resultList, relativeDistanceList):
            assert(raw.name == relative.name)
            prefix = f'Probed {raw.name} ({raw.x:5.1f}, {raw.y:5.1f}): {raw.z:6.3f}'

            if self.outputComboBox.currentData() == self.Output.NONE:
                suffix = ''
            elif raw.name == referenceName:
                suffix = ' (Fixed reference)'
            elif self.fixedMap[raw.name]:
                suffix = ''
            else:
                suffix = self.adjustText(relative.z)

            self.log.append(prefix + suffix)
        self.previousCommand = self.Command.ALL

        # Remember this run for live adjust
        self.lastResults = {p.name: p.z for p in resultList}
        self.lastReferenceName = referenceName

        # Warn when the corners agree but the middle does not (a bowed bed)
        bowNote = self.bowWarning(resultList)
        if bowNote:
            self.appendNote(bowNote)

    def adjustText(self, relativeZ):
        """ Returns the ' (Adjust: ...)' / ' (Delta: ...)' text for a height difference. """
        output = self.outputComboBox.currentData()

        if output == self.Output.NONE:
            return ''
        if output == self.Output.DELTA:
            return f' (Delta: {relativeZ:6.3f})'

        turns = relativeZ / self.printerInfo.screwType.pitch
        positiveTurns = turns > 0
        turns = abs(turns)

        if output == self.Output.TURNS:
            amount = round(turns, 3)
            value = f'{amount:5.3f}'
            units = ' turns'
        elif output == self.Output.DEGREES:
            amount = round(360.0 * turns, 2)
            value = f'{amount:6.2f}'
            units = '\u00B0'
        elif output == self.Output.RADIANS:
            amount = round(2*math.pi * turns, 4)
            value = f'{amount:7.4f}'
            units = f' rad'
        else:
            hours = math.trunc(turns)
            minutes = round(60 * (turns - hours))
            amount = hours + minutes
            value = f'{hours:02.0f}:{minutes:02.0f}'
            units = ''

        if amount == 0:
            sign = ''
        elif self.printerInfo.screwType.clockwise:
            sign = ' CCW' if positiveTurns else ' CW'
        else:
            sign = ' CW' if positiveTurns else ' CCW'
        return f' (Adjust: {value}{units}{sign})'

    def appendNote(self, text):
        self.log.append(f'Note: {text}')

    @staticmethod
    def bowWarning(resultList, cornerTolerance=0.05, bowThreshold=0.08):
        """ Detects a bowed bed: outer points level with each other, middle point not. """
        if len(resultList) < 4:
            return None

        centerX = sum(p.x for p in resultList) / len(resultList)
        centerY = sum(p.y for p in resultList) / len(resultList)
        distance = lambda p: math.hypot(p.x - centerX, p.y - centerY)

        middle = min(resultList, key=distance)
        others = [p for p in resultList if p is not middle]
        nearestOther = min(distance(p) for p in others)
        if nearestOther <= 0 or distance(middle) > 0.5 * nearestOther:
            return None

        otherZ = [p.z for p in others]
        otherRange = max(otherZ) - min(otherZ)
        difference = middle.z - sum(otherZ) / len(otherZ)

        if otherRange > cornerTolerance or abs(difference) < bowThreshold:
            return None

        shape = 'higher than the edges (bed is domed)' if difference > 0 else 'lower than the edges (bed dips in the middle)'
        return (f'The outer points agree within {otherRange:.3f} mm, but {middle.name} is '
                f'{abs(difference):.3f} mm {shape}. Turning the knobs can\'t fix a bow; '
                f'leave them and let mesh bed leveling (G29) compensate.')

    def _startLiveAdjust(self):
        if not self.lastResults or self.lastReferenceName is None:
            QtWidgets.QMessageBox.information(self, 'Live adjust',
                                              'Run "Probe all" first so there is a reference height to adjust toward.')
            return

        candidates = [p for p in self.printerInfo.manualProbePoints
                      if p.name != self.lastReferenceName and not self.fixedMap.get(p.name, False)]
        if not candidates:
            QtWidgets.QMessageBox.information(self, 'Live adjust', 'There are no adjustable points.')
            return

        # Default to the point that is furthest off
        candidates.sort(key=lambda p: -abs(self.lastResults.get(p.name, 0.0) - self.lastResults[self.lastReferenceName]))
        names = [p.name for p in candidates]
        name, ok = QtWidgets.QInputDialog.getItem(self, 'Live adjust',
                                                  f'Point to adjust (reference: {self.lastReferenceName}):',
                                                  names, 0, False)
        if not ok:
            return

        point = next(p for p in candidates if p.name == name)
        self.liveAdjust.emit(NamedPoint2F(point.name, point.x, point.y),
                             self.lastReferenceName,
                             float(self.lastResults[self.lastReferenceName]))

    def liveReadingText(self, name, z, referenceName, referenceZ):
        relative = z - referenceZ
        return f'{name}: {z:6.3f} mm, {relative:+.3f} vs {referenceName}{self.adjustText(relative)}'

    def logLiveReading(self, text):
        if self.previousCommand is not None:
            self.log.append('--------------------------------------------------')
        self.log.append(f'Live adjust final reading - {text}')
        self.previousCommand = self.Command.SINGLE

    @classmethod
    def _relativeDistances(self, probeList, referenceName, direction, clockwiseScrew):
        # Determine the reference height
        if direction == self.Direction.ANY:
            for probe in probeList:
                if probe.name == referenceName:
                    referenceHeight = probe.z
                    break
        else:
            if (clockwiseScrew and direction == self.Direction.CW) or \
               (not clockwiseScrew and direction == self.Direction.CCW):
                index = -1
            else:
                index = 0
            sortedProbeList = sorted(probeList, key=lambda p: p.z)
            referenceName = sortedProbeList[index].name
            referenceHeight = sortedProbeList[index].z

        assert(referenceHeight is not None)
        return referenceName, [NamedPoint3F(p.name, p.x, p.y, p.z-referenceHeight) for p in probeList]

if __name__ == '__main__':
    # Main only imports
    from Common import Common
    from Common import PrinterInfo
    import sys
    import json

    def manualProbe(command, pointList):
        manualWidget.reportProbe(command,
                                 [NamedPoint3F(name=point.name, x=point.x, y=point.y, z=(index + 1) * 0.02) for index, point in enumerate(pointList)])

    # Read in the test printer description
    printerInfo = PrinterInfo.fromFile(Common.printersDir() / 'ElegooNeptune3Max.json')

    app = QtWidgets.QApplication(sys.argv)
    widget = QtWidgets.QWidget()

    # Create test ManualWidget
    manualWidget = ManualWidget()
    manualWidget.setPrinter(printerInfo)
    manualWidget.probe.connect(lambda command, pointList : manualProbe(command, pointList))

    # Layout widgets
    layout = QtWidgets.QVBoxLayout()
    layout.addWidget(manualWidget)
    widget.setLayout(layout)

    widget.show()
    sys.exit(app.exec())