from services.model_scenarios import (
    PHASE_ONE_KEYS,
    PHASE_TWO_KEYS,
    PHASE_THREE_KEYS,
    PHASE_FOUR_KEYS,
    PHASE_FIVE_KEYS,
    PHASE_SIX_KEYS,
    PHASE_SEVEN_KEYS,
    PHASE_EIGHT_KEYS,
    PHASE_NINE_KEYS,
    PHASE_TEN_KEYS,
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

EXPECTED_PHASE_TWO_KEYS = (
    "yolo26n-plate",
    "yolo26s-plate-pose",
    "yolov11-license-plate-n",
    "yolov11-license-plate-s",
    "yolov8-license-plate",
    "insightface-buffalo-l",
    "insightface-buffalo-s",
    "opencv-yunet-sface",
    "brain-tumor-yolo-opennoor",
)

EXPECTED_PHASE_THREE_KEYS = (
    "inpainting-lama",
    "mobilenet-v2",
    "vit-base",
    "yolo-master-cls-n",
    "vlm-fo1-3b",
    "dwpose-m",
    "rtmo-m",
    "rtmo-s",
    "rtmpose-m",
)

EXPECTED_PHASE_FOUR_KEYS = (
    'yolo-master-pose-n',
    'yolo11n-pose',
    'yolo26n-pose',
    'ppe-detection',
    'damoyolo-cigarette',
    'sec-fall-coco-yolov12m',
    'sec-fall-yolo11n',
    'sec-fight-nano',
    'sec-fight-small',
)

EXPECTED_PHASE_FIVE_KEYS = (
    'sec-fire-collision-yolo11',
    'sec-fire-forest-yolov8',
    'sec-fire-yolov8n',
    'sec-helmet-yolov8s',
    'sec-plate-yolov8',
    'sec-ppe-yolo',
    'sec-weapon-yolov8',
    'yolo26-smoking-detection',
    'yolo8-smoking-behavior',
)

EXPECTED_PHASE_SIX_KEYS = (
    'yolov8n-mobile-phone',
    'bert-ner',
    'rf-detr-seg-medium',
    'yolo-master-seg-n',
    'yoloe-26s-seg',
    'qwen3-vl-seg-cloud',
    'omdet-turbo-swin-tiny',
    'chinese-sign-language-tigerhhzz-yolo11s',
    'opencv-handpose-mediapipe',
)

EXPECTED_PHASE_SEVEN_KEYS = (
    'linly-talker',
    'bert-emotion',
    'finbert',
    'bart-mnli',
    'bert-fill-mask',
    'distilbart-cnn',
    'opus-mt-en-zh',
    'PP-OCRv6_small_det_onnx',
    'PP-OCRv6_small_rec_onnx',
)

EXPECTED_PHASE_EIGHT_KEYS = (
    'rapidtable-slanet-plus',
    'yolov8m-table-extraction',
    'yolo-master-obb-n',
    'distilbert-squad',
    'yolo11-fish-detector-grayscale',
    'fire-smoke-detection',
    'yolo11s-ball',
    'rocket-detect-nasaspaceflight',
    'clip-reid-person',
)

EXPECTED_PHASE_NINE_KEYS = (
    'opencv-person-reid-youtu',
    'osnet-x1-0',
    'melotts-zh-en',
    'mms-tts-eng',
    'vibevoice-realtime',
    'fun-asr-nano',
    'moonshine-tiny',
    'moss-transcribe-diarize-0p9b',
    'paraformer-zh',
)

EXPECTED_PHASE_TEN_KEYS = (
    'sensevoice-small',
    'sensevoice-small-onnx',
    'detr-resnet-50',
    'rf-detr-medium',
    'yolo-master-esmoe-n',
    'yolo-master-esmoe-s',
    'yolo-master-v01-n',
    'yolo26n',
    'yolo26s',
)

_ZERO_LATER_WORKBENCHES = {
    "image_inpainting": 0,
    "image_classification": 0,
    "multimodal_grounding": 0,
    "body_pose": 0,
    "squat_counting": 0,
    "instance_segmentation": 0,
    "person_reid": 0,
    "hand_pose": 0,
    "industrial_diagnosis": 0,
    "document_ocr": 0,
    "text_nlp": 0,
    "speech_asr": 0,
    "speech_tts": 0,
    "talking_head": 0,
}


def test_phase_one_scenarios_are_unique_and_in_document_order():
    scenarios = list_scenarios(phase=1)

    assert PHASE_ONE_KEYS == EXPECTED_PHASE_ONE_KEYS
    assert tuple(item["modelKey"] for item in scenarios) == EXPECTED_PHASE_ONE_KEYS
    assert len(scenarios) == len(set(item["modelKey"] for item in scenarios)) == 9


def test_phase_two_scenarios_are_unique_and_in_document_order():
    scenarios = list_scenarios(phase=2)

    assert PHASE_TWO_KEYS == EXPECTED_PHASE_TWO_KEYS
    assert tuple(item["modelKey"] for item in scenarios) == EXPECTED_PHASE_TWO_KEYS
    assert len(scenarios) == len(set(item["modelKey"] for item in scenarios)) == 9


def test_phase_three_scenarios_are_unique_and_in_document_order():
    scenarios = list_scenarios(phase=3)

    assert PHASE_THREE_KEYS == EXPECTED_PHASE_THREE_KEYS
    assert tuple(item["modelKey"] for item in scenarios) == EXPECTED_PHASE_THREE_KEYS
    assert len(scenarios) == len(set(item["modelKey"] for item in scenarios)) == 9



def test_phase_four_through_ten_scenarios_are_unique_and_in_document_order():
    expected = {
        4: (PHASE_FOUR_KEYS, EXPECTED_PHASE_FOUR_KEYS),
        5: (PHASE_FIVE_KEYS, EXPECTED_PHASE_FIVE_KEYS),
        6: (PHASE_SIX_KEYS, EXPECTED_PHASE_SIX_KEYS),
        7: (PHASE_SEVEN_KEYS, EXPECTED_PHASE_SEVEN_KEYS),
        8: (PHASE_EIGHT_KEYS, EXPECTED_PHASE_EIGHT_KEYS),
        9: (PHASE_NINE_KEYS, EXPECTED_PHASE_NINE_KEYS),
        10: (PHASE_TEN_KEYS, EXPECTED_PHASE_TEN_KEYS),
    }
    for phase, (const_keys, expected_keys) in expected.items():
        scenarios = list_scenarios(phase=phase)
        assert const_keys == expected_keys
        assert tuple(item["modelKey"] for item in scenarios) == expected_keys
        assert len(scenarios) == len(set(item["modelKey"] for item in scenarios)) == 9


def test_full_catalog_covers_ninety_models():
    scenarios = list_scenarios()
    assert len(scenarios) == 90
    assert len({item["modelKey"] for item in scenarios}) == 90
    assert [item["order"] for item in scenarios] == list(range(1, 91))

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
        "plate_pose": 0,
        "face_recognition": 0,
        "object_detection": 0,
        **_ZERO_LATER_WORKBENCHES,
    }


