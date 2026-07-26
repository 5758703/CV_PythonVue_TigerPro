# -*- coding: utf-8 -*-
"""根据目录 JSON + 手写规格表生成《API开放管理平台文档》。"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATALOG = json.loads((ROOT / "_api_catalog_dump.json").read_text(encoding="utf-8"))
OUT = ROOT.parent / "docs" / "API开放管理平台文档.md"

# path|METHOD -> 详细规格
SPECS: dict[str, dict] = {}


def spec(method: str, path: str, **kw):
    SPECS[f"{method.upper()}|{path}"] = kw


# ── 通用说明写入 SPECS ─────────────────────────────────

spec("GET", "/api/health",
     title="服务健康检查", auth="公开",
     desc="探测后端进程是否存活。",
     params=[],
     resp='`{ "code": 0, "message": "ok" }`',
     example="""```bash
curl -s http://127.0.0.1:5001/api/health
```""")

# Auth
spec("POST", "/api/auth/login",
     title="用户登录", auth="公开",
     desc="校验账号密码，返回 JWT。",
     params=[
         ("Body", "username", "string", "是", "用户名"),
         ("Body", "password", "string", "是", "密码"),
     ],
     resp='`{ code:0, data:{ token } }`；失败 400/401/403',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"admin","password":"admin123"}'
```""")

spec("POST", "/api/auth/register",
     title="用户注册", auth="公开",
     desc="注册普通用户（默认 common 角色）。",
     params=[
         ("Body", "username", "string", "是", "≥3 位"),
         ("Body", "password", "string", "是", "≥6 位"),
     ],
     resp="201 `{ code:0, data: user }`；409 用户名已存在")

spec("GET", "/api/auth/info",
     title="当前用户信息", auth="JWT",
     desc="返回用户资料、角色标识、权限标识集合。",
     params=[],
     resp='`{ user, roles[], permissions[] }`')

spec("GET", "/api/auth/routers",
     title="侧边栏菜单树", auth="JWT",
     desc="当前用户可见的目录/菜单(M/C)树。",
     params=[],
     resp="`MenuTree[]`（id/name/path/component/icon/children）")

spec("POST", "/api/auth/logout",
     title="退出登录", auth="公开",
     desc="客户端清除 Token 即可；服务端无吊销列表。",
     params=[],
     resp='`{ code:0, message:"退出成功" }`')

# User
spec("GET", "/api/system/user",
     title="用户分页列表", auth="JWT + system:user:list",
     desc="支持用户名/状态筛选与数据权限范围。",
     params=[
         ("Query", "pageNum", "int", "否", "默认 1"),
         ("Query", "pageSize", "int", "否", "默认 10"),
         ("Query", "username", "string", "否", "模糊匹配"),
         ("Query", "status", "string", "否", "0 正常 / 1 停用"),
     ],
     resp='`{ rows: User[], total }`',
     example="""```bash
curl -s "http://127.0.0.1:5001/api/system/user?pageNum=1&pageSize=10" \\
  -H "Authorization: Bearer $TOKEN"
```""")

spec("GET", "/api/system/user/<int:uid>",
     title="用户详情", auth="JWT + system:user:query",
     desc="含关联部门 ID 列表 deptIds。",
     params=[("Path", "uid", "int", "是", "用户 ID")],
     resp="`user.to_dict()` + `deptIds`")

spec("POST", "/api/system/user",
     title="新增用户", auth="JWT + system:user:add",
     desc="创建用户并绑定角色/岗位/部门。",
     params=[
         ("Body", "username", "string", "是", "唯一"),
         ("Body", "nickname", "string", "否", "默认同 username"),
         ("Body", "password", "string", "否", "默认 123456"),
         ("Body", "deptId", "int", "否", "主部门"),
         ("Body", "email/phone/sex/status", "string", "否", "sex 默认 0"),
         ("Body", "roleIds", "int[]", "否", "角色"),
         ("Body", "postIds", "int[]", "否", "岗位"),
         ("Body", "deptIds", "int[]", "否", "多部门"),
     ],
     resp="201 `user`",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/system/user \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"username":"demo","nickname":"演示","roleIds":[2],"password":"demo123"}'
