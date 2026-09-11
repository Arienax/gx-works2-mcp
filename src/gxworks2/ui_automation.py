from abc import ABC, abstractmethod
import ctypes
import os
from pathlib import Path
import re
import time

from .diagnostics import (
    GXAutomationError,
    classify_automation_error,
    describe_exception,
    exception_details,
)
from .models import GXSyncErrorCode


class GXWorks2UIAutomation(ABC):
    """Internal automation boundary; callers never receive click primitives."""

    @abstractmethod
    def inspect_project(self, session):
        """Return current project/program state without changing GX Works2."""

    @abstractmethod
    def export_current_program(self, session, destination):
        """Use GX Works2's CSV writer to create the pre-import backup."""

    @abstractmethod
    def import_program_csv(self, session, csv_path):
        """Run Edit -> Read from CSV File and return observed result state."""

    @abstractmethod
    def export_current_comments(self, session, destination):
        """Back up the project's global device comments."""

    @abstractmethod
    def import_comments_csv(self, session, csv_path):
        """Import global device comments and return observed result state."""

    def save_project(self, session):
        """Persist the open GX project when the driver supports safe saving."""

        return {
            "success": False,
            "save_required": True,
            "message": "请在GX Works2中保存当前工程。",
        }

    def prepare_export_retry(self, session):
        """Safely reset transient read/export UI before a retry."""

        return {"dismissed_dialogs": [], "main_activated": False}


class UnavailableGXWorks2UIAutomation(GXWorks2UIAutomation):
    """Safe default until a supported Windows UIA driver is injected."""

    reason = (
        "未配置GX Works2 UI Automation驱动。为避免盲目按键或坐标点击，"
        "导入操作已停止。"
    )

    def inspect_project(self, session):
        return {
            "project_open": bool(session.project_open),
            "project_name": session.project_name,
            "program_ready": False,
            "automation_available": False,
            "message": self.reason,
        }

    def export_current_program(self, session, destination):
        raise RuntimeError(self.reason)

    def import_program_csv(self, session, csv_path):
        raise RuntimeError(self.reason)

    def export_current_comments(self, session, destination):
        raise RuntimeError(self.reason)

    def import_comments_csv(self, session, csv_path):
        raise RuntimeError(self.reason)

    def save_project(self, session):
        return {
            "success": False,
            "save_required": True,
            "message": self.reason,
        }


