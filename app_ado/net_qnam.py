from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Optional

from PySide6 import QtCore, QtNetwork


@dataclass(frozen=True)
class NetError:
    message: str
    url: str
    status: int | None = None
    body: str | None = None


class NetJob(QtCore.QObject):
    ok = QtCore.Signal(object)      # parsed json
    failed = QtCore.Signal(object)  # NetError
    finished = QtCore.Signal()

    def __init__(self, reply: QtNetwork.QNetworkReply, *, url: str, timeout_ms: int = 10000, tag: str = "") -> None:
        super().__init__()
        self._reply = reply
        self._url = url
        self._tag = tag

        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.start(timeout_ms)

        reply.finished.connect(self._on_finished)

    def cancel(self) -> None:
        try:
            if self._reply and self._reply.isRunning():
                self._reply.abort()
        except Exception:
            pass

    def _on_timeout(self) -> None:
        self.cancel()

    def _on_finished(self) -> None:
        try:
            self._timer.stop()
        except Exception:
            pass

        r = self._reply
        status = r.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute)
        try:
            status_i = int(status) if status is not None else None
        except Exception:
            status_i = None

        try:
            raw = bytes(r.readAll()).decode("utf-8", errors="replace")
        except Exception:
            raw = ""

        err = r.error()
        if err != QtNetwork.QNetworkReply.NetworkError.NoError:
            # include Qt error code for diagnostics
            try:
                err_code = int(err.value)  # type: ignore[attr-defined]
            except Exception:
                try:
                    err_code = int(err)  # fallback
                except Exception:
                    err_code = -1

            self.failed.emit(
                NetError(
                    f"{self._tag} QtError={err_code} {r.errorString()}".strip(),
                    url=self._url,
                    status=status_i,
                    body=raw[:2000],
                )
            )
            self.finished.emit()
            r.deleteLater()
            return

        if status_i is not None and status_i >= 400:
            self.failed.emit(NetError(f"{self._tag} HTTP {status_i}".strip(), url=self._url, status=status_i, body=raw[:4000]))
            self.finished.emit()
            r.deleteLater()
            return

        try:
            data: Any = json.loads(raw) if raw else {}
        except Exception as e:
            self.failed.emit(NetError(f"{self._tag} JSON解析失败: {e}".strip(), url=self._url, status=status_i, body=raw[:2000]))
            self.finished.emit()
            r.deleteLater()
            return

        self.ok.emit(data)
        self.finished.emit()
        r.deleteLater()


class Net(QtCore.QObject):
    def __init__(self, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._m = QtNetwork.QNetworkAccessManager(self)

    def get_json(self, url: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None,
                 timeout_ms: int = 10000, tag: str = "") -> NetJob:
        qurl = QtCore.QUrl(url)
        if params:
            q = QtCore.QUrlQuery()
            for k, v in params.items():
                q.addQueryItem(str(k), str(v))
            qurl.setQuery(q)

        req = QtNetwork.QNetworkRequest(qurl)
        # Some enterprise servers/proxies break on HTTP/2; force HTTP/1.1
        try:
            req.setAttribute(QtNetwork.QNetworkRequest.Http2AllowedAttribute, False)
        except Exception:
            pass
        if headers:
            for k, v in headers.items():
                req.setRawHeader(k.encode("utf-8"), v.encode("utf-8"))

        reply = self._m.get(req)
        return NetJob(reply, url=str(qurl.toString()), timeout_ms=timeout_ms, tag=tag)


_NET_KEY = "app_ado_net_singleton"


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


def auth_headers_from_pat(pat: str) -> dict[str, str]:
    token = base64.b64encode(f":{pat}".encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {token}", "Accept": "application/json"}
