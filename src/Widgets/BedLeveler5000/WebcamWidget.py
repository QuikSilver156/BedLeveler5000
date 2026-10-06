#!/usr/bin/env python
""" Shows OctoPrint's webcams, so you can watch the nozzle while probing.

Cameras are read from OctoPrint's settings (GET /api/settings):
  - webcam.webcams[]                 OctoPrint 1.9+ (one entry per webcam plugin camera)
  - webcam.snapshotUrl / streamUrl   older OctoPrint, single classic webcam
  - plugins.multicam.multicam_profiles[]   MultiCam plugin

Frames come from the camera's snapshot URL, polled a few times a second. If a
camera only has an MJPEG stream URL, JPEG frames are cut out of the stream.
"""

from PySide6 import QtCore
from PySide6 import QtGui
from PySide6 import QtNetwork
from PySide6 import QtWidgets
import json
from typing import NamedTuple

class Camera(NamedTuple):
    name: str
    snapshotUrl: str
    streamUrl: str
    flipH: bool = False
    flipV: bool = False
    rotate90: bool = False

def _absolute(baseUrl, url):
    if not url:
        return ''
    url = url.strip()
    if url.startswith(('http://', 'https://')):
        return url
    return QtCore.QUrl(baseUrl + '/').resolved(QtCore.QUrl(url)).toString()

def camerasFromSettings(settingsJson, baseUrl):
    """ Builds the camera list from OctoPrint's /api/settings response. """
    cameras = []
    webcam = settingsJson.get('webcam') or {}

    for entry in webcam.get('webcams') or []:
        compat = entry.get('compat') or {}
        extras = entry.get('extras') or {}
        snapshot = compat.get('snapshot') or extras.get('snapshot') or ''
        if not snapshot and str(entry.get('snapshotDisplay', '')).startswith(('http://', 'https://', '/')):
            snapshot = entry['snapshotDisplay']
        stream = compat.get('stream') or extras.get('stream') or extras.get('streamUrl') or ''
        cameras.append(Camera(entry.get('displayName') or entry.get('name') or f'Camera {len(cameras) + 1}',
                              _absolute(baseUrl, snapshot), _absolute(baseUrl, stream),
                              bool(entry.get('flipH')), bool(entry.get('flipV')), bool(entry.get('rotate90'))))

    for profile in ((settingsJson.get('plugins') or {}).get('multicam') or {}).get('multicam_profiles') or []:
        cameras.append(Camera(profile.get('name') or f'Camera {len(cameras) + 1}',
                              _absolute(baseUrl, profile.get('snapshot', '')),
                              _absolute(baseUrl, profile.get('URL', '')),
                              bool(profile.get('flipH')), bool(profile.get('flipV')), bool(profile.get('rotate90'))))

    if not cameras and (webcam.get('snapshotUrl') or webcam.get('streamUrl')):
        cameras.append(Camera('Webcam', _absolute(baseUrl, webcam.get('snapshotUrl', '')),
                              _absolute(baseUrl, webcam.get('streamUrl', '')),
                              bool(webcam.get('flipH')), bool(webcam.get('flipV')), bool(webcam.get('rotate90'))))

    # Fill in a missing snapshot URL for mjpg-streamer style stream URLs
    fixed = []
    seen = set()
    for camera in cameras:
        if not camera.snapshotUrl and 'action=stream' in camera.streamUrl:
            camera = camera._replace(snapshotUrl=camera.streamUrl.replace('action=stream', 'action=snapshot'))
        key = (camera.snapshotUrl, camera.streamUrl)
        if key in seen:
            continue
        seen.add(key)
        fixed.append(camera)
    return fixed