def test_phase_two_workbench_distribution_matches_supported_capabilities():
    scenarios = list_scenarios(phase=2)
    counts = {workbench: 0 for workbench in WORKBENCH_TYPES}
    for scenario in scenarios:
        counts[scenario["workbenchType"]] += 1

    assert counts == {
        "segmentation": 0,
        "vehicle_reid": 0,
        "plate_detection": 4,
        "obb_detection": 0,
        "plate_pose": 1,
        "face_recognition": 3,
        "object_detection": 1,
        **_ZERO_LATER_WORKBENCHES,
    }


def test_phase_three_workbench_distribution_matches_supported_capabilities():
    scenarios = list_scenarios(phase=3)
    counts = {workbench: 0 for workbench in WORKBENCH_TYPES}
    for scenario in scenarios:
        counts[scenario["workbenchType"]] += 1

    assert counts == {
        "segmentation": 0,
        "vehicle_reid": 0,
        "plate_detection": 0,
        "obb_detection": 0,
        "plate_pose": 0,
        "face_recognition": 0,
        "object_detection": 0,
        "image_inpainting": 1,
        "image_classification": 3,
        "multimodal_grounding": 1,
        "body_pose": 4,
        "squat_counting": 0,
        "instance_segmentation": 0,
        "person_reid": 0,
        "hand_pose": 0,
        "industrial_diagnosis": 0,
        "document_ocr": 0,
        "text_nlp": 0,
        "speech_asr": 0,
        "speech_tts": 0,
        "talking_head": 0,
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
        "adapter",
    )

    for scenario in list_scenarios(phase=1):
        for field in required_fields:
            assert scenario[field], f"{scenario['modelKey']} is missing {field}"
        assert scenario["published"] is True
        assert scenario["apiEnabled"] is True


