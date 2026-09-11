from pathlib import Path


def replace_once(text: str, old: str, new: str, name: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{name} preimage mismatch: expected 1 match, found {count}")
    return text.replace(old, new, 1)


generation = Path("src/application/generation.py")
text = generation.read_text(encoding="utf-8")

text = replace_once(
    text,
    '''        self.conversation_history = self.conversation_history or []
        self.task_type = self.task_type or ("edit" if self.previous_json is not None else "generate")
        self.previous_ir = self.previous_ir if is_plc_ir(self.previous_ir) else None
''',
    '''        self.conversation_history = self.conversation_history or []
        self.task_type = self.task_type or ("edit" if self.previous_json is not None else "generate")
        # The local merge base must also be visible to the model. Previously an
        # edit request set ``is_edit_mode`` but omitted the current ladder from
        # model context, so the model often regenerated the program from spec.
        if self.current_version_json is None and self.previous_json is not None:
            self.current_version_json = copy.deepcopy(self.previous_json)
        self.previous_ir = self.previous_ir if is_plc_ir(self.previous_ir) else None
''',
    "generation init",
)

text = replace_once(
    text,
    '''            is_edit_mode = self.target_mode == "ladder" and self.previous_json is not None
            try:
''',
    '''            is_edit_mode = self.target_mode == "ladder" and self.previous_json is not None
            model_user_input = self.user_input
            if is_edit_mode and not self.repair_mode:
                # This is a model instruction, not an application-side gate.
                # The parser deliberately continues to accept both partial and
                # full JSON so an imperfect model choice never becomes another
                # hard-validation failure or hidden retry loop.
                model_user_input = (
                    '这是对系统提供的 Current version JSON 的修改请求。除非用户明确要求整体重写，'
                    '优先返回 mode="partial"：device_comments 只列新增或修改项，rungs 只列修改或新增的完整梯级，'
                    'delete_rung_ids 只列需要删除的梯级；不要重复输出未修改梯级。'
                    '如果你仍返回完整 JSON，应用也会正常接受，不需要为了格式选择重新生成。\\n\\n'
                    '用户修改要求：\\n'
                    + self.user_input
                )
            try:
''',
    "edit-mode prompt",
)

text = replace_once(
    text,
    '''                _reasoning, full_content = model_call(
                    stream_model_response,
                    self.user_input,
''',
    '''                _reasoning, full_content = model_call(
                    stream_model_response,
                    model_user_input,
''',
    "stream model call",
)

text = replace_once(
    text,
    '''                json_str = model_call(
                    self.dependencies.generate_json or api.generate_model_json,
                    self.user_input,
''',
    '''                json_str = model_call(
                    self.dependencies.generate_json or api.generate_model_json,
                    model_user_input,
''',
    "fallback model call",
)

generation.write_text(text, encoding="utf-8", newline="")


tests = Path("tests/test_generation_workflow.py")
text = tests.read_text(encoding="utf-8")
if not text.startswith("import copy\n"):
    text = replace_once(text, "import json\n", "import copy\nimport json\n", "test copy import")

marker = '''@pytest.mark.parametrize("mutation", ["delete", "rung", "device", "comment", "full"])
'''
new_tests = '''def test_edit_generation_sends_current_program_and_prefers_partial_output(tmp_path):
    base = _ladder()
    changed_rung = copy.deepcopy(base["rungs"][0])
    changed_rung["branches"][0]["inputs"][0]["type"] = "NC"
    partial = {
        "mode": "partial",
        "device_comments": {},
        "rungs": [changed_rung],
        "delete_rung_ids": [],
    }
    observed = {}

    def stream(user_input, *args, **kwargs):
        observed["user_input"] = user_input
        observed["current_version_json"] = copy.deepcopy(kwargs.get("current_version_json"))
        observed["is_edit_mode"] = kwargs.get("is_edit_mode")
        return "", json.dumps(partial, ensure_ascii=False)

    result = GenerationWorkflow(
        GenerationRequest("把 X0 改成常闭", previous_json=base, model_name="offline"),
        tmp_path,
        dependencies=GenerationDependencies(stream_response=stream),
    ).run()

    assert observed["is_edit_mode"] is True
    assert observed["current_version_json"] == base
    assert '优先返回 mode="partial"' in observed["user_input"]
    assert "不要重复输出未修改梯级" in observed["user_input"]
    persisted = json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8"))
    assert persisted["rungs"][0]["branches"][0]["inputs"][0]["type"] == "NC"
    assert result["repair_attempts"] == 0


def test_edit_generation_full_json_remains_accepted_without_retry(tmp_path):
    base = _ladder()
    full = copy.deepcopy(base)
    full["rungs"][0]["branches"][0]["inputs"][0]["type"] = "NC"
    calls = []

    def stream(*args, **kwargs):
        calls.append((args, kwargs))
        return "", json.dumps(full, ensure_ascii=False)

    result = GenerationWorkflow(
        GenerationRequest("把 X0 改成常闭", previous_json=base, model_name="offline"),
        tmp_path,
        dependencies=GenerationDependencies(
            stream_response=stream,
            generate_json=lambda *a, **k: pytest.fail("Full edit response must not trigger retry"),
        ),
    ).run()

    assert result["validation"]["status"] == "candidate_ready"
    assert result["repair_attempts"] == 0
    assert len(calls) == 1
    assert json.loads((tmp_path / "ladder.json").read_text(encoding="utf-8")) == full


'''
if "test_edit_generation_sends_current_program_and_prefers_partial_output" not in text:
    text = replace_once(text, marker, new_tests + marker, "test insertion")

tests.write_text(text, encoding="utf-8", newline="")
