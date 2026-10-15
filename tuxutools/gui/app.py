"""Qt (PySide6) front-end for TuxuTools.

Threading model: **workers never touch widgets.**  A worker only calls the
blocking :class:`~tuxutools.app.TuxuTools` API and returns plain data; the
result is rendered on the GUI thread by a per-task ``on_success`` callback.
Widget state (current UDID, path text, selection) is captured on the GUI thread
*before* a worker starts.  This avoids the Qt "cannot create children for a
parent in a different thread" crash and keeps the event loop responsive.
"""

from __future__ import annotations

import sys
import traceback
from typing import Any, Callable, Optional

from PySide6 import QtCore, QtWidgets

from ..app import TuxuTools
from ..config import Settings
from ..models import Progress


class Worker(QtCore.QThread):
    """Run a callable in a background thread.

    ``fn`` is called with a ``progress`` keyword callback; if it does not accept
    one, it is called with no arguments.  No Qt widget may be touched inside.
    """

    finished_ok = QtCore.Signal(object)
    failed = QtCore.Signal(str)
    progressed = QtCore.Signal(object)

    def __init__(self, fn: Callable[..., Any], with_progress: bool = True) -> None:
        super().__init__()
        self._fn = fn
        self._with_progress = with_progress
        self.on_success: Optional[Callable[[Any], None]] = None

    def run(self) -> None:  # noqa: D401 - QThread entry point
        try:
            if self._with_progress:
                try:
                    result = self._fn(progress=self.progressed.emit)
                except TypeError:
                    result = self._fn()
            else:
                result = self._fn()
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, settings: Optional[Settings] = None, backend: Optional[str] = None) -> None:
        super().__init__()
        self.settings = settings or Settings()
        if backend:
            self.settings.backend = backend
        self.app = TuxuTools(settings=self.settings)
        self._workers: list[Worker] = []
        self._current_udid: Optional[str] = None

        self.setWindowTitle("TuxuTools")
        self.resize(1040, 700)
        self._build_ui()
        self.refresh_devices()

    # -- ui ----------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Device:"))
        self.device_combo = QtWidgets.QComboBox()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        top.addWidget(self.device_combo, 1)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_devices)
        top.addWidget(refresh)
        root.addLayout(top)

        self.status = QtWidgets.QLabel("Ready")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.status)
        root.addWidget(self.progress)

        self.tabs = QtWidgets.QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_info_tab()
        self._build_files_tab()
        self._build_apps_tab()
        self._build_backup_tab()
        self._build_firmware_tab()
        self._build_jailbreak_tab()

    def _build_info_tab(self) -> None:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        self.info_view = QtWidgets.QPlainTextEdit()
        self.info_view.setReadOnly(True)
        btn = QtWidgets.QPushButton("Load device information")
        btn.clicked.connect(lambda: self.run_task(self._fetch_info, self._render_info))
        layout.addWidget(btn)
        layout.addWidget(self.info_view, 1)
        self.tabs.addTab(w, "Info")

    def _build_files_tab(self) -> None:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        bar = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit("/")
        bar.addWidget(self.path_edit, 1)
        go = QtWidgets.QPushButton("Go")
        go.clicked.connect(self._go_path)
        bar.addWidget(go)
        pull = QtWidgets.QPushButton("Download")
        pull.clicked.connect(self._download_selected)
        bar.addWidget(pull)
        layout.addLayout(bar)
        self.file_list = QtWidgets.QListWidget()
        self.file_list.itemDoubleClicked.connect(self._navigate_entry)
        layout.addWidget(self.file_list, 1)
        self.tabs.addTab(w, "Files")

    def _build_apps_tab(self) -> None:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        bar = QtWidgets.QHBoxLayout()
        load = QtWidgets.QPushButton("List apps")
        load.clicked.connect(lambda: self.run_task(self._fetch_apps, self._render_apps))
        bar.addWidget(load)
        install = QtWidgets.QPushButton("Install IPA...")
        install.clicked.connect(self._install_ipa)
        bar.addWidget(install)
        uninstall = QtWidgets.QPushButton("Uninstall selected")
        uninstall.clicked.connect(self._uninstall_selected)
        bar.addWidget(uninstall)
        layout.addLayout(bar)
        self.app_table = QtWidgets.QTableWidget(0, 3)
        self.app_table.setHorizontalHeaderLabels(["Bundle ID", "Version", "Name"])
        self.app_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.app_table, 1)
        self.tabs.addTab(w, "Applications")

    def _build_backup_tab(self) -> None:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        backup = QtWidgets.QPushButton("Back up now")
        backup.clicked.connect(self._do_backup)
        row.addWidget(backup)
        restore = QtWidgets.QPushButton("Restore from...")
        restore.clicked.connect(self._do_restore)
        row.addWidget(restore)
        refresh = QtWidgets.QPushButton("Refresh list")
        refresh.clicked.connect(lambda: self.run_task(self._fetch_backups, self._render_backups, with_progress=False))
        row.addWidget(refresh)
        layout.addLayout(row)
        self.backup_list = QtWidgets.QListWidget()
        layout.addWidget(self.backup_list, 1)
        self.tabs.addTab(w, "Backup")

    def _build_firmware_tab(self) -> None:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        row = QtWidgets.QHBoxLayout()
        self.product_edit = QtWidgets.QLineEdit("iPhone16,1")
        row.addWidget(self.product_edit, 1)
        list_btn = QtWidgets.QPushButton("List firmwares")
        list_btn.clicked.connect(self._list_firmware)
        row.addWidget(list_btn)
        flash_btn = QtWidgets.QPushButton("Flash IPSW...")
        flash_btn.clicked.connect(self._flash_firmware)
        row.addWidget(flash_btn)
        layout.addLayout(row)
        self.fw_list = QtWidgets.QListWidget()
        layout.addWidget(self.fw_list, 1)
        self.tabs.addTab(w, "Firmware")

    def _build_jailbreak_tab(self) -> None:
        w = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(w)
        tools_btn = QtWidgets.QPushButton("Detect tools / payloads")
        tools_btn.clicked.connect(lambda: self.run_task(self._fetch_jailbreak, self._render_jailbreak, with_progress=False))
        layout.addWidget(tools_btn)
        self.jb_view = QtWidgets.QPlainTextEdit()
        self.jb_view.setReadOnly(True)
        layout.addWidget(self.jb_view, 1)
        self.tabs.addTab(w, "Jailbreak")

    # -- task plumbing -----------------------------------------------------

    def run_task(
        self,
        fn: Callable[..., Any],
        on_success: Optional[Callable[[Any], None]] = None,
        with_progress: bool = True,
    ) -> None:
        worker = Worker(fn, with_progress=with_progress)
        worker.on_success = on_success
        worker.finished_ok.connect(self._on_ok)
        worker.failed.connect(self._on_error)
        worker.progressed.connect(self._on_progress)
        self._start_worker(worker)

    def _start_worker(self, worker: Worker) -> None:
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: self._forget_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _forget_worker(self, worker: Worker) -> None:
        try:
            self._workers.remove(worker)
        except ValueError:
            pass

    @QtCore.Slot(object)
    def _on_ok(self, result: Any) -> None:
        worker = self.sender()
        self.status.setText("Done")
        self.progress.setValue(0)
        callback = getattr(worker, "on_success", None)
        if callback is not None:
            try:
                callback(result)
            except Exception as exc:  # noqa: BLE001
                self._on_error(f"{exc}\n\n{traceback.format_exc()}")

    @QtCore.Slot(str)
    def _on_error(self, message: str) -> None:
        self.status.setText("Error")
        self.progress.setValue(0)
        first = (message or "error").splitlines()[0]
        QtWidgets.QMessageBox.critical(self, "Operation failed", first)

    @QtCore.Slot(object)
    def _on_progress(self, progress: Progress) -> None:
        self.status.setText(f"{progress.operation}: {progress.message}")
        if progress.fraction is not None:
            self.progress.setValue(int(progress.fraction * 100))

    # -- device ------------------------------------------------------------

    def refresh_devices(self) -> None:
        worker = Worker(lambda: self.app.devices(), with_progress=False)
        worker.finished_ok.connect(self._populate_devices)
        worker.failed.connect(self._on_error)
        self._start_worker(worker)

    def _populate_devices(self, devices) -> None:
        current = self._current_udid
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        if not devices:
            self.device_combo.addItem("No device connected", None)
        else:
            for d in devices:
                self.device_combo.addItem(f"{d.udid} ({d.connection_type.value})", d.udid)
            index = self.device_combo.findData(current)
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)
        self._current_udid = self.device_combo.currentData()

    def _on_device_changed(self, index: int) -> None:
        self._current_udid = self.device_combo.itemData(index)

    # -- fetch (worker thread; returns plain data only) --------------------

    def _fetch_info(self, progress=None):
        return self.app.info(self._current_udid)

    def _fetch_dir(self, path: str, udid, progress=None):
        return self.app.list_dir(path, udid=udid)

    def _fetch_apps(self, progress=None):
        return self.app.apps(udid=self._current_udid)

    def _fetch_backups(self, progress=None):
        return self.app.list_local_backups()

    def _fetch_firmwares(self, product: str, progress=None):
        return self.app.list_firmwares(product)

    def _fetch_jailbreak(self, progress=None):
        return self.app.jailbreak_tools(), self.app.jailbreak_payloads()

    # -- render (GUI thread) ----------------------------------------------

    def _render_info(self, info) -> None:
        self.info_view.setPlainText("\n".join(f"{k}: {v}" for k, v in info.to_dict().items()))

    def _render_dir(self, entries) -> None:
        self.file_list.clear()
        for e in entries:
            item = QtWidgets.QListWidgetItem(("[D] " if e.is_dir else "    ") + e.name)
            item.setData(QtCore.Qt.UserRole, e)
            self.file_list.addItem(item)

    def _render_apps(self, apps) -> None:
        self.app_table.setRowCount(0)
        for a in apps:
            row = self.app_table.rowCount()
            self.app_table.insertRow(row)
            self.app_table.setItem(row, 0, QtWidgets.QTableWidgetItem(a.bundle_identifier))
            self.app_table.setItem(row, 1, QtWidgets.QTableWidgetItem(a.version or ""))
            self.app_table.setItem(row, 2, QtWidgets.QTableWidgetItem(a.name or ""))

    def _render_backups(self, backups) -> None:
        self.backup_list.clear()
        for b in backups:
            self.backup_list.addItem(f"{b.date}  {b.product_version or '?'}  {b.directory}")

    def _render_firmwares(self, fws) -> None:
        self.fw_list.clear()
        for f in fws:
            self.fw_list.addItem(f"{f.version} (build {f.build}) {'signed' if f.signed else 'unsigned'}")

    def _render_jailbreak(self, result) -> None:
        tools, payloads = result
        lines = ["Tools:"]
        lines += [f"  {n}: {s.path or 'not found'}" for n, s in tools.items()]
        lines.append("Bundled payloads:")
        lines.extend([f"  {p}" for p in payloads] or ["  (none found)"])
        self.jb_view.setPlainText("\n".join(lines))

    # -- actions (capture widget state on GUI thread) ----------------------

    def _go_path(self) -> None:
        path = self.path_edit.text() or "/"
        udid = self._current_udid
        self.file_list.clear()
        self.run_task(lambda progress=None: self._fetch_dir(path, udid, progress=progress), self._render_dir)

    def _navigate_entry(self, item) -> None:
        entry = item.data(QtCore.Qt.UserRole)
        if entry is not None and entry.is_dir:
            self.path_edit.setText(entry.path)
            self._go_path()

    def _download_selected(self) -> None:
        item = self.file_list.currentItem()
        if item is None:
            return
        entry = item.data(QtCore.Qt.UserRole)
        target, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save as", entry.name)
        if not target:
            return
        udid = self._current_udid
        remote = entry.path
        self.run_task(lambda progress=None: self.app.pull(remote, target, udid=udid, progress=progress))

    def _install_ipa(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select IPA", filter="IPA (*.ipa)")
        if not path:
            return
        udid = self._current_udid
        self.run_task(lambda progress=None: self.app.install_ipa(path, udid=udid, progress=progress))

    def _uninstall_selected(self) -> None:
        row = self.app_table.currentRow()
        if row < 0:
            return
        bundle = self.app_table.item(row, 0).text()
        if QtWidgets.QMessageBox.question(self, "Uninstall", f"Uninstall {bundle}?") != QtWidgets.QMessageBox.Yes:
            return
        udid = self._current_udid
        self.run_task(lambda progress=None: self.app.uninstall(bundle, udid=udid), with_progress=False)

    def _do_backup(self) -> None:
        udid = self._current_udid
        self.run_task(lambda progress=None: self.app.backup(udid=udid, progress=progress))

    def _do_restore(self) -> None:
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select backup directory")
        if not directory:
            return
        udid = self._current_udid
        self.run_task(lambda progress=None: self.app.restore(directory, udid=udid, progress=progress))

    def _list_firmware(self) -> None:
        product = self.product_edit.text()
        self.run_task(
            lambda progress=None: self._fetch_firmwares(product, progress=progress),
            self._render_firmwares,
        )

    def _flash_firmware(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select IPSW", filter="IPSW (*.ipsw)")
        if not path:
            return
        self.run_task(lambda progress=None: self.app.flash_firmware(path, progress=progress))

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        for worker in list(self._workers):
            try:
                worker.wait(2000)
            except RuntimeError:
                pass
        self.app.close()
        super().closeEvent(event)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="tuxutools-gui", description="Qt GUI for TuxuTools (3uTools for Linux)."
    )
    parser.add_argument("--backend", choices=["auto", "pymobiledevice3", "mock"], default=None)
    parser.add_argument("--mock", action="store_true", help="use the virtual mock device")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    backend = "mock" if args.mock else args.backend
    qt = QtWidgets.QApplication.instance() or QtWidgets.QApplication([sys.argv[0]])
    window = MainWindow(backend=backend)
    window.show()
    return qt.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
