"""边缘 AI 视频分析引擎 · DAG 契约（Phase 0–3）。"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

NODE_TYPES: dict[str, dict[str, Any]] = {
    "source.rtsp": {
        "category": "source",
        "label": "RTSP / 摄像头源",
        "requiredConfig": ["cameraId"],
        "portsIn": [],
        "portsOut": ["frame"],
        "phase": 0,
        "color": "#409eff",
    },
    "detect.yolo": {
        "category": "detect",
        "label": "YOLO 检测（ONNX 优先）",
        "requiredConfig": [],
        "portsIn": ["frame"],
        "portsOut": ["frame"],
        "phase": 0,
        "color": "#67c23a",
    },
    "track.bytetrack": {
        "category": "track",
        "label": "ByteTrack 跟踪",
        "requiredConfig": [],
        "portsIn": ["frame"],
        "portsOut": ["frame"],
        "phase": 1,
        "color": "#e6a23c",
    },
    "logic.alert": {
        "category": "logic",
        "label": "告警规则",
        "requiredConfig": [],
        "portsIn": ["frame"],
        "portsOut": ["frame", "event"],
        "phase": 1,
        "color": "#f56c6c",
    },
    "logic.vlm_gate": {
        "category": "logic",
        "label": "VLM 门控确认",
        "requiredConfig": [],
        "portsIn": ["frame", "event"],
        "portsOut": ["event"],
        "phase": 2,
        "color": "#c45656",
    },
    "composite.mtmc": {
        "category": "composite",
        "label": "MTMC 跨镜复合",
        "requiredConfig": ["cameraIds"],
        "portsIn": [],
        "portsOut": ["event"],
        "phase": 3,
        "color": "#0d9488",
    },
    "sink.overlay": {
        "category": "sink",
        "label": "标注叠加输出",
        "requiredConfig": [],
        "portsIn": ["frame"],
        "portsOut": [],
        "phase": 0,
        "color": "#909399",
    },
    "sink.db": {
        "category": "sink",
        "label": "告警落库",
        "requiredConfig": [],
        "portsIn": ["event"],
        "portsOut": [],
        "phase": 1,
        "color": "#909399",
    },
    "sink.webhook": {
        "category": "sink",
        "label": "HTTP Webhook",
        "requiredConfig": ["url"],
        "portsIn": ["event"],
        "portsOut": [],
        "phase": 1,
        "color": "#909399",
    },
    "sink.mqtt": {
        "category": "sink",
        "label": "MQTT Publish",
        "requiredConfig": ["topic"],
        "portsIn": ["event"],
        "portsOut": [],
        "phase": 2,
        "color": "#b37feb",
    },
}

PHASE0_EXECUTABLE = frozenset({"source.rtsp", "detect.yolo", "sink.overlay"})
PHASE1_EXECUTABLE = PHASE0_EXECUTABLE | frozenset({
    "track.bytetrack",
    "logic.alert",
    "sink.db",
    "sink.webhook",
})
PHASE2_EXECUTABLE = PHASE1_EXECUTABLE | frozenset({
    "sink.mqtt",
    "logic.vlm_gate",
})
PHASE3_EXECUTABLE = PHASE2_EXECUTABLE | frozenset({
    "composite.mtmc",
})


def new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex[:16]}"


def make_frame_envelope(
    *,
    pipeline_id: str,
    run_id: str,
    camera_id: int,
    frame_seq: int,
    dets: list[dict] | None = None,
    tracks: dict | None = None,
    attrs: dict | None = None,
    metrics: dict | None = None,
    ts: float | None = None,
) -> dict:
    return {
        "pipelineId": str(pipeline_id),
        "runId": str(run_id),
        "cameraId": int(camera_id),
        "frameSeq": int(frame_seq),
        "ts": float(ts if ts is not None else time.time()),
        "dets": list(dets or []),
        "tracks": dict(tracks or {}),
        "attrs": dict(attrs or {}),
        "metrics": dict(metrics or {}),
    }


def make_event_envelope(
    *,
    event_type: str,
    pipeline_id: str,
    run_id: str,
    camera_id: int | None = None,
    rule_key: str | None = None,
    track_id: int | None = None,
    score: float | None = None,
    payload: dict | None = None,
    snapshot_url: str | None = None,
    ts: str | None = None,
) -> dict:
    from datetime import datetime, timezone

    return {
        "eventId": new_event_id(),
        "type": event_type,
        "pipelineId": str(pipeline_id),
        "runId": str(run_id),
        "cameraId": camera_id,
        "ruleKey": rule_key,
        "trackId": track_id,
        "score": score,
        "ts": ts or datetime.now(timezone.utc).isoformat(),
        "snapshotUrl": snapshot_url,
        "payload": dict(payload or {}),
    }


def _normalize_edges(edges: list) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for e in edges or []:
        if isinstance(e, (list, tuple)) and len(e) >= 2:
            out.append((str(e[0]), str(e[1])))
        elif isinstance(e, dict):
            out.append((str(e.get("from") or e.get("source")), str(e.get("to") or e.get("target"))))
        else:
            raise ValueError(f"非法 edge: {e!r}")
    return out


def dag_required_phase(dag: dict) -> int:
    """根据节点类型推断所需最低 Phase。"""
    nodes = dag.get("nodes") if isinstance(dag, dict) else None
    if not isinstance(nodes, list):
        return 1
    need = 0
    for n in nodes:
        if not isinstance(n, dict):
            continue
        ntype = str(n.get("type") or "")
        meta = NODE_TYPES.get(ntype) or {}
        need = max(need, int(meta.get("phase") or 0))
    return need


def _allowed_types(phase: int) -> frozenset:
    if phase <= 0:
        return PHASE0_EXECUTABLE
    if phase == 1:
        return PHASE1_EXECUTABLE
    if phase == 2:
        return PHASE2_EXECUTABLE
    return PHASE3_EXECUTABLE


def _parse_camera_ids(raw) -> list[int]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [int(x) for x in raw.split(",") if str(x).strip()]
    if isinstance(raw, (list, tuple)):
        return [int(x) for x in raw]
    return [int(raw)]


def validate_dag(dag: dict, *, phase0_only: bool | None = None, phase: int | None = None) -> dict:
    """校验 DAG。phase=0/1/2/3；未指定时按节点最大 phase 自动选择（至少 1）。"""
    if phase0_only is True and phase is None:
        phase = 0
    if phase is None:
        phase = max(1, dag_required_phase(dag) if isinstance(dag, dict) else 1)
    allowed = _allowed_types(int(phase))

    if not isinstance(dag, dict):
        raise ValueError("dag 必须为对象")
    nodes = dag.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("dag.nodes 不能为空")

    by_id: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict):
            raise ValueError("每个 node 必须为对象")
        nid = str(n.get("id") or "").strip()
        ntype = str(n.get("type") or "").strip()
        if not nid:
            raise ValueError("node.id 必填")
        if nid in by_id:
            raise ValueError(f"重复 node.id: {nid}")
        if ntype not in NODE_TYPES:
            raise ValueError(f"未知 node.type: {ntype}")
        if ntype not in allowed:
            raise ValueError(f"当前 Phase{phase} 暂不支持节点类型: {ntype}")
        cfg = n.get("config") if isinstance(n.get("config"), dict) else {}
        for key in NODE_TYPES[ntype].get("requiredConfig") or []:
            if key == "cameraIds":
                if not _parse_camera_ids(cfg.get("cameraIds")):
                    raise ValueError(f"节点 {nid} ({ntype}) 缺少 config.cameraIds")
            elif cfg.get(key) in (None, ""):
                raise ValueError(f"节点 {nid} ({ntype}) 缺少 config.{key}")
        by_id[nid] = {
            "id": nid,
            "type": ntype,
            "config": cfg,
            "position": n.get("position") if isinstance(n.get("position"), dict) else None,
        }

    edges = _normalize_edges(dag.get("edges") or [])
    for a, b in edges:
        if a not in by_id or b not in by_id:
            raise ValueError(f"edge 引用未知节点: {a} → {b}")

    out_adj: dict[str, list[str]] = {nid: [] for nid in by_id}
    for a, b in edges:
        out_adj[a].append(b)

    order = topological_order(by_id, out_adj)
    mtmc_ids = [nid for nid, n in by_id.items() if n["type"] == "composite.mtmc"]
    sources = [nid for nid, n in by_id.items() if n["type"].startswith("source.")]
    overlays = [nid for nid, n in by_id.items() if n["type"] == "sink.overlay"]
    detects = [nid for nid, n in by_id.items() if n["type"] == "detect.yolo"]
    webhook_ids = [nid for nid, n in by_id.items() if n["type"] == "sink.webhook"]
    db_ids = [nid for nid, n in by_id.items() if n["type"] == "sink.db"]
    mqtt_ids = [nid for nid, n in by_id.items() if n["type"] == "sink.mqtt"]

    if mtmc_ids:
        if sources or detects:
            raise ValueError("composite.mtmc 流水线请勿混用 source.rtsp / detect.yolo（请单独建经典图）")
        if len(mtmc_ids) != 1:
            raise ValueError("要求恰好 1 个 composite.mtmc 节点")
        cam_ids = _parse_camera_ids(by_id[mtmc_ids[0]]["config"].get("cameraIds"))
        if len(cam_ids) < 2:
            raise ValueError("composite.mtmc 至少需要 2 路 cameraIds")
        event_sinks = webhook_ids + db_ids + mqtt_ids
        if not event_sinks:
            raise ValueError("MTMC 复合图至少需要 1 个事件 Sink（db / webhook / mqtt）")
        # 边：mtmc → sinks
        reachable = set()
        stack = [mtmc_ids[0]]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(out_adj.get(cur) or [])
        if not any(s in reachable for s in event_sinks):
            raise ValueError("composite.mtmc 无法沿边到达事件 Sink")
        camera_id = int(cam_ids[0])
        source_id = mtmc_ids[0]
    else:
        if len(sources) != 1:
            raise ValueError(f"要求恰好 1 个 source 节点，当前 {len(sources)} 个")
        if not overlays:
            raise ValueError("要求至少 1 个 sink.overlay")
        if not detects:
            raise ValueError("要求至少 1 个 detect.yolo")
        reachable = set()
        stack = [sources[0]]
        while stack:
            cur = stack.pop()
            if cur in reachable:
                continue
            reachable.add(cur)
            stack.extend(out_adj.get(cur) or [])
        if not any(o in reachable for o in overlays):
            raise ValueError("source 无法沿边到达 sink.overlay")
        camera_id = int(by_id[sources[0]]["config"]["cameraId"])
        source_id = sources[0]

    return {
        "nodes": by_id,
        "edges": edges,
        "outAdj": out_adj,
        "order": order,
        "sourceId": source_id,
        "detectIds": detects,
        "overlayIds": overlays,
        "trackIds": [nid for nid, n in by_id.items() if n["type"] == "track.bytetrack"],
        "alertIds": [nid for nid, n in by_id.items() if n["type"] == "logic.alert"],
        "vlmGateIds": [nid for nid, n in by_id.items() if n["type"] == "logic.vlm_gate"],
        "mtmcIds": mtmc_ids,
        "webhookIds": webhook_ids,
        "dbIds": db_ids,
        "mqttIds": mqtt_ids,
        "cameraId": camera_id,
        "cameraIds": _parse_camera_ids(by_id[mtmc_ids[0]]["config"].get("cameraIds")) if mtmc_ids else [camera_id],
        "phase": phase,
        "mode": "mtmc" if mtmc_ids else "classic",
    }


def topological_order(by_id: dict[str, dict], out_adj: dict[str, list[str]]) -> list[str]:
    indeg = {nid: 0 for nid in by_id}
    for _a, outs in out_adj.items():
        for b in outs:
            indeg[b] += 1
    queue = [nid for nid, d in indeg.items() if d == 0]
    order: list[str] = []
    while queue:
        queue.sort()
        n = queue.pop(0)
        order.append(n)
        for b in out_adj.get(n) or []:
            indeg[b] -= 1
            if indeg[b] == 0:
                queue.append(b)
    if len(order) != len(by_id):
        raise ValueError("DAG 存在环，无法拓扑排序")
    return order


def parse_dag_json(raw: str | dict) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError) as e:
        raise ValueError(f"DAG JSON 无效: {e}") from e


def example_phase0_dag(camera_id: int = 1, model_key: str = "yolo26n", conf: float = 0.35) -> dict:
    return {
        "id": "tpl_rtsp_yolo_overlay",
        "version": 1,
        "name": "RTSP→YOLO→Overlay",
        "nodes": [
            {"id": "n_src", "type": "source.rtsp", "config": {"cameraId": int(camera_id)},
             "position": {"x": 40, "y": 120}},
            {
                "id": "n_det",
                "type": "detect.yolo",
                "config": {"modelKey": model_key, "modelId": None, "conf": float(conf), "sampleFps": 4},
                "position": {"x": 280, "y": 120},
            },
            {"id": "n_ov", "type": "sink.overlay", "config": {}, "position": {"x": 520, "y": 120}},
        ],
        "edges": [["n_src", "n_det"], ["n_det", "n_ov"]],
    }


def template_security_alert(
    camera_id: int = 1,
    model_key: str = "yolo26n",
    conf: float = 0.35,
    webhook_url: str = "",
    mqtt_topic: str = "",
) -> dict:
    """官方模板 T1：安防检测告警（检测→跟踪→告警→叠加/落库/Webhook/MQTT）。"""
    nodes = [
        {"id": "n_src", "type": "source.rtsp", "config": {"cameraId": int(camera_id)},
         "position": {"x": 20, "y": 160}},
        {
            "id": "n_det",
            "type": "detect.yolo",
            "config": {"modelKey": model_key, "conf": float(conf), "sampleFps": 4},
            "position": {"x": 240, "y": 160},
        },
        {"id": "n_trk", "type": "track.bytetrack", "config": {"maxAge": 30}, "position": {"x": 460, "y": 160}},
        {
            "id": "n_alert",
            "type": "logic.alert",
            "config": {"ruleIds": [], "persist": True},
            "position": {"x": 680, "y": 160},
        },
        {"id": "n_ov", "type": "sink.overlay", "config": {}, "position": {"x": 900, "y": 40}},
        {"id": "n_db", "type": "sink.db", "config": {}, "position": {"x": 900, "y": 160}},
    ]
    edges = [
        ["n_src", "n_det"], ["n_det", "n_trk"], ["n_trk", "n_alert"],
        ["n_alert", "n_ov"], ["n_alert", "n_db"],
    ]
    if webhook_url:
        nodes.append({
            "id": "n_wh",
            "type": "sink.webhook",
            "config": {"url": webhook_url, "event": "alert.fired", "secret": ""},
            "position": {"x": 900, "y": 280},
        })
        edges.append(["n_alert", "n_wh"])
    if mqtt_topic:
        nodes.append({
            "id": "n_mqtt",
            "type": "sink.mqtt",
            "config": {
                "topic": mqtt_topic,
                "qos": 1,
                "event": "alert.fired",
            },
            "position": {"x": 900, "y": 400},
        })
        edges.append(["n_alert", "n_mqtt"])
    return {
        "id": "tpl_security_alert",
        "version": 1,
        "name": "安防检测告警",
        "nodes": nodes,
        "edges": edges,
    }


def template_zone_intrusion(
    camera_id: int = 1,
    model_key: str = "yolo26n",
    conf: float = 0.35,
    region: list | None = None,
) -> dict:
    """官方模板 T2：区域入侵（需启用 zone_crossing 类告警规则）。"""
    region = region or [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]
    return {
        "id": "tpl_zone_intrusion",
        "version": 1,
        "name": "区域入侵",
        "nodes": [
            {"id": "n_src", "type": "source.rtsp", "config": {"cameraId": int(camera_id)},
             "position": {"x": 20, "y": 140}},
            {
                "id": "n_det",
                "type": "detect.yolo",
                "config": {"modelKey": model_key, "conf": float(conf), "sampleFps": 4},
                "position": {"x": 240, "y": 140},
            },
            {"id": "n_trk", "type": "track.bytetrack", "config": {}, "position": {"x": 460, "y": 140}},
            {
                "id": "n_alert",
                "type": "logic.alert",
                "config": {
                    "ruleIds": [],
                    "ruleTypes": ["zone_crossing", "line_crossing"],
                    "region": region,
                    "persist": True,
                },
                "position": {"x": 680, "y": 140},
            },
            {"id": "n_ov", "type": "sink.overlay", "config": {"drawRegion": True}, "position": {"x": 900, "y": 80}},
            {"id": "n_db", "type": "sink.db", "config": {}, "position": {"x": 900, "y": 220}},
        ],
        "edges": [
            ["n_src", "n_det"], ["n_det", "n_trk"], ["n_trk", "n_alert"],
            ["n_alert", "n_ov"], ["n_alert", "n_db"],
        ],
    }


def template_vlm_gated_alert(
    camera_id: int = 1,
    model_key: str = "yolo26n",
    conf: float = 0.35,
    webhook_url: str = "",
    mqtt_topic: str = "",
    vlm_prompt: str = "",
) -> dict:
    """Phase2 模板：告警经 VLM 门控后再 Webhook/MQTT。"""
    prompt = (vlm_prompt or (
        "这是安防告警候选画面裁剪。请判断是否为真实告警（烟火/入侵/未戴PPE等）。"
        '仅返回 JSON：{"confirm": true|false, "reason": "简短中文"}'
    )).strip()
    nodes = [
        {"id": "n_src", "type": "source.rtsp", "config": {"cameraId": int(camera_id)},
         "position": {"x": 20, "y": 180}},
        {
            "id": "n_det",
            "type": "detect.yolo",
            "config": {"modelKey": model_key, "conf": float(conf), "sampleFps": 3},
            "position": {"x": 220, "y": 180},
        },
        {"id": "n_trk", "type": "track.bytetrack", "config": {"maxAge": 30}, "position": {"x": 420, "y": 180}},
        {
            "id": "n_alert",
            "type": "logic.alert",
            "config": {"ruleIds": [], "persist": False},
            "position": {"x": 620, "y": 180},
        },
        {
            "id": "n_vlm",
            "type": "logic.vlm_gate",
            "config": {
                "enabled": True,
                "prompt": prompt,
                "timeoutSec": 12,
                "useCrop": True,
                "onBusy": "pass",
            },
            "position": {"x": 820, "y": 180},
        },
        {"id": "n_ov", "type": "sink.overlay", "config": {}, "position": {"x": 1040, "y": 40}},
        {"id": "n_db", "type": "sink.db", "config": {}, "position": {"x": 1040, "y": 160}},
    ]
    edges = [
        ["n_src", "n_det"], ["n_det", "n_trk"], ["n_trk", "n_alert"],
        ["n_alert", "n_vlm"], ["n_alert", "n_ov"], ["n_vlm", "n_db"],
    ]
    if webhook_url:
        nodes.append({
            "id": "n_wh",
            "type": "sink.webhook",
            "config": {"url": webhook_url, "event": "alert.fired", "secret": ""},
            "position": {"x": 1040, "y": 280},
        })
        edges.append(["n_vlm", "n_wh"])
    topic = mqtt_topic or "alerts/{site}/{ruleKey}"
    nodes.append({
        "id": "n_mqtt",
        "type": "sink.mqtt",
        "config": {"topic": topic, "qos": 1, "event": "alert.fired"},
        "position": {"x": 1040, "y": 400},
    })
    edges.append(["n_vlm", "n_mqtt"])
    return {
        "id": "tpl_vlm_gated_alert",
        "version": 1,
        "name": "VLM门控告警+MQTT",
        "nodes": nodes,
        "edges": edges,
    }


def template_vehicle_pass(
    camera_id: int = 1,
    model_key: str = "yolo26n",
    conf: float = 0.35,
    mqtt_topic: str = "",
) -> dict:
    """Phase3 模板：车辆过线/区域（依赖启用的车辆类告警规则）。"""
    nodes = [
        {"id": "n_src", "type": "source.rtsp", "config": {"cameraId": int(camera_id)},
         "position": {"x": 20, "y": 160}},
        {
            "id": "n_det",
            "type": "detect.yolo",
            "config": {
                "modelKey": model_key,
                "conf": float(conf),
                "sampleFps": 5,
                "classFilter": ["car", "truck", "bus", "motorcycle"],
            },
            "position": {"x": 240, "y": 160},
        },
        {"id": "n_trk", "type": "track.bytetrack", "config": {"maxAge": 40}, "position": {"x": 460, "y": 160}},
        {
            "id": "n_alert",
            "type": "logic.alert",
            "config": {
                "ruleIds": [],
                "ruleTypes": ["line_crossing", "zone_crossing", "vehicle"],
                "persist": True,
            },
            "position": {"x": 680, "y": 160},
        },
        {"id": "n_ov", "type": "sink.overlay", "config": {}, "position": {"x": 900, "y": 60}},
        {"id": "n_db", "type": "sink.db", "config": {}, "position": {"x": 900, "y": 180}},
    ]
    edges = [
        ["n_src", "n_det"], ["n_det", "n_trk"], ["n_trk", "n_alert"],
        ["n_alert", "n_ov"], ["n_alert", "n_db"],
    ]
    topic = mqtt_topic or "alerts/{site}/{ruleKey}"
    nodes.append({
        "id": "n_mqtt",
        "type": "sink.mqtt",
        "config": {"topic": topic, "qos": 1, "event": "alert.fired"},
        "position": {"x": 900, "y": 300},
    })
    edges.append(["n_alert", "n_mqtt"])
    return {
        "id": "tpl_vehicle_pass",
        "version": 1,
        "name": "车辆过线告警",
        "nodes": nodes,
        "edges": edges,
    }


def template_mtmc_composite(
    camera_ids: list | None = None,
    mqtt_topic: str = "",
    persist_events: bool = True,
) -> dict:
    """Phase3 模板：MTMC 跨镜复合 → DB / MQTT。"""
    cams = camera_ids or [1, 2]
    cams = [int(x) for x in cams]
    if len(cams) < 2:
        cams = [1, 2]
    nodes = [
        {
            "id": "n_mtmc",
            "type": "composite.mtmc",
            "config": {
                "cameraIds": cams,
                "enablePerson": True,
                "enableVehicle": True,
                "persistEvents": bool(persist_events),
                "ownSession": True,
                "sampleFps": 4,
                "appearThresh": 0.48,
            },
            "position": {"x": 80, "y": 180},
        },
        {"id": "n_db", "type": "sink.db", "config": {}, "position": {"x": 420, "y": 100}},
        {
            "id": "n_mqtt",
            "type": "sink.mqtt",
            "config": {
                "topic": mqtt_topic or "mtmc/{site}/cross",
                "qos": 1,
                "event": "mtmc.cross_camera",
            },
            "position": {"x": 420, "y": 260},
        },
    ]
    edges = [["n_mtmc", "n_db"], ["n_mtmc", "n_mqtt"]]
    return {
        "id": "tpl_mtmc_composite",
        "version": 1,
        "name": "MTMC跨镜复合",
        "nodes": nodes,
        "edges": edges,
    }


def list_templates() -> list[dict]:
    return [
        {"id": "tpl_rtsp_yolo_overlay", "name": "基础检测叠加", "phase": 0, "builder": "phase0"},
        {"id": "tpl_security_alert", "name": "安防检测告警", "phase": 1, "builder": "security"},
        {"id": "tpl_zone_intrusion", "name": "区域入侵", "phase": 1, "builder": "zone"},
        {"id": "tpl_vlm_gated_alert", "name": "VLM门控+MQTT", "phase": 2, "builder": "vlm"},
        {"id": "tpl_vehicle_pass", "name": "车辆过线告警", "phase": 3, "builder": "vehicle"},
        {"id": "tpl_mtmc_composite", "name": "MTMC跨镜复合", "phase": 3, "builder": "mtmc"},
    ]


def build_template(template_id: str, **kwargs) -> dict:
    tid = (template_id or "").strip()
    if tid in ("tpl_rtsp_yolo_overlay", "phase0", "basic"):
        return example_phase0_dag(
            camera_id=int(kwargs.get("cameraId") or 1),
            model_key=str(kwargs.get("modelKey") or "yolo26n"),
            conf=float(kwargs.get("conf") or 0.35),
        )
    if tid in ("tpl_security_alert", "security"):
        return template_security_alert(
            camera_id=int(kwargs.get("cameraId") or 1),
            model_key=str(kwargs.get("modelKey") or "yolo26n"),
            conf=float(kwargs.get("conf") or 0.35),
            webhook_url=str(kwargs.get("webhookUrl") or ""),
            mqtt_topic=str(kwargs.get("mqttTopic") or ""),
        )
    if tid in ("tpl_zone_intrusion", "zone"):
        return template_zone_intrusion(
            camera_id=int(kwargs.get("cameraId") or 1),
            model_key=str(kwargs.get("modelKey") or "yolo26n"),
            conf=float(kwargs.get("conf") or 0.35),
        )
    if tid in ("tpl_vlm_gated_alert", "vlm", "vlm_gate"):
        return template_vlm_gated_alert(
            camera_id=int(kwargs.get("cameraId") or 1),
            model_key=str(kwargs.get("modelKey") or "yolo26n"),
            conf=float(kwargs.get("conf") or 0.35),
            webhook_url=str(kwargs.get("webhookUrl") or ""),
            mqtt_topic=str(kwargs.get("mqttTopic") or ""),
            vlm_prompt=str(kwargs.get("vlmPrompt") or ""),
        )
    if tid in ("tpl_vehicle_pass", "vehicle"):
        return template_vehicle_pass(
            camera_id=int(kwargs.get("cameraId") or 1),
            model_key=str(kwargs.get("modelKey") or "yolo26n"),
            conf=float(kwargs.get("conf") or 0.35),
            mqtt_topic=str(kwargs.get("mqttTopic") or ""),
        )
    if tid in ("tpl_mtmc_composite", "mtmc"):
        cams = kwargs.get("cameraIds")
        if isinstance(cams, str) and cams.strip():
            cams = [int(x) for x in cams.split(",") if x.strip()]
        if not cams and kwargs.get("cameraId"):
            cams = [int(kwargs.get("cameraId")), int(kwargs.get("cameraId2") or 2)]
        return template_mtmc_composite(
            camera_ids=cams,
            mqtt_topic=str(kwargs.get("mqttTopic") or ""),
            persist_events=bool(kwargs.get("persistEvents", True)),
        )
    raise ValueError(f"未知模板: {tid}")