```""")

spec("PUT", "/api/system/user/<int:uid>",
     title="修改用户", auth="JWT + system:user:edit",
     desc="更新资料、密码与关联。",
     params=[
         ("Path", "uid", "int", "是", ""),
         ("Body", "nickname/email/phone/sex/status/deptId", "any", "否", ""),
         ("Body", "password", "string", "否", "非空则重置"),
         ("Body", "roleIds/postIds/deptIds", "int[]", "否", ""),
     ],
     resp="更新后的 user")

spec("DELETE", "/api/system/user/<int:uid>",
     title="删除用户（软删）", auth="JWT + system:user:remove",
     desc="del_flag=2；admin 不可删。",
     params=[("Path", "uid", "int", "是", "")],
     resp="成功消息")

# Role
spec("GET", "/api/system/role",
     title="角色分页列表", auth="JWT + system:role:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", "1 / 10"),
         ("Query", "roleName", "string", "否", "模糊"),
     ],
     resp='`{ rows, total }`')

spec("GET", "/api/system/role/<int:rid>",
     title="角色详情", auth="JWT + system:role:query",
     params=[("Path", "rid", "int", "是", "")],
     resp="`to_dict(with_menus=True)`")

spec("POST", "/api/system/role",
     title="新增角色", auth="JWT + system:role:add",
     params=[
         ("Body", "roleName", "string", "是", ""),
         ("Body", "roleKey", "string", "是", "权限字符"),
         ("Body", "roleSort", "int", "否", "排序"),
         ("Body", "dataScope", "string", "否", "1–4 数据范围"),
         ("Body", "status/remark", "string", "否", ""),
         ("Body", "menuIds", "int[]", "否", "菜单授权"),
     ],
     resp="201 role")

spec("PUT", "/api/system/role/<int:rid>",
     title="修改角色", auth="JWT + system:role:edit",
     desc="role_key=admin 不可改。",
     params=[("Path", "rid", "int", "是", ""), ("Body", "同新增可更新字段", "any", "否", "")],
     resp="role")

spec("DELETE", "/api/system/role/<int:rid>",
     title="删除角色", auth="JWT + system:role:remove",
     desc="admin 角色不可删。",
     params=[("Path", "rid", "int", "是", "")],
     resp="成功消息")

# Dept
spec("GET", "/api/system/dept",
     title="部门树列表", auth="JWT + system:dept:list",
     params=[("Query", "deptName", "string", "否", "过滤")],
     resp="树形 `children[]`")

spec("GET", "/api/system/dept/<int:did>",
     title="部门详情", auth="JWT + system:dept:query",
     params=[("Path", "did", "int", "是", "")],
     resp="dept")

spec("POST", "/api/system/dept",
     title="新增部门", auth="JWT + system:dept:add",
     params=[
         ("Body", "deptName", "string", "是", ""),
         ("Body", "parentId", "int", "否", "默认 0"),
         ("Body", "orderNum", "int", "否", ""),
         ("Body", "leader/phone/email/status", "string", "否", ""),
     ],
     resp="201 dept")

spec("PUT", "/api/system/dept/<int:did>",
     title="修改部门", auth="JWT + system:dept:edit",
     params=[("Path", "did", "int", "是", ""), ("Body", "同新增", "any", "否", "")],
     resp="dept")

spec("DELETE", "/api/system/dept/<int:did>",
     title="删除部门", auth="JWT + system:dept:remove",
     desc="有子部门或下属用户时返回 400。",
     params=[("Path", "did", "int", "是", "")],
     resp="成功消息")

# Job (post)
spec("GET", "/api/system/job",
     title="岗位分页列表", auth="JWT + system:job:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", "1 / 10"),
         ("Query", "postName", "string", "否", ""),
     ],
     resp='`{ rows, total }`')

spec("GET", "/api/system/job/<int:jid>",
     title="岗位详情", auth="JWT + system:job:query",
     params=[("Path", "jid", "int", "是", "")],
     resp="job")

spec("POST", "/api/system/job",
     title="新增岗位", auth="JWT + system:job:add",
     params=[
         ("Body", "postCode", "string", "是", ""),
         ("Body", "postName", "string", "是", ""),
         ("Body", "postSort", "int", "否", ""),
         ("Body", "status", "string", "否", "0"),
     ],
     resp="201 job")

spec("PUT", "/api/system/job/<int:jid>",
     title="修改岗位", auth="JWT + system:job:edit",
     params=[("Path", "jid", "int", "是", ""), ("Body", "同新增", "any", "否", "")],
     resp="job")

spec("DELETE", "/api/system/job/<int:jid>",
     title="删除岗位", auth="JWT + system:job:remove",
     params=[("Path", "jid", "int", "是", "")],
     resp="成功消息")

# Menu
spec("GET", "/api/system/menu",
     title="菜单树列表", auth="JWT + system:menu:list",
     params=[("Query", "menuName", "string", "否", "")],
     resp="树形菜单")

spec("GET", "/api/system/menu/<int:mid>",
     title="菜单详情", auth="JWT + system:menu:query",
     params=[("Path", "mid", "int", "是", "")],
     resp="menu")

spec("POST", "/api/system/menu",
     title="新增菜单", auth="JWT + system:menu:add",
     params=[
         ("Body", "menuName", "string", "是", ""),
         ("Body", "menuType", "string", "是", "M 目录 / C 菜单 / F 按钮"),
         ("Body", "parentId", "int", "否", "0"),
         ("Body", "perms", "string", "否", "权限标识"),
         ("Body", "path/component/icon", "string", "否", ""),
         ("Body", "orderNum", "int", "否", ""),
         ("Body", "visible/status", "string", "否", ""),
     ],
     resp="201 menu")

spec("PUT", "/api/system/menu/<int:mid>",
     title="修改菜单", auth="JWT + system:menu:edit",
     params=[("Path", "mid", "int", "是", ""), ("Body", "同新增", "any", "否", "")],
     resp="menu")

spec("DELETE", "/api/system/menu/<int:mid>",
     title="删除菜单", auth="JWT + system:menu:remove",
     params=[("Path", "mid", "int", "是", "")],
     resp="成功消息")

# Camera
spec("GET", "/api/camera",
     title="摄像头分页列表", auth="JWT + camera:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", "1 / 10"),
         ("Query", "name", "string", "否", ""),
         ("Query", "status", "string", "否", ""),
     ],
     resp='`{ rows: Camera(+sourceReady), total }`')

spec("GET", "/api/camera/devices",
     title="本机采集设备", auth="JWT + camera:query",
     desc="枚举本地摄像头设备索引。",
     params=[],
     resp="设备列表")

spec("POST", "/api/camera",
     title="新增摄像头", auth="JWT + camera:add",
     params=[
         ("Body", "name", "string", "是", ""),
         ("Body", "sourceType", "string", "是", "file | rtsp | device"),
         ("Body", "source", "string", "是", "路径/URL/设备号"),
         ("Body", "location", "string", "否", ""),
         ("Body", "resolution", "int", "否", "默认 640"),
         ("Body", "fps", "int", "否", "默认 15"),
         ("Body", "status", "string", "否", "0"),
     ],
     resp="201 camera",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/camera \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"name":"大门","sourceType":"rtsp","source":"rtsp://user:pwd@ip/stream"}'
```""")

spec("PUT", "/api/camera/<int:cid>",
     title="修改摄像头", auth="JWT + camera:edit",
     params=[("Path", "cid", "int", "是", ""), ("Body", "同新增", "any", "否", "")],
     resp="camera")

spec("DELETE", "/api/camera/<int:cid>",
     title="删除摄像头", auth="JWT + camera:remove",
     params=[("Path", "cid", "int", "是", "")],
     resp="成功消息")

spec("POST", "/api/camera/batch-delete",
     title="批量删除摄像头", auth="JWT + camera:remove",
     params=[("Body", "ids", "int[]", "是", "摄像头 ID 列表")],
     resp="成功消息")

spec("POST", "/api/camera/upload",
     title="上传视频文件源", auth="JWT + camera:add",
     params=[("Form", "file", "file", "是", "视频文件")],
     resp='`{ filePath, fileName }`')

spec("GET", "/api/camera/<int:cid>/stream",
     title="MJPEG 实时流", auth="JWT(query token) + camera:query",
     desc="`<img>` 无法带 Header，须用 `?token=` 传 JWT。",
     params=[
         ("Path", "cid", "int", "是", ""),
         ("Query", "token", "string", "是", "JWT"),
         ("Query", "check", "string", "否", "1=仅探活返回 JSON"),
         ("Query", "shared", "string", "否", "0=关闭共享拉流"),
     ],
     resp="`multipart/x-mixed-replace` MJPEG；check 时 JSON",
     example="""```bash
# 浏览器: /api/camera/1/stream?token=$TOKEN
curl -s "http://127.0.0.1:5001/api/camera/1/stream?token=$TOKEN&check=1"
```""")

# AI Model — CRUD
spec("GET", "/api/ai/model",
     title="模型分页列表", auth="JWT + ai:model:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", "1 / 10"),
         ("Query", "modelName", "string", "否", "模糊"),
         ("Query", "category", "string", "否", ""),
         ("Query", "task", "string", "否", "如 object-detection"),
         ("Query", "source", "string", "否", "huggingface|modelscope|other"),
         ("Query", "orderBy/orderDir", "string", "否", "列排序"),
     ],
     resp='`{ rows: AiModel[], total }`')

spec("GET", "/api/ai/model/categories",
     title="模型分类列表", auth="JWT + ai:model:list",
     params=[], resp="string[]")

spec("GET", "/api/ai/model/tasks",
     title="任务类型列表", auth="JWT + ai:model:list",
     params=[], resp="task slug[]")

spec("GET", "/api/ai/model/<int:mid>",
     title="模型详情", auth="JWT + ai:model:query",
     params=[("Path", "mid", "int", "是", "")], resp="AiModel")

spec("POST", "/api/ai/model/upload",
     title="上传模型权重", auth="JWT + ai:model:add",
     params=[
         ("Form", "file", "file", "是", "权重文件"),
         ("Form", "modelKey", "string", "否", "子目录名"),
     ],
     resp='`{ fileName, filePath, fileSize }`')

spec("POST", "/api/ai/model",
     title="登记模型元数据", auth="JWT + ai:model:add",
     params=[
         ("Body", "modelName", "string", "是", ""),
         ("Body", "category", "string", "否", ""),
         ("Body", "modelKey", "string", "否", "唯一标识"),
         ("Body", "task", "string", "否", "默认 object-detection"),
         ("Body", "library", "string", "否", "默认 ultralytics"),
         ("Body", "version/sourceUrl/filePath/description/status", "any", "否", ""),
         ("Body", "fileSize", "int", "否", "0"),
     ],
     resp="201 AiModel")

spec("PUT", "/api/ai/model/<int:mid>",
     title="更新模型", auth="JWT + ai:model:edit",
     params=[("Path", "mid", "int", "是", ""), ("Body", "可更新字段", "any", "否", "")],
     resp="AiModel")

spec("DELETE", "/api/ai/model/<int:mid>",
     title="删除模型", auth="JWT + ai:model:remove",
     params=[("Path", "mid", "int", "是", "")], resp="成功消息")

spec("POST", "/api/ai/model/batch-delete",
     title="批量删除模型", auth="JWT + ai:model:remove",
     params=[("Body", "ids", "int[]", "是", "")], resp="成功消息")

spec("GET", "/api/ai/model/<int:mid>/download",
     title="下载权重文件", auth="JWT + ai:model:download",
     params=[("Path", "mid", "int", "是", "")], resp="文件流")

spec("POST", "/api/ai/model/<int:mid>/fetch",
     title="拉取远程权重", auth="JWT + ai:model:add",
     desc="按 sourceUrl/library 从 HF / ModelScope / Roboflow 等拉取。",
     params=[("Path", "mid", "int", "是", "")],
     resp="更新后的 AiModel",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/model/1/fetch \\
  -H "Authorization: Bearer $TOKEN"
```""")

spec("GET", "/api/ai/model/output/<path:name>",
     title="获取推理输出文件", auth="JWT + ai:model:query",
     params=[("Path", "name", "string", "是", "相对输出路径")],
     resp="文件流（图片/视频等）")

# AI inference
spec("POST", "/api/ai/model/<int:mid>/analyze-text",
     title="文本分类/情感分析", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "text", "string", "是", "待分析文本"),
     ],
     resp="inference 结果（labels/scores 等）")

spec("POST", "/api/ai/model/<int:mid>/classify-image",
     title="图像分类", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", "图片"),
         ("Form", "topK", "int", "否", "默认 5"),
     ],
     resp="Top-K 分类结果")

spec("POST", "/api/ai/model/<int:mid>/ocr",
     title="GOT-OCR 文字识别", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", "OCR 模型"),
         ("Form", "file", "file", "是", "图片"),
         ("Form", "formatted", "string", "否", "1=格式化输出"),
     ],
     resp="识别文本")