class WebcamWidget(QtWidgets.QWidget):
    FPS_CHOICES = [1, 2, 5, 10]

    def __init__(self, settings, *args, compact=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.compact = compact
        self.settings = settings
        self.networkAccessManager = QtNetwork.QNetworkAccessManager(self)
        self.cameras = []
        self.pendingReply = None
        self.streamReply = None
        self.streamBuffer = b''
        self.octoPrintSettings = None
        self.lastPixmap = None

        self.cameraComboBox = QtWidgets.QComboBox()
        self.cameraComboBox.currentIndexChanged.connect(self._cameraChanged)

        self.fpsComboBox = QtWidgets.QComboBox()
        for fps in self.FPS_CHOICES:
            self.fpsComboBox.addItem(f'{fps} fps', fps)
        self.fpsComboBox.setCurrentIndex(self.FPS_CHOICES.index(2))
        self.fpsComboBox.currentIndexChanged.connect(self._restart)

        self.reloadButton = QtWidgets.QPushButton('Reload')
        self.reloadButton.setToolTip('Read the camera list from OctoPrint again')
        self.reloadButton.clicked.connect(self.reload)

        self.imageLabel = QtWidgets.QLabel('Webcam')
        self.imageLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.imageLabel.setMinimumSize(*((128, 96) if compact else (240, 180)))
        self.imageLabel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.imageLabel.setStyleSheet('QLabel { background-color: black; color: #ccc; }')
        self.imageLabel.setWordWrap(True)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._fetchSnapshot)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.cameraComboBox, stretch=1)
        top.addWidget(self.fpsComboBox)
        top.addWidget(self.reloadButton)

        layout = QtWidgets.QVBoxLayout()
        if compact:
            # Just the picture; click it to switch cameras
            for widget in (self.cameraComboBox, self.fpsComboBox, self.reloadButton):
                widget.hide()
            self.imageLabel.setCursor(QtCore.Qt.PointingHandCursor)
            self.imageLabel.setToolTip('Click to switch camera')
            layout.setContentsMargins(0, 0, 0, 0)
        else:
            layout.addLayout(top)
            layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.imageLabel, stretch=1)
        self.setLayout(layout)

    def mousePressEvent(self, event):
        if self.compact and self.cameraComboBox.count() > 1:
            self.cameraComboBox.setCurrentIndex((self.cameraComboBox.currentIndex() + 1) % self.cameraComboBox.count())
        elif self.compact and self.cameraComboBox.count() == 0:
            self.reload()
        super().mousePressEvent(event)

    # ----- Camera list -----
    def reload(self):
        from Dialogs.OctoPrintSettingsDialog import loadSettings
        self._stop()
        self.octoPrintSettings = loadSettings(self.settings)
        self.cameras = []
        self.cameraComboBox.blockSignals(True)
        self.cameraComboBox.clear()
        self.cameraComboBox.blockSignals(False)

        if self.octoPrintSettings is None:
            self._message('Set up OctoPrint first (Ports -> OctoPrint settings) to see its webcams.')
            return

        self._message('Asking OctoPrint for its webcams...')
        request = self._request(self.octoPrintSettings.baseUrl() + '/api/settings')
        reply = self.networkAccessManager.get(request)
        reply.finished.connect(lambda reply=reply: self._settingsReceived(reply))

    def _settingsReceived(self, reply):
        reply.deleteLater()
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            self._message(f'Could not read OctoPrint\'s settings: {reply.errorString()}')
            return
        try:
            data = json.loads(bytes(reply.readAll().data()))
        except ValueError:
            self._message('OctoPrint sent settings Bed Leveler 5000 couldn\'t read.')
            return

        self.cameras = camerasFromSettings(data, self.octoPrintSettings.baseUrl())
        if not self.cameras:
            self._message('OctoPrint has no webcams configured.')
            return

        lastName = str(self.settings.value('webcam/lastCamera', '') or '')
        self.cameraComboBox.blockSignals(True)
        for camera in self.cameras:
            self.cameraComboBox.addItem(camera.name)
            index = self.cameraComboBox.count() - 1
            self.cameraComboBox.setItemData(index, f'Snapshot: {camera.snapshotUrl or "-"}\nStream: {camera.streamUrl or "-"}',
                                            QtCore.Qt.ToolTipRole)
        names = [c.name for c in self.cameras]
        self.cameraComboBox.setCurrentIndex(names.index(lastName) if lastName in names else 0)
        self.cameraComboBox.blockSignals(False)
        self._cameraChanged()

    def _cameraChanged(self):
        if 0 <= self.cameraComboBox.currentIndex() < len(self.cameras):
            camera = self.cameras[self.cameraComboBox.currentIndex()]
            self.settings.setValue('webcam/lastCamera', camera.name)
            if self.compact:
                hint = ' - click to switch camera' if len(self.cameras) > 1 else ''
                self.imageLabel.setToolTip(f'{camera.name}{hint}')
        self.lastPixmap = None
        self._restart()

    # ----- Frames -----
    def currentCamera(self):
        index = self.cameraComboBox.currentIndex()
        return self.cameras[index] if 0 <= index < len(self.cameras) else None

    def _restart(self):
        self._stop()
        camera = self.currentCamera()
        if camera is None or not self.isVisible():
            return
        if camera.snapshotUrl:
            self.timer.start(int(1000 / self.fpsComboBox.currentData()))
            self._fetchSnapshot()
        elif camera.streamUrl:
            self._startStream(camera.streamUrl)
        else:
            self._message(f'"{camera.name}" has no snapshot or stream address in OctoPrint.')

    def _stop(self):
        self.timer.stop()
        if self.pendingReply is not None:
            self.pendingReply.abort()
            self.pendingReply = None
        if self.streamReply is not None:
            self.streamReply.abort()
            self.streamReply = None
        self.streamBuffer = b''

    def _request(self, url):
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        if self.octoPrintSettings is not None and url.startswith(self.octoPrintSettings.baseUrl()):
            request.setRawHeader(b'X-Api-Key', self.octoPrintSettings.apiKey.strip().encode())
        request.setTransferTimeout(5000)
        return request

    def _fetchSnapshot(self):
        camera = self.currentCamera()
        if camera is None or self.pendingReply is not None:
            return # Skip a frame rather than pile up requests
        reply = self.networkAccessManager.get(self._request(camera.snapshotUrl))
        self.pendingReply = reply
        reply.finished.connect(lambda reply=reply: self._snapshotReceived(reply))

    def _snapshotReceived(self, reply):
        if reply is self.pendingReply:
            self.pendingReply = None
        reply.deleteLater()
        if reply.error() == QtNetwork.QNetworkReply.OperationCanceledError:
            return
        if reply.error() != QtNetwork.QNetworkReply.NoError:
            if self.lastPixmap is None:
                self._message(f'Snapshot failed: {reply.errorString()}')
            return
        self._showJpeg(bytes(reply.readAll().data()))

    def _startStream(self, url):
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        if self.octoPrintSettings is not None and url.startswith(self.octoPrintSettings.baseUrl()):
            request.setRawHeader(b'X-Api-Key', self.octoPrintSettings.apiKey.strip().encode())
        self.streamBuffer = b''
        self.streamReply = self.networkAccessManager.get(request)
        self.streamReply.readyRead.connect(self._streamData)

    def _streamData(self):
        if self.streamReply is None:
            return
        self.streamBuffer += bytes(self.streamReply.readAll().data())
        # Show the newest complete JPEG (start FFD8, end FFD9) and drop older ones
        end = self.streamBuffer.rfind(b'\xff\xd9')
        if end < 0:
            if len(self.streamBuffer) > 8_000_000:
                self.streamBuffer = b''
            return
        start = self.streamBuffer.rfind(b'\xff\xd8', 0, end)
        if start >= 0:
            self._showJpeg(self.streamBuffer[start:end + 2])
        self.streamBuffer = self.streamBuffer[end + 2:]

    def _showJpeg(self, data):
        image = QtGui.QImage.fromData(data)
        if image.isNull():
            return
        camera = self.currentCamera()
        if camera is not None and (camera.flipH or camera.flipV):
            image = image.mirrored(camera.flipH, camera.flipV)
        if camera is not None and camera.rotate90:
            image = image.transformed(QtGui.QTransform().rotate(-90))
        self.lastPixmap = QtGui.QPixmap.fromImage(image)
        self._scalePixmap()

    def _scalePixmap(self):
        if self.lastPixmap is not None:
            self.imageLabel.setPixmap(self.lastPixmap.scaled(self.imageLabel.size(), QtCore.Qt.KeepAspectRatio,
                                                             QtCore.Qt.SmoothTransformation))

    def _message(self, text):
        if self.compact:
            if 'OctoPrint first' in text:
                text = 'Set up OctoPrint\n(Ports menu)\nto see cameras'
            elif 'Asking' in text:
                text = 'Loading cameras...'
            elif 'no webcams' in text:
                text = 'No cameras in OctoPrint'
            self.imageLabel.setToolTip(text.replace('\n', ' '))
        self.lastPixmap = None
        self.imageLabel.setPixmap(QtGui.QPixmap())
        self.imageLabel.setText(text)

    # ----- Only stream while visible -----
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scalePixmap()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.cameras:
            self.reload()
        else:
            self._restart()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._stop()
