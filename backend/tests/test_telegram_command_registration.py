from backend.scripts.manage import _telegram_bot_commands


def test_registered_telegram_commands_include_webhook_server_commands():
    commands = {item["command"] for item in _telegram_bot_commands()}

    assert "docker_status" in commands
    assert "jellyfin_restart" in commands
    assert "haruhi_llm_start" in commands
    assert "haruhi_llm_stop" in commands
