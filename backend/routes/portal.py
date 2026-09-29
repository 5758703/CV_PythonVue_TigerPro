"""门户公开接口：无需登录，仅返回匿名聚合统计。"""
from flask import Blueprint, jsonify
from sqlalchemy import func

from extensions import db
from models import AiModel, TrainingDataset, TrainingJob

portal_bp = Blueprint("portal", __name__, url_prefix="/api/portal")

# 与后台 Dashboard 对齐的任务中文名（未知 task 原样返回）
_TASK_LABELS = {
    "object-detection": "目标检测",
    "image-classification": "图像分类",
    "pose-estimation": "姿态估计",
    "face-recognition": "人脸识别",
    "object-tracking": "目标追踪",
    "text-classification": "文本分类",
    "token-classification": "实体识别",
    "question-answering": "智能问答",
    "text-generation": "文本生成",
    "automatic-speech-recognition": "语音识别",
    "text-to-speech": "文本转语音",
    "image-segmentation": "图像分割",
    "optical-character-recognition": "文字识别",
    "table-recognition": "表格识别",
}


def _task_label(task: str) -> str:
    return _TASK_LABELS.get(task or "", task or "其他")


def _count(model) -> int:
    return db.session.query(func.count(model.id)).scalar() or 0


@portal_bp.get("/summary")
def portal_summary():
    """门户首页聚合数据（公开只读）。"""
    enabled = AiModel.status == "0"
    task_rows = (
        db.session.query(AiModel.task, func.count(AiModel.id))
        .filter(enabled).group_by(AiModel.task).all()
    )
    category_rows = (
        db.session.query(AiModel.category, func.count(AiModel.id))
        .filter(enabled).group_by(AiModel.category).all()
    )
    model_total = sum(count for _task, count in task_rows)
    ready_count = (
        AiModel.query.filter(enabled, AiModel.file_path.isnot(None), AiModel.file_path != "")
        .count()
    )
    task_kinds = sum(1 for task, _count in task_rows if task)
    category_kinds = sum(1 for category, _count in category_rows if category)

    dataset_total = _count(TrainingDataset)
    job_total = _count(TrainingJob)
    jobs_running = (
        TrainingJob.query.filter(TrainingJob.status.in_(("pending", "running", "cancelling")))
        .count()
    )

    task_counter = {}
    for task, count in task_rows:
        label = _task_label(task)
        task_counter[label] = task_counter.get(label, 0) + count
    category_counter = {}
    for category, count in category_rows:
        label = category or "未分类"
        category_counter[label] = category_counter.get(label, 0) + count

    task_distribution = [
        {"name": name, "value": count}
        for name, count in sorted(task_counter.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]
    category_ranking = [
        {"name": name, "value": count}
        for name, count in sorted(category_counter.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    return jsonify(
        code=0,
        message="ok",
        data={
            "modelTotal": model_total,
            "readyCount": ready_count,
            "datasetTotal": dataset_total,
            "jobTotal": job_total,
            "jobsRunning": jobs_running,
            "taskKinds": task_kinds,
            "categoryKinds": category_kinds,
            "taskDistribution": task_distribution,
            "categoryRanking": category_ranking,
        },
    )