class PywinautoGXWorks2UIAutomation(GXWorks2UIAutomation):
    """Control GX Works2 by UI Automation names, never by screen coordinates."""

    EDIT_MENU = re.compile(r"^编辑(?:\([&]?E\))?$")
    READ_CSV_ITEM = re.compile(r"从\s*CSV\s*文件(?:中)?(?:读取|导入)|Read.*CSV", re.I)
    WRITE_CSV_ITEM = re.compile(r"(?:写入|导出|保存).*CSV\s*文件|Write.*CSV", re.I)
    SUCCESS_TEXT = re.compile(r"完成|成功|读取.*结束|导入.*结束", re.I)
    FAILURE_TEXT = re.compile(r"错误|失败|无法|不能|异常|不正确|error|failed", re.I)
    CONFIRMATION_TEXT = re.compile(
        r"(?:读取|写入).*?(?:指定的)?文件.*?确定|执行读取后.*?无法撤消|"
        r"read|write|confirm",
        re.I | re.S,
    )
    PROGRAM_EDITOR = re.compile(r"\[PRG\].*\bMAIN\b", re.I)
    PROGRAM_WRITE_EDITOR = re.compile(
        r"\[PRG\]\s*(?:写入|Write(?:\s+Mode)?)\s+MAIN\b",
        re.I,
    )
    COMMENT_EDITOR = re.compile(r"软元件注释\s*COMMENT", re.I)
    PROGRAM_READ_KEY = "j"
    PROGRAM_WRITE_KEY = "k"
    COMMENT_READ_KEY = "f"
    COMMENT_WRITE_KEY = "o"

    def __init__(self, timeout=12.0):
        self.timeout = float(timeout)
        self._progress_reporter = None

    def set_progress_reporter(self, reporter):
        self._progress_reporter = reporter

    def _report_progress(self, stage, message):
        if self._progress_reporter is not None:
            self._progress_reporter(stage, message)

    @staticmethod
    def available():
        try:
            import pywinauto  # noqa: F401
            return True
        except ImportError:
            return False

    def _application(self, session, backend="uia"):
        from pywinauto import Application

        return Application(backend=backend).connect(
            process=session.process_id,
            timeout=self.timeout,
        )

    def _main_window(self, session):
        app = self._application(session)
        return app.window(handle=session.window_handle)

    @staticmethod
    def _unique_controls(window, **criteria):
        seen = set()
        result = []
        for control in window.descendants(**criteria):
            key = getattr(control.element_info, "handle", None) or (
                control.window_text(),
                getattr(control.element_info, "control_type", ""),
            )
            if key in seen:
                continue
            seen.add(key)
            result.append(control)
        return result

    def _find_menu_item(self, window, pattern, enabled=None):
        for control in self._unique_controls(window, control_type="MenuItem"):
            if not pattern.search(control.window_text().strip()):
                continue
            if enabled is not None and bool(control.is_enabled()) != bool(enabled):
                continue
            return control
        return None

    def _open_edit_menu(self, window):
        # GX Works2 is a 32-bit MFC application.  Its top-level menu item is
        # exposed through UIA, but ``Invoke`` does not reliably expand the
        # popup when the caller is 64-bit.  The native Alt+E accelerator is
        # stable across DPI/scaling settings and still avoids screen
        # coordinates.
        window.set_focus()
        window.type_keys("%e")
        # The legacy MFC popup is visibly open before its keyboard focus is
        # ready.  Sending the second access key at 40 ms is occasionally lost,
        # which forced the expensive full accessibility-tree fallback.
        time.sleep(0.12)

    def _send_edit_accelerator(self, window, accelerator):
        """Invoke a visible Edit-menu command without scanning the UIA tree."""
        self._open_edit_menu(window)
        # Calling ``window.type_keys`` a second time focuses the MFC frame
        # again and steals keyboard focus from the already-open popup menu.
        # Send the access key globally so the popup receives it directly.
        self._send_popup_access_key(accelerator)

    @staticmethod
    def _send_popup_access_key(accelerator):
        from pywinauto.keyboard import send_keys

        send_keys(str(accelerator).lower(), pause=0, vk_packet=False)

    def _csv_command(self, window, pattern):
        # Popup menu providers can appear a few hundred milliseconds after
        # the accelerator.  Poll and retry instead of treating the first
        # incomplete UIA snapshot as "no project".
        for _attempt in range(3):
            self._open_edit_menu(window)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                command = self._find_menu_item(window, pattern, enabled=True)
                if command is not None:
                    return command
                time.sleep(0.05)
            window.type_keys("{ESC}")
            time.sleep(0.1)
        return None

    def inspect_project(self, session):
        if session.project_state_known and not session.project_open:
            return {
                "automation_available": True,
                "project_open": False,
                "program_ready": False,
                "project_name": "",
                "read_csv_available": False,
            }
        try:
            window = self._main_window(session)
            titles = self._child_window_titles(session)
            program_ready = any(self.PROGRAM_EDITOR.search(title) for title in titles)
            if not program_ready:
                program_ready = bool(self.PROGRAM_EDITOR.search(window.window_text()))
            program_writable = any(
                self.PROGRAM_WRITE_EDITOR.search(title) for title in titles
            )
            if not program_writable:
                program_writable = bool(
                    self.PROGRAM_WRITE_EDITOR.search(window.window_text())
                )
        except Exception as error:
            classified = classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_PROJECT_INSPECT_FAILED,
                stage="inspect_project",
                retryable=True,
                message=f"无法读取GX Works2当前程序：{describe_exception(error)}",
            )
            return {
                "automation_available": False,
                "project_open": bool(session.project_open),
                "program_ready": False,
                "project_name": session.project_name,
                "read_csv_available": False,
                "message": str(classified),
                "error_code": classified.code,
                "stage": classified.stage,
                "retryable": classified.retryable,
                **exception_details(classified),
            }
        project_open = bool(session.project_open or program_ready)
        return {
            "automation_available": True,
            "project_open": project_open,
            "program_ready": program_ready,
            "project_name": session.project_name or window.window_text(),
            "read_csv_available": program_ready,
            "program_writable": program_writable,
        }

    @staticmethod
    def _child_window_titles(session):
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        values = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def visit(hwnd, _lparam):
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value.strip()
                if title:
                    values.append(title)
            return True

        user32.EnumChildWindows(
            int(session.window_handle),
            callback_type(visit),
            0,
        )
        return values

    def _activate_editor(self, session, editor_pattern, tree_pattern):
        window = self._main_window(session)
        # GX Works2 puts the active MDI document name in the frame title.  The
        # title alone does not mean the document owns keyboard focus, though;
        # mode shortcuts such as F2 would otherwise be delivered to the frame.
        if self._activate_native_document(session, editor_pattern):
            return window

        if editor_pattern.search(window.window_text()):
            return window

        # Reuse an already-open document tab first. Opening the project tree is
        # only needed the first time the comments editor is used.
        targets = []
        for control_type in ("TabItem", "TreeItem"):
            try:
                controls = self._unique_controls(window, control_type=control_type)
            except Exception:
                controls = []
            for control in controls:
                text = control.window_text().strip()
                if editor_pattern.search(text) or tree_pattern.search(text):
                    targets.append((control_type, control))
            if targets:
                break
        if not targets:
            raise RuntimeError("GX Works2导航中没有找到对应编辑器")

        control_type, target = targets[0]
        if control_type == "TreeItem":
            target.double_click_input()
        else:
            try:
                target.select()
            except Exception:
                target.click_input()

        deadline = time.monotonic() + min(self.timeout, 4.0)
        while time.monotonic() < deadline:
            if editor_pattern.search(window.window_text()):
                return window
            time.sleep(0.05)
        raise RuntimeError("GX Works2未切换到对应编辑器")

    @staticmethod
    def _activate_native_document(session, editor_pattern):
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32
        matches = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def visit(hwnd, _lparam):
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if editor_pattern.search(buffer.value.strip()):
                matches.append(int(hwnd))
                return False
            return True

        user32.EnumChildWindows(
            int(session.window_handle),
            callback_type(visit),
            0,
        )
        if not matches:
            return False

        wm_mdiactivate = 0x0222
        parent = int(user32.GetParent(matches[0]))
        if parent:
            user32.SendMessageW(parent, wm_mdiactivate, matches[0], 0)
        # WM_MDIACTIVATE selects the document but does not always transfer
        # keyboard focus across process threads.  pywinauto performs the
        # required thread attachment; retain the Win32 fallback for minimal
        # installations and unit-test doubles.
        try:
            from pywinauto import Desktop

            Desktop(backend="win32").window(handle=matches[0]).set_focus()
        except Exception:
            user32.SetForegroundWindow(int(session.window_handle))
            user32.SetFocus(matches[0])
        return True

    def _activate_program_editor(self, session):
        return self._activate_editor(
            session,
            self.PROGRAM_EDITOR,
            re.compile(r"^MAIN$", re.I),
        )

    def _program_editor_titles(self, session):
        titles = list(self._child_window_titles(session))
        try:
            titles.append(self._main_window(session).window_text())
        except Exception:
            pass
        return [str(title or "").strip() for title in titles if str(title or "").strip()]

    @staticmethod
    def _send_write_mode_shortcut():
        from pywinauto.keyboard import send_keys

        # Mitsubishi documents F2 as the current-window Write Mode shortcut.
        send_keys("{F2}", pause=0)

    def _ensure_program_writable(self, session):
        """Focus MAIN and leave it in Write Mode before a physical import."""

        window = self._activate_program_editor(session)
        if any(
            self.PROGRAM_WRITE_EDITOR.search(title)
            for title in self._program_editor_titles(session)
        ):
            return window

        # Re-activate the native MDI child even when the frame title already
        # names MAIN.  Live GX Works2 testing showed that F2 is ignored unless
        # this document, rather than the MFC frame, owns keyboard focus.
        if not self._activate_native_document(session, self.PROGRAM_EDITOR):
            window.set_focus()
        self._send_write_mode_shortcut()

        deadline = time.monotonic() + min(self.timeout, 2.0)
        while time.monotonic() < deadline:
            if any(
                self.PROGRAM_WRITE_EDITOR.search(title)
                for title in self._program_editor_titles(session)
            ):
                return window
            time.sleep(0.05)
        raise RuntimeError(
            "GX Works2 MAIN程序仍为读取/只读模式，无法执行CSV导入；"
            "请确认工程允许写入。"
        )

    def _activate_comments_editor(self, session):
        return self._activate_editor(
            session,
            self.COMMENT_EDITOR,
            re.compile(r"^全局软元件注释$"),
        )

    def _wait_dialog(self, session, title_pattern, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            for window in self._dialog_candidates(session):
                title = window.window_text().strip()
                class_name = str(
                    getattr(window.element_info, "class_name", "") or ""
                )
                if class_name == "#32770" and title_pattern.search(title):
                    return window
            time.sleep(0.1)
        raise RuntimeError("未检测到GX Works2文件选择对话框")

    def _dialog_candidates(self, session):
        """Return process-owned top-level and nested dialogs.

        GX Works2 embeds some modal dialogs below its MFC main window instead
        of exposing them through ``Application.windows()``.  Searching the
        nested Window controls is therefore required for the confirmation
        shown before CSV export/import.
        """
        native_handles = self._native_dialog_handles(session)
        if os.name == "nt":
            app = self._application(session)
            return [app.window(handle=handle) for handle in native_handles]

        app = self._application(session)
        result = []
        seen = set()
        for top in app.windows():
            candidates = [top]
            try:
                candidates.extend(top.descendants(control_type="Window"))
            except Exception:
                pass
            for candidate in candidates:
                try:
                    handle = int(candidate.handle)
                except Exception:
                    handle = 0
                key = handle or tuple(
                    getattr(candidate.element_info, "runtime_id", ()) or ()
                ) or id(candidate)
                if key in seen:
                    continue
                seen.add(key)
                result.append(candidate)
        return result

    @staticmethod
    def _native_dialog_handles(session):
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        handles = []
        seen = set()
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def add_if_dialog(hwnd, _lparam):
            class_buffer = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
            if (
                class_buffer.value == "#32770"
                and int(process_id.value) == int(session.process_id)
                and user32.IsWindowVisible(hwnd)
                and user32.GetWindowTextLengthW(hwnd) > 0
            ):
                value = int(hwnd)
                if value not in seen:
                    seen.add(value)
                    handles.append(value)
            return True

        # File and confirmation dialogs are sometimes owned top-level MFC
        # windows and sometimes nested children, depending on GX Works2 build.
        user32.EnumWindows(callback_type(add_if_dialog), 0)
        user32.EnumChildWindows(
            int(session.window_handle),
            callback_type(add_if_dialog),
            0,
        )
        return handles

    @staticmethod
    def _native_window_title(hwnd):
        if os.name != "nt" or not hwnd:
            return ""
        user32 = ctypes.windll.user32
        length = int(user32.GetWindowTextLengthW(int(hwnd)))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(int(hwnd), buffer, length + 1)
        return buffer.value.strip()

    @staticmethod
    def _native_descendants(hwnd):
        if os.name != "nt" or not hwnd:
            return []
        user32 = ctypes.windll.user32
        handles = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def visit(child, _lparam):
            handles.append(int(child))
            return True

        user32.EnumChildWindows(int(hwnd), callback_type(visit), 0)
        return handles

    @classmethod
    def _native_dialog_text(cls, hwnd):
        if os.name != "nt":
            return ""
        user32 = ctypes.windll.user32
        values = [cls._native_window_title(hwnd)]
        for child in cls._native_descendants(hwnd):
            length = int(user32.GetWindowTextLengthW(child))
            if length <= 0 or length > 4096:
                continue
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(child, buffer, length + 1)
            value = buffer.value.strip()
            if value:
                values.append(value)
        return " ".join(dict.fromkeys(value for value in values if value))

    @classmethod
    def _native_confirm_dialog(cls, hwnd):
        if os.name != "nt":
            return False
        user32 = ctypes.windll.user32
        for child in cls._native_descendants(hwnd):
            class_buffer = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(child, class_buffer, len(class_buffer))
            if class_buffer.value.casefold() != "button":
                continue
            text = cls._native_window_title(child)
            if re.search(r"^(?:是|确定|OK|Yes)(?:\(&?.*?\))?$", text, re.I):
                user32.SendMessageW(child, 0x00F5, 0, 0)  # BM_CLICK
                return True
        return False

    def _legacy_dialog(self, session, title_pattern):
        from pywinauto import Desktop

        for handle in self._native_dialog_handles(session):
            title = self._native_window_title(handle)
            if title_pattern.search(title):
                return Desktop(backend="win32").window(handle=handle)
        return None

    def _wait_legacy_dialog(
        self,
        session,
        title_pattern,
        timeout=None,
        *,
        failure_stage="",
    ):
        wait_seconds = self.timeout if timeout is None else float(timeout)
        started_at = time.monotonic()
        deadline = started_at + wait_seconds
        while time.monotonic() < deadline:
            dialog = self._legacy_dialog(session, title_pattern)
            if dialog is not None:
                return dialog
            time.sleep(0.05)
        if failure_stage:
            elapsed = max(0.0, time.monotonic() - started_at)
            timeout_error = TimeoutError()
            raise GXAutomationError(
                GXSyncErrorCode.GX_FILE_DIALOG_TIMEOUT,
                failure_stage,
                f"{elapsed:.1f}秒内未检测到GX Works2文件选择窗口。",
                retryable=True,
                original_error=timeout_error,
                details={
                    "timeout_seconds": wait_seconds,
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
        raise RuntimeError("未检测到GX Works2文件选择对话框")

    @staticmethod
    def _set_legacy_file_name(dialog, path):
        edits = [control for control in dialog.children(class_name="Edit") if control.is_enabled()]
        if not edits:
            edits = [control for control in dialog.descendants(class_name="Edit") if control.is_enabled()]
        if not edits:
            raise RuntimeError("文件选择对话框中没有文件名输入框")
        target = edits[0]
        target.set_edit_text(str(Path(path).resolve()))

        # GX Works2 uses a legacy MFC common dialog. Depending on Windows/GX
        # build, the default Save/Open button may be a direct child or exposed
        # deeper in the Win32 wrapper. Search both before falling back to the
        # native IDOK command; merely pressing Enter in the edit box is not
        # reliable and was leaving comment exports waiting for a manual Save.
        buttons = []
        seen = set()
        for getter in (dialog.children, dialog.descendants):
            try:
                candidates = getter(class_name="Button")
            except Exception:
                candidates = []
            for control in candidates:
                try:
                    enabled = control.is_enabled()
                except Exception:
                    enabled = True
                if not enabled:
                    continue
                handle = int(getattr(control, "handle", 0) or 0)
                key = handle or id(control)
                if key in seen:
                    continue
                seen.add(key)
                buttons.append(control)
        for button in buttons:
            raw_id = getattr(button, "control_id", 0)
            try:
                control_id = int(raw_id() if callable(raw_id) else raw_id or 0)
            except Exception:
                control_id = 0
            if control_id != 1:
                continue
            handle = int(getattr(button, "handle", 0) or 0)
            if os.name == "nt" and handle:
                ctypes.windll.user32.SendMessageW(handle, 0x00F5, 0, 0)  # BM_CLICK
            else:
                click = getattr(button, "click", None)
                if callable(click):
                    click()
                else:
                    button.click_input()
            return

        dialog_handle = int(getattr(dialog, "handle", 0) or 0)
        if os.name == "nt" and dialog_handle:
            ctypes.windll.user32.SendMessageW(dialog_handle, 0x0111, 1, 0)  # WM_COMMAND/IDOK
            return
        target.type_keys("{ENTER}")

    def _wait_confirmation_and_accept(self, session, context, timeout=None):
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while time.monotonic() < deadline:
            for handle in self._native_dialog_handles(session):
                text = self._native_dialog_text(handle)
                if not text:
                    continue
                # "执行读取后，将无法撤消" is part of GX Works2's normal
                # confirmation prompt, not an automation failure.
                if self.CONFIRMATION_TEXT.search(text):
                    if self._native_confirm_dialog(handle):
                        return handle
                if self.FAILURE_TEXT.search(text):
                    raise RuntimeError(text)
            time.sleep(0.05)
        raise RuntimeError(f"未检测到GX Works2{context}确认对话框")

    @staticmethod
    def _window_text(window):
        texts = [window.window_text()]
        try:
            texts.extend(
                control.window_text()
                for control in window.descendants()
                if control.window_text()
            )
        except Exception:
            pass
        return " ".join(dict.fromkeys(text.strip() for text in texts if text.strip()))

    @staticmethod
    def _set_file_name(dialog, path):
        edits = [
            control
            for control in dialog.descendants(control_type="Edit")
            if control.is_enabled()
        ]
        if not edits:
            raise RuntimeError("文件选择对话框中没有文件名输入框")
        target = next(
            (
                control
                for control in edits
                if re.search(
                    r"文件名|File name",
                    " ".join(
                        filter(
                            None,
                            (
                                control.window_text(),
                                getattr(control.element_info, "name", ""),
                                getattr(control.element_info, "automation_id", ""),
                            ),
                        )
                    ),
                    re.I,
                )
            ),
            edits[-1],
        )
        target.set_edit_text(str(Path(path).resolve()))
        buttons = [
            control
            for control in dialog.descendants(control_type="Button")
            if control.is_enabled()
        ]
        # The legacy common dialog also exposes combo-box drop-down arrows as
        # buttons named "打开".  Only the dialog's default command button has
        # automation id 1; accepting any other "打开" button leaves the dialog
        # waiting forever.
        for button in buttons:
            automation_id = str(
                getattr(button.element_info, "automation_id", "") or ""
            )
            if automation_id == "1" and re.search(
                r"打开|保存|确定|Open|Save|OK",
                button.window_text(),
                re.I,
            ):
                button.invoke()
                return
        target.type_keys("{ENTER}")

    def _invoke_csv_command(
        self,
        session,
        pattern,
        path,
        *,
        accelerator,
        confirm_before_file=False,
        operation="",
    ):
        export_code = (
            GXSyncErrorCode.GX_COMMENT_EXPORT_FAILED
            if operation == "comment_export"
            else GXSyncErrorCode.GX_PROGRAM_EXPORT_FAILED
        )
        file_dialog_stage = (
            "wait_comment_file_dialog"
            if operation == "comment_export"
            else "wait_program_file_dialog"
        )
        submit_stage = (
            "submit_comment_export_path"
            if operation == "comment_export"
            else "submit_program_export_path"
        )
        operation_label = "注释" if operation == "comment_export" else "程序"
        try:
            window = self._main_window(session)
            if operation:
                self._report_progress(
                    "open_export_menu",
                    f"正在打开GX Works2{operation_label}CSV导出命令",
                )
            self._send_edit_accelerator(window, accelerator)
        except GXAutomationError:
            raise
        except Exception as error:
            if not operation:
                raise
            raise classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_EXPORT_MENU_FAILED,
                stage="open_export_menu",
                retryable=True,
                message=(
                    f"无法打开GX Works2{operation_label}CSV导出菜单："
                    f"{describe_exception(error)}"
                ),
                details={"operation": operation},
            ) from error
        if confirm_before_file:
            try:
                self._wait_confirmation_and_accept(session, "写入", timeout=1.5)
            except RuntimeError as initial_error:
                try:
                    window.type_keys("{ESC}")
                    command = self._csv_command(window, pattern)
                    if command is None:
                        raise GXAutomationError(
                            GXSyncErrorCode.GX_EXPORT_MENU_FAILED,
                            "open_export_menu",
                            "当前编辑器没有可用的“写入至CSV文件”命令。",
                            retryable=True,
                            original_error=initial_error,
                            details={"operation": operation},
                        )
                    command.invoke()
                    self._wait_confirmation_and_accept(
                        session, "写入", timeout=min(self.timeout, 4.0)
                    )
                except GXAutomationError:
                    raise
                except Exception as error:
                    raise classify_automation_error(
                        error,
                        default_code=GXSyncErrorCode.GX_EXPORT_MENU_FAILED,
                        stage="open_export_menu",
                        retryable=True,
                        message=(
                            f"GX Works2未打开{operation_label}CSV导出命令："
                            f"{describe_exception(error)}"
                        ),
                        details={"operation": operation},
                    ) from error
            if operation:
                self._report_progress(
                    file_dialog_stage,
                    f"正在等待GX Works2{operation_label}文件选择窗口",
                )
            dialog = self._wait_legacy_dialog(
                session,
                re.compile(r"打开|保存|CSV|Open|Save", re.I),
                timeout=min(self.timeout, 5.0),
                failure_stage=file_dialog_stage if operation else "",
            )
        else:
            try:
                dialog = self._wait_legacy_dialog(
                    session,
                    re.compile(r"打开|保存|CSV|Open|Save", re.I),
                    timeout=1.5,
                )
            except RuntimeError:
                window.type_keys("{ESC}")
                command = self._csv_command(window, pattern)
                if command is None:
                    raise RuntimeError("当前编辑器没有对应CSV命令")
                command.invoke()
                dialog = self._wait_legacy_dialog(
                    session,
                    re.compile(r"打开|保存|CSV|Open|Save", re.I),
                    timeout=min(self.timeout, 5.0),
                )
        if operation:
            self._report_progress(
                submit_stage,
                f"正在提交GX Works2{operation_label}CSV导出路径",
            )
        try:
            self._set_legacy_file_name(dialog, path)
        except Exception as error:
            if not operation:
                raise
            raise classify_automation_error(
                error,
                default_code=export_code,
                stage=submit_stage,
                retryable=True,
                message=(
                    f"无法向GX Works2提交{operation_label}CSV导出路径："
                    f"{describe_exception(error)}"
                ),
                details={"operation": operation},
            ) from error
        if not confirm_before_file:
            self._wait_confirmation_and_accept(
                session, "读取", timeout=min(self.timeout, 4.0)
            )
        result_stage = (
            "wait_comment_export_file"
            if operation == "comment_export"
            else "wait_program_export_file"
        )
        if operation:
            self._report_progress(
                result_stage,
                f"正在等待GX Works2生成{operation_label}CSV",
            )
        try:
            return self._wait_operation_result(
                session,
                destination=path if confirm_before_file else None,
            )
        except Exception as error:
            if not operation:
                raise
            raise classify_automation_error(
                error,
                default_code=export_code,
                stage=result_stage,
                retryable=True,
                message=(
                    f"等待GX Works2生成{operation_label}CSV时失败："
                    f"{describe_exception(error)}"
                ),
                details={"operation": operation},
            ) from error

    def _wait_operation_result(self, session, destination=None):
        started_at = time.monotonic()
        deadline = time.monotonic() + self.timeout
        last_message = ""
        destination_signature = None
        destination_stable_since = None
        main_ready_since = None
        while time.monotonic() < deadline:
            # Export mode is determined only from the requested backup file.
            # Do not ask the legacy UIA provider for another main-window
            # wrapper here: some GX Works2 MDI states block that call for
            # minutes even though the file is already being flushed.  A short
            # stable-size window filters the create-before-write race; the
            # following CSV validation remains authoritative.
            if destination and Path(destination).is_file():
                try:
                    stat = Path(destination).stat()
                    signature = (stat.st_size, stat.st_mtime_ns)
                except OSError:
                    signature = None
                now = time.monotonic()
                if signature and signature[0] > 2:
                    if signature != destination_signature:
                        destination_signature = signature
                        destination_stable_since = now
                    elif (
                        destination_stable_since is not None
                        and now - destination_stable_since >= 0.10
                    ):
                        return {
                            "success": True,
                            "message": "GX Works2已生成CSV备份",
                        }
                else:
                    destination_signature = None
                    destination_stable_since = None

                time.sleep(0.02)
                continue

            # After Read from CSV, GX Works2 writes its authoritative summary
            # (for example "Error: 0, Warning: 0") to the output pane.  The
            # pane is a legacy Win32 Edit that UIA does not expose reliably,
            # so read the control text directly instead of waiting for the
            # full timeout.
            main = self._main_window(session)
            main_ready = main.exists() and main.is_enabled()
            summary = (
                self._read_output_summary(session)
                if not destination
                and main_ready
                and time.monotonic() - started_at >= 0.25
                else ""
            )
            match = re.search(
                r"Error\s*:\s*(\d+)\s*,?\s*Warning\s*:\s*(\d+)",
                summary,
                re.I,
            )
            if match:
                error_count = int(match.group(1))
                warning_count = int(match.group(2))
                return {
                    "success": error_count == 0,
                    "message": summary,
                    "error_count": error_count,
                    "warning_count": warning_count,
                }

            dialog_handles = self._native_dialog_handles(session)
            for handle in dialog_handles:
                message = self._native_dialog_text(handle)
                if not message:
                    continue
                if message:
                    last_message = message
                if self.CONFIRMATION_TEXT.search(message):
                    continue
                if self.FAILURE_TEXT.search(message):
                    return {"success": False, "message": message}
                if self.SUCCESS_TEXT.search(message):
                    self._native_confirm_dialog(handle)
                    return {"success": True, "message": message}

            # Some GX Works2 versions never expose a parseable completion text.
            # The old code intentionally accepted an enabled MAIN frame as the
            # fallback acknowledgement, but only after waiting the full 12 s.
            # Accept the same observable state once it is stable and no modal
            # dialog remains; this removes ~12 s from each program/comment read.
            now = time.monotonic()
            if (
                not destination
                and main_ready
                and not dialog_handles
                and now - started_at >= 0.60
            ):
                if main_ready_since is None:
                    main_ready_since = now
                elif now - main_ready_since >= 0.45:
                    return {
                        "success": True,
                        "message": last_message or "GX Works2已返回可编辑状态",
                    }
            else:
                main_ready_since = None
            time.sleep(0.10)
        # Some GX Works2 versions close a successful import without a success
        # dialog. Returning to the editable main window is the observable ack.
        main = self._main_window(session)
        if main.exists() and main.is_enabled():
            return {"success": True, "message": last_message or "GX Works2已返回可编辑状态"}
        return {"success": False, "message": last_message or "未检测到GX Works2导入完成状态"}

    @staticmethod
    def _read_output_summary(session):
        if os.name != "nt":
            return ""
        user32 = ctypes.windll.user32
        values = []
        callback_type = ctypes.WINFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

        def visit(hwnd, _lparam):
            class_buffer = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
            if class_buffer.value.casefold() != "edit":
                return True
            length = int(user32.SendMessageW(hwnd, 0x000E, 0, 0))  # WM_GETTEXTLENGTH
            if length <= 0 or length > 2048:
                return True
            text_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.SendMessageW(
                hwnd,
                0x000D,  # WM_GETTEXT
                length + 1,
                text_buffer,
            )
            value = text_buffer.value.strip()
            if re.search(r"Error\s*:\s*\d+.*Warning\s*:\s*\d+", value, re.I):
                values.append(value)
            return True

        user32.EnumChildWindows(
            int(session.window_handle),
            callback_type(visit),
            0,
        )
        return values[-1] if values else ""

    @staticmethod
    def _confirm_dialog(window):
        for button in window.descendants(control_type="Button"):
            if button.is_enabled() and re.search(r"是|确定|OK|Yes", button.window_text(), re.I):
                button.invoke()
                return True
        return False

    def prepare_export_retry(self, session):
        """Dismiss only CSV-related transient UI, then reactivate MAIN."""

        dismissed = []
        if os.name == "nt":
            user32 = ctypes.windll.user32
            transient_pattern = re.compile(
                r"CSV|写入|读取|导出|打开|保存|另存为|Open|Save|Write|Read",
                re.I,
            )
            for handle in self._native_dialog_handles(session):
                text = self._native_dialog_text(handle)
                if not (
                    transient_pattern.search(text)
                    or self.CONFIRMATION_TEXT.search(text)
                ):
                    continue
                title = self._native_window_title(handle)
                # WM_COMMAND/IDCANCEL is the native equivalent of pressing
                # Escape in a common file or confirmation dialog.  Never send
                # it to the GX Works2 frame itself.
                user32.PostMessageW(int(handle), 0x0111, 2, 0)
                dismissed.append(title or text[:120])

        if dismissed:
            time.sleep(0.05)

        try:
            window = self._main_window(session)
            window.set_focus()
            window.type_keys("{ESC}")
            self._activate_program_editor(session)
        except GXAutomationError:
            raise
        except Exception as error:
            raise classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_MAIN_ACTIVATE_FAILED,
                stage="activate_main",
                retryable=True,
                message=(
                    "清理导出界面后无法重新激活MAIN："
                    + describe_exception(error)
                ),
                details={"dismissed_dialogs": dismissed},
            ) from error
        return {
            "dismissed_dialogs": dismissed,
            "main_activated": True,
        }

    def export_current_program(self, session, destination):
        self._report_progress("activate_main", "正在激活GX Works2 MAIN程序")
        try:
            self._activate_program_editor(session)
        except GXAutomationError:
            raise
        except Exception as error:
            raise classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_MAIN_ACTIVATE_FAILED,
                stage="activate_main",
                retryable=True,
                message="无法激活GX Works2 MAIN程序：" + describe_exception(error),
            ) from error
        try:
            result = self._invoke_csv_command(
                session,
                self.WRITE_CSV_ITEM,
                destination,
                accelerator=self.PROGRAM_WRITE_KEY,
                confirm_before_file=True,
                operation="program_export",
            )
        except GXAutomationError:
            raise
        except Exception as error:
            raise classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_PROGRAM_EXPORT_FAILED,
                stage="export_program",
                retryable=True,
                message="GX Works2程序CSV导出失败：" + describe_exception(error),
            ) from error
        if not result.get("success"):
            raise GXAutomationError(
                GXSyncErrorCode.GX_PROGRAM_EXPORT_FAILED,
                "wait_program_export_file",
                result.get("message") or "GX Works2程序CSV写出失败。",
                retryable=True,
                details={"gxworks2_result": dict(result)},
            )
        if not Path(destination).is_file():
            raise GXAutomationError(
                GXSyncErrorCode.GX_PROGRAM_EXPORT_FAILED,
                "wait_program_export_file",
                "GX Works2未生成程序CSV。",
                retryable=True,
                details={"export_path": str(Path(destination).resolve())},
            )

    def import_program_csv(self, session, csv_path):
        self._ensure_program_writable(session)
        return self._invoke_csv_command(
            session,
            self.READ_CSV_ITEM,
            csv_path,
            accelerator=self.PROGRAM_READ_KEY,
        )

    def export_current_comments(self, session, destination):
        self._report_progress("activate_comments", "正在打开GX Works2软元件注释")
        try:
            self._activate_comments_editor(session)
        except GXAutomationError:
            raise
        except Exception as error:
            raise classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_COMMENT_EXPORT_FAILED,
                stage="activate_comments",
                retryable=True,
                message="无法激活GX Works2软元件注释：" + describe_exception(error),
            ) from error
        try:
            result = self._invoke_csv_command(
                session,
                self.WRITE_CSV_ITEM,
                destination,
                accelerator=self.COMMENT_WRITE_KEY,
                confirm_before_file=True,
                operation="comment_export",
            )
        except GXAutomationError:
            raise
        except Exception as error:
            raise classify_automation_error(
                error,
                default_code=GXSyncErrorCode.GX_COMMENT_EXPORT_FAILED,
                stage="export_comments",
                retryable=True,
                message="GX Works2注释CSV导出失败：" + describe_exception(error),
            ) from error
        if not result.get("success"):
            raise GXAutomationError(
                GXSyncErrorCode.GX_COMMENT_EXPORT_FAILED,
                "wait_comment_export_file",
                result.get("message") or "GX Works2注释CSV写出失败。",
                retryable=True,
                details={"gxworks2_result": dict(result)},
            )
        if not Path(destination).is_file():
            raise GXAutomationError(
                GXSyncErrorCode.GX_COMMENT_EXPORT_FAILED,
                "wait_comment_export_file",
                "GX Works2未生成软元件注释CSV。",
                retryable=True,
                details={"export_path": str(Path(destination).resolve())},
            )

    def import_comments_csv(self, session, csv_path):
        self._activate_comments_editor(session)
        try:
            return self._invoke_csv_command(
                session,
                self.READ_CSV_ITEM,
                csv_path,
                accelerator=self.COMMENT_READ_KEY,
            )
        finally:
            # Leave the user on the program they asked to update.
            try:
                self._activate_program_editor(session)
            except Exception:
                pass

    def save_project(self, session):
        project_name = str(getattr(session, "project_name", "") or "").strip().casefold()
        if project_name in {
            "(工程未设置)",
            "工程未设置",
            "(project not set)",
            "project not set",
        }:
            return {
                "success": False,
                "save_required": True,
                "message": "当前GX Works2工程尚未命名，请先在GX Works2中选择保存位置。",
            }
        try:
            window = self._main_window(session)
            window.set_focus()
            window.type_keys("^s")
            time.sleep(0.2)
            return {
                "success": True,
                "save_required": False,
                "message": "GX Works2工程已保存。",
            }
        except Exception as error:
            return {
                "success": False,
                "save_required": True,
                "message": f"无法自动保存GX Works2工程：{error}",
            }