spec("POST", "/api/ai/model/ocr-paddle",
     title="Paddle/RapidOCR", auth="JWT + ai:model:query",
     params=[
         ("Form", "file", "file", "是", "图片"),
         ("Form", "detId", "int", "是", "检测模型 ID"),
         ("Form", "recId", "int", "是", "识别模型 ID"),
     ],
     resp="文本行 + 框",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/model/ocr-paddle \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@./doc.jpg" -F "detId=10" -F "recId=11"
```""")

spec("POST", "/api/ai/model/<int:mid>/transcribe",
     title="语音转写", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", "音频"),
         ("Form", "language", "string", "否", "nano 模型用，默认 auto"),
     ],
     resp="转写文本 + 情感/事件（视库而定）")

spec("GET", "/api/ai/model/<int:mid>/tts-speakers",
     title="TTS 音色列表", auth="JWT + ai:model:query",
     params=[("Path", "mid", "int", "是", "")],
     resp="音色数组（VibeVoice 等）")

spec("POST", "/api/ai/model/<int:mid>/tts",
     title="文本转语音", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "text", "string", "是", ""),
         ("Body", "speaker", "string", "否", "默认「中文女」"),
     ],
     resp="wav base64 等")

spec("POST", "/api/ai/model/<int:mid>/tts-clone",
     title="零样本音色克隆", auth="JWT + ai:model:query",
     desc="VoxCPM：参考音频 + 参考文本 + 目标文本。",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "text", "string", "是", "目标文本"),
         ("Form", "promptText", "string", "是", "参考音频对应文本"),
         ("Form", "promptAudio", "file", "是", "参考音频"),
     ],
     resp="wav base64")

spec("POST", "/api/ai/model/<int:mid>/generate-text",
     title="文本生成/摘要/翻译", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "text", "string", "是", ""),
         ("Body", "maxNewTokens", "int", "否", "默认 256"),
     ],
     resp="生成文本")

spec("POST", "/api/ai/model/<int:mid>/zero-shot",
     title="零样本文本分类", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "text", "string", "是", ""),
         ("Body", "labels", "string[]", "是", "候选标签"),
     ],
     resp="分类分数")

spec("POST", "/api/ai/model/<int:mid>/fill-mask",
     title="完形填空", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "text", "string", "是", "含 [MASK]"),
         ("Body", "topK", "int", "否", "默认 5"),
     ],
     resp="候选填空")

spec("POST", "/api/ai/model/<int:mid>/extract-entities",
     title="命名实体识别 NER", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "text", "string", "是", ""),
     ],
     resp="实体列表")

spec("POST", "/api/ai/model/<int:mid>/answer-question",
     title="抽取式问答", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "question", "string", "是", ""),
         ("Body", "context", "string", "是", ""),
     ],
     resp="答案与分数")

spec("POST", "/api/ai/model/<int:mid>/detect",
     title="图片目标检测", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", "图片"),
         ("Form", "conf", "float", "否", "默认 0.25"),
         ("Form", "draw", "string", "否", "默认 1；0 不画框"),
     ],
     resp='`{ detections[], imageBase64?, width, height }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/model/1/detect \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@./sample.jpg" -F "conf=0.3" -F "draw=1"
```""")

spec("POST", "/api/ai/model/<int:mid>/pose",
     title="姿态估计（单图）", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", ""),
         ("Form", "conf", "float", "否", "0.25"),
         ("Form", "draw", "string", "否", "1"),
     ],
     resp="关键点 + 可选标注图")

spec("POST", "/api/ai/model/<int:mid>/segment",
     title="图像分割", auth="JWT + ai:model:query",
     desc="YOLO-seg 或 MobileSAM（points/box 提示）。",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", ""),
         ("Form", "conf", "float", "否", "0.25"),
         ("Form", "draw", "string", "否", "1"),
         ("Form", "classes", "string", "否", "类别过滤"),
         ("Form", "mode/points/pointLabels/box", "string", "否", "MobileSAM JSON"),
     ],
     resp="masks / 标注图")

spec("POST", "/api/ai/model/<int:mid>/track-frame",
     title="单帧目标跟踪", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", ""),
         ("Form", "conf", "float", "否", "0.25"),
         ("Form", "reset", "string", "否", "1=重置 tracker"),
     ],
     resp="带 trackId 的 detections")

spec("POST", "/api/ai/model/<int:mid>/analyze-report",
     title="检测结果分析报告", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Body", "detections", "array", "是", "检测框列表"),
         ("Body", "conf/width/height/imageName", "any", "否", ""),
     ],
     resp="结构化报告")

spec("POST", "/api/ai/model/<int:mid>/detect-video",
     title="视频目标检测（异步）", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", "视频"),
         ("Form", "conf", "float", "否", "0.25"),
         ("Form", "alertEnabled", "bool", "否", "启用告警"),
         ("Form", "alertRuleKeys", "string", "否", "规则 key 列表"),
     ],
     resp='`{ jobId }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/model/1/detect-video \\
  -H "Authorization: Bearer $TOKEN" -F "file=@./clip.mp4" -F "conf=0.25"
# 轮询进度
curl -s http://127.0.0.1:5001/api/ai/model/1/video-progress/$JOB_ID \\
  -H "Authorization: Bearer $TOKEN"
```""")

spec("POST", "/api/ai/model/<int:mid>/pose-video",
     title="视频姿态估计（异步）", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", ""),
         ("Form", "conf", "float", "否", "0.25"),
     ],
     resp='`{ jobId }`')

spec("POST", "/api/ai/model/<int:mid>/segment-video",
     title="视频分割（异步）", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", ""),
         ("Form", "conf", "float", "否", ""),
         ("Form", "classes", "string", "否", ""),
     ],
     resp='`{ jobId }`')

spec("POST", "/api/ai/model/<int:mid>/track-video",
     title="视频跟踪（异步）", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "file", "file", "是", ""),
         ("Form", "conf", "float", "否", ""),
         ("Form", "imgsz", "int", "否", ""),
         ("Form", "line", "string", "否", "JSON[4] 越线"),
         ("Form", "alertEnabled/alertRuleKeys", "any", "否", ""),
     ],
     resp='`{ jobId }`')

spec("GET", "/api/ai/model/<int:mid>/video-progress/<job_id>",
     title="视频任务进度", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Path", "job_id", "string", "是", ""),
     ],
     resp='`{ status, processed, total, stats?, error? }`')

spec("POST", "/api/ai/model/<int:mid>/talking-head",
     title="数字人 Talking Head（异步）", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Form", "image", "file", "是", "人脸图"),
         ("Form", "audio", "file", "是", "驱动音频"),
     ],
     resp='`{ jobId }`')

spec("GET", "/api/ai/model/<int:mid>/talking-progress/<job_id>",
     title="数字人任务进度", auth="JWT + ai:model:query",
     params=[
         ("Path", "mid", "int", "是", ""),
         ("Path", "job_id", "string", "是", ""),
     ],
     resp="进度与产物路径")

# Training — datasets
spec("GET", "/api/ai/training/datasets/formats",
     title="支持的数据集格式", auth="JWT + ai:training:query",
     params=[], resp="格式规格列表")

spec("GET", "/api/ai/training/datasets",
     title="数据集分页", auth="JWT + ai:training:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", "1 / 10"),
         ("Query", "name", "string", "否", ""),
     ],
     resp='`{ rows, total }`')

spec("GET", "/api/ai/training/datasets/<int:did>",
     title="数据集详情", auth="JWT + ai:training:query",
     params=[("Path", "did", "int", "是", "")], resp="dataset")

spec("POST", "/api/ai/training/datasets",
     title="创建数据集", auth="JWT + ai:training:add",
     params=[
         ("Body", "name", "string", "是", ""),
         ("Body", "format", "string", "否", "auto/yolo/coco/labelme/import/..."),
         ("Body", "classNames", "string[]", "条件", "多数格式建议填写"),
         ("Body", "sourcePath", "string", "条件", "import 必填，项目内路径"),
         ("Body", "splitRatio", "float", "否", "默认 0.8"),
         ("Body", "description", "string", "否", ""),
     ],
     resp="dataset",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/training/datasets \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"name":"烟火检测","format":"yolo","classNames":["smoke","fire"]}'
```""")

spec("PUT", "/api/ai/training/datasets/<int:did>",
     title="更新数据集", auth="JWT + ai:training:edit",
     params=[("Path", "did", "int", "是", ""), ("Body", "name/classNames/splitRatio/format/sourcePath/description", "any", "否", "")],
     resp="dataset")

spec("DELETE", "/api/ai/training/datasets/<int:did>",
     title="删除数据集", auth="JWT + ai:training:remove",
     desc="已被训练任务引用则不可删。",
     params=[("Path", "did", "int", "是", "")], resp="成功消息")

spec("POST", "/api/ai/training/datasets/<int:did>/upload",
     title="上传数据集文件", auth="JWT + ai:training:add",
     params=[
         ("Path", "did", "int", "是", ""),
         ("Form", "files 或 file", "file[]", "是", "图片/标注/zip"),
         ("Form", "relativePath", "string", "否", "相对路径"),
     ],
     resp='`{ saved, zipExtracted, detectedFormat }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/training/datasets/1/upload \\
  -H "Authorization: Bearer $TOKEN" -F "files=@./data.zip"
```""")

