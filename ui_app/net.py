from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Optional

from PySide6 import QtCore, QtNetwork


@dataclass(frozen=True)
class NetError(Exception):
    message: str
    status: int | None = None
    body: str | None = None


class NetJob(QtCore.QObject):
    ok = QtCore.Signal(object)  # parsed JSON
    failed = QtCore.Signal(object)  # NetError
    finished = QtCore.Signal()

    def __init__(
        self,
        reply: QtNetwork.QNetworkReply,
        *,
        timeout_ms: int = 10000,
        tag: str = "",
    ) -> None:
        super().__init__()
        self.reply = reply
        self.tag = tag
        self._t0 = time.time()

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.start(timeout_ms)

        reply.finished.connect(self._on_finished)

    def cancel(self) -> None:
        try:
            if self.reply and self.reply.isRunning():
                self.reply.abort()
        except Exception:
            pass

    def _on_timeout(self) -> None:
        self.cancel()

    def _on_finished(self) -> None:
        try:
            self._timer.stop()
        except Exception:
            pass

        reply = self.reply
        status = None
        try:
            status = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
        except Exception:
            status = None

        try:
            raw = bytes(reply.readAll()).decode("utf-8", errors="replace")
        except Exception:
            raw = ""

        # Qt can finish with an error code even if HTTP status exists.
        err = reply.error()
        if err != QtNetwork.QNetworkReply.NetworkError.NoError:
            msg = reply.errorString()
            self.failed.emit(NetError(f"{self.tag} {msg}".strip(), status=int(status) if status else None, body=raw[:400]))
            self.finished.emit()
            reply.deleteLater()
            return

        if status is not None and int(status) >= 400:
            self.failed.emit(NetError(f"{self.tag} HTTP {int(status)}".strip(), status=int(status), body=raw[:400]))
            self.finished.emit()
            reply.deleteLater()
            return

        # Parse JSON
        try:
            data: Any = json.loads(raw) if raw else {}
        except Exception as e:
            self.failed.emit(NetError(f"{self.tag} JSON parse failed: {e}".strip(), status=int(status) if status else None, body=raw[:400]))
            self.finished.emit()
            reply.deleteLater()
            return

        self.ok.emit(data)
        self.finished.emit()
        reply.deleteLater()


class Net(QtCore.QObject):
    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self.manager = QtNetwork.QNetworkAccessManager(self)

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        timeout_ms: int = 10000,
        tag: str = "",
    ) -> NetJob:
        qurl = QtCore.QUrl(url)
        if params:
            q = QtCore.QUrlQuery()
            for k, v in params.items():
                q.addQueryItem(str(k), str(v))
            qurl.setQuery(q)

        req = QtNetwork.QNetworkRequest(qurl)
        if headers:
            for k, v in headers.items():
                req.setRawHeader(str(k).encode("utf-8"), str(v).encode("utf-8"))

        m = method.upper()
        payload: QtCore.QByteArray | None = None
        if json_body is not None:
            req.setRawHeader(b"Content-Type", b"application/json")
            payload = QtCore.QByteArray(json.dumps(json_body).encode("utf-8"))

        if m == "GET":
            reply = self.manager.get(req)
        elif m == "POST":
            reply = self.manager.post(req, payload or QtCore.QByteArray())
        elif m == "PUT":
            reply = self.manager.put(req, payload or QtCore.QByteArray())
        elif m == "PATCH":
            reply = self.manager.sendCustomRequest(req, b"PATCH", payload or QtCore.QByteArray())
        elif m == "DELETE":
            reply = self.manager.deleteResource(req)
        else:
            reply = self.manager.sendCustomRequest(req, m.encode("utf-8"), payload or QtCore.QByteArray())

        return NetJob(reply, timeout_ms=timeout_ms, tag=tag)


_NET_KEY = "my_own_script_net_singleton"


def get_net() -> Net:
    app = QtCore.QCoreApplication.instance()
    if app is None:
        raise RuntimeError("QApplication not initialized")
    net = app.property(_NET_KEY)
    if isinstance(net, Net):
        return net
    net = Net(app)
    app.setProperty(_NET_KEY, net)
    return net
