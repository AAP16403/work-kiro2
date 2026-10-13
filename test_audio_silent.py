"""Test runs use pyglet's silent audio driver, so the suite never plays sound.

The AudioManager logic still runs in test runs (the audio tests check it), only the output is silent.
"""

import audio


def test_silent_switch_is_on_for_test_scripts():
    assert audio._silent_requested(), "a test_ script must select the silent audio driver"
    print("[PASS] test_silent_switch_is_on_for_test_scripts passed")


def test_audio_manager_uses_silent_driver_and_keeps_logic_on():
    from pyglet import media

    am = audio.AudioManager()
    driver = media.get_audio_driver()
    assert "silent" in type(driver).__module__, f"test run opened {type(driver).__module__}"
    assert am.available, "silent mode must keep the AudioManager logic path on"
    am.play("ui_click")  # must not raise and must not make sound
    print("[PASS] test_audio_manager_uses_silent_driver_and_keeps_logic_on passed")


def test_explicit_silent_env_selects_silent_driver():
    import os

    old = os.environ.get("PLOUTO_SILENT")
    os.environ["PLOUTO_SILENT"] = "1"
    try:
        assert audio._silent_requested()
    finally:
        if old is None:
            os.environ.pop("PLOUTO_SILENT", None)
        else:
            os.environ["PLOUTO_SILENT"] = old
    print("[PASS] test_explicit_silent_env_selects_silent_driver passed")


if __name__ == "__main__":
    test_silent_switch_is_on_for_test_scripts()
    test_audio_manager_uses_silent_driver_and_keeps_logic_on()
    test_explicit_silent_env_selects_silent_driver()
    print("ALL AUDIO SILENT TESTS PASSED")
