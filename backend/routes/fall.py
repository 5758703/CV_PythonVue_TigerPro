"""跌倒检测与报警 /api/ai/fall。

姿态关键点 -> person 检测框(+trackId) -> fall_detection 规则判定 -> 合成 fall 框 + 告警事件。
"""
import json
import os
import threading
import time
import uuid

from flask import Blueprint, current_app, jsonify, request, send_file
from werkzeug.utils import secure_filename

from extensions import db
from models import AiModel
from models.alert import AlertEvent
from security import permission_required
from services.alert_engine import (
    active_overlay_style,
    evaluate_rules,
    fall_detections,
    reset_runtime,
)
from services.alert_rules_query import (
    load_enabled_alert_rules,
    parse_rule_keys,
    serialize_alert_rules_payload,
)

fall_bp = Blueprint("fall", __name__, url_prefix="/api/ai/fall")

# 视频异步任务进度表：jobId -> {status, processed, total, stats, error}（同蓝图自持，
# 范式照 routes/absence.py 的 _video_jobs / _video_jobs_lock）
_video_jobs: dict = {}
_video_jobs_lock = threading.Lock()


def _form_float(name, default):
    try:
        return float(request.form.get(name, default))
    except (TypeError, ValueError):
        return default


@fall_bp.post("/detect")
@permission_required("ai:fall:list")
def detect():
    """单帧跌倒检测：姿态关键点 + 四指标规则判定 + 合成 fall 框 + 告警事件。

    表单：file 图片；modelId 姿态模型；conf 姿态置信度(默认0.25)；
    sourceKey 来源标识(默认 fall-live)；sourceType(默认 camera)；
    ruleKeys 规则过滤(不传=全部启用规则，传 [] =不评估)；persist 是否落事件(默认1)；
    draw 是否返回骨架图 base64(默认0)。
    """
    from routes.ai_model import _resolve_pose_runtime
    from services.fall_detect import (
        assign_track_ids,
        build_person_detections,
        fall_track_params,
        nms_person_detections,
    )

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到图片"), 400
    try:
        mid = int(request.form.get("modelId", 0))
    except (TypeError, ValueError):
        mid = 0
    if not mid:
        return jsonify(code=400, message="缺少 modelId"), 400
    m = AiModel.query.get(mid)
    if m is None:
        return jsonify(code=404, message="模型不存在"), 404
    try:
        lib, abs_path, _task = _resolve_pose_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    conf = _form_float("conf", 0.25)
    draw = (request.form.get("draw") or "0") in ("1", "true", "True")
    source_key = (request.form.get("sourceKey") or "fall-live").strip() or "fall-live"
    source_type = (request.form.get("sourceType") or "camera").strip() or "camera"
    persist = (request.form.get("persist") or "1") in ("1", "true", "True")

    raw_keys = request.form.get("ruleKeys")
    rule_keys = parse_rule_keys(raw_keys) if raw_keys is not None else None

    try:
        image_bytes = file.read()
        if lib == "rtmlib":
            from inference import estimate_pose_rtmlib
            result = estimate_pose_rtmlib(
                m.model_key or "rtmo-s", abs_path, image_bytes, conf=conf, draw=draw)
        else:
            from inference import estimate_pose
            result = estimate_pose(abs_path, image_bytes, conf=conf, draw=draw)
    except FileNotFoundError as e:
        return jsonify(code=400, message=str(e)), 400
    except Exception as e:  # noqa: BLE001
        return jsonify(code=500, message=f"姿态估计失败：{e}"), 500

    width = result.get("width")
    height = result.get("height")
    rules = load_enabled_alert_rules(rule_keys)
    kp_min_conf, track_max_age = fall_track_params(rules)
    detections = build_person_detections(
        result.get("persons") or [], width, height, kp_min_conf)
    detections = nms_person_detections(detections)
    assign_track_ids(
        detections, source_key, max_age=track_max_age, kp_min_conf=kp_min_conf)

    data = {
        "persons": result.get("persons") or [],
        "count": result.get("count", 0),
        "width": width,
        "height": height,
        "keypointCount": result.get("keypointCount", 17),
        "imageBase64": result.get("imageBase64"),
        "detections": detections,
        "triggered": [],
        "overlay": None,
    }
    if not rules:
        return jsonify(code=0, message="无匹配的启用规则", data=data)

    frame_token = str(uuid.uuid4())

    def _persist(rule, title, message, detail):
        ev = AlertEvent(
            rule_id=rule.id,
            rule_key=rule.rule_key,
            rule_name=rule.name,
            severity=rule.severity,
            title=title,
            message=message,
            source_type=source_type,
            source_key=source_key,
            model_id=mid,
            payload_json=json.dumps(detail, ensure_ascii=False),
            status="0",
        )
        db.session.add(ev)
        db.session.commit()
        return ev.to_dict()

    # source_type 透传给引擎：图片模式（"image"）豁免跌倒判定的冷启动误报自锁
    # 门控（见 alert_engine._eval_fall_detection）。三处调用都要传，保证同一帧
    # 内 evaluate_rules / fall_detections / active_overlay_style 行为一致——
    # 后两者虽然会命中 frame_token memo 直接复用缓存，但参数仍应一致，避免
    # 未来 memo 逻辑变化时因参数不一致而产生难以复现的偏差。
    triggered = evaluate_rules(
        rules,
        detections,
        source_key,
        persist_event=_persist if persist else None,
        frame_width=width,
        frame_height=height,
        frame_token=frame_token,
        source_type=source_type,
    )
    boxes = fall_detections(
        rules,
        detections,
        source_key=source_key,
        frame_width=width,
        frame_height=height,
        frame_token=frame_token,
        source_type=source_type,
    )
    overlay = active_overlay_style(
        rules,
        detections,
        video=False,
        frame_width=width,
        frame_height=height,
        source_key=source_key,
        frame_token=frame_token,
        source_type=source_type,
    )
    data["detections"] = detections + boxes
    data["triggered"] = triggered
    data["overlay"] = overlay
    return jsonify(code=0, message="ok", data=data)