spec("POST", "/api/ai/training/datasets/<int:did>/build",
     title="构建 YOLO 数据集", auth="JWT + ai:training:edit",
     desc="多格式统一为 YOLO + data.yaml。",
     params=[("Path", "did", "int", "是", "")],
     resp="dataset + buildInfo",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/training/datasets/1/build \\
  -H "Authorization: Bearer $TOKEN"
```""")

spec("GET", "/api/ai/training/datasets/<int:did>/samples",
     title="样本结构预览", auth="JWT + ai:training:query",
     params=[("Path", "did", "int", "是", "")],
     resp="结构扫描 + annotation 统计")

spec("POST", "/api/ai/training/datasets/<int:did>/extract-frames",
     title="视频抽帧", auth="JWT + ai:training:add",
     params=[
         ("Path", "did", "int", "是", ""),
         ("Form", "file", "file", "是", "视频"),
         ("Form", "frameInterval", "int", "否", "默认 1"),
         ("Form", "maxFrames", "int", "否", "默认 250"),
         ("Form", "startSec/endSec", "float", "否", "时间窗"),
     ],
     resp="抽帧统计")

spec("GET", "/api/ai/training/datasets/<int:did>/annotate/samples",
     title="标注样本列表", auth="JWT + ai:training:query",
     params=[("Path", "did", "int", "是", "")], resp="样本 stem 列表")

spec("GET", "/api/ai/training/datasets/<int:did>/annotate/image/<stem>",
     title="标注原图", auth="JWT + ai:training:query",
     params=[("Path", "did/stem", "any", "是", "")], resp="图片流")

spec("GET", "/api/ai/training/datasets/<int:did>/annotate/labels/<stem>",
     title="读取标注框", auth="JWT + ai:training:query",
     params=[("Path", "did/stem", "any", "是", "")],
     resp='`{ stem, boxes, classNames }`')

spec("PUT", "/api/ai/training/datasets/<int:did>/annotate/labels/<stem>",
     title="保存标注框", auth="JWT + ai:training:edit",
     params=[
         ("Path", "did/stem", "any", "是", ""),
         ("Body", "boxes", "array", "是", "[{classId|className,x,y,w,h,...}]"),
     ],
     resp="保存结果",
     example="""```bash
curl -s -X PUT http://127.0.0.1:5001/api/ai/training/datasets/1/annotate/labels/img001 \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"boxes":[{"classId":0,"x":0.5,"y":0.5,"w":0.2,"h":0.3}]}'
```""")

spec("DELETE", "/api/ai/training/datasets/<int:did>/annotate/labels/<stem>",
     title="删除标注", auth="JWT + ai:training:edit",
     params=[("Path", "did/stem", "any", "是", "")], resp="成功消息")

spec("GET", "/api/ai/training/datasets/<int:did>/annotate/tools",
     title="外接标注工具列表", auth="JWT + ai:training:query",
     params=[("Path", "did", "int", "是", "")],
     resp="xanylabeling / cvat / roboflow 等")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/<tool>/export",
     title="导出给外接工具", auth="JWT + ai:training:add",
     params=[("Path", "did/tool", "any", "是", "tool=xanylabeling|cvat|roboflow")],
     resp="zip 文件流")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/<tool>/import",
     title="从外接工具导入", auth="JWT + ai:training:edit",
     params=[
         ("Path", "did/tool", "any", "是", ""),
         ("Form", "file", "file", "是", "标注包"),
     ],
     resp="导入统计")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/<tool>/apply",
     title="应用导入标注", auth="JWT + ai:training:edit",
     params=[
         ("Path", "did/tool", "any", "是", ""),
         ("Body", "mode", "string", "否", "merge | replace"),
     ],
     resp="应用结果")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/cvat/push",
     title="推送到 CVAT", auth="JWT + ai:training:add",
     params=[("Path", "did", "int", "是", "")], resp="任务信息")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/cvat/pull",
     title="从 CVAT 拉取", auth="JWT + ai:training:edit",
     params=[("Path", "did", "int", "是", "")], resp="拉取结果")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/roboflow/push",
     title="推送到 Roboflow", auth="JWT + ai:training:add",
     params=[("Path", "did", "int", "是", "")], resp="推送结果")

spec("POST", "/api/ai/training/datasets/<int:did>/annotate/tools/roboflow/pull",
     title="从 Roboflow 拉取", auth="JWT + ai:training:edit",
     params=[
         ("Path", "did", "int", "是", ""),
         ("Body", "version", "string", "否", "数据集版本"),
     ],
     resp="拉取结果")

spec("POST", "/api/ai/training/datasets/<int:did>/quality/analyze",
     title="标注质量分析", auth="JWT + ai:training:query",
     params=[
         ("Path", "did", "int", "是", ""),
         ("Body", "mode", "string", "否", "raw | yaml"),
     ],
     resp="质量报告")

spec("GET", "/api/ai/training/datasets/convert/types",
     title="格式转换类型", auth="JWT + ai:training:query",
     params=[], resp="可转换类型列表")

spec("POST", "/api/ai/training/datasets/<int:did>/convert",
     title="数据集格式转换", auth="JWT + ai:training:edit",
     params=[
         ("Path", "did", "int", "是", ""),
         ("Body", "type", "string", "是", "目标类型"),
         ("Body", "classNames/classMap", "any", "否", ""),
         ("Body", "targetSubdir/exportSubdir", "string", "否", ""),
     ],
     resp="转换结果")

# Training jobs
spec("GET", "/api/ai/training/base-models",
     title="可选基座模型", auth="JWT + ai:training:query",
     params=[], resp="base model 列表")

spec("GET", "/api/ai/training/presets/badminton",
     title="羽毛球训练预设", auth="JWT + ai:training:query",
     params=[], resp="预设超参/类别")

spec("GET", "/api/ai/training/jobs",
     title="训练任务分页", auth="JWT + ai:training:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", ""),
         ("Query", "status", "string", "否", ""),
     ],
     resp='`{ rows, total }`')

spec("POST", "/api/ai/training/jobs",
     title="创建训练任务", auth="JWT + ai:training:add",
     params=[
         ("Body", "jobName", "string", "是", ""),
         ("Body", "datasetId", "int", "是", "ready 数据集"),
         ("Body", "baseModel", "string", "否", "如 yolov8n.pt"),
         ("Body", "epochs", "int", "否", ""),
         ("Body", "batch", "int", "否", ""),
         ("Body", "imgsz", "int", "否", ""),
         ("Body", "device", "string", "否", "cpu / 0"),
         ("Body", "patience", "int", "否", "早停"),
     ],
     resp="job",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/training/jobs \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"jobName":"smoke-v1","datasetId":1,"baseModel":"yolov8n.pt","epochs":50,"batch":8}'
```""")

spec("GET", "/api/ai/training/jobs/<int:jid>",
     title="训练任务详情", auth="JWT + ai:training:query",
     params=[("Path", "jid", "int", "是", "")], resp="job")

spec("GET", "/api/ai/training/jobs/<int:jid>/progress",
     title="训练进度", auth="JWT + ai:training:query",
     params=[("Path", "jid", "int", "是", "")],
     resp="epoch/metrics/status")

spec("GET", "/api/ai/training/jobs/<int:jid>/logs",
     title="训练日志", auth="JWT + ai:training:query",
     params=[
         ("Path", "jid", "int", "是", ""),
         ("Query", "type", "string", "否", "train | val"),
         ("Query", "offset/limit", "int", "否", "分页读日志"),
     ],
     resp="日志文本片段")

spec("GET", "/api/ai/training/jobs/<int:jid>/artifact/<path:filename>",
     title="训练产物文件", auth="JWT + ai:training:query",
     params=[("Path", "jid/filename", "any", "是", "")], resp="文件流")

spec("POST", "/api/ai/training/jobs/<int:jid>/start",
     title="启动训练", auth="JWT + ai:training:edit",
     params=[("Path", "jid", "int", "是", "")],
     resp="启动结果",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/training/jobs/1/start \\
  -H "Authorization: Bearer $TOKEN"
```""")

spec("POST", "/api/ai/training/jobs/<int:jid>/cancel",
     title="取消训练", auth="JWT + ai:training:edit",
     params=[
         ("Path", "jid", "int", "是", ""),
         ("Body/Query", "force", "bool", "否", "强制终止"),
     ],
     resp="取消结果")

spec("DELETE", "/api/ai/training/jobs/<int:jid>",
     title="删除训练任务", auth="JWT + ai:training:remove",
     params=[("Path", "jid", "int", "是", "")], resp="成功消息")

spec("POST", "/api/ai/training/jobs/<int:jid>/validate",
     title="验证集评估", auth="JWT + ai:training:query",
     params=[("Path", "jid", "int", "是", "")], resp="启动验证")

spec("GET", "/api/ai/training/jobs/<int:jid>/validate-progress",
     title="验证进度", auth="JWT + ai:training:query",
     params=[("Path", "jid", "int", "是", "")], resp="进度")

spec("POST", "/api/ai/training/jobs/<int:jid>/test",
     title="权重试推理", auth="JWT + ai:training:query",
     params=[
         ("Path", "jid", "int", "是", ""),
         ("Form", "image", "file", "是", ""),
         ("Form", "conf", "float", "否", ""),
     ],
     resp="检测结果")

spec("POST", "/api/ai/training/jobs/<int:jid>/export",
     title="导出模型", auth="JWT + ai:training:edit",
     params=[
         ("Path", "jid", "int", "是", ""),
         ("Body", "format", "string", "否", "默认 onnx"),
     ],
     resp="导出信息")

spec("GET", "/api/ai/training/jobs/<int:jid>/download-export",
     title="下载导出文件", auth="JWT + ai:training:query",
     params=[
         ("Path", "jid", "int", "是", ""),
         ("Query", "file", "string", "是", "文件名"),
     ],
     resp="文件流")

