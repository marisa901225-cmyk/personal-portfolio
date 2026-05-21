from backend.scripts.manage import _telegram_bot_commands


def test_registered_telegram_commands_include_webhook_server_commands():
    commands = {item["command"] for item in _telegram_bot_commands()}

    assert "docker_status" in commands
    assert "jellyfin_restart" in commands
    assert "com_on" in commands
    assert "com_off" in commands
    assert "haruhi_llm_start" in commands
    assert "haruhi_llm_stop" in commands
    assert "night_llm_on" not in commands
    assert "night_llm_off" not in commands