@fall_bp.post("/reset-runtime")
@permission_required("ai:fall:list")
def reset_runtime_api():
    """停止检测时清连续帧/冷却/跌倒跟踪状态。"""
    data = request.get_json(silent=True) or {}
    source_key = (data.get("sourceKey") or "").strip() or None
    reset_runtime(source_key)
    return jsonify(code=0, message="已重置")


def _fall_video_worker(job_id, library, model_key, abs_path, src_path, out_path, out_name,
                       conf, rules):
    """后台线程：逐帧跌倒检测视频，按帧上报进度，完成写结果。

    rules 是 serialize_alert_rules_payload() 序列化后的 dict 列表（不是 ORM
    AlertRule 实例）——请求上下文销毁后线程仍要长时间访问 r.config()，避免
    ORM 实例跨线程可能因 session 变化而 DetachedInstanceError。无启用规则时
    rules 为空列表，仍正常处理视频，只是不产出 fall 框与事件（inference.
    fall_video 内部对空规则列表天然安全）。
    """
    from inference import fall_video

    source_key = f"fall-video-{job_id}"

    def cb(processed, total):
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j["processed"] = processed
                j["total"] = total

    try:
        stats = fall_video(
            library, model_key, abs_path, src_path, out_path,
            rules=rules, source_key=source_key, conf=conf, progress_cb=cb,
        )
        stats["output"] = out_name
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j.update(status="done", stats=stats,
                        processed=stats["frames"], total=stats["frames"])
    except Exception as e:  # noqa: BLE001
        with _video_jobs_lock:
            j = _video_jobs.get(job_id)
            if j:
                j.update(status="error", error=str(e))
    finally:
        if os.path.isfile(src_path):
            try:
                os.remove(src_path)  # 处理完删除上传源
            except OSError:
                pass