def test_each_phase_two_scenario_has_complete_user_facing_metadata():
    required_fields = (
        "project",
        "workflow",
        "outputs",
        "metrics",
        "risks",
        "defaults",
        "input",
        "apiPath",
        "adapter",
    )

    for scenario in list_scenarios(phase=2):
        for field in required_fields:
            assert scenario[field], f"{scenario['modelKey']} is missing {field}"
        assert scenario["published"] is True
        assert scenario["apiEnabled"] is True
        assert scenario["phase"] == 2


def test_each_phase_three_scenario_has_complete_user_facing_metadata():
    required_fields = (
        "project",
        "workflow",
        "outputs",
        "metrics",
        "risks",
        "defaults",
        "input",
        "apiPath",
        "adapter",
    )

    for scenario in list_scenarios(phase=3):
        for field in required_fields:
            assert scenario[field], f"{scenario['modelKey']} is missing {field}"
        assert scenario["published"] is True
        assert scenario["apiEnabled"] is True
        assert scenario["phase"] == 3




def test_each_later_phase_scenario_has_complete_user_facing_metadata():
    required_fields = (
        "project",
        "workflow",
        "outputs",
        "metrics",
        "risks",
        "defaults",
        "input",
        "apiPath",
        "adapter",
    )
    for phase in range(4, 11):
        for scenario in list_scenarios(phase=phase):
            for field in required_fields:
                assert scenario[field] is not None and (scenario[field] != "" or field == "defaults"), (
                    f"{scenario['modelKey']} is missing {field}"
                )
            assert scenario["published"] is True
            assert scenario["apiEnabled"] is True
            assert scenario["phase"] == phase


def test_registry_exposes_the_callable_open_api_inference_paths():
    assert [item["apiPath"] for item in list_scenarios(phase=1)] == [
        "/openapi/v1/model-scenarios/efficient-sam/infer",
        "/openapi/v1/model-scenarios/mobile-sam/infer",
        "/openapi/v1/model-scenarios/clip-reid-vehicle/infer",
        "/openapi/v1/model-scenarios/keremberke-yolov5m-license-plate/infer",
        "/openapi/v1/model-scenarios/keremberke-yolov5n-license-plate/infer",
        "/openapi/v1/model-scenarios/transreid-vehicle/infer",
        "/openapi/v1/model-scenarios/vehicle-vit-reid/infer",
        "/openapi/v1/model-scenarios/yolo26n-obb/infer",
        "/openapi/v1/model-scenarios/yolo26n-p2-plate/infer",
    ]
    assert [item["apiPath"] for item in list_scenarios(phase=2)] == [
        "/openapi/v1/model-scenarios/yolo26n-plate/infer",
        "/openapi/v1/model-scenarios/yolo26s-plate-pose/infer",
        "/openapi/v1/model-scenarios/yolov11-license-plate-n/infer",
        "/openapi/v1/model-scenarios/yolov11-license-plate-s/infer",
        "/openapi/v1/model-scenarios/yolov8-license-plate/infer",
        "/openapi/v1/model-scenarios/insightface-buffalo-l/infer",
        "/openapi/v1/model-scenarios/insightface-buffalo-s/infer",
        "/openapi/v1/model-scenarios/opencv-yunet-sface/infer",
        "/openapi/v1/model-scenarios/brain-tumor-yolo-opennoor/infer",
    ]
    assert [item["apiPath"] for item in list_scenarios(phase=3)] == [
        "/openapi/v1/model-scenarios/inpainting-lama/infer",
        "/openapi/v1/model-scenarios/mobilenet-v2/infer",
        "/openapi/v1/model-scenarios/vit-base/infer",
        "/openapi/v1/model-scenarios/yolo-master-cls-n/infer",
        "/openapi/v1/model-scenarios/vlm-fo1-3b/infer",
        "/openapi/v1/model-scenarios/dwpose-m/infer",
        "/openapi/v1/model-scenarios/rtmo-m/infer",
        "/openapi/v1/model-scenarios/rtmo-s/infer",
        "/openapi/v1/model-scenarios/rtmpose-m/infer",
    ]


