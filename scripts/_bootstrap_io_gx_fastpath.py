from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"skip: {label}")
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print(f"applied: {label}")


api = ROOT / "src" / "api.py"
execution = ROOT / "src" / "application" / "execution.py"
uia = ROOT / "src" / "gxworks2" / "ui_automation.py"
test_file = ROOT / "tests" / "test_io_protocol_and_gx_fastpath.py"

replace_once(
    api,
    '''# suggested_io 硬约束\n- 只允许普通类别 X、Y、M、D、T、C、S，以及 special_relays、special_registers；FX5U 的 SM 地址归入 special_relays，SD 地址归入 special_registers。\n- 类别中的键必须是该 PLC 型号下真实、语法合法且前缀一致的软元件地址。\n- CHANNEL、ADDRESS、NOTE、ANALOG_OUTPUT、模块名、通道、量程、接线和频率档位都不是 I/O 类别或地址；必须放入 hardware_config 或 assumptions。\n- 不确定的地址不得写入 suggested_io。把不确定性写入 assumptions；不要因此生成硬件必填项。\n''',
    '''# suggested_io 硬约束\n- 只允许普通类别 X、Y、M、D、T、C、S，以及 special_relays、special_registers；FX5U 的 SM 地址归入 special_relays，SD 地址归入 special_registers。\n- 普通类别 X/Y/M/D/T/C/S 必须使用 JSON 对象：键为真实软元件地址，值为基于当前需求的简短非空用途说明；不得只返回地址数组。\n- 普通类别中的每个地址都必须有非空说明。若用途无法从当前需求确定，就不要把该地址写入 suggested_io，而应在 assumptions 或 missing_info 中表达不确定性。\n- special_relays / special_registers 可以使用地址数组或“地址到说明”的对象；系统软元件的固定说明允许由程序补全。\n- 类别中的键必须是该 PLC 型号下真实、语法合法且前缀一致的软元件地址。\n- CHANNEL、ADDRESS、NOTE、ANALOG_OUTPUT、模块名、通道、量程、接线和频率档位都不是 I/O 类别或地址；必须放入 hardware_config 或 assumptions。\n- 不确定的地址不得写入 suggested_io。把不确定性写入 assumptions；不要因此生成硬件必填项。\n''',
    "tighten suggested_io abstract protocol",
)

replace_once(
    api,
    '''        if isinstance(values, dict):\n            entries = list(values.items())\n        elif isinstance(values, list):\n            entries = [(value, "") for value in values]\n        else:\n            metadata[category_text] = values\n            add_diagnostic(\n                "invalid_io_container",\n                "suggested_io.%s" % category_text,\n                str(tr("I/O 类别必须是地址字典或地址列表，原值已移入 hardware_config。")),\n                values,\n            )\n            continue\n''',
    '''        if isinstance(values, dict):\n            entries = list(values.items())\n        elif isinstance(values, list):\n            if is_device_category:\n                add_diagnostic(\n                    "io_labels_required",\n                    "suggested_io.%s" % category_text,\n                    str(tr("普通 I/O 类别必须使用地址到非空用途说明的字典；仅地址列表已忽略。")),\n                    values,\n                )\n                continue\n            entries = [(value, "") for value in values]\n        else:\n            metadata[category_text] = values\n            add_diagnostic(\n                "invalid_io_container",\n                "suggested_io.%s" % category_text,\n                str(tr("I/O 类别必须是地址字典；特殊软元件类别也可使用地址列表，原值已移入 hardware_config。")),\n                values,\n            )\n            continue\n''',
    "reject unlabeled normal io lists",
)

replace_once(
    api,
    '''            else:\n                label = str(label or "").strip()\n            if actual_kind == "SM" or (special_relays and actual_kind == "M"):\n''',
    '''            else:\n                label = str(label or "").strip()\n            if is_device_category and not label:\n                add_diagnostic(\n                    "missing_io_label",\n                    path,\n                    str(tr("普通 I/O 地址缺少用途说明，已忽略该项。")),\n                )\n                continue\n            if actual_kind == "SM" or (special_relays and actual_kind == "M"):\n''',
    "drop blank normal io labels",
)

