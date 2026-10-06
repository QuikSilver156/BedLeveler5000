#!/usr/bin/env python
""" Sends Marlin commands through OctoPrint instead of a local serial port.

Commands go out through OctoPrint's REST API (POST /api/printer/command) and
replies are read from OctoPrint's terminal log over its push socket
(/sockjs/websocket).

OctoPrint shares the printer with us and may send its own commands (for
example M105 temperature polling on firmware without auto-reporting). Marlin
answers commands strictly in order, so every 'Send:' line in OctoPrint's log
is tracked in a FIFO: reply lines are handed to Bed Leveler only while the
oldest unanswered command is one of ours, and each 'ok' retires the oldest
command. Replies to OctoPrint's own commands are dropped.
"""

from .CommandConnection import CommandConnection
from PySide6 import QtCore
from PySide6 import QtNetwork
from PySide6 import QtWebSockets
from collections import deque
import json
import re
from typing import NamedTuple

class OctoPrintSettings(NamedTuple):
    url: str
    apiKey: str

    def baseUrl(self):
        url = self.url.strip().rstrip('/')
        if '://' not in url:
            url = 'http://' + url
        return url

    def socketUrl(self):
        url = self.baseUrl()
        if url.startswith('https://'):
            return 'wss://' + url[len('https://'):] + '/sockjs/websocket'
        return 'ws://' + url[len('http://'):] + '/sockjs/websocket'

# OctoPrint logs sent lines as "Send: N12 G28*45" (line number and checksum optional)
SEND_PATTERN = re.compile(r'^(?:N\d+\s+)?(.*?)(?:\*\d+)?\s*$')

# OctoPrint's terminal log marks lines either 'Send: '/'Recv: ' or '>>> '/'<<< '
SEND_PREFIXES = ('Send: ', '>>> ')
RECV_PREFIXES = ('Recv: ', '<<< ')

def splitLogLine(logLine):
    """ Returns ('send'|'recv'|None, text). """
    for prefix in SEND_PREFIXES:
        if logLine.startswith(prefix):
            return 'send', logLine[len(prefix):]
    for prefix in RECV_PREFIXES:
        if logLine.startswith(prefix):
            return 'recv', logLine[len(prefix):]
    return None, logLine

# Commands that move the machine. If one of these appears in OctoPrint's log
# and it isn't ours, someone else is driving the printer.
MOTION_CODES = {'G0', 'G1', 'G2', 'G3', 'G28', 'G29', 'G30', 'G38.2', 'G38.3', 'G80', 'M48'}

# OctoPrint state flags that mean the printer is busy with a job
BUSY_FLAGS = ('printing', 'paused', 'pausing', 'resuming', 'cancelling', 'finishing')

def busyReasonFromFlags(flags):
    for flag in BUSY_FLAGS:
        if flags.get(flag):
            return flag
    return None

TEMPERATURE_REPORT = re.compile(r'^\s*T\d*:\s*-?[0-9.]+')

def normalizeCommand(command):
    return ' '.join(command.strip().upper().split())

def request(networkAccessManager, settings, method, path, body=None, timeoutMs=5000):
    """ Blocking HTTP request (runs a local event loop). Returns (status, bytes, errorString). """
    qtRequest = QtNetwork.QNetworkRequest(QtCore.QUrl(settings.baseUrl() + path))
    qtRequest.setRawHeader(b'X-Api-Key', settings.apiKey.strip().encode())
    qtRequest.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, 'application/json')
    qtRequest.setTransferTimeout(timeoutMs)

    data = QtCore.QByteArray(json.dumps(body).encode()) if body is not None else QtCore.QByteArray()
    if method == 'GET':
        reply = networkAccessManager.get(qtRequest)
    else:
        reply = networkAccessManager.post(qtRequest, data)

    loop = QtCore.QEventLoop()
    reply.finished.connect(loop.quit)
    if not reply.isFinished():
        loop.exec()

    status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
    payload = bytes(reply.readAll().data())
    error = None if reply.error() == QtNetwork.QNetworkReply.NoError else reply.errorString()
    reply.deleteLater()
    return status, payload, error