spec("POST", "/api/ai/training/jobs/<int:jid>/deploy",
     title="部署到模型库", auth="JWT + ai:training:edit",
     params=[
         ("Path", "jid", "int", "是", ""),
         ("Body", "modelName/modelKey/category/task/library/version/description", "any", "否", ""),
         ("Body", "forBadminton", "bool", "否", "羽毛球专用标记"),
     ],
     resp="新 AiModel")

# Face
spec("GET", "/api/ai/face/persons",
     title="人脸库人员列表", auth="JWT + ai:face:list",
     params=[("Query", "name", "string", "否", "")],
     resp='`{ rows, total }`')

spec("GET", "/api/ai/face/persons/<int:pid>",
     title="人员详情（含特征）", auth="JWT + ai:face:list",
     params=[("Path", "pid", "int", "是", "")],
     resp="person + embeddings")

spec("POST", "/api/ai/face/persons",
     title="新建人员", auth="JWT + ai:face:add",
     params=[
         ("Body", "name", "string", "是", ""),
         ("Body", "employeeNo/remark/status", "string", "否", ""),
     ],
     resp="person")

spec("PUT", "/api/ai/face/persons/<int:pid>",
     title="更新人员", auth="JWT + ai:face:edit",
     params=[("Path", "pid", "int", "是", ""), ("Body", "name/employeeNo/remark/status", "any", "否", "")],
     resp="person")

spec("DELETE", "/api/ai/face/persons/<int:pid>",
     title="删除人员", auth="JWT + ai:face:remove",
     params=[("Path", "pid", "int", "是", "")], resp="成功消息")

spec("POST", "/api/ai/face/persons/<int:pid>/enroll",
     title="登记人脸特征", auth="JWT + ai:face:add",
     params=[
         ("Path", "pid", "int", "是", ""),
         ("Form", "modelId", "int", "是", "InsightFace 模型"),
         ("Form", "files 或 file", "file[]", "是", "可多图平均"),
     ],
     resp="person + embeddings",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/face/persons/1/enroll \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "modelId=5" -F "files=@./face1.jpg" -F "files=@./face2.jpg"
```""")

spec("POST", "/api/ai/face/recognize",
     title="1:N 人脸识别", auth="JWT + ai:face:list",
     params=[
         ("Form", "file 或 image", "file", "是", ""),
         ("Form", "modelId", "int", "是", ""),
         ("Form", "threshold", "float", "否", "默认 0.4"),
         ("Form", "detThresh", "float", "否", "默认 0.5"),
         ("Form", "draw", "string", "否", "1 画框"),
     ],
     resp="faces / matched / person 等",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/face/recognize \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@./probe.jpg" -F "modelId=5" -F "threshold=0.4"
# Open 桥接等价:
curl -s -X POST http://127.0.0.1:5001/openapi/v1/x/ai/face/recognize \\
  -H "X-App-Id: app_face" -H "X-Api-Key: $API_KEY" \\
  -F "file=@./probe.jpg" -F "modelId=5"
```""")

# Vehicle
spec("POST", "/api/ai/vehicle/detect-image",
     title="车辆/车牌检测（单图）", auth="JWT + ai:vehicle:list",
     params=[
         ("Form", "file", "file", "是", ""),
         ("Form", "detectId", "int", "是", "车辆检测模型"),
         ("Form", "plateId", "int", "否", "车牌检测"),
         ("Form", "detId/recId", "int", "否", "车牌 OCR"),
         ("Form", "conf/imgsz", "float/int", "否", ""),
         ("Form", "enableOcr/plateConf/vehicleOnly", "any", "否", ""),
     ],
     resp='`{ detections, count, plateCount, imageBase64, congestion }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/vehicle/detect-image \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "file=@./road.jpg" -F "detectId=2" -F "enableOcr=1" -F "detId=3" -F "recId=4"
```""")

spec("POST", "/api/ai/vehicle/track-frame",
     title="车辆单帧跟踪", auth="JWT + ai:vehicle:list",
     params=[
         ("Form", "file", "file", "是", ""),
         ("Form", "detectId", "int", "是", ""),
         ("Form", "line", "string", "否", "JSON[4] 计数线"),
         ("Form", "enableSpeed/metersPerPixel", "any", "否", ""),
         ("Form", "sessionId", "string", "否", "会话"),
         ("Form", "reset", "string", "否", "1 重置"),
         ("Form", "congestionLight/Moderate/Heavy", "float", "否", "拥堵阈值"),
         ("Form", "其余同 detect-image 模型参数", "any", "否", ""),
     ],
     resp="enriched detections + sessionId")

spec("POST", "/api/ai/vehicle/track-video",
     title="车辆视频跟踪（异步）", auth="JWT + ai:vehicle:list",
     params=[
         ("Form", "file", "file", "是", "视频"),
         ("Form", "detectId", "int", "是", ""),
         ("Form", "line/alertEnabled/alertRuleKeys/sessionId 等", "any", "否", ""),
     ],
     resp='`{ jobId, sessionId }`')

spec("GET", "/api/ai/vehicle/video-progress/<job_id>",
     title="车辆视频进度", auth="JWT + ai:vehicle:list",
     params=[("Path", "job_id", "string", "是", "")], resp="进度")

spec("GET", "/api/ai/vehicle/output/<path:name>",
     title="车辆输出视频", auth="JWT + ai:vehicle:list",
     params=[("Path", "name", "string", "是", "")], resp="mp4 流")

spec("POST", "/api/ai/vehicle/reset-session",
     title="重置跟踪会话", auth="JWT + ai:vehicle:list",
     params=[("Body/Form", "sessionId", "string", "是", "")], resp="成功消息")

spec("POST", "/api/ai/vehicle/export-records",
     title="导出过车记录 CSV", auth="JWT + ai:vehicle:list",
     params=[("Body/Form", "sessionId", "string", "是", "")],
     resp='`{ csv, count }`')

