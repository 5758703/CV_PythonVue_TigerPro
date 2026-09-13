from services.model_scenarios import (
    PHASE_ONE_KEYS,
    WORKBENCH_TYPES,
    get_scenario,
    list_scenarios,
)
from config import Config


EXPECTED_PHASE_ONE_KEYS = (
    "efficient-sam",
    "mobile-sam",
    "clip-reid-vehicle",
    "keremberke-yolov5m-license-plate",
    "keremberke-yolov5n-license-plate",
    "transreid-vehicle",
    "vehicle-vit-reid",
    "yolo26n-obb",
    "yolo26n-p2-plate",
)


def test_phase_one_scenarios_are_unique_and_in_document_order():
    scenarios = list_scenarios(phase=1)

    assert PHASE_ONE_KEYS == EXPECTED_PHASE_ONE_KEYS
    assert tuple(item["modelKey"] for item in scenarios) == EXPECTED_PHASE_ONE_KEYS
    assert len(scenarios) == len(set(item["modelKey"] for item in scenarios)) == 9


def test_phase_one_workbench_distribution_matches_supported_capabilities():
    scenarios = list_scenarios(phase=1)
    counts = {workbench: 0 for workbench in WORKBENCH_TYPES}
    for scenario in scenarios:
        counts[scenario["workbenchType"]] += 1

    assert counts == {
        "segmentation": 2,
        "vehicle_reid": 3,
        "plate_detection": 3,
        "obb_detection": 1,
    }


def test_each_phase_one_scenario_has_complete_user_facing_metadata():
    required_fields = (
        "project",
        "workflow",
        "outputs",
        "metrics",
        "risks",
        "defaults",
        "input",
        "apiPath",
    )

    for scenario in list_scenarios(phase=1):
        for field in required_fields:
            assert scenario[field], f"{scenario['modelKey']} is missing {field}"


def test_image_inputs_match_existing_upload_format_and_size_constraints():
    max_size_mb = Config.MAX_CONTENT_LENGTH // (1024 * 1024)

    for scenario in list_scenarios(phase=1):
        assert ".webp" in scenario["input"]["formats"]
        assert scenario["input"]["maxSizeMb"] == max_size_mb


def test_unknown_model_key_has_no_scenario():
    assert get_scenario("not-a-registered-model") is None


def test_returned_scenarios_are_defensive_copies():
    listed = list_scenarios(phase=1)
    listed[0]["defaults"]["conf"] = 0.01
    listed[0]["input"]["formats"].append(".mutated")

    retrieved = get_scenario("efficient-sam")

    assert retrieved["defaults"]["conf"] != 0.01
    assert ".mutated" not in retrieved["input"]["formats"]