def checkSettings(settings, networkAccessManager=None):
    """ Returns (ok, message) describing whether OctoPrint is reachable and connected to the printer. """
    networkAccessManager = networkAccessManager or QtNetwork.QNetworkAccessManager()

    status, payload, error = request(networkAccessManager, settings, 'GET', '/api/version')
    if status is None:
        return False, f'Could not reach OctoPrint at {settings.baseUrl()}: {error}'
    if status in (401, 403):
        return False, 'OctoPrint rejected the API key. Create one under OctoPrint Settings -> Application Keys.'
    if status != 200:
        return False, f'OctoPrint answered with HTTP {status}.'
    try:
        version = json.loads(payload).get('server', '?')
    except ValueError:
        version = '?'

    status, payload, error = request(networkAccessManager, settings, 'GET', '/api/connection')
    try:
        state = json.loads(payload)['current']['state']
    except (ValueError, KeyError, TypeError):
        state = 'Unknown'

    # Refuse while a job is running or paused
    status, payload, error = request(networkAccessManager, settings, 'GET', '/api/printer?exclude=temperature,sd')
    try:
        flags = json.loads(payload)['state']['flags']
    except (ValueError, KeyError, TypeError):
        flags = {}
    busy = busyReasonFromFlags(flags)
    if busy:
        return False, f'OctoPrint reports the printer is {busy} ("{state}"). Wait for the job to finish ' \
                      f'(or cancel it) before leveling.'

    if state not in ('Operational',):
        return False, f'OctoPrint {version} is reachable, but its printer state is "{state}". ' \
                      f'Connect OctoPrint to the printer (and make sure nothing is printing) first.'
    return True, f'Connected to OctoPrint {version}. Printer is Operational.'

