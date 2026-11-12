#!/usr/bin/env python

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtWidgets

class LiveAdjustDialog(QtWidgets.QDialog):
    """ Live adjust status with 'Next point' (stays open) and 'Done' (rejects). """
    nextRequested = QtCore.Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowFlags(QtCore.Qt.Dialog | QtCore.Qt.CustomizeWindowHint | QtCore.Qt.WindowTitleHint)
        self.setWindowTitle('Live adjust')
        self.setModal(True)

        icon = QtWidgets.QLabel()
        icon.setPixmap(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation).pixmap(40, 40))
        icon.setAlignment(QtCore.Qt.AlignTop)

        self.textLabel = QtWidgets.QLabel()
        self.textLabel.setWordWrap(True)
        # A fixed width lets the label work out exactly how tall its wrapped text is
        self.textLabel.setFixedWidth(560)
        self.textLabel.setTextFormat(QtCore.Qt.PlainText)
        self.textLabel.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        font = self.textLabel.font()
        font.setPointSizeF(font.pointSizeF() * 1.15)
        self.textLabel.setFont(font)

        self.nextButton = QtWidgets.QPushButton('Next point')
        self.nextButton.setToolTip('Finish this point and move to the next one (1, 2, 3, ...)')
        self.nextButton.clicked.connect(self.nextRequested)
        self.doneButton = QtWidgets.QPushButton('Done')
        self.doneButton.setDefault(True)
        self.doneButton.clicked.connect(self.reject)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(icon)
        top.addWidget(self.textLabel, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.nextButton)
        buttons.addWidget(self.doneButton)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(top)
        layout.addLayout(buttons)
        # Grow and shrink with the text so nothing is cut off
        layout.setSizeConstraint(QtWidgets.QLayout.SetFixedSize)
        self.setLayout(layout)

    def setText(self, text):
        self.textLabel.setText(text)
        self.textLabel.setMinimumHeight(self.textLabel.heightForWidth(self.textLabel.width()))
        self.adjustSize()