replace_once(
    execution,
    '''            imported = _mapping(bundle["importer"](\n                paths[0], comment_csv_path=paths[1], start_if_needed=False,\n                synchronize_comments=True, verify_roundtrip=True, save_project=True,\n''',
    '''            # Normal “Send to GX” already keeps a pre-import backup and waits\n            # for GX Works2 to acknowledge each import. Exporting program/comments\n            # again after the write doubles the MFC-dialog traffic and belongs to\n            # explicit inspect/sync workflows, not the fast send path.\n            imported = _mapping(bundle["importer"](\n                paths[0], comment_csv_path=paths[1], start_if_needed=False,\n                synchronize_comments=True, verify_roundtrip=False, save_project=True,\n''',
    "disable redundant post-import roundtrip on normal gx send",
)

replace_once(
    uia,
    '''    @staticmethod\n    def _set_legacy_file_name(dialog, path):\n        edits = [control for control in dialog.children(class_name="Edit") if control.is_enabled()]\n        if not edits:\n            edits = [control for control in dialog.descendants(class_name="Edit") if control.is_enabled()]\n        if not edits:\n            raise RuntimeError("文件选择对话框中没有文件名输入框")\n        target = edits[0]\n        target.set_edit_text(str(Path(path).resolve()))\n\n        buttons = [\n            control\n            for control in dialog.children(class_name="Button")\n            if control.is_enabled()\n        ]\n        for button in buttons:\n            if int(getattr(button, "control_id", lambda: 0)() or 0) == 1:\n                button.click()\n                return\n        target.type_keys("{ENTER}")\n''',
    '''    @staticmethod\n    def _set_legacy_file_name(dialog, path):\n        edits = [control for control in dialog.children(class_name="Edit") if control.is_enabled()]\n        if not edits:\n            edits = [control for control in dialog.descendants(class_name="Edit") if control.is_enabled()]\n        if not edits:\n            raise RuntimeError("文件选择对话框中没有文件名输入框")\n        target = edits[0]\n        target.set_edit_text(str(Path(path).resolve()))\n\n        # GX Works2 uses a legacy MFC common dialog. Depending on Windows/GX\n        # build, the default Save/Open button may be a direct child or exposed\n        # deeper in the Win32 wrapper. Search both before falling back to the\n        # native IDOK command; merely pressing Enter in the edit box is not\n        # reliable and was leaving comment exports waiting for a manual Save.\n        buttons = []\n        seen = set()\n        for getter in (dialog.children, dialog.descendants):\n            try:\n                candidates = getter(class_name="Button")\n            except Exception:\n                candidates = []\n            for control in candidates:\n                try:\n                    enabled = control.is_enabled()\n                except Exception:\n                    enabled = True\n                if not enabled:\n                    continue\n                handle = int(getattr(control, "handle", 0) or 0)\n                key = handle or id(control)\n                if key in seen:\n                    continue\n                seen.add(key)\n                buttons.append(control)\n        for button in buttons:\n            raw_id = getattr(button, "control_id", 0)\n            try:\n                control_id = int(raw_id() if callable(raw_id) else raw_id or 0)\n            except Exception:\n                control_id = 0\n            if control_id != 1:\n                continue\n            handle = int(getattr(button, "handle", 0) or 0)\n            if os.name == "nt" and handle:\n                ctypes.windll.user32.SendMessageW(handle, 0x00F5, 0, 0)  # BM_CLICK\n            else:\n                click = getattr(button, "click", None)\n                if callable(click):\n                    click()\n                else:\n                    button.click_input()\n            return\n\n        dialog_handle = int(getattr(dialog, "handle", 0) or 0)\n        if os.name == "nt" and dialog_handle:\n            ctypes.windll.user32.SendMessageW(dialog_handle, 0x0111, 1, 0)  # WM_COMMAND/IDOK\n            return\n        target.type_keys("{ENTER}")\n''',
    "reliably submit legacy save dialog",
)

replace_once(
    uia,
    '''        destination_signature = None\n        destination_stable_since = None\n        while time.monotonic() < deadline:\n''',
    '''        destination_signature = None\n        destination_stable_since = None\n        main_ready_since = None\n        while time.monotonic() < deadline:\n''',
    "track editable-main quiescence",
)

