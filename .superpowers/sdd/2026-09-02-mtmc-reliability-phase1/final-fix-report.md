# MTMC 可靠性 Phase 1 最终修复报告

## 状态

DONE_WITH_CONCERNS

## 基线与范围

- 修复基线：`be3ecbededc24f8644acb164802fe312f09b7a98`
- 分支：按授权直接在 `main` 完成，不创建 worktree，不委派子代理。
- 范围：处理最终整体审查列出的全部 Critical / Important 项，以及 Active Gallery 精确空间和真实流 grace 两项 minor；同时补齐回归、运行态展示、停止 API 语义和本报告。

## RED 证据

第一组后端回归在生产修复前执行：

```text
pytest backend/unittests/test_mtmc_phase1_final_fixes.py -q -p no:cacheprovider
10 failed, 1 skipped
```

失败覆盖：FAISS 冷缓存自死锁、sticky 终结未提交聚合证据、拓扑/粘性使用错误的全局摘要时间、builder 早于 tracker `max_age` 终结、OCR 缓存重复投票、车辆哈希身份键、跨维度/版本比较、车辆模型空间丢失和 shortlist 未携带精确空间。

第二组停止可靠性回归在实现前执行：

```text
pytest backend/unittests/test_mtmc_phase1_final_fixes.py -q -p no:cacheprovider
3 failed, 10 passed, 1 skipped
```

失败证明外部 stop 超时没有结构化 pending 状态，终结异常会先移除 builder，并且 stop 失败后没有保留资源供重试。

前端契约实现前执行：

```text
node --test src/utils/mtmcRuntimeStatus.test.js
5 failed, 14 passed
```

失败覆盖拓扑 `edgeType/weight` 保真与校验、逐相机 active/lost 展示、候选完整分数组成，以及只有 `stopped` 才能清理前端会话状态的规则。

## 修复结果

1. 注册人员 Gallery 的 FAISS 冷索引构建移出普通锁，并以 generation 双检防止构建期间的失效操作被旧索引覆盖；假 FAISS 子进程用硬超时验证不再自死锁。
2. Tracklet 终结若仍保持同一 local→Global 粘性绑定，会通过原子 `commit_bound_tracklet` 提交聚合 embedding、精确模型空间、车牌/人员身份和 Active Gallery 原型，不再仅返回旧 Global，也不会错误新建替代 ID。
3. 长期匹配和 sticky 过期以 `cameraObservations` 为事实源；拓扑对所有真实相机观测选择可行来源并记录 `sourceCameraId/sourceObservedAt`。同时拒绝用目的相机的陈旧观测把已前进到新相机的 Global 拉回，保留延迟帧防振荡约束。
4. builder 的超时 grace 取 `max(lostReviveSec, localTrackMaxAge / sampleFps)`；tracker 显式 removal 仍可立即终结，短暂 miss 不再提前切断真实流 tracklet。
5. 车牌 OCR 拥有独立的 cooldown/质量提升采样器和预算，不再依赖车辆 ReID 是否采样；显示缓存不会阻止后续更优 OCR，也不会被逐帧重复计票。聚合只对真实 OCR observation 投票。
6. 车辆持久身份键只采用可靠车牌；精确浮点 embedding 哈希保留为诊断 `visualKey`，无牌车辆不再产生 `NOPLATE|hash` 身份。
7. 车辆相似度禁止跨维度补零和跨版本比较。Extractor 的实际 backend、维度与 ONNX 文件版本现在以 `(model_key, dim, model_version)` 贯穿 builder、Global、Active Gallery 和候选原型查询；直方图回退使用独立稳定空间。
8. Active Gallery shortlist 可选携带精确模型空间，旧的二元 tuple 调用保持兼容；Global 快照新增 `prototypeCount` 和逐相机观测状态。
9. 移除 builder 改为“终结/持久化成功后再 pop”。失败 builder、local 绑定和上传资源均保留，`builders_flushed` 不会虚假置真，运行态写入可重试的 finalization failure；后续 stop 可重新尝试并在成功后恢复 ready。
10. stop 新增 `not_found / pending / failed / stopped` 结构化状态。外部 join 超时也会安排后台最终协调器；HTTP 分别返回 404、202、503、200，布尔 `stop_session` 兼容包装继续保留。
11. 前端 stop 只在收到 `stopped` 后清除 session ID 并显示成功；pending 保留 ID 并提示重试，HTTP failure 不再被吞掉。启动新会话前若旧会话仍 pending，也不会越过停止失败继续启动。
12. 拓扑表单和 API 显式支持并校验 `overlap/non_overlap` 与 `weight`，保留合法的零权重，拒绝同相机、自相矛盾时间窗和非法数值；表格展示实际边类型与权重。
13. 工作台 Global 表展示 prototype 数和逐相机 active/lost 状态；候选表统一展示 best、second、margin、appearance、topology、time、final。持久化候选响应新增这些扁平字段，同时保留旧 `evidence`、`finalScore`、`reidScore`。

## GREEN 与最终验证

新增最终修复回归：

```text
pytest backend/unittests/test_mtmc_phase1_final_fixes.py -q -p no:cacheprovider
18 passed, 1 skipped in 2.70s
```

所有 MTMC 测试（PowerShell 文件枚举，避免通配符不展开）：

```text
$phase1Tests = (Get-ChildItem 'backend/unittests' -File -Filter 'test_mtmc*.py').FullName
python -u -m pytest $phase1Tests -q -p no:cacheprovider --basetemp .pytest-phase1-all-final
203 passed, 1 skipped, 44 warnings in 147.37s
```

Vehicle 回归：

```text
python -u -m pytest backend/unittests/test_vehicle_zone.py backend/unittests/test_vehicle_speed.py -q -p no:cacheprovider
67 passed in 1.33s
```

前端纯函数：

```text
node --test src/utils/mtmcRuntimeStatus.test.js
19 passed, 0 failed
```

前端生产构建：

```text
npm run build
2731 modules transformed
built in 26.46s
exit code 0
```

Python 语法检查：

```text
python -m py_compile backend/models/mtmc.py backend/routes/mtmc.py backend/services/mtmc_active_gallery.py backend/services/mtmc_associator.py backend/services/mtmc_engine.py backend/services/mtmc_tracklet.py backend/services/reid_gallery.py backend/services/vehicle_reid_feat.py backend/unittests/test_mtmc_phase1_final_fixes.py
exit code 0
```

`git diff --check` 退出码为 0；仅显示 Windows 工作树既有的 LF→CRLF 提示，没有空白错误。

## 兼容性与关注项

- API 兼容：原 Session、Global、Candidate 嵌套字段保留；`stop_session()` 布尔接口仍存在，新路由采用结构化状态；Active Gallery 默认仍返回旧二元 tuple。
- 数据兼容：未新增数据库列或迁移；候选分解从既有 `evidence_json` 派生，旧记录缺失字段时安全返回空值。
- 环境边界：当前环境未安装可选 `faiss-cpu`，因此真实 FAISS 冷缓存用例跳过；等价 fake index 已在独立子进程内通过 3 秒死锁哨兵。部署环境应再执行真实 FAISS 用例。
- 硬件边界：未连接生产摄像头、GPU 或真实 ReID/OCR 模型；精确模型版本与跨镜策略已由合成流和 stub 覆盖，仍建议在部署环境以真实首帧确认 provider/资产状态。
- 既有告警：44 条 pytest warning 为 `datetime.utcnow()` 与 SQLAlchemy `Query.get()` 弃用提示；Vite 仍报告第三方 PURE 注释和大 chunk 警告，均不影响退出码，且不属于本轮修复范围。
