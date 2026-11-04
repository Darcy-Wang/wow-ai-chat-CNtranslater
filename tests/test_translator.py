from types import SimpleNamespace
import pytest
import app.translator as module


class FakeClient:
    def __init__(self, **settings):
        self.calls = []
        self.settings = settings
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **request):
        self.calls.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content="译文：" + request["messages"][-1]["content"]), finish_reason="stop")])


@pytest.fixture
def translator(monkeypatch):
    monkeypatch.setattr(module, "OpenAI", FakeClient)
    return module.WowTranslator(api_key="secret-for-tests")


@pytest.mark.parametrize("first,second", [("pull in 1.5", "pull in 15"), ("don't pull", "do pull"),
                                         ("we'll pull", "well pull"), ("inv Alice", "inv ALICE")])
def test_cache_preserves_meaning(translator, first, second):
    assert translator.translate_message(first)[1] == "openai"
    assert translator.translate_message(second)[1] == "openai"
    assert translator.translate_message(first)[1] == "cache"
    assert len(translator._client.calls) == 2


def test_configuration_changes_isolate_cache(translator):
    translator.translate_message("attack now")
    assert translator.translate_message("attack now")[1] == "cache"
    translator.update_settings("another-test-secret", "https://example.test/v1", "another-model")
    assert translator.translate_message("attack now")[1] == "openai"
    assert translator._client.settings["max_retries"] == 0


def test_mixed_language_and_pure_chinese(translator):
    assert translator.translate_message("坦克 please interrupt")[1] == "openai"
    assert translator.translate_message("坦克请打断")[1] == "skipped"


def test_manual_name_removal_and_restoration(translator):
    translator.set_protected_names(["Darkhunter"])
    assert translator.translate_message("inv Darkhunter")[0] == "译文：inv Darkhunter"
    assert "__PLAYER_1__" in translator._client.calls[-1]["messages"][-1]["content"]
    translator.set_protected_names([])
    translator.translate_message("inv Darkhunter")
    assert "__PLAYER_1__" not in translator._client.calls[-1]["messages"][-1]["content"]


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_do_not_echo_secrets_or_chat(translator, capsys, status):
    class ApiError(Exception):
        status_code = status
    def fail(**request):
        raise ApiError("secret-for-tests PRIVATE_CHAT")
    translator._client.chat.completions.create = fail
    result, source, elapsed = translator.translate_message("PRIVATE_CHAT")
    assert source == "error"
    assert "secret-for-tests" not in result + capsys.readouterr().out
    assert "PRIVATE_CHAT" not in result
    assert not translator.cache


def test_truncated_and_invalid_name_results_not_cached(translator):
    translator._client.chat.completions.create = lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content="incomplete"), finish_reason="length")])
    assert translator.translate_message("attack now")[1] == "error"
    assert not translator.cache


def test_rate_limit_cooldown_keeps_local_dictionary_available(translator):
    calls = []
    class RateLimit(Exception):
        status_code = 429
    def fail(**request):
        calls.append(request)
        raise RateLimit()
    translator._client.chat.completions.create = fail
    assert translator.translate_message("first request")[1] == "error"
    assert translator.translate_message("second request")[1] == "error"
    assert len(calls) == 1
    assert translator.translate_message("oom")[1] == "local_dict"


def test_authentication_failure_blocks_until_settings_updated(translator):
    calls = []
    class Unauthorized(Exception):
        status_code = 401
    def fail(**request):
        calls.append(request)
        raise Unauthorized()
    translator._client.chat.completions.create = fail
    translator.translate_message("first request")
    translator.translate_message("second request")
    assert len(calls) == 1
    translator.update_settings("replacement-key", "https://example.test/v1", "test-model")
    assert translator.translate_message("second request")[1] == "openai"