def test_image_inputs_use_the_independent_scenario_resource_policy():
    max_size_mb = Config.SCENARIO_MAX_IMAGE_BYTES // (1024 * 1024)
    non_image = {"text_nlp", "speech_asr", "speech_tts", "talking_head"}

    for scenario in list_scenarios():
        if scenario["workbenchType"] in non_image:
            continue
        assert ".webp" in scenario["input"]["formats"]
        assert scenario["input"]["maxSizeMb"] == max_size_mb
        assert scenario["input"]["maxPixels"] == Config.SCENARIO_MAX_PIXELS

    for key in ("efficient-sam", "mobile-sam"):
        assert get_scenario(key)["input"]["maxPrompts"] > 0
    for key in ("clip-reid-vehicle", "transreid-vehicle", "vehicle-vit-reid"):
        assert get_scenario(key)["input"]["maxGalleryImages"] == Config.SCENARIO_MAX_GALLERY_IMAGES
    for key in ("clip-reid-person", "opencv-person-reid-youtu", "osnet-x1-0"):
        assert get_scenario(key)["input"]["maxGalleryImages"] == Config.SCENARIO_MAX_GALLERY_IMAGES
    assert get_scenario("bert-ner")["input"]["text"] is True
    assert ".wav" in get_scenario("paraformer-zh")["input"]["formats"]


def test_segmentation_registry_does_not_advertise_an_ignored_confidence_threshold():
    for key in ("efficient-sam", "mobile-sam"):
        scenario = get_scenario(key)
        assert "conf" not in scenario["defaults"]


def test_unknown_model_key_has_no_scenario():
    assert get_scenario("not-a-registered-model") is None


def test_returned_scenarios_are_defensive_copies():
    listed = list_scenarios(phase=1)
    listed[0]["defaults"]["precision"] = "mutated"
    listed[0]["input"]["formats"].append(".mutated")

    retrieved = get_scenario("efficient-sam")

    assert retrieved["defaults"]["precision"] == "fp32"
    assert ".mutated" not in retrieved["input"]["formats"]


def test_same_task_models_are_merged_into_scenario_groups():
    from services.model_scenarios import (
        SCENARIO_GROUP_KEYS,
        list_scenario_groups,
        resolve_group_key,
    )

    groups = list_scenario_groups()
    assert SCENARIO_GROUP_KEYS == tuple(item["groupKey"] for item in groups)
    assert len(groups) == 40

    plate = next(item for item in groups if item["groupKey"] == "plate-detection")
    assert len(plate["models"]) == 8
    assert "sec-plate-yolov8" in {item["modelKey"] for item in plate["models"]}
    assert "yolo26s-plate-pose" not in {item["modelKey"] for item in plate["models"]}

    pose = next(item for item in groups if item["groupKey"] == "plate-pose")
    assert [item["modelKey"] for item in pose["models"]] == ["yolo26s-plate-pose"]

    classify = next(item for item in groups if item["groupKey"] == "image-classification")
    assert [item["modelKey"] for item in classify["models"]] == [
        "mobilenet-v2", "vit-base", "yolo-master-cls-n",
    ]
    body = next(item for item in groups if item["groupKey"] == "body-pose")
    squat = next(item for item in groups if item["groupKey"] == "squat-counting")
    assert squat["workbenchType"] == "squat_counting"
    assert squat["defaultModelKey"] == "rtmo-m"
    assert squat["modelKeys"] == ("rtmo-m", "rtmo-s", "rtmpose-m", "yolo-master-pose-n", "yolo11n-pose", "yolo26n-pose")
    assert squat["input"]["modes"] == ("video", "local_camera", "network_camera")
    assert [item["modelKey"] for item in body["models"]] == [
        "dwpose-m", "rtmo-m", "rtmo-s", "rtmpose-m",
        "yolo-master-pose-n", "yolo11n-pose", "yolo26n-pose",
    ]
    obb = next(item for item in groups if item["groupKey"] == "obb-detection")
    assert [item["modelKey"] for item in obb["models"]] == ["yolo26n-obb", "yolo-master-obb-n"]
    general = next(item for item in groups if item["groupKey"] == "general-detection")
    assert len(general["models"]) == 8

    assert resolve_group_key("efficient-sam") == "interactive-segmentation"
    assert resolve_group_key("plate-detection") == "plate-detection"
    assert resolve_group_key("yolo26s-plate-pose") == "plate-pose"
    assert resolve_group_key("inpainting-lama") == "image-inpainting"
    assert resolve_group_key("vlm-fo1-3b") == "multimodal-grounding"
    assert resolve_group_key("rtmo-s") == "body-pose"
    assert resolve_group_key("omdet-turbo-swin-tiny") == "open-vocab-detection"
    assert resolve_group_key("paraformer-zh") == "speech-recognition"