# Water
spec("POST", "/api/ai/water-level/detect",
     title="水位尺读数", auth="JWT + ai:water:list",
     params=[
         ("Form", "image", "file", "是", "图片"),
         ("Form", "detId", "int", "是", "刻度检测"),
         ("Form", "recId", "int", "是", "刻度识别"),
         ("Form", "waterYRatio", "float", "否", "0–1 水面 Y 比"),
     ],
     resp='`{ level, waterY, waterYRatio, surfaceConfidence, method, marks, imageBase64, ... }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/water-level/detect \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "image=@./gauge.jpg" -F "detId=12" -F "recId=13"
```""")

# Table
spec("POST", "/api/ai/table/recognize",
     title="表格识别", auth="JWT + ai:table:list",
     params=[
         ("Form", "file 或 image", "file", "是", ""),
         ("Form", "detectId", "int", "是", "表格/单元格检测"),
         ("Form", "detId/recId", "int", "是", "OCR"),
         ("Form", "tableId", "int", "是", "表格结构模型"),
         ("Form", "conf", "float", "否", "0.25"),
     ],
     resp='`{ tables, tableCount, detections, imageBase64, ... }`')

# Badminton
spec("POST", "/api/ai/badminton/extract-frame",
     title="提取球场标定帧", auth="JWT + ai:badminton:list",
     params=[
         ("Form", "video", "file", "是", ""),
         ("Form", "autoDetect", "bool", "否", "自动检场"),
     ],
     resp="帧图 base64 等")

spec("POST", "/api/ai/badminton/detect-court",
     title="自动检测球场点", auth="JWT + ai:badminton:list",
     params=[("Form", "video", "file", "是", "")],
     resp="courtPoints 等")

spec("POST", "/api/ai/badminton/analyze",
     title="羽毛球视频分析（异步）", auth="JWT + ai:badminton:list",
     params=[
         ("Form", "video", "file", "是", ""),
         ("Form", "poseId", "int", "是", "姿态模型"),
         ("Form", "ballId", "int", "否", "羽毛球检测"),
         ("Form", "courtPoints", "string", "是", "JSON[4] 四角"),
         ("Form", "netPoints", "string", "否", "JSON[2]"),
         ("Form", "conf/ballConf", "float", "否", ""),
         ("Form", "language", "string", "否", "zh|en"),
         ("Form", "showSkeleton/Trajectories/Shuttle/Stats/Court", "bool", "否", "叠加开关"),
     ],
     resp='`{ jobId }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/ai/badminton/analyze \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "video=@./match.mp4" -F "poseId=20" \\
  -F 'courtPoints=[[0.1,0.2],[0.9,0.2],[0.9,0.9],[0.1,0.9]]'
```""")

spec("GET", "/api/ai/badminton/progress/<job_id>",
     title="分析进度", auth="JWT + ai:badminton:list",
     params=[("Path", "job_id", "string", "是", "")],
     resp='`{ status, processed, total, stats?, artifacts? }`')

spec("GET", "/api/ai/badminton/artifact/<job_id>/<path:name>",
     title="分析产物下载", auth="JWT + ai:badminton:list",
     params=[("Path", "job_id/name", "any", "是", "video/heatmap/...")],
     resp="文件流")

# Alert
spec("GET", "/api/alerts/rules",
     title="告警规则列表", auth="JWT + ai:alert:list",
     params=[], resp="rules[]")

spec("GET", "/api/alerts/rules/<int:rid>",
     title="告警规则详情", auth="JWT + ai:alert:query",
     params=[("Path", "rid", "int", "是", "")], resp="rule")

spec("PUT", "/api/alerts/rules/<int:rid>",
     title="更新告警规则", auth="JWT + ai:alert:edit",
     params=[
         ("Path", "rid", "int", "是", ""),
         ("Body", "name/description/severity/status", "any", "否", "severity: low|medium|high"),
         ("Body", "config", "object", "否", "阈值/classes/line/direction/overlay/模板"),
     ],
     resp="rule")

spec("GET", "/api/alerts/events",
     title="告警事件分页", auth="JWT + ai:alert:list",
     params=[
         ("Query", "pageNum", "int", "否", "1"),
         ("Query", "pageSize", "int", "否", "≤100"),
         ("Query", "status", "string", "否", "0 未确认 / 1 已确认"),
         ("Query", "ruleKey", "string", "否", ""),
     ],
     resp='`{ rows, total }`')

spec("PUT", "/api/alerts/events/<int:eid>/ack",
     title="确认告警事件", auth="JWT + ai:alert:edit",
     params=[("Path", "eid", "int", "是", "")], resp="成功消息")

spec("DELETE", "/api/alerts/events/<int:eid>",
     title="删除告警事件", auth="JWT + ai:alert:remove",
     params=[("Path", "eid", "int", "是", "")], resp="成功消息")

spec("POST", "/api/alerts/evaluate",
     title="实时评估告警", auth="JWT + ai:alert:list",
     desc="对一帧 detections 跑规则引擎。",
     params=[
         ("Body", "detections", "array", "是", ""),
         ("Body", "sourceKey/sourceType/modelId", "any", "否", ""),
         ("Body", "persist", "bool", "否", "默认 true"),
         ("Body", "frameWidth/frameHeight", "int", "否", ""),
         ("Body", "line", "array", "否", "越线"),
         ("Body", "frameToken/ruleKeys", "any", "否", ""),
     ],
     resp='`{ triggered, overlay }`',
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/alerts/evaluate \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"detections":[{"className":"person","conf":0.9,"xyxy":[10,10,100,200]}],"sourceKey":"cam1"}'
```""")

spec("POST", "/api/alerts/reset-runtime",
     title="重置告警运行时状态", auth="JWT + ai:alert:list",
     params=[("Body", "sourceKey", "string", "否", "指定源；空=全部")],
     resp="成功消息")

# Open app admin
spec("GET", "/api/system/open-app/scopes",
     title="Scope / 域目录", auth="JWT + system:openapp:list",
     desc="开放平台元数据：全部域、端点、建议 appId。**不可桥接**。",
     params=[],
     resp="scopes / groups / domains / stats",
     example="""```bash
curl -s http://127.0.0.1:5001/api/system/open-app/scopes \\
  -H "Authorization: Bearer $TOKEN"
```""")

spec("GET", "/api/system/open-app",
     title="开放应用列表", auth="JWT + system:openapp:list",
     params=[
         ("Query", "pageNum/pageSize", "int", "否", "1 / 50"),
         ("Query", "name", "string", "否", ""),
         ("Query", "domainId", "string", "否", "如 face"),
         ("Query", "category", "string", "否", "分组"),
     ],
     resp='`{ rows, total }`')

spec("GET", "/api/system/open-app/<int:aid>",
     title="应用详情（含密钥摘要）", auth="JWT + system:openapp:query",
     params=[("Path", "aid", "int", "是", "")],
     resp="app.to_dict(with_keys=True)")

spec("POST", "/api/system/open-app/from-domain",
     title="按域一键创建应用", auth="JWT + system:openapp:add",
     params=[
         ("Body", "domainId", "string", "是", "如 face / ai_model"),
         ("Body", "name/appId/qpsLimit/dailyLimit/scopes", "any", "否", ""),
         ("Body", "createKey", "bool", "否", "默认 true"),
     ],
     resp="app + 一次性 apiKey",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/system/open-app/from-domain \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"domainId":"face","qpsLimit":20,"dailyLimit":5000}'
```""")

spec("POST", "/api/system/open-app/ensure-domains",
     title="一键对齐全部域应用", auth="JWT + system:openapp:add",
     desc="为每个域建/刷新应用，并创建 app_full_all。",
     params=[],
     resp='`{ created[], updated[], domainCount }`')

