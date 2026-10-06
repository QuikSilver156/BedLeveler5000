#!/usr/bin/env python

from Printers.Marlin2.OctoPrintConnection import OctoPrintSettings
from Printers.Marlin2.OctoPrintConnection import checkSettings
from PySide6 import QtCore
from PySide6 import QtWidgets

def loadSettings(settings):
    """ Returns OctoPrintSettings from QSettings, or None if not configured. """
    url = str(settings.value('octoPrint/url', '') or '')
    apiKey = str(settings.value('octoPrint/apiKey', '') or '')
    if not url or not apiKey:
        return None
    return OctoPrintSettings(url, apiKey)

class OctoPrintSettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = settings

        self.setWindowTitle('OctoPrint settings')

        self.urlLineEdit = QtWidgets.QLineEdit(str(settings.value('octoPrint/url', '') or ''))
        self.urlLineEdit.setPlaceholderText('http://octopi.local')

        self.apiKeyLineEdit = QtWidgets.QLineEdit(str(settings.value('octoPrint/apiKey', '') or ''))
        self.apiKeyLineEdit.setEchoMode(QtWidgets.QLineEdit.PasswordEchoOnEdit)
        self.apiKeyLineEdit.setPlaceholderText('From OctoPrint Settings -> Application Keys')

        help = QtWidgets.QLabel('Bed Leveler 5000 sends its commands through OctoPrint, so OctoPrint can stay '
                                'connected to the printer. In OctoPrint, open Settings -> Application Keys, '
                                'generate a key for "Bed Leveler 5000" and paste it here.\n\n'
                                'Don\'t level while a print is running.')
        help.setWordWrap(True)

        self.statusLabel = QtWidgets.QLabel('')
        self.statusLabel.setWordWrap(True)

        self.testButton = QtWidgets.QPushButton('Test')
        self.testButton.clicked.connect(self.test)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        form = QtWidgets.QFormLayout()
        form.addRow('OctoPrint address:', self.urlLineEdit)
        form.addRow('API key:', self.apiKeyLineEdit)

        testLayout = QtWidgets.QHBoxLayout()
        testLayout.addWidget(self.testButton)
        testLayout.addWidget(self.statusLabel, stretch=1)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(help)
        layout.addLayout(form)
        layout.addLayout(testLayout)
        layout.addWidget(buttons)
        self.setLayout(layout)
        self.setMinimumWidth(460)

    def currentSettings(self):
        return OctoPrintSettings(self.urlLineEdit.text(), self.apiKeyLineEdit.text())

    def test(self):
        if not self.urlLineEdit.text().strip() or not self.apiKeyLineEdit.text().strip():
            self.statusLabel.setText('Enter the address and API key first.')
            return
        self.statusLabel.setText('Testing...')
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            ok, message = checkSettings(self.currentSettings())
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        self.statusLabel.setText(('OK: ' if ok else 'Problem: ') + message)

    def save(self):
        self.settings.setValue('octoPrint/url', self.urlLineEdit.text().strip())
        self.settings.setValue('octoPrint/apiKey', self.apiKeyLineEdit.text().strip())
        self.accept()
