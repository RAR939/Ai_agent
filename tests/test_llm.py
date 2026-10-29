"""src/llm.py: адрес сервера Ollama, токен и таймаут; проверка на настоящей HTTP-связи с подставным сервером."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from src import llm
from src.tracker import extract


def cfg_with(**models):
    base = {"llm": "qwen3:8b", "embed": "bge-m3", "temperature": 0.1}
    return {"models": {**base, **models}}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    llm._make.cache_clear()
    yield
    llm._make.cache_clear()


def use_config(monkeypatch, **models):
    monkeypatch.setattr(llm, "load_config", lambda: cfg_with(**models))


# ---------- настройки ----------
def test_defaults_are_local(monkeypatch):
    use_config(monkeypatch)
    assert llm.settings() == {"host": None, "token": None, "timeout": 120.0}
    assert llm.describe() == "локальная Ollama"
    assert str(llm.client()._client.base_url) == "http://127.0.0.1:11434"


def test_host_from_config_and_env_overrides(monkeypatch):
    use_config(monkeypatch, host="http://gpu.example:11434", timeout_sec=30)
    s = llm.settings()
    assert (s["host"], s["timeout"]) == ("http://gpu.example:11434", 30.0)
    assert str(llm.client()._client.base_url) == "http://gpu.example:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:21434")                     # туннель у каждого свой
    assert llm.settings()["host"] == "http://localhost:21434"
    assert str(llm.client()._client.base_url) == "http://localhost:21434"


def test_empty_host_falls_back_to_env(monkeypatch):
    use_config(monkeypatch, host="")
    monkeypatch.setenv("OLLAMA_HOST", "gpu:11434")
    assert str(llm.client()._client.base_url) == "http://gpu:11434"


def test_token_goes_to_authorization_header_and_not_to_describe(monkeypatch):
    use_config(monkeypatch, host="https://llm.example.org")
    assert "authorization" not in {k.lower() for k in llm.client()._client.headers}
    monkeypatch.setenv("OLLAMA_API_KEY", "s3cret")
    assert llm.client()._client.headers["authorization"] == "Bearer s3cret"
    assert llm.describe() == "https://llm.example.org, токен задан" and "s3cret" not in llm.describe()


def test_client_is_cached_and_timeout_override(monkeypatch):
    use_config(monkeypatch, host="http://a:1", timeout_sec=60)
    assert llm.client() is llm.client()
    assert llm.client(timeout=3) is not llm.client()
    assert llm.client(timeout=3)._client.timeout.read == 3 and llm.client()._client.timeout.read == 60


def test_bad_timeout_value_uses_default(monkeypatch):
    use_config(monkeypatch, timeout_sec=0)
    assert llm.settings()["timeout"] == llm.DEFAULT_TIMEOUT


# ---------- настоящий HTTP: подставной сервер Ollama ----------
class FakeOllama(BaseHTTPRequestHandler):
    seen: list[dict] = []
    delay = 0.0

    def log_message(self, *a):        # тишина в выводе тестов
        pass

    def _reply(self, payload: dict):
        time.sleep(self.delay)
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeOllama.seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
        self._reply({"models": [{"model": "qwen3:8b", "name": "qwen3:8b"}, {"model": "bge-m3:latest",
                                                                           "name": "bge-m3:latest"}]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOllama.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        if self.path == "/api/chat":
            self._reply({"model": body["model"], "message": {"role": "assistant", "content": "ответ с сервера"},
                         "done": True})
        elif self.path == "/api/embed":
            self._reply({"model": body["model"], "embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]})
        else:
            self.send_error(404)


@pytest.fixture
def server(monkeypatch):
    FakeOllama.seen, FakeOllama.delay = [], 0.0
    httpd = HTTPServer(("127.0.0.1", 0), FakeOllama)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    host = f"http://127.0.0.1:{httpd.server_port}"
    use_config(monkeypatch, host=host, timeout_sec=5)
    yield host
    httpd.shutdown()
    httpd.server_close()


def test_chat_and_embed_reach_the_configured_server_with_token(server, monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "s3cret")
    reply = llm.chat(model="qwen3:8b", messages=[{"role": "user", "content": "привет"}])
    assert reply.message.content == "ответ с сервера"
    vectors = llm.embed(model="bge-m3", input=["раз", "два"]).embeddings
    assert len(vectors) == 2 and vectors[0] == [0.1, 0.2, 0.3]
    assert [(r["path"], r["auth"]) for r in FakeOllama.seen] == [("/api/chat", "Bearer s3cret"),
                                                                ("/api/embed", "Bearer s3cret")]
    assert FakeOllama.seen[0]["body"]["messages"][0]["content"] == "привет"


def test_list_models_and_vector_store_embed_use_the_server(server):
    assert llm.list_models() == ["qwen3:8b", "bge-m3:latest"]
    from src.index import vector_store
    assert vector_store.embed(["текст"]) == [[0.1, 0.2, 0.3]]
    assert FakeOllama.seen[-1]["path"] == "/api/embed" and FakeOllama.seen[-1]["body"]["model"] == "bge-m3"


def test_extract_calls_remote_model(server):
    assert extract._chat([{"role": "user", "content": "x"}]) == "ответ с сервера"
    sent = FakeOllama.seen[-1]["body"]
    assert sent["model"] == "qwen3:8b" and sent["think"] is False and sent["options"] == {"temperature": 0}


def test_slow_server_becomes_model_unavailable_with_host_in_message(server, monkeypatch):
    use_config(monkeypatch, host=server, timeout_sec=0.2)
    FakeOllama.delay = 1.0
    with pytest.raises(extract.ModelUnavailable) as e:
        extract._chat([{"role": "user", "content": "x"}])
    assert server in str(e.value) and "Ollama недоступна" in str(e.value)


def test_unreachable_server_becomes_model_unavailable(monkeypatch):
    use_config(monkeypatch, host="http://127.0.0.1:9", timeout_sec=1)               # порт, на котором никто не слушает
    with pytest.raises(extract.ModelUnavailable, match="127.0.0.1:9"):
        extract._chat([{"role": "user", "content": "x"}])