class OctoPrintCommandConnection(CommandConnection):
    connectionError = QtCore.Signal(str)

    OPEN_TIMEOUT_MS = 8000

    def __init__(self, *args, octoPrintSettings, **kwargs):
        super().__init__(*args, **kwargs)
        self.settings = octoPrintSettings
        self.networkAccessManager = QtNetwork.QNetworkAccessManager(self)
        self.socket = None
        self._isOpen = False
        self._ready = False
        self._sentFifo = deque()      # [isOurs] for every command OctoPrint logged as sent
        self._oursPending = deque()   # normalized commands we've posted but not yet seen sent
        self._replies = set()
        self._resetStats()
        self.busyReason = None
        self.failedCommands = []

    def _resetStats(self):
        self.stats = {'socketMessages': 0, 'liveUpdates': 0, 'sendLines': 0, 'recvLines': 0,
                      'oursSent': 0, 'oursPosted': 0, 'logLines': 0, 'lastLogLines': deque(maxlen=12),
                      'messageTypes': set()}

    def diagnostics(self):
        """ Plain-language summary of what has come back from OctoPrint so far. """
        s = self.stats
        if s['socketMessages'] == 0:
            return ('Nothing has arrived on OctoPrint\'s push socket. The connection to '
                    f'{self.settings.socketUrl()} opened but stayed silent - this usually means a proxy or '
                    'remote-access service (e.g. OctoEverywhere) is in between. Use OctoPrint\'s local address '
                    '(like http://octopi.local or its IP address) instead.')
        types = ', '.join(sorted(s['messageTypes'])) or 'none'
        if s['liveUpdates'] == 0:
            return ('OctoPrint\'s push socket answered but sent no live updates, so it most likely rejected the '
                    f'login. Try generating a new Application Key in OctoPrint. (Message types received: {types})')
        if s['logLines'] == 0:
            return (f'OctoPrint sent {s["liveUpdates"]} live updates, but none contained terminal lines. '
                    f'(Message types received: {types})')
        if s['sendLines'] == 0 and s['recvLines'] == 0:
            return (f'OctoPrint sent {s["logLines"]} terminal lines, but in a format Bed Leveler doesn\'t '
                    'recognize. Last lines seen:\n' + '\n'.join(s['lastLogLines']))
        if s['oursSent'] == 0:
            return (f'OctoPrint accepted {s["oursPosted"]} command(s), but none of them appeared in its terminal '
                    'log, so the replies could not be matched. Last lines seen:\n' + '\n'.join(s['lastLogLines']))
        return ('Commands reached the printer, but no reply has finished yet (homing can take a while). '
                'Last lines seen:\n' + '\n'.join(s['lastLogLines']))

    # ----- SerialConnection interface -----
    def connected(self):
        return self._isOpen

    def port(self):
        return 'OctoPrint'

    def open(self, portName=None, *, clear=True):
        assert not self._isOpen

        ok, message = checkSettings(self.settings, self.networkAccessManager)
        if not ok:
            self._error(message)

        # Passive login turns the API key into a session for the push socket
        status, payload, error = request(self.networkAccessManager, self.settings, 'POST', '/api/login', {'passive': True})
        try:
            login = json.loads(payload)
            auth = f'{login["name"]}:{login["session"]}'
        except (ValueError, KeyError, TypeError):
            self._error(f'OctoPrint login failed ({status or error}).')

        self.socket = QtWebSockets.QWebSocket()
        self.socket.textMessageReceived.connect(self._socketMessage)
        self.socket.disconnected.connect(self._socketDisconnected)

        loop = QtCore.QEventLoop()
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        self.socket.connected.connect(loop.quit)
        self.socket.open(QtCore.QUrl(self.settings.socketUrl()))
        timer.start(self.OPEN_TIMEOUT_MS)
        loop.exec()

        if self.socket.state() != QtNetwork.QAbstractSocket.ConnectedState:
            self.socket.abort()
            self.socket = None
            self._error(f'Could not open OctoPrint\'s push socket at {self.settings.socketUrl()}.')

        self.socket.sendTextMessage(json.dumps({'auth': auth}))
        self.socket.sendTextMessage(json.dumps({'throttle': 1}))

        self._sentFifo.clear()
        self._oursPending.clear()
        self._resetStats()
        self.linesReceived = 0
        self._isOpen = True
        self._ready = True
        self.logger.info(f'Opened OctoPrint connection to {self.settings.baseUrl()}')

    def close(self):
        self._isOpen = False
        self._ready = False
        if self.socket is not None:
            try:
                self.socket.disconnected.disconnect(self._socketDisconnected)
            except (RuntimeError, TypeError):
                pass
            self.socket.close()
            self.socket.deleteLater()
            self.socket = None
        self.logger.info('Closed OctoPrint connection')

    MAX_POST_ATTEMPTS = 3

    # Errors where the request never reached OctoPrint, so sending it again is safe
    RETRYABLE_ERRORS = (QtNetwork.QNetworkReply.RemoteHostClosedError,
                        QtNetwork.QNetworkReply.ConnectionRefusedError,
                        QtNetwork.QNetworkReply.TimeoutError,
                        QtNetwork.QNetworkReply.TemporaryNetworkFailureError,
                        QtNetwork.QNetworkReply.NetworkSessionFailedError,
                        QtNetwork.QNetworkReply.UnknownNetworkError)

    def write(self, string):
        command = string.strip()
        self._oursPending.append(normalizeCommand(command))
        self.stats['oursPosted'] += 1
        self._post(command, attempt=1)

    def _post(self, command, attempt):
        qtRequest = QtNetwork.QNetworkRequest(QtCore.QUrl(self.settings.baseUrl() + '/api/printer/command'))
        qtRequest.setRawHeader(b'X-Api-Key', self.settings.apiKey.strip().encode())
        qtRequest.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, 'application/json')
        qtRequest.setTransferTimeout(10000)
        reply = self.networkAccessManager.post(qtRequest, QtCore.QByteArray(json.dumps({'commands': [command]}).encode()))
        self._replies.add(reply)
        reply.finished.connect(lambda reply=reply, command=command, attempt=attempt:
                               self._commandPosted(reply, command, attempt))

    def waitForPosts(self, timeoutMs=5000):
        """ Waits (running the event loop) until every posted command has an answer.
            Returns the commands OctoPrint did not accept. """
        self.failedCommands = []
        timer = QtCore.QElapsedTimer()
        timer.start()
        while self._replies and timer.elapsed() < timeoutMs:
            loop = QtCore.QEventLoop()
            QtCore.QTimer.singleShot(50, loop.quit)
            loop.exec()
        unanswered = len(self._replies)
        return self.failedCommands + (['(no answer)'] * unanswered)

    # ----- Internals -----
    def _commandPosted(self, reply, command, attempt):
        self._replies.discard(reply)
        status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
        error = reply.error()
        errorString = reply.errorString()
        reply.deleteLater()

        if status in (200, 204) or not self._isOpen:
            return # Done, or we've disconnected and no longer care

        # 408: the web server in front of OctoPrint closed an idle connection just as this request
        # arrived, so OctoPrint never saw it. Same for connection-level errors. Send it again.
        if (status == 408 or (status is None and error in self.RETRYABLE_ERRORS)) and attempt < self.MAX_POST_ATTEMPTS:
            self.logger.info(f'Retrying "{command}" (attempt {attempt + 1}) after {status or errorString}')
            self._post(command, attempt + 1)
            return

        if status == 409:
            message = 'OctoPrint refused the command because the printer is not operational or is printing.'
        else:
            message = f'OctoPrint did not accept "{command}" (HTTP {status}: {errorString}).'
        self.logger.error(message)
        if not hasattr(self, 'failedCommands'):
            self.failedCommands = []
        self.failedCommands.append(command)

        # While shutting down (heaters-off), the caller reports failures itself
        if not self._isOpen or self.ignoreReplies:
            return
        self.connectionError.emit(message)

    def _socketDisconnected(self):
        if self._isOpen:
            self._isOpen = False
            self.connectionError.emit('Lost the connection to OctoPrint.')

    def _socketMessage(self, text):
        self.stats['socketMessages'] += 1
        try:
            message = json.loads(text)
        except ValueError:
            return
        if isinstance(message, dict):
            self.stats['messageTypes'].update(message.keys())
            self.logger.debug(f'OctoPrint push message: {", ".join(message.keys())}')

        # Only live updates; 'history' holds log lines from before we connected
        current = message.get('current') if isinstance(message, dict) else None
        if not current:
            return
        self.stats['liveUpdates'] += 1

        stateInfo = current.get('state') or {}
        state = stateInfo.get('text')
        if state and state.startswith(('Offline', 'Error', 'Closed')) and self._isOpen:
            self.connectionError.emit(f'OctoPrint lost the printer (state: {state}).')
            return

        # Fail-safe: stop immediately if a job starts in OctoPrint while we're connected
        self.busyReason = busyReasonFromFlags(stateInfo.get('flags') or {})
        if self.busyReason and self._isOpen:
            self.connectionError.emit(f'OctoPrint reports the printer is {self.busyReason} ("{state}"). '
                                      'Bed Leveler 5000 disconnected so it can\'t interfere with the job.')
            return

        for logLine in current.get('logs') or []:
            self._processLogLine(logLine)

    def _processLogLine(self, logLine):
        self.stats['logLines'] += 1
        self.stats['lastLogLines'].append(logLine)
        self.logger.debug(f'OctoPrint log: {logLine}')

        kind, text = splitLogLine(logLine)

        if kind == 'send':
            self.stats['sendLines'] += 1
            sent = SEND_PATTERN.match(text).group(1)
            normalized = normalizeCommand(sent)
            # Exact match, or the same G/M code (OctoPrint can reformat parameters)
            isOurs = len(self._oursPending) > 0 and \
                     (self._oursPending[0] == normalized or
                      self._oursPending[0].split()[:1] == normalized.split()[:1])
            if isOurs:
                self._oursPending.popleft()
                self.stats['oursSent'] += 1
            elif self._isOpen and normalized.split()[:1] and normalized.split()[0] in MOTION_CODES:
                # Fail-safe: another OctoPrint user, plugin or terminal is moving the printer
                self.connectionError.emit(f'Another program sent a movement command through OctoPrint '
                                          f'("{sent.strip()}"). Bed Leveler 5000 disconnected so the two '
                                          'don\'t fight over the printer. Wait for it to finish, then reconnect.')
            self._sentFifo.append(isOurs)
            return

        if kind != 'recv':
            return

        line = text
        self.stats['recvLines'] += 1
        if line.strip() == '' or line.strip() == 'wait':
            return

        isOk = line.startswith('ok')

        # Temperature auto-reports (M155) aren't replies to anything
        if not isOk and TEMPERATURE_REPORT.match(line):
            return
        if not self._sentFifo:
            return # Unsolicited line (auto-report, echo) with nothing outstanding

        headIsOurs = self._sentFifo[0]
        if isOk:
            self._sentFifo.popleft()

        if headIsOurs and self._ready:
            self.logger.debug(f'Line: {line}')
            self.linesReceived += 1
            try:
                self._processLine(line)
            except IOError as exception:
                self.logger.error(str(exception))
                self.connectionError.emit(str(exception))
