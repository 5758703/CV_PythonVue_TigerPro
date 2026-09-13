"""Phase-one model scenario metadata.

This module is the single source of business metadata for model scenario
management and presentation. Runtime readiness deliberately belongs to the
service layer that can inspect registered models and installed dependencies.
"""

from copy import deepcopy

from config import Config


PHASE_ONE_KEYS = (
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

WORKBENCH_TYPES = (
    "segmentation",
    "vehicle_reid",
    "plate_detection",
    "obb_detection",
)

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
_MAX_UPLOAD_SIZE_MB = Config.MAX_CONTENT_LENGTH // (1024 * 1024)
_IMAGE_INPUT = {"formats": list(_IMAGE_EXTENSIONS), "maxSizeMb": _MAX_UPLOAD_SIZE_MB}
_SEGMENT_INPUT = {
    **_IMAGE_INPUT,
    "prompts": ["points", "labels", "box"],
}
_REID_INPUT = {
    "formats": list(_IMAGE_EXTENSIONS),
    "query": "single vehicle image",
    "gallery": "one or more vehicle images",
    "maxSizeMb": _MAX_UPLOAD_SIZE_MB,
}

_SCENARIOS = (
    {
        "phase": 1,
        "order": 1,
        "modelKey": "efficient-sam",
        "name": "EfficientSAM-Ti（OpenCV）",
        "category": "工业视觉",
        "ability": "interactive-segmentation",
        "workbenchType": "segmentation",
        "project": "工业缺陷精细轮廓提取",
        "description": "以点选或框选提示提取缺陷和目标的精细轮廓。",
        "workflow": "检测或用户提示生成 mask，计算面积和占比，并可联动 LaMa 修复或质检流程。",
        "outputs": "像素级 mask、面积、占比和叠加预览，可导出标注或缺陷统计。",
        "metrics": "IoU、Dice、边界误差和交互点击次数。",
        "risks": "通用分割不等同于行业缺陷分类，生产前须以行业样本校验。",
        "defaults": {"precision": "balanced", "conf": 0.5},
        "input": _SEGMENT_INPUT,
        "route": "/ai/scenarios/efficient-sam",
        "apiPath": "/api/open/v1/model-scenarios/efficient-sam",
    },
    {
        "phase": 1,
        "order": 2,
        "modelKey": "mobile-sam",
        "name": "MobileSAM 交互分割",
        "category": "工业视觉",
        "ability": "interactive-segmentation",
        "workbenchType": "segmentation",
        "project": "边缘端目标快速标注",
        "description": "轻量交互分割，支持点击、框选和全自动分割，适合边缘端标注。",
        "workflow": "检测或用户提示生成 mask，计算面积和占比，并可联动 LaMa 修复或质检流程。",
        "outputs": "像素级 mask、面积、占比和叠加预览，可导出标注或缺陷统计。",
        "metrics": "IoU、Dice、边界误差和交互点击次数。",
        "risks": "通用分割不等同于行业缺陷分类，生产前须以行业样本校验。",
        "defaults": {"precision": "fast", "conf": 0.5},
        "input": _SEGMENT_INPUT,
        "route": "/ai/scenarios/mobile-sam",
        "apiPath": "/api/open/v1/model-scenarios/mobile-sam",
    },
    {
        "phase": 1,
        "order": 3,
        "modelKey": "clip-reid-vehicle",
        "name": "CLIP-ReID Vehicle",
        "category": "交通车辆",
        "ability": "vehicle-reid",
        "workbenchType": "vehicle_reid",
        "project": "园区车辆跨镜轨迹串联",
        "description": "用车辆外观特征完成跨摄像头轨迹关联。",
        "workflow": "检测和单镜跟踪生成 tracklet，提取车辆特征后结合拓扑、时间窗、车牌和类别关联。",
        "outputs": "global_id、相似度、跨镜时间线和最佳截图，用于轨迹检索与滞留分析。",
        "metrics": "跨镜 top-1、IDF1、误合并率和未知目标拒识率。",
        "risks": "ReID 不是检测器，必须结合检测、跟踪、质量筛选和拓扑约束。",
        "defaults": {"threshold": 0.7},
        "input": _REID_INPUT,
        "route": "/ai/scenarios/clip-reid-vehicle",
        "apiPath": "/api/open/v1/model-scenarios/clip-reid-vehicle",
    },
    {
        "phase": 1,
        "order": 4,
        "modelKey": "keremberke-yolov5m-license-plate",
        "name": "车牌检测 YOLOv5m（keremberke）",
        "category": "交通车辆",
        "ability": "plate-detection",
        "workbenchType": "plate_detection",
        "project": "高精度出入口号牌采集",
        "description": "高精度车牌定位，适合出入口号牌采集。",
        "workflow": "通用车辆模型裁剪车辆 ROI 后定位车牌；姿态或 OBB 结果可透视矫正后交给 OCR。",
        "outputs": "车牌框、矫正图、可选 OCR 文本与置信度，并可绑定 track_id 触发告警。",
        "metrics": "按昼夜和近中远距离的车牌完整识别率验收，而非仅检测 mAP。",
        "risks": "定位模型不能直接读取字符；模糊、反光和侧拍场景应允许多帧投票。",
        "defaults": {"conf": 0.5, "imgsz": 640},
        "input": _IMAGE_INPUT,
        "route": "/ai/scenarios/keremberke-yolov5m-license-plate",
        "apiPath": "/api/open/v1/model-scenarios/keremberke-yolov5m-license-plate",
    },
    {
        "phase": 1,
        "order": 5,
        "modelKey": "keremberke-yolov5n-license-plate",
        "name": "车牌检测 YOLOv5n（keremberke）",
        "category": "交通车辆",
        "ability": "plate-detection",
        "workbenchType": "plate_detection",
        "project": "边缘端实时号牌采集",
        "description": "轻量车牌定位，面向边缘端实时采集。",
        "workflow": "通用车辆模型裁剪车辆 ROI 后定位车牌；姿态或 OBB 结果可透视矫正后交给 OCR。",
        "outputs": "车牌框、矫正图、可选 OCR 文本与置信度，并可绑定 track_id 触发告警。",
        "metrics": "按昼夜和近中远距离的车牌完整识别率验收，而非仅检测 mAP。",
        "risks": "定位模型不能直接读取字符；模糊、反光和侧拍场景应允许多帧投票。",
        "defaults": {"conf": 0.5, "imgsz": 640},
        "input": _IMAGE_INPUT,
        "route": "/ai/scenarios/keremberke-yolov5n-license-plate",
        "apiPath": "/api/open/v1/model-scenarios/keremberke-yolov5n-license-plate",
    },
    {
        "phase": 1,
        "order": 6,
        "modelKey": "transreid-vehicle",
        "name": "TransReID Vehicle",
        "category": "交通车辆",
        "ability": "vehicle-reid",
        "workbenchType": "vehicle_reid",
        "project": "复杂视角车辆跨镜关联",
        "description": "针对复杂视角的车辆外观特征关联。",
        "workflow": "检测和单镜跟踪生成 tracklet，提取车辆特征后结合拓扑、时间窗、车牌和类别关联。",
        "outputs": "global_id、相似度、跨镜时间线和最佳截图，用于轨迹检索与滞留分析。",
        "metrics": "跨镜 top-1、IDF1、误合并率和未知目标拒识率。",
        "risks": "ReID 不是检测器，必须结合检测、跟踪、质量筛选和拓扑约束。",
        "defaults": {"threshold": 0.7},
        "input": _REID_INPUT,
        "route": "/ai/scenarios/transreid-vehicle",
        "apiPath": "/api/open/v1/model-scenarios/transreid-vehicle",
    },
    {
        "phase": 1,
        "order": 7,
        "modelKey": "vehicle-vit-reid",
        "name": "Vehicle ViT ReID",
        "category": "交通车辆",
        "ability": "vehicle-reid",
        "workbenchType": "vehicle_reid",
        "project": "园区车辆视觉检索",
        "description": "以 ViT 车辆特征支持园区车辆视觉检索。",
        "workflow": "检测和单镜跟踪生成 tracklet，提取车辆特征后结合拓扑、时间窗、车牌和类别关联。",
        "outputs": "global_id、相似度、跨镜时间线和最佳截图，用于轨迹检索与滞留分析。",
        "metrics": "跨镜 top-1、IDF1、误合并率和未知目标拒识率。",
        "risks": "ReID 不是检测器，必须结合检测、跟踪、质量筛选和拓扑约束。",
        "defaults": {"threshold": 0.7},
        "input": _REID_INPUT,
        "route": "/ai/scenarios/vehicle-vit-reid",
        "apiPath": "/api/open/v1/model-scenarios/vehicle-vit-reid",
    },
    {
        "phase": 1,
        "order": 8,
        "modelKey": "yolo26n-obb",
        "name": "YOLO26n 旋转框 OBB",
        "category": "交通车辆",
        "ability": "obb",
        "workbenchType": "obb_detection",
        "project": "旋转目标与车牌方向检测",
        "description": "检测旋转目标并输出方向信息，可辅助车牌透视矫正。",
        "workflow": "图片、视频或摄像头帧进入模型并统一输出旋转框，再按区域、越线和持续时间组合业务事件。",
        "outputs": "四点坐标、角度、类别、置信度、track_id 和证据图，可供告警、统计或 OCR/ReID 使用。",
        "metrics": "场景 mAP、召回、误报/小时和 FPS，并建立困难负样本集。",
        "risks": "通用 COCO 权重只覆盖既定类别；行业目标须专训或使用开放词汇模型。",
        "defaults": {"conf": 0.5, "imgsz": 640},
        "input": _IMAGE_INPUT,
        "route": "/ai/scenarios/yolo26n-obb",
        "apiPath": "/api/open/v1/model-scenarios/yolo26n-obb",
    },
    {
        "phase": 1,
        "order": 9,
        "modelKey": "yolo26n-p2-plate",
        "name": "车牌检测 YOLO26n-P2（自训脚手架）",
        "category": "交通车辆",
        "ability": "plate-detection",
        "workbenchType": "plate_detection",
        "project": "小目标车牌专训验证",
        "description": "用于小目标车牌专训与部署验证。",
        "workflow": "通用车辆模型裁剪车辆 ROI 后定位车牌；姿态或 OBB 结果可透视矫正后交给 OCR。",
        "outputs": "车牌框、矫正图、可选 OCR 文本与置信度，并可绑定 track_id 触发告警。",
        "metrics": "按昼夜和近中远距离的车牌完整识别率验收，而非仅检测 mAP。",
        "risks": "定位模型不能直接读取字符；模糊、反光和侧拍场景应允许多帧投票。",
        "defaults": {"conf": 0.5, "imgsz": 640},
        "input": _IMAGE_INPUT,
        "route": "/ai/scenarios/yolo26n-p2-plate",
        "apiPath": "/api/open/v1/model-scenarios/yolo26n-p2-plate",
    },
)


def list_scenarios(phase: int | None = None) -> list[dict]:
    """Return scenario records in document order, optionally for one phase."""
    scenarios = _SCENARIOS if phase is None else tuple(item for item in _SCENARIOS if item["phase"] == phase)
    return deepcopy(list(scenarios))


def get_scenario(model_key: str) -> dict | None:
    """Return one scenario by its model key without exposing registry state."""
    for scenario in _SCENARIOS:
        if scenario["modelKey"] == model_key:
            return deepcopy(scenario)
    return None
