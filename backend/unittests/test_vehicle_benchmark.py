import numpy as np

from scripts.benchmark_vehicle_reid import content_rect, retrieval_metrics


def test_misses_stay_in_retrieval_denominator():
    a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    result = retrieval_metrics([a, None], [a, b], 0.8, 0.04)
    assert result["pairs"] == 2
    assert result["rank1_left_to_right"] == 1
    assert result["accepted_correct"] == 1


def test_identical_embeddings_are_not_perfect_recognition():
    a = np.array([1.0, 0.0])
    result = retrieval_metrics([a, a], [a, a], 0.8, 0.04)
    assert result["accepted_correct"] == 0
    assert result["negative_pairs_above_threshold"] == 2


def test_video_view_excludes_player_controls_and_black_bars():
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    image[:5] = 255
    image[30:80] = 100
    image[95:] = 255
    assert content_rect(image, 0, 100) == [0, 30, 100, 80]