@fall_bp.post("/detect-video")
@permission_required("ai:fall:list")
def detect_video():
    """跌倒检测（视频）：异步逐帧处理，产出带标注的结果视频 + 触发时间点列表。

    表单：file 视频；modelId 姿态模型；conf 姿态置信度(默认0.25)；
    ruleKeys 规则过滤(不传=全部启用规则，传 [] =不评估)。
    立即返回 jobId，前端轮询 /video-progress/<jobId> 获取进度与结果。
    """
    from routes.ai_model import _resolve_pose_runtime

    file = request.files.get("file")
    if file is None or not file.filename:
        return jsonify(code=400, message="未接收到视频"), 400
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in current_app.config["VIDEO_ALLOWED_EXT"]:
        return jsonify(code=400, message="不支持的视频格式"), 400

    try:
        mid = int(request.form.get("modelId", 0))
    except (TypeError, ValueError):
        mid = 0
    if not mid:
        return jsonify(code=400, message="缺少 modelId"), 400
    m = AiModel.query.get(mid)
    if m is None:
        return jsonify(code=404, message="模型不存在"), 404
    try:
        lib, abs_path, _task = _resolve_pose_runtime(m)
    except ValueError as e:
        return jsonify(code=400, message=str(e)), 400

    conf = _form_float("conf", 0.25)
    raw_keys = request.form.get("ruleKeys")
    rule_keys = parse_rule_keys(raw_keys) if raw_keys is not None else None
    # ORM 实例（AlertRule）不能带过请求上下文边界交给后台线程：请求上下文销毁后
    # 若任何代码路径对 session 做过 commit，实例会 expire，worker 里再访问
    # r.config() 会抛 DetachedInstanceError（被下面的宽 except 吞成晦涩 job
    # error）。序列化成纯 dict 再传线程，照 ai_model.py:1745/vehicle.py:573 的
    # 既有范式；services.alert_engine 三个引擎函数与 fall_track_params 均已
    # 兼容 dict（ruleType/config 驼峰键）。
    rules_payload = serialize_alert_rules_payload(load_enabled_alert_rules(rule_keys))

    video_folder = current_app.config["VIDEO_FOLDER"]
    out_folder = current_app.config["OUTPUT_FOLDER"]
    os.makedirs(video_folder, exist_ok=True)
    os.makedirs(out_folder, exist_ok=True)

    ts = int(time.time())
    base = secure_filename(os.path.splitext(file.filename)[0]) or "video"
    src_path = os.path.join(video_folder, f"{base}_{ts}{ext}")
    out_name = f"{base}_{ts}_fall.mp4"
    out_path = os.path.join(out_folder, out_name)
    file.save(src_path)

    job_id = uuid.uuid4().hex
    with _video_jobs_lock:
        _video_jobs[job_id] = {
            "status": "running", "processed": 0, "total": 0, "stats": None, "error": None,
        }
    threading.Thread(
        target=_fall_video_worker,
        args=(job_id, lib, m.model_key or "", abs_path, src_path, out_path, out_name,
              conf, rules_payload),
        daemon=True,
    ).start()
    return jsonify(code=0, message="任务已启动", data={"jobId": job_id})


@fall_bp.get("/video-progress/<job_id>")
@permission_required("ai:fall:list")
def video_progress(job_id):
    """查询跌倒检测视频任务进度。"""
    with _video_jobs_lock:
        j = _video_jobs.get(job_id)
        if j is None:
            return jsonify(code=404, message="任务不存在或已过期"), 404
        data = dict(j)
    # 进度轮询统一 HTTP 200，避免前端 axios 将业务失败误判为 Network Error
    if data["status"] == "error":
        return jsonify(code=0, message=data.get("error") or "视频处理失败", data=data)
    return jsonify(code=0, data=data)


@fall_bp.get("/output/<path:name>")
@permission_required("ai:fall:list")
def output_video(name):
    """下载跌倒检测结果视频。"""
    if not name.endswith("_fall.mp4"):
        return jsonify(code=400, message="非法文件名"), 400
    safe_name = secure_filename(name)
    if not safe_name or safe_name != name:
        return jsonify(code=400, message="非法文件名"), 400
    path = os.path.join(current_app.config["OUTPUT_FOLDER"], safe_name)
    if not os.path.isfile(path):
        return jsonify(code=404, message="文件不存在"), 404
    return send_file(path, mimetype="video/mp4", conditional=True)
