"""Bounded per-job diagnostic logs. Never store prompts, replies, keys or locals.

This module observes failures only: it does not repair, retry, accept, execute or
change model messages. Files live in private application state, not the PLC
workspace. Logging failures must never replace the original workflow outcome.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from collections import deque
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import zipfile

_SCHEMA = 1
_MAX_FILE = 512 * 1024
_MAX_EXPORT_LINES = 512
_ROOT = Path(__file__).resolve().parent
_active = ContextVar('runtime_diagnostics', default=None)
_attempt = ContextVar('diagnostic_attempt', default=0)
_ALLOWED_EVENTS = {'job_started', 'job_finished', 'model_request', 'provider_request', 'provider_result', 'attempt_finished',
                   'model_response', 'response_rejected', 'model_accepted',
                   'provider_exception', 'workflow_exception', 'logging_limit'}
_NUMBERS = {'request_index', 'attempt_index', 'message_count', 'message_chars', 'tool_count',
            'content_chars', 'reasoning_chars', 'chunk_count', 'choice_count', 'input_tokens',
            'output_tokens', 'total_tokens', 'reasoning_tokens', 'max_tokens',
            'max_completion_tokens', 'elapsed_ms', 'status_code', 'line', 'column',
            'position', 'original_line', 'original_column', 'original_position',
            'exception_count', 'event_count'}
_BOOLEANS = {'stream', 'refusal_present', 'finish_seen', 'at_or_near_end', 'fenced',
             'bom', 'traceback_truncated', 'content_present'}
_IDS = {'model', 'provider', 'contract', 'error_type', 'code', 'function'}
_ENUMS = {
    'stage': {'workflow', 'model_request', 'provider_transport', 'response_acceptance', 'publication'},
    'status': {'completed', 'failed', 'cancelled', 'interrupted', 'running'},
    'kind': {'analysis', 'generation', 'agent', 'review', 'test_plan', 'debug_plan',
             'execution', 'gx_read', 'gx_inspect'},
    'policy': {'legacy', 'minimal', 'manual', 'examples', 'combined', 'adaptive'},
    'format': {'text', 'json'},
    'response_format': {'text', 'json_object', 'json_schema', 'unspecified'},
    'content_type': {'str', 'list', 'dict', 'NoneType', 'int', 'bool'},
    'reasoning_type': {'str', 'list', 'dict', 'NoneType', 'int', 'bool'},
    'finish_reason': {'stop', 'length', 'content_filter', 'tool_calls', 'function_call',
                      'insufficient_system_resource', 'end_turn', 'max_tokens'},
    'root_type': {'dict', 'list', 'str', 'int', 'float', 'bool', 'NoneType'},
    'envelope': {'empty', 'object', 'array', 'fenced', 'bom', 'markup', 'other_text'},
    'json_status': {'valid_object', 'non_object', 'syntax_error', 'too_deep', 'not_checked', 'empty'},
    'json_error': {'Illegal trailing comma before end of object', 'Illegal trailing comma before end of array',
                   'Expecting value', "Expecting ',' delimiter", "Expecting ':' delimiter",
                   'Expecting property name enclosed in double quotes', 'Extra data',
                   'Unterminated string starting at', 'Invalid control character at',
                   'Invalid \\escape', 'Invalid \\uXXXX escape', 'Unexpected UTF-8 BOM (decode using utf-8-sig)'},
    'reason': {'invalid_json_object', 'invalid_prose_field', 'invalid_code_field',
               'unsupported_script', 'non_english_script', 'japanese_script',
               'latin_prose', 'ambiguous_han_only'},
}


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_./:\-]{1,100}', value):
        return 'redacted'
    if any(word in value.lower() for word in ('sk-', 'bearer', 'secret', 'api_key', 'token=')):
        return 'redacted'
    return value


def _number(value):
    return max(0, min(value, 10**12)) if type(value) is int else None


def _safe_fields(fields):
    result = {}
    for key, value in fields.items():
        if key in _NUMBERS:
            result[key] = _number(value)
        elif key in _BOOLEANS and type(value) is bool:
            result[key] = value
        elif key in _IDS:
            result[key] = _identifier(value)
        elif key in _ENUMS:
            result[key] = value if isinstance(value, str) and value in _ENUMS[key] else 'unknown'
        elif key in ('job_id', 'project_id', 'version_id'):
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value):
                result[key] = value
        elif key == 'content_sha256' and isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value):
            result[key] = value
        elif key == 'json' and isinstance(value, dict):
            result[key] = _safe_fields(value)
        elif key in ('exceptions', 'frames', 'violations') and isinstance(value, (list, tuple)):
            result[key] = [_safe_fields(item) for item in value[:32] if isinstance(item, dict)]
        elif key == 'file' and isinstance(value, str):
            # Export only source-relative file locations, never filesystem roots.
            if re.fullmatch(r'(src|external)/[A-Za-z0-9_./-]{1,180}', value) and '..' not in value:
                result[key] = value
        elif key == 'timestamp' and isinstance(value, str) and re.fullmatch(r'[0-9T:.+Z-]{10,40}', value):
            result[key] = value
    return result


def json_diagnostic(content):
    """Inspect using the same fence handling as response_language.inspect_response.

    Coordinates include both the parsed JSON and the original model content.
    No surrounding characters, property names or values are returned.
    """
    text = content if isinstance(content, str) else ''
    raw = text.strip()
    offset = len(text) - len(text.lstrip())
    fenced = raw.startswith('```') and raw.endswith('```') and '\n' in raw
    envelope = ('empty' if not raw else 'bom' if raw.startswith('\ufeff') else
                'fenced' if raw.startswith('```') else 'object' if raw.startswith('{') else
                'array' if raw.startswith('[') else 'markup' if raw.startswith('<') else 'other_text')
    if fenced:
        inner = raw.split('\n', 1)[1].rsplit('```', 1)[0]
        offset += raw.index('\n') + 1 + len(inner) - len(inner.lstrip())
        raw = inner.strip()
    result = {'envelope': envelope, 'fenced': fenced, 'bom': raw.startswith('\ufeff')}
    try:
        payload = json.loads(raw)
        result.update(json_status='valid_object' if isinstance(payload, dict) else 'non_object',
                      root_type=type(payload).__name__)
    except json.JSONDecodeError as exc:
        original = min(len(text), offset + exc.pos)
        result.update(json_status='empty' if not raw else 'syntax_error', json_error=exc.msg,
                      line=exc.lineno, column=exc.colno, position=exc.pos,
                      original_position=original, original_line=text.count('\n', 0, original) + 1,
                      original_column=original - text.rfind('\n', 0, original),
                      at_or_near_end=exc.pos >= max(0, len(raw) - 8))
    except (RecursionError, ValueError):
        result.update(json_status='too_deep')
    return _safe_fields(result)


def _directory(state_dir):
    state = Path(state_dir).resolve()
    target = state / 'diagnostics'
    if target.is_symlink() or (target.exists() and target.resolve().parent != state):
        raise ValueError('Unsafe diagnostic directory')
    return target


def _path(state_dir, job_id):
    if not isinstance(job_id, str) or not re.fullmatch(r'job_[a-zA-Z0-9_-]{1,120}', job_id):
        raise ValueError('Invalid diagnostic job identifier')
    directory = _directory(state_dir)
    path = directory / (job_id + '.jsonl')
    if path.is_symlink() or (path.exists() and path.resolve().parent != directory.resolve()):
        raise ValueError('Unsafe diagnostic file')
    return path


class DiagnosticSession:
    def __init__(self, state_dir, job_id):
        self.state_dir, self.job_id = Path(state_dir), job_id
        self.request_index = 0
        self.started = time.monotonic()
        self.failed = False
        self.limited = False
        self.lock = threading.Lock()
        self._write_failed = False

    def write(self, event, **fields):
        if event not in _ALLOWED_EVENTS:
            return
        try:
            with self.lock:
                path = _path(self.state_dir, self.job_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                if os.name != 'nt':
                    path.parent.chmod(0o700)
                size = path.stat().st_size if path.exists() else 0
                # Reserve room for error + completion even for unusually long agent runs.
                if size >= _MAX_FILE - 48 * 1024 and event not in {'workflow_exception', 'job_finished'}:
                    self.limited = True
                    return
                if size >= _MAX_FILE:
                    return
                record = {'schema_version': _SCHEMA, 'event': event,
                          'timestamp': datetime.now(timezone.utc).isoformat(),
                          'job_id': self.job_id, 'request_index': self.request_index,
                          'attempt_index': _attempt.get(), **_safe_fields(fields)}
                data = (json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
                if size + len(data) > _MAX_FILE:
                    return
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0)
                descriptor = os.open(str(path), flags, 0o600)
                with os.fdopen(descriptor, 'ab') as stream:
                    stream.write(data)
        except Exception:
            if not self._write_failed:
                self._write_failed = True
                print('Diagnostic log unavailable; original job outcome is unchanged.', file=sys.stderr)


@contextmanager
def diagnostic_scope(state_dir, job_id, **metadata):
    session = DiagnosticSession(state_dir, job_id)
    token, attempt_token = _active.set(session), _attempt.set(0)
    try:
        emit('job_started', stage='workflow', **metadata)
        yield session
    finally:
        _attempt.reset(attempt_token)
        _active.reset(token)


def emit(event, **fields):
    session = _active.get()
    if session is not None:
        session.write(event, **fields)


def begin_request(request, provider):
    session = _active.get()
    if session is None:
        return
    session.request_index += 1
    _attempt.set(0)
    # Strings only: do not call repr()/str() on image or tool payload objects.
    total = sum(len(m.content) for m in request.messages if isinstance(getattr(m, 'content', None), str))
    emit('model_request', stage='model_request', model=request.model,
         provider=type(provider).__name__, contract=request.response_contract.name,
         format=request.response_contract.format, stream=request.stream,
         message_count=len(request.messages), message_chars=total, tool_count=len(request.tools))


def begin_attempt():
    if _active.get() is not None:
        _attempt.set(_attempt.get() + 1)


def response_received(raw, request):
    if _active.get() is None:
        return
    content = raw.message.content
    emit('model_response', stage='response_acceptance', stream=raw.stream,
         content_chars=len(content), reasoning_chars=len(raw.message.reasoning),
         tool_count=len(raw.message.tool_calls),
         content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest(),
         json=json_diagnostic(content) if request.response_contract.format == 'json' else {'json_status':'not_checked'},
         input_tokens=getattr(raw.usage, 'input_tokens', None),
         output_tokens=getattr(raw.usage, 'output_tokens', None),
         total_tokens=getattr(raw.usage, 'total_tokens', None))


def exception_record(error, *, event='workflow_exception', stage='workflow'):
    if _active.get() is None:
        return
    chain, seen = [], set()
    while isinstance(error, BaseException) and id(error) not in seen and len(chain) < 8:
        seen.add(id(error))
        frames, tb = [], error.__traceback__
        while tb is not None:
            frame = tb.tb_frame
            try:
                name = 'src/' + Path(frame.f_code.co_filename).resolve().relative_to(_ROOT).as_posix()
            except (ValueError, OSError):
                name = 'external/' + Path(frame.f_code.co_filename).name
            frames.append({'file': name, 'line': tb.tb_lineno, 'function': frame.f_code.co_name})
            tb = tb.tb_next
        chain.append({'error_type':type(error).__name__, 'code':getattr(error, 'code', ''),
                      'status_code':getattr(error, 'status_code', None), 'frames':frames[-32:],
                      'traceback_truncated':len(frames) > 32})
        error = error.__cause__ or error.__context__
    emit(event, stage=stage, exceptions=chain, exception_count=len(chain))


def export_diagnostics(state_dir, job):
    """Export one authorized job only; no configuration, events, prompts or sources."""
    job_id = job['id']
    path = _path(state_dir, job_id)
    records, capture_status = deque(maxlen=_MAX_EXPORT_LINES), 'not_captured'
    valid_count = 0
    if path.is_file():
        if path.stat().st_size > _MAX_FILE:
            raise ValueError('Diagnostic file exceeds export limit')
        # Reproject at export: a hand-edited/corrupt log must not become an arbitrary file download.
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                    if (not isinstance(value, dict) or value.get('job_id') != job_id or
                        value.get('schema_version') != _SCHEMA or value.get('event') not in _ALLOWED_EVENTS):
                        continue
                    valid_count += 1
                    records.append({'schema_version':_SCHEMA, 'event':value['event'], **_safe_fields(value)})
                except (ValueError, RecursionError):
                    continue
            else:
                capture_status = ('export_truncated' if valid_count > _MAX_EXPORT_LINES else
                                  'captured' if records else 'unreadable')
    # Do not include job.result or the input snapshot. They can contain user data.
    meta = {'schema_version':_SCHEMA, 'job_id':job_id, 'capture_status':capture_status,
            'job':_safe_fields({key: job.get(key) for key in ('kind', 'status', 'project_id', 'version_id')}),
            'event_count':len(records), 'content_included':False, 'keys_included':False,
            'captured_after_upgrade_only':True}
    from application.job_errors import public_error_details
    meta['error_details'] = public_error_details(job.get('error_details'))
    meta['error_code'] = _identifier(job.get('error_code') or 'none')
    # Capture release identity only; never serialize the environment/config.
    roots = [Path(sys.executable).parent] if getattr(sys, 'frozen', False) else [_ROOT.parent]
    for root in roots:
        info = root / 'build-info.json'
        if info.is_file() and info.stat().st_size <= 128*1024:
            try:
                source = json.loads(info.read_text(encoding='utf-8-sig'))
                meta['build'] = {key:value for key in ('base_commit','build_input_commit')
                                 if isinstance(value := source.get(key), str) and re.fullmatch('[0-9a-f]{40}', value)}
            except (ValueError, OSError):
                pass
    text = json.dumps(meta, ensure_ascii=False, indent=2) + '\n'
    guide = ('GXWorks task diagnostics\n\n'
             'This archive contains metadata only, not model replies, prompts, API keys or PLC projects.\n'
             'Read summary.json, then diagnostics.jsonl in chronological order.\n'
             'Find response_rejected/model_response for JSON line, column and parser error;\n'
             'provider_result contains finish_reason when the provider actually supplied it.\n'
             'unknown / finish_seen=false is not evidence of token truncation.\n'
             'workflow_exception contains source file, function and line, but no locals/code/message.\n'
             'not_captured means this job predates diagnostic instrumentation; reproduce once on the new build.\n'
             'Output is not uploaded automatically. Inspect before sharing.\n')
    target = io.BytesIO()
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('summary.json', text)
        archive.writestr('diagnostics.jsonl', ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
        archive.writestr('README.txt', guide)
    return target.getvalue()
