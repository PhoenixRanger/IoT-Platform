from pathlib import Path


ROOT = Path(__file__).parents[1]


def firmware_source(target):
    return (ROOT / "firmware" / target / "src" / "main.cpp").read_text()


def test_shared_cycle_identity_uses_random_boot_id_and_ram_sequence():
    helper = (ROOT / "firmware/shared/telemetry/CycleIdentity.h").read_text()
    assert helper.count("esp_random()") == 2
    assert "uint64_t bootId_" in helper
    assert "uint32_t sequence_" in helper
    assert "sequence_ = 0" in helper
    assert "++sequence_" in helper
    assert '"cy_%08lx%08lx_%lu"' in helper


def test_environment_publish_cycle_is_created_once_and_reused():
    source = firmware_source("environment-node")
    loop = source[source.index("void loop()") :]
    assert loop.count("cycleIdentity.next()") == 1
    assert loop.count("publishReading(") == 2
    assert loop.count("publishReading(TEMPERATURE_INSTANCE_ID, cycleId") == 1
    assert loop.count("publishReading(HUMIDITY_INSTANCE_ID, cycleId") == 1
    assert "if (!isnan(temperature))" in loop
    assert "if (!isnan(humidity))" in loop


def test_irrigation_publish_cycle_survives_missing_ms8607_data():
    source = firmware_source("irrigation-controller")
    loop = source[source.index("void loop()") :]
    assert loop.count("cycleIdentity.next()") == 1
    assert loop.count("publishReading(") == 5
    assert loop.count(", cycleId,") == 5
    assert loop.index("const String cycleId") < loop.index("if (ms8607Available)")
    assert "if (ms8607.getEvent" in loop
