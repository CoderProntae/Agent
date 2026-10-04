"""Configuration persistence and defaults."""

from agentdesk.core.config import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_PORT,
    AppConfig,
    load_config,
    save_config,
)


def test_defaults_target_port_11435():
    cfg = AppConfig()
    assert cfg.ollama_port == 11435
    assert DEFAULT_OLLAMA_PORT == 11435
    assert cfg.base_url == "http://localhost:11435"
    assert cfg.model == DEFAULT_MODEL == "qwen3.5-9b-abliterated"


def test_base_url_with_custom_host():
    cfg = AppConfig(ollama_host="10.0.0.5", ollama_port=9999)
    assert cfg.base_url == "http://10.0.0.5:9999"


def test_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = AppConfig(model="llama3", ollama_port=1234, temperature=0.9)
    save_config(cfg, path)
    loaded = load_config(path)
    assert loaded.model == "llama3"
    assert loaded.ollama_port == 1234
    assert loaded.temperature == 0.9


def test_corrupt_file_falls_back(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.ollama_port == DEFAULT_OLLAMA_PORT


def test_unknown_keys_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"ollama_port": 4321, "bogus_key": true}', encoding="utf-8")
    cfg = load_config(path)
    assert cfg.ollama_port == 4321