replace_once(
    uia,
    '''            for handle in self._native_dialog_handles(session):\n                message = self._native_dialog_text(handle)\n                if not message:\n                    continue\n                if message:\n                    last_message = message\n                if self.CONFIRMATION_TEXT.search(message):\n                    continue\n                if self.FAILURE_TEXT.search(message):\n                    return {"success": False, "message": message}\n                if self.SUCCESS_TEXT.search(message):\n                    self._native_confirm_dialog(handle)\n                    return {"success": True, "message": message}\n            time.sleep(0.15)\n''',
    '''            dialog_handles = self._native_dialog_handles(session)\n            for handle in dialog_handles:\n                message = self._native_dialog_text(handle)\n                if not message:\n                    continue\n                if message:\n                    last_message = message\n                if self.CONFIRMATION_TEXT.search(message):\n                    continue\n                if self.FAILURE_TEXT.search(message):\n                    return {"success": False, "message": message}\n                if self.SUCCESS_TEXT.search(message):\n                    self._native_confirm_dialog(handle)\n                    return {"success": True, "message": message}\n\n            # Some GX Works2 versions never expose a parseable completion text.\n            # The old code intentionally accepted an enabled MAIN frame as the\n            # fallback acknowledgement, but only after waiting the full 12 s.\n            # Accept the same observable state once it is stable and no modal\n            # dialog remains; this removes ~12 s from each program/comment read.\n            now = time.monotonic()\n            if (\n                not destination\n                and main_ready\n                and not dialog_handles\n                and now - started_at >= 0.60\n            ):\n                if main_ready_since is None:\n                    main_ready_since = now\n                elif now - main_ready_since >= 0.45:\n                    return {\n                        "success": True,\n                        "message": last_message or "GX Works2已返回可编辑状态",\n                    }\n            else:\n                main_ready_since = None\n            time.sleep(0.10)\n''',
    "finish imports on stable editable main",
)

replace_once(
    uia,
    '''                    command.invoke()\n                    self._wait_confirmation_and_accept(session, "写入")\n''',
    '''                    command.invoke()\n                    self._wait_confirmation_and_accept(\n                        session, "写入", timeout=min(self.timeout, 4.0)\n                    )\n''',
    "bound export confirmation fallback",
)

replace_once(
    uia,
    '''            dialog = self._wait_legacy_dialog(\n                session,\n                re.compile(r"打开|保存|CSV|Open|Save", re.I),\n                failure_stage=file_dialog_stage if operation else "",\n            )\n''',
    '''            dialog = self._wait_legacy_dialog(\n                session,\n                re.compile(r"打开|保存|CSV|Open|Save", re.I),\n                timeout=min(self.timeout, 5.0),\n                failure_stage=file_dialog_stage if operation else "",\n            )\n''',
    "bound export file-dialog wait",
)

replace_once(
    uia,
    '''                dialog = self._wait_legacy_dialog(\n                    session,\n                    re.compile(r"打开|保存|CSV|Open|Save", re.I),\n                )\n''',
    '''                dialog = self._wait_legacy_dialog(\n                    session,\n                    re.compile(r"打开|保存|CSV|Open|Save", re.I),\n                    timeout=min(self.timeout, 5.0),\n                )\n''',
    "bound import file-dialog fallback",
)

replace_once(
    uia,
    '''        if not confirm_before_file:\n            self._wait_confirmation_and_accept(session, "读取")\n''',
    '''        if not confirm_before_file:\n            self._wait_confirmation_and_accept(\n                session, "读取", timeout=min(self.timeout, 4.0)\n            )\n''',
    "bound import confirmation wait",
)

