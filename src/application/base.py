"""Small callback/language boundary for synchronous application workflows."""
import copy

from i18n import get_language, language_context


class WorkflowError(RuntimeError):
    pass


def model_call(function, *args, **kwargs):
    """Guard only a model invocation; local engineering errors keep their detail."""
    from model_provider import ResponseRejectedError, public_model_error
    try:
        return function(*args, **kwargs)
    except ResponseRejectedError:
        raise
    except Exception as error:
        safe_error = public_model_error(error)
        raise WorkflowError(str(safe_error)) from safe_error


class Workflow:
    def __init__(self, *, on_event=None, response_language=None, provider=None, model_name=None):
        self.on_event = on_event
        self.response_language = response_language or get_language()
        self.provider = provider
        self.model_name = model_name

    def _emit(self, event_type, payload):
        if self.on_event:
            if not isinstance(payload, dict):
                key = "message" if event_type == "progress" else "text"
                payload = {key: str(payload)}
            self.on_event(event_type, copy.deepcopy(payload))

    def run(self):
        import api

        with language_context(self.response_language), api.provider_scope(self.provider, model_name=self.model_name):
            return self._run()