spec("POST", "/api/system/open-app",
     title="创建开放应用", auth="JWT + system:openapp:add",
     params=[
         ("Body", "name", "string", "是", ""),
         ("Body", "appId", "string", "否", "自动生成 app_xxx"),
         ("Body", "scopes", "string[]", "否", "或配合 domainId 自动全覆盖"),
         ("Body", "domainId/category", "string", "否", ""),
         ("Body", "qpsLimit", "int", "否", "默认 10"),
         ("Body", "dailyLimit", "int", "否", "默认 10000"),
         ("Body", "status/remark/keyName", "string", "否", ""),
         ("Body", "createKey", "bool", "否", "默认 true"),
         ("Body", "webhookUrl/webhookSecret/webhookEvents", "any", "否", ""),
     ],
     resp="201 app + apiKey（仅一次）",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/api/system/open-app \\
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\
  -d '{"name":"演示应用","scopes":["domain:ai_model","vision:detect"],"qpsLimit":10}'
```""")

spec("PUT", "/api/system/open-app/<int:aid>",
     title="更新开放应用", auth="JWT + system:openapp:edit",
     params=[("Path", "aid", "int", "是", ""), ("Body", "name/status/scopes/qpsLimit/dailyLimit/remark/domainId/category/webhook*", "any", "否", "")],
     resp="app")

spec("DELETE", "/api/system/open-app/<int:aid>",
     title="删除开放应用", auth="JWT + system:openapp:remove",
     params=[("Path", "aid", "int", "是", "")], resp="成功消息")

spec("POST", "/api/system/open-app/<int:aid>/keys",
     title="新建 API Key", auth="JWT + system:openapp:add",
     params=[
         ("Path", "aid", "int", "是", ""),
         ("Body", "name", "string", "否", "默认 default"),
     ],
     resp="key + 一次性 apiKey")

spec("PUT", "/api/system/open-app/<int:aid>/keys/<int:kid>",
     title="更新 API Key", auth="JWT + system:openapp:edit",
     params=[
         ("Path", "aid/kid", "int", "是", ""),
         ("Body", "name/status", "string", "否", "status 0|1"),
     ],
     resp="key")

spec("DELETE", "/api/system/open-app/<int:aid>/keys/<int:kid>",
     title="删除 API Key", auth="JWT + system:openapp:remove",
     params=[("Path", "aid/kid", "int", "是", "")], resp="成功消息")

spec("GET", "/api/system/open-app/<int:aid>/logs",
     title="调用审计日志", auth="JWT + system:openapp:query",
     params=[
         ("Path", "aid", "int", "是", ""),
         ("Query", "pageNum", "int", "否", "1"),
         ("Query", "pageSize", "int", "否", "≤100"),
     ],
     resp='`{ rows, total }`')

spec("GET", "/api/system/open-app/<int:aid>/usage",
     title="用量统计", auth="JWT + system:openapp:query",
     params=[
         ("Path", "aid", "int", "是", ""),
         ("Query", "days", "int", "否", "默认 7，≤90"),
     ],
     resp='`{ total, errorCount, daily[], byCapability[] }`')

spec("POST", "/api/system/open-app/<int:aid>/webhook/test",
     title="Webhook 连通性测试", auth="JWT + system:openapp:edit",
     params=[("Path", "aid", "int", "是", "")],
     resp="投递成功/失败")

# OpenAPI v1 meta
spec("GET", "/openapi/v1/health",
     title="Open API 存活", auth="公开",
     desc="含 uptime、对象存储、目录统计。",
     params=[],
     resp="status/version/catalog")

spec("GET", "/openapi/v1/openapi.json",
     title="OpenAPI 3.0 规范", auth="公开",
     params=[], resp="OpenAPI JSON")

spec("GET", "/openapi/v1/docs",
     title="Swagger UI", auth="公开",
     params=[], resp="HTML")

spec("GET", "/openapi/v1/metrics",
     title="Prometheus 指标", auth="公开",
     params=[], resp="text/plain")

spec("GET", "/openapi/v1/capabilities",
     title="当前应用能力视图", auth="AppKey",
     params=[],
     resp="scopes / domains / grantedCount / bridgeBase",
     example="""```bash
curl -s http://127.0.0.1:5001/openapi/v1/capabilities \\
  -H "X-App-Id: app_demo" -H "X-Api-Key: $API_KEY"
```""")

spec("GET", "/openapi/v1/catalog",
     title="分域 API 全量目录", auth="AppKey",
     params=[],
     resp="domains + endpoints + 授权状态")

spec("POST", "/openapi/v1/vision/detect",
     title="【精简】图片检测", auth="AppKey + vision:detect",
     params=[
         ("Form", "file 或 image", "file", "是", ""),
         ("Form", "modelId", "int", "是", ""),
         ("Form", "conf", "float", "否", "0.25"),
         ("Form", "draw", "string", "否", "1"),
         ("Form", "async", "string", "否", "1=异步返回 jobId"),
     ],
     resp="检测结果或 `{ jobId, status:queued }`",
     example="""```bash
curl -s -X POST http://127.0.0.1:5001/openapi/v1/vision/detect \\
  -H "X-App-Id: app_demo" -H "X-Api-Key: $API_KEY" \\
  -F "file=@./sample.jpg" -F "modelId=1"
```""")

spec("POST", "/openapi/v1/vision/ocr",
     title="【精简】OCR", auth="AppKey + vision:ocr",
     params=[
         ("Form", "file", "file", "是", ""),
         ("Form", "detId", "int", "是", ""),
         ("Form", "recId", "int", "是", ""),
     ],
     resp="OCR 结果")

spec("POST", "/openapi/v1/face/recognize",
     title="【精简】人脸识别", auth="AppKey + face:recognize",
     params=[
         ("Form", "file", "file", "是", ""),
         ("Form", "modelId", "int", "是", ""),
         ("Form", "threshold/detThresh/draw", "any", "否", ""),
     ],
     resp="识别结果")

spec("POST", "/openapi/v1/water/read",
     title="【精简】水位读数", auth="AppKey + water:read",
     params=[
         ("Form", "file 或 image", "file", "是", ""),
         ("Form", "detId/recId", "int", "是", ""),
         ("Form", "waterYRatio", "float", "否", ""),
     ],
     resp="水位结果")

spec("GET", "/openapi/v1/jobs/<job_id>",
     title="开放异步任务查询", auth="AppKey + jobs:read",
     desc="按 appId 隔离；需 worker：`python scripts/open_job_worker.py`。",
     params=[("Path", "job_id", "string", "是", "")],
     resp="public_job 状态")

# Bridge catch-all (document once)
spec("ANY", "/openapi/v1/x/<path:subpath>",
     title="全量桥接网关", auth="AppKey + 目标 Scope",
     desc="将 `/openapi/v1/x/{去掉 /api/ 后的路径}` 内调对应 `/api/...`，透传 Query/Form/JSON/文件。禁止桥接 `/api/system/open-app` 与 `/openapi/v1` 自身。",
     params=[
         ("Path", "subpath", "string", "是", "如 ai/face/recognize"),
         ("Header", "X-App-Id", "string", "建议", ""),
         ("Header", "X-Api-Key", "string", "是", "或 Bearer"),
     ],
     resp="透传控制台响应",
     example="""```bash
# 等价 POST /api/ai/model/1/detect
curl -s -X POST http://127.0.0.1:5001/openapi/v1/x/ai/model/1/detect \\
  -H "X-App-Id: app_ai_model" -H "X-Api-Key: $API_KEY" \\
  -F "file=@./a.jpg" -F "conf=0.25"
```""")


def _norm_path(p: str) -> str:
    return p


def lookup(method: str, path: str) -> dict | None:
    key = f"{method.upper()}|{path}"
    if key in SPECS:
        return SPECS[key]
    # flask converter variants already in catalog as <int:uid>
    return SPECS.get(key)


def render_params(params: list) -> str:
    if not params:
        return "_无参数_\n"
    lines = ["| 位置 | 名称 | 类型 | 必填 | 说明 |", "|---|---|---|---|---|"]
    for loc, name, typ, req, note in params:
        lines.append(f"| {loc} | `{name}` | {typ} | {req} | {note} |")
    return "\n".join(lines) + "\n"


def render_endpoint(ep: dict, idx: int) -> str:
    method = ep["method"]
    path = ep["path"]
    s = lookup(method, path) or {}
    title = s.get("title") or ep.get("summary") or path
    auth = s.get("auth") or (
        "公开" if ep.get("auth") == "public"
        else f"JWT + `{ep.get('scope')}`" if ep.get("auth") == "perm"
        else f"`{ep.get('scope')}`"
    )
    desc = s.get("desc") or ep.get("summary") or ""
    open_path = ep.get("openPath")
    bridge = ep.get("bridgeable")

    parts = [
        f"### {idx}. `{method}` `{path}` — {title}",
        "",
        f"- **鉴权 / Scope**：{auth}",
        f"- **控制台权限标识**：`{ep.get('scope')}`",
        f"- **可桥接**：{'是 → `' + open_path + '`' if bridge and open_path else '否（仅控制台）'}",
        f"- **说明**：{desc}",
        "",
        "**参数**",
        "",
        render_params(s.get("params") or _hints_as_params(ep.get("hints") or {})),
    ]
    if s.get("resp"):
        parts += ["**响应**", "", s["resp"], ""]
    else:
        parts += ["**响应**", "", "统一信封：`{ code:0|非0, message?, data? }`（Open 侧另含 `requestId`）", ""]
    if s.get("example"):
        parts += ["**示例**", "", s["example"], ""]
    elif bridge and open_path and method in ("GET", "POST", "PUT", "DELETE"):
        parts += [
            "**示例（Open 桥接）**",
            "",
            "```bash",
            f'curl -s -X {method} "http://127.0.0.1:5001{open_path}" \\',
            '  -H "X-App-Id: $APP_ID" -H "X-Api-Key: $API_KEY"',
            "```",
            "",
        ]
    return "\n".join(parts)


def _hints_as_params(hints: dict) -> list:
    rows = []
    for k in hints.get("query") or []:
        rows.append(("Query", k, "string", "否", "见实现"))
    for k in hints.get("form") or []:
        rows.append(("Form", k, "string", "否", "见实现"))
    for k in hints.get("files") or []:
        rows.append(("Form", k, "file", "视接口", "上传文件"))
    for k in hints.get("jsonKeys") or []:
        rows.append(("Body", k, "any", "视接口", "JSON 字段"))
    return rows