test_file.write_text(
    r'''import types
from pathlib import Path

import api
import gxworks2.ui_automation as uia_module
from application.execution import GXExecutionCoordinator
from gxworks2.ui_automation import PywinautoGXWorks2UIAutomation


def test_analysis_prompt_requires_nonempty_labels_for_normal_io():
    prompt = api.ANALYSIS_SYSTEM_PROMPT
    assert "普通类别 X/Y/M/D/T/C/S 必须使用 JSON 对象" in prompt
    assert "不得只返回地址数组" in prompt
    assert "每个地址都必须有非空说明" in prompt


def test_normal_io_list_is_not_silently_converted_to_blank_labels():
    result = api._normalize_analysis_result(
        {
            "summary": "test",
            "approaches": [],
            "missing_info": [],
            "suggested_io": {
                "X": ["X1", "X3"],
                "Y": {"Y0": "输送带"},
                "special_relays": ["M8000"],
            },
        },
        "FX3U",
        "",
    )
    assert "X" not in result["suggested_io"]
    assert result["suggested_io"]["Y"] == {"Y0": "输送带"}
    assert result["suggested_io"]["special_relays"] == {"M8000": ""}
    assert any(item.get("code") == "io_labels_required" for item in result["format_diagnostics"])


def test_blank_normal_io_label_is_dropped_instead_of_rendering_empty_input():
    result = api._normalize_analysis_result(
        {
            "summary": "test",
            "approaches": [],
            "missing_info": [],
            "suggested_io": {"X": {"X1": ""}, "D": {"D0": "状态寄存器"}},
        },
        "FX3U",
        "",
    )
    assert "X" not in result["suggested_io"]
    assert result["suggested_io"]["D"] == {"D0": "状态寄存器"}
    assert any(item.get("code") == "missing_io_label" for item in result["format_diagnostics"])


class _Edit:
    def __init__(self):
        self.value = ""
        self.entered = False

    def is_enabled(self):
        return True

    def set_edit_text(self, value):
        self.value = value

    def type_keys(self, value):
        self.entered = value == "{ENTER}"


class _Button:
    handle = 0

    def __init__(self):
        self.clicked = False

    def is_enabled(self):
        return True

    def control_id(self):
        return 1

    def click(self):
        self.clicked = True


class _LegacyDialog:
    handle = 0

    def __init__(self):
        self.edit = _Edit()
        self.button = _Button()

    def children(self, class_name=None):
        if class_name == "Edit":
            return [self.edit]
        if class_name == "Button":
            return []
        return []

    def descendants(self, class_name=None):
        if class_name == "Button":
            return [self.button]
        return []


def test_legacy_save_dialog_finds_nested_default_button(tmp_path):
    dialog = _LegacyDialog()
    destination = tmp_path / "comments.csv"
    PywinautoGXWorks2UIAutomation._set_legacy_file_name(dialog, destination)
    assert dialog.edit.value == str(destination.resolve())
    assert dialog.button.clicked is True
    assert dialog.edit.entered is False


def test_operation_result_accepts_stable_editable_main_without_full_timeout(monkeypatch):
    clock = {"value": 0.0}
    monkeypatch.setattr(uia_module.time, "monotonic", lambda: clock["value"])
    monkeypatch.setattr(
        uia_module.time,
        "sleep",
        lambda seconds: clock.__setitem__("value", clock["value"] + float(seconds)),
    )

    automation = PywinautoGXWorks2UIAutomation(timeout=12.0)
    main = types.SimpleNamespace(exists=lambda: True, is_enabled=lambda: True)
    monkeypatch.setattr(automation, "_main_window", lambda _session: main)
    monkeypatch.setattr(automation, "_read_output_summary", lambda _session: "")
    monkeypatch.setattr(automation, "_native_dialog_handles", lambda _session: [])

    result = automation._wait_operation_result(types.SimpleNamespace(), destination=None)
    assert result["success"] is True
    assert result["message"] == "GX Works2已返回可编辑状态"
    assert clock["value"] < 2.0


def test_web_gx_send_skips_redundant_post_import_roundtrip(tmp_path):
    class Store:
        def __init__(self):
            self.root = tmp_path
            self.version = {
                "id": "v1",
                "revision": 1,
                "artifacts": {"program_csv": "program.csv", "comment_csv": "comments.csv"},
            }
            root = self.version_dir("p1", "v1")
            root.mkdir(parents=True)
            (root / "program.csv").write_text("program", encoding="utf-8")
            (root / "comments.csv").write_text("comments", encoding="utf-8")

        def get_project(self, _project_id):
            return {"id": "p1", "active_version_id": "v1"}

        def get_version(self, _project_id, _version_id):
            return dict(self.version)

        def project_dir(self, project_id):
            return self.root / project_id

        def version_dir(self, project_id, version_id):
            return self.project_dir(project_id) / version_id

    calls = []

    def importer(*args, **kwargs):
        calls.append(kwargs)
        return {"success": True, "message": "ok"}

    service = GXExecutionCoordinator(
        Store(),
        dependencies_factory=lambda _operation: {"importer": importer},
        com_factory=lambda: types.SimpleNamespace(CoInitialize=lambda: None, CoUninitialize=lambda: None),
        resource_lock_path=tmp_path / "desktop.lock",
    )
    try:
        result = service.submit_approved(
            "gx_import",
            {"project_id": "p1", "version_id": "v1"},
            approval_id="a1",
        ).result(5)
    finally:
        service.close()
    assert result["status"] == "imported"
    assert calls and calls[0]["verify_roundtrip"] is False
    assert calls[0]["synchronize_comments"] is True
''',
    encoding="utf-8",
    newline="\n",
)
print("created: I/O protocol and GX fast-path regression tests")
