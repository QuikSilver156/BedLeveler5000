#!/usr/bin/env python
""" Live temperature graph (bed and nozzle, actual and target), drawn with QPainter. """

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets
from collections import deque
import math
import time

class TemperatureGraphWidget(QtWidgets.QWidget):
    WINDOW_CHOICES = [(60, '1 min'), (300, '5 min'), (900, '15 min'), (1800, '30 min')]
    MAX_SAMPLES = 4000

    BED_COLOR = QtGui.QColor('#1f77b4')
    NOZZLE_COLOR = QtGui.QColor('#d62728')

    def __init__(self, *args, compact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.compact = compact
        self.samples = deque(maxlen=self.MAX_SAMPLES)  # (time, bedActual, bedTarget, nozzleActual, nozzleTarget)

        self.windowComboBox = QtWidgets.QComboBox()
        for seconds, label in self.WINDOW_CHOICES:
            self.windowComboBox.addItem(label, seconds)
        self.windowComboBox.setCurrentIndex(1)
        self.windowComboBox.currentIndexChanged.connect(self.update)

        self.clearButton = QtWidgets.QPushButton('Clear')
        self.clearButton.clicked.connect(self.clear)

        self.currentLabel = QtWidgets.QLabel('No readings yet')

        self.canvas = _Canvas(self)
        self.canvas.setMinimumSize(*((170, 96) if compact else (260, 160)))

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.currentLabel, stretch=1)
        top.addWidget(self.windowComboBox)
        top.addWidget(self.clearButton)

        layout = QtWidgets.QVBoxLayout()
        if compact:
            # Graph only (last 5 minutes); current values in the tooltip
            for widget in (self.currentLabel, self.windowComboBox, self.clearButton):
                widget.hide()
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            layout.addLayout(top)
            layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.canvas, stretch=1)
        self.setLayout(layout)

    def addReading(self, bedActual, bedTarget, nozzleActual, nozzleTarget):
        self.samples.append((time.monotonic(), bedActual, bedTarget, nozzleActual, nozzleTarget))
        self.currentLabel.setText(f'<span style="color:{self.BED_COLOR.name()}">Bed {bedActual:.1f}/{bedTarget:.0f}°C</span>'
                                  f' &nbsp; <span style="color:{self.NOZZLE_COLOR.name()}">Nozzle '
                                  f'{nozzleActual:.1f}/{nozzleTarget:.0f}°C</span>')
        if self.compact:
            self.canvas.setToolTip(f'Bed {bedActual:.1f}/{bedTarget:.0f}\u00B0C, nozzle {nozzleActual:.1f}/{nozzleTarget:.0f}\u00B0C')
        if self.isVisible():
            self.canvas.update()

    def clear(self):
        self.samples.clear()
        self.currentLabel.setText('No readings yet')
        self.canvas.update()

    def windowSeconds(self):
        return self.windowComboBox.currentData()

class _Canvas(QtWidgets.QWidget):
    def __init__(self, graph):
        super().__init__(graph)
        self.graph = graph

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(QtGui.QPalette.Base))

        metrics = painter.fontMetrics()
        left = metrics.horizontalAdvance('250°') + 8
        right, top, bottom = 8, 8, metrics.height() + 6
        plot = QtCore.QRectF(left, top, max(10, self.width() - left - right), max(10, self.height() - top - bottom))

        now = time.monotonic()
        window = self.graph.windowSeconds()
        samples = [s for s in self.graph.samples if now - s[0] <= window]

        # Y range: 0 to a round number above the highest reading or target
        highest = max([max(s[1:]) for s in samples], default=50)
        yMax = max(50, math.ceil((highest + 10) / 50) * 50)

        def x(t):
            return plot.left() + plot.width() * (1 - (now - t) / window)

        def y(value):
            return plot.bottom() - plot.height() * max(0.0, min(value, yMax)) / yMax

        # Grid and labels
        gridPen = QtGui.QPen(palette.color(QtGui.QPalette.Mid))
        gridPen.setStyle(QtCore.Qt.DotLine)
        textColor = palette.color(QtGui.QPalette.Text)
        step = 50 if yMax > 150 else 25
        value = 0
        while value <= yMax:
            painter.setPen(gridPen)
            painter.drawLine(QtCore.QPointF(plot.left(), y(value)), QtCore.QPointF(plot.right(), y(value)))
            painter.setPen(textColor)
            painter.drawText(QtCore.QRectF(0, y(value) - metrics.height() / 2, left - 4, metrics.height()),
                             QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, f'{value}°')
            value += step
        painter.setPen(textColor)
        painter.drawText(QtCore.QRectF(plot.left(), plot.bottom() + 2, plot.width(), metrics.height()),
                         QtCore.Qt.AlignLeft, f'-{self.graph.windowComboBox.currentText()}')
        painter.drawText(QtCore.QRectF(plot.left(), plot.bottom() + 2, plot.width(), metrics.height()),
                         QtCore.Qt.AlignRight, 'now')
        painter.setPen(QtGui.QPen(palette.color(QtGui.QPalette.Mid)))
        painter.drawRect(plot)

        if len(samples) < 2:
            painter.setPen(textColor)
            painter.drawText(plot, QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap,
                             'No readings yet' if self.graph.compact else 'Connect to the printer to see temperatures')
            return

        def drawSeries(index, color, dashed):
            pen = QtGui.QPen(color, 1.5 if dashed else 2)
            if dashed:
                pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen)
            path = QtGui.QPainterPath()
            for n, sample in enumerate(samples):
                point = QtCore.QPointF(x(sample[0]), y(sample[index]))
                if n == 0:
                    path.moveTo(point)
                else:
                    path.lineTo(point)
            painter.drawPath(path)

        drawSeries(2, self.graph.BED_COLOR, True)
        drawSeries(4, self.graph.NOZZLE_COLOR, True)
        drawSeries(1, self.graph.BED_COLOR, False)
        drawSeries(3, self.graph.NOZZLE_COLOR, False)

        # Legend
        painter.setPen(textColor)
        if self.graph.compact:
            # Current values instead of a legend
            last = samples[-1]
            painter.setPen(self.graph.BED_COLOR)
            painter.drawText(QtCore.QRectF(plot.left() + 4, plot.top() + 2, plot.width() - 8, metrics.height()),
                             QtCore.Qt.AlignLeft, f'Bed {last[1]:.0f}\u00B0')
            painter.setPen(self.graph.NOZZLE_COLOR)
            painter.drawText(QtCore.QRectF(plot.left() + 4, plot.top() + 2, plot.width() - 8, metrics.height()),
                             QtCore.Qt.AlignRight, f'Noz {last[3]:.0f}\u00B0')
            return
        legend = 'solid = actual, dashed = target'
        painter.drawText(QtCore.QRectF(plot.left() + 4, plot.top() + 2, plot.width() - 8, metrics.height()),
                         QtCore.Qt.AlignRight, legend)