def main():
    stats = CATALOG["stats"]
    lines: list[str] = []
    lines += [
        "# TigerPro API 开放管理平台文档",
        "",
        "> 版本：与仓库后端同步 · 端点目录来自 `backend/services/openapi_catalog.py`",
        ">",
        (
            f"> 目录规模：**{stats['endpointCount']}** 个已扫描端点，"
            f"**{stats['bridgeableCount']}** 个可经 Open 桥接，"
            f"**{stats['domainCount']}** 个业务域，**{stats['scopeCount']}** 个 Scope。"
        ),
        ">",
        "> 交互文档：`GET /openapi/v1/docs` · 规范：`GET /openapi/v1/openapi.json`",
        "",
        "---",
        "",
        "## 目录",
        "",
        "1. [概述与访问地址](#1-概述与访问地址)",
        "2. [鉴权与响应约定](#2-鉴权与响应约定)",
        "3. [开放平台管理（控制台）](#3-开放平台管理控制台)",
        "4. [Open API v1 与桥接](#4-open-api-v1-与桥接)",
        "5. [业务域 API 详解](#5-业务域-api-详解)",
        "6. [错误码与限流](#6-错误码与限流)",
        "7. [附录：快速索引表](#7-附录快速索引表)",
        "",
        "---",
        "",
        "## 1. 概述与访问地址",
        "",
        "| 项 | 说明 |",
        "|---|---|",
        "| 主服务 | `http://<host>:5001`（`backend/app.py`） |",
        "| 网关-only | `http://<host>:5002`（`gateway_app.py`，仅 `/openapi/*`） |",
        "| 控制台 API 前缀 | `/api/*`（JWT + RBAC） |",
        "| 开放 API 前缀 | `/openapi/v1/*`（AppId + ApiKey） |",
        "| 桥接规则 | `/openapi/v1/x/<去掉 /api/ 后的路径>` → 内调 `/api/...` |",
        "| 异步 Open 任务 | 需运行 `python scripts/open_job_worker.py` |",
        "",
        "平台同时提供：",
        "",
        "- **控制台 API**：供 Vue 管理端使用，`Authorization: Bearer <JWT>`。",
        "- **开放 API**：供第三方集成；精简别名（detect/ocr/face/water）+ **全量桥接**（约 148 条）。",
        "- **开放应用管理**：在控制台创建 App、分配 Scope、查看用量与 Webhook（**不可**经桥接外泄）。",
        "",
        "---",
        "",
        "## 2. 鉴权与响应约定",
        "",
        "### 2.1 控制台（JWT）",
        "",
        "```http",
        "Authorization: Bearer <access_token>",
        "Content-Type: application/json",
        "```",
        "",
        "登录：`POST /api/auth/login` → `data.token`。",
        "权限：接口上的 `@permission_required(\"a:b:c\")` 须出现在用户 `permissions` 中（admin 放行）。",
        "",
        "### 2.2 开放平台（AppKey）",
        "",
        "```http",
        "X-App-Id: app_xxx",
        "X-Api-Key: tp_live_...",
        "```",
        "",
        "或 `Authorization: Bearer <api_key>`（建议仍带 `X-App-Id`）。",
        "",
        "**Scope 匹配规则**：",
        "",
        "| 授权写法 | 含义 |",
        "|---|---|",
        "| `ai:face:list` | 精确权限（与 RBAC 相同） |",
        "| `domain:face` | 该业务域全部可桥接接口 |",
        "| `vision:*` | 前缀通配 |",
        "| `*:*:*` / `*` | 超管 |",
        "| 旧别名 | `vision:detect`→`ai:model:query` 等（见 `LEGACY_SCOPE_ALIASES`） |",
        "",
        "### 2.3 响应信封",
        "",
        "**控制台**",
        "",
        "```json",
        '{ "code": 0, "message": "ok", "data": {} }',
        "```",
        "",
        "`code === 0` 表示业务成功；HTTP 状态码可能同时为 4xx/5xx。",
        "",
        "**Open API**",
        "",
        "```json",
        '{ "code": 0, "message": "ok", "requestId": "…", "data": {} }',
        "```",
        "",
        "失败时含 `error: { type, message }`，响应头带 `X-Request-Id`。",
        "",
        "### 2.4 状态码约定",
        "",
        "| HTTP / code | 含义 |",
        "|---|---|",
        "| 200 / 0 | 成功 |",
        "| 201 | 创建成功 |",
        "| 400 | 参数错误 |",
        "| 401 | 未登录 / Key 无效 |",
        "| 403 | 无权限 / Scope 不足 |",
        "| 404 | 资源不存在 |",
        "| 409 | 冲突（重名等） |",
        "| 429 | QPS / 日限额 |",
        "| 500 / 502 | 服务端错误 |",
        "",
        "---",
        "",
        "## 3. 开放平台管理（控制台）",
        "",
        "管理端前缀：`/api/system/open-app`（**禁止桥接**）。",
        "需要 JWT 权限 `system:openapp:*`。",
        "",
        "推荐流程：",
        "",
        "1. `GET /scopes` 查看域与端点目录",
        "2. `POST /from-domain` 或 `POST /ensure-domains` 创建应用并拿到一次性 `apiKey`",
        "3. 第三方使用 `X-App-Id` + `X-Api-Key` 调用 `/openapi/v1/...`",
        "4. `GET /{aid}/usage`、`GET /{aid}/logs` 观测用量",
        "",
        "Webhook 事件：`job.succeeded` / `job.failed` / `api.call` / `*`。",
        "",
        "（本节各接口的完整参数见下文「开放平台管理」域。）",
        "",
        "---",
        "",
        "## 4. Open API v1 与桥接",
        "",
        "### 4.1 元接口",
        "",
        "| Method | Path | 鉴权 | 说明 |",
        "|---|---|---|---|",
        "| GET | `/openapi/v1/health` | 公开 | 存活 + 目录统计 |",
        "| GET | `/openapi/v1/docs` | 公开 | Swagger UI |",
        "| GET | `/openapi/v1/openapi.json` | 公开 | OpenAPI 3.0 |",
        "| GET | `/openapi/v1/metrics` | 公开 | Prometheus |",
        "| GET | `/openapi/v1/capabilities` | AppKey | 当前应用授权视图 |",
        "| GET | `/openapi/v1/catalog` | AppKey | 分域全量目录 |",
        "",
        "### 4.2 精简别名",
        "",
        "| Method | Path | Scope |",
        "|---|---|---|",
        "| POST | `/openapi/v1/vision/detect` | `vision:detect` |",
        "| POST | `/openapi/v1/vision/ocr` | `vision:ocr` |",
        "| POST | `/openapi/v1/face/recognize` | `face:recognize` |",
        "| POST | `/openapi/v1/water/read` | `water:read` |",
        "| GET | `/openapi/v1/jobs/<job_id>` | `jobs:read` |",
        "",
        "### 4.3 全量桥接",
        "",
        "```text",
        "控制台:  POST /api/ai/face/recognize",
        "开放:    POST /openapi/v1/x/ai/face/recognize",
        "```",
        "",
        "支持 GET/POST/PUT/PATCH/DELETE；透传 query、form、json、files。",
        "不可桥接：`/api/system/open-app/**`、`/openapi/v1/**`。",
        "",
        "```bash",
        "# 等价 POST /api/ai/model/1/detect",
        "curl -s -X POST http://127.0.0.1:5001/openapi/v1/x/ai/model/1/detect \\",
        '  -H "X-App-Id: app_ai_model" -H "X-Api-Key: $API_KEY" \\',
        '  -F "file=@./a.jpg" -F "conf=0.25"',
        "```",
        "",
        "---",
        "",
        "## 5. 业务域 API 详解",
        "",
    ]

    global_idx = 0
    for d in CATALOG["domains"]:
        lines += [
            f"### 5.{d['order'] if d['order'] else '0'} {d['label']}（`{d['id']}`）",
            "",
            f"- **分组**：{d.get('groupLabel')}（`{d.get('group')}`）",
            f"- **风险**：{d.get('risk')}",
            f"- **域 Scope**：`{d.get('domainScope')}`",
            f"- **端点数**：{d.get('endpointCount')}（可桥接 {d.get('bridgeableCount')}）",
            "",
        ]
        eps = sorted(d["endpoints"], key=lambda e: (e["path"], e["method"]))
        for ep in eps:
            global_idx += 1
            lines.append(render_endpoint(ep, global_idx))
            lines.append("")

    lines += [
        "---",
        "",
        "## 6. 错误码与限流",
        "",
        "### 6.1 Open 限流",
        "",
        "应用字段：",
        "",
        "- `qpsLimit`：每秒请求上限（进程内滑动窗口）",
        "- `dailyLimit`：自然日调用上限",
        "",
        "超限返回 HTTP 429，`error.type = rate_limited`。",
        "",
        "### 6.2 常见业务错误",
        "",
        "| message 关键字 | 处理建议 |",
        "|---|---|",
        "| 缺少 API Key | 检查 Header |",
        "| 缺少能力授权 | 为应用追加 Scope 或 `domain:*` |",
        "| 该模型暂无本地权重 | 先 `POST .../fetch` 或 upload |",
        "| 未接收到图片/文件 | multipart 字段名 `file`/`image` |",
        "| 登录已过期 | 重新 `POST /api/auth/login` |",
        "",
        "---",
        "",
        "## 7. 附录：快速索引表",
        "",
        "| # | Method | Path | Scope | 可桥接 | Open Path |",
        "|---|---|---|---|---|---|",
    ]

    n = 0
    for d in CATALOG["domains"]:
        for ep in sorted(d["endpoints"], key=lambda e: (e["path"], e["method"])):
            n += 1
            open_p = ep.get("openPath") or "-"
            bridge = "Y" if ep.get("bridgeable") else "N"
            lines.append(
                f"| {n} | {ep['method']} | `{ep['path']}` | `{ep.get('scope')}` | {bridge} | `{open_p}` |"
            )

    lines += [
        "",
        "---",
        "",
        "## 附录 B：一站式调用示例",
        "",
        "### B.1 控制台登录 → 检测",
        "",
        "```bash",
        'TOKEN=$(curl -s -X POST http://127.0.0.1:5001/api/auth/login \\',
        '  -H "Content-Type: application/json" \\',
        '  -d \'{"username":"admin","password":"admin123"}\' | python -c "import sys,json;print(json.load(sys.stdin)[\'data\'][\'token\'])")',
        "",
        "curl -s -X POST http://127.0.0.1:5001/api/ai/model/1/detect \\",
        '  -H "Authorization: Bearer $TOKEN" \\',
        '  -F "file=@./sample.jpg" -F "conf=0.25"',
        "```",
        "",
        "### B.2 开放平台：按域建应用 → 桥接调用",
        "",
        "```bash",
        "curl -s -X POST http://127.0.0.1:5001/api/system/open-app/from-domain \\",
        '  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \\',
        '  -d \'{"domainId":"ai_model"}\'',
        "",
        "curl -s -X POST http://127.0.0.1:5001/openapi/v1/x/ai/model/1/detect \\",
        '  -H "X-App-Id: app_ai_model" -H "X-Api-Key: $API_KEY" \\',
        '  -F "file=@./sample.jpg"',
        "```",
        "",
        "### B.3 精简别名 + 异步任务",
        "",
        "```bash",
        "curl -s -X POST http://127.0.0.1:5001/openapi/v1/vision/detect \\",
        '  -H "X-App-Id: app_demo" -H "X-Api-Key: $API_KEY" \\',
        '  -F "file=@./sample.jpg" -F "modelId=1" -F "async=1"',
        "# → data.jobId ；另开终端: python scripts/open_job_worker.py",
        "curl -s http://127.0.0.1:5001/openapi/v1/jobs/$JOB_ID \\",
        '  -H "X-App-Id: app_demo" -H "X-Api-Key: $API_KEY"',
        "```",
        "",
        "---",
        "",
        "*文档由 `backend/_gen_api_docs.py` 根据路由扫描结果与规格表生成。如路由变更，请重新运行生成脚本。*",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({n} endpoints, {OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
