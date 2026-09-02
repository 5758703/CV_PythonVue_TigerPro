# 任务 6 报告：暴露 MTMC 运行时真值并补齐现场问题回归

## 状态

DONE_WITH_CONCERNS

## 基线与范围

- 基线提交：`7b5b563cb8c7f1fd8b867e05af56a114a6b16be5`
- 提交主题：`feat: expose MTMC runtime reliability`
- 范围严格限定在任务简报列出的后端运行时/API、MTMC 工作台、纯函数辅助模块与两组回归测试。

## RED 证据

生产代码修改前执行：

```text
pytest backend/unittests/test_mtmc_runtime_status.py backend/unittests/test_mtmc_stream_regressions.py -q -p no:cacheprovider
4 failed, 3 passed
```

失败分别证明：会话缺少有效阈值/有向拓扑策略、Strong ReID 降级后的实际 Youtu 运行状态与预算不可见、关联 API 缺少独立扁平分数字段，以及延迟帧回放未经过流引擎 sticky 边界时会发生振荡。

前端纯函数尚不存在时执行：

```text
node --test src/utils/mtmcRuntimeStatus.test.js
6 failed, 0 passed
```

后续新增的两条真实性用例也分别先观察到 RED：人员 Strong 输入尺寸不得从模型名猜测；车辆模型版本必须优先采用实际加载的 ONNX 文件名而非目录标签。Gallery 降级风险呈现用例也先失败，再进行最小实现。

## 实现结果

- 会话 `runtime` 现在暴露有效模型键/版本、就绪状态、实际后端、输入尺寸、向量维度、降级原因、按相机运行观测、三类预算的累计与最近帧队列/消耗/跳过计数、有效阈值和精确有向拓扑策略。
- Strong 失败而 Youtu 成功时，人员 ReID 保持可用但明确标记降级；Strong 输入尺寸只读取已加载 ONNX 会话的 NCHW，不按模型名推断；车辆版本优先采用实际 ONNX 资产名，直方图回退显式可见。
- 关联列表保留原 `scores`/`evidence` 字段，并新增 `appearanceScore`、`topologyScore`、`timeScore`、`margin`、`finalScore`；最终关联分数不会误用事件分数。
- MTMC 工作台新增“运行飞行记录器”，展示实际模型、风险、预算、有效阈值和有向拓扑；关联证据拆分为五列；高级关联控制默认折叠，且未新增模型 ID 请求字段，继续采用后端推荐模型默认值。
- 新增四组确定性合成回放，覆盖错误复用、静态目标局部 ID 切换、合法 non-overlap 跨镜续接失败、延迟帧引发 Global ID 振荡。
- 自审发现并修正一次采样语义回归：预算耗尽时必须短路，不能调用关键帧采样器并产生预留副作用。

## GREEN 与最终验证

focused 后端：

```text
pytest backend/unittests/test_mtmc_runtime_status.py backend/unittests/test_mtmc_stream_regressions.py -q -p no:cacheprovider
9 passed in 3.62s
```

PowerShell 不会把 pytest 参数中的 `backend/unittests/test_mtmc*.py` 展开，直接照抄该参数会得到“file or directory not found”。使用等价的 PowerShell 文件枚举执行所有匹配测试：

```text
$task6MtmcTests = (Get-ChildItem 'backend/unittests' -File -Filter 'test_mtmc*.py').FullName
pytest @task6MtmcTests -q -p no:cacheprovider --basetemp '.pytest-task6-final'
161 passed, 35 warnings in 117.30s
```

35 条警告均来自既有 `datetime.datetime.utcnow()` 弃用提示；工作区内 pytest 临时目录已在验证绝对路径后删除。

前端纯函数：

```text
node --test src/utils/mtmcRuntimeStatus.test.js
7 passed, 0 failed
```

前端生产构建：

```text
npm run build
2731 modules transformed
built in 28.51s
exit code 0
```

Python 语法检查通过：

```text
python -m py_compile backend/services/mtmc_engine.py backend/routes/mtmc.py backend/unittests/test_mtmc_runtime_status.py backend/unittests/test_mtmc_stream_regressions.py
exit code 0
```

`git diff --check` 退出码为 0；只有 Windows 工作树的 LF→CRLF 提示，没有空白错误。

## 变更文件 SHA-256

```text
d816b92f04e02fba6bf504f5cb4cc53e7d23c36b8e91fa3e9746e556b131355d  backend/routes/mtmc.py
523cab9ae5f332936f4c72894214fa1ea8a3bf9a72c6a142544a7964f4192eeb  backend/services/mtmc_engine.py
2662dcdc785908565af3c45163029f5a88d6b6594e1b57f4b69e29e689ce7ba6  backend/unittests/test_mtmc_runtime_status.py
8b29fb38741121acf3f8ff052d373b26580639d049757d44e794bae08255c3d5  backend/unittests/test_mtmc_stream_regressions.py
9549f3dbddf52af98bd7c7b2fb1116e7060a8a8c29c89d4bdc9a17fe767c8f3e  frontend/frontend_admin/src/views/ai/mtmc/index.vue
5e52f876ad0d379e9634b653b5fe790ad219bad11b86f5e5c0470a7394ae9d5a  frontend/frontend_admin/src/utils/mtmcRuntimeStatus.js
25937ac91f7e53170a090f2f2534d593e0de7fe1c4eea87cf2a05664b25035a5  frontend/frontend_admin/src/utils/mtmcRuntimeStatus.test.js
```

## 自审与关注项

- 兼容性：会话旧字段、关联旧嵌套字段和后端推荐模型选择均保留；运行时字段为增量扩展。
- 并发性：运行状态与预算聚合使用会话锁，`to_dict()` 返回深复制快照；多相机失败不会被另一相机的成功静默覆盖。
- 可观测性：未实际执行过的模型保留“配置资产是否存在”的初始状态；ReID 一旦真实推理即由按相机实际观测覆盖，避免把回退说成主模型就绪。
- 环境边界：本机验证未加载生产 GPU/摄像头和真实模型资产，模型供应器/输入/维度的硬件实测仍需部署环境运行一帧后确认；UI 会在此前保持等待或显示资产级状态。
- 构建警告：Vite 仍报告第三方 `@vueuse/core` PURE 注释位置及既有大 chunk 警告，不影响构建成功，且不属于本任务范围。

---

## 审查修复轮次 1/5

### 状态与基线

- 状态：`DONE_WITH_CONCERNS`
- 审查基线：`0aa1a947c0393493995ceda165e1b81ad311cd99`（`feat: expose MTMC runtime reliability`）
- 本轮提交主题：`fix: report truthful MTMC runtime state`
- 范围：仅修复审查列出的 7 项 Important 问题，补充真实引擎边界、持久化链路和前端纯函数回归；没有新增产品入口或配置字段。

### RED 证据

生产实现前/回退实现后实际观察到：

```text
pytest backend/unittests/test_mtmc_runtime_status.py backend/unittests/test_mtmc_stream_regressions.py -q
16 failed, 4 passed

node --test src/utils/mtmcRuntimeStatus.test.js
5 failed, 6 passed

修正测试夹具自身的超时配置后，真实 _process_frame 回放：
3 failed, 1 passed
```

此外，Youtu provider、路由构造 OCR 元数据、车辆 ReID 异常状态和分离检测器“一成一败不互相覆盖”均以单独失败用例确认 RED；最后一项失败表现为 vehicle 检测异常错误地把已成功的 person detection 标为失败。

### 七项审查意见的修复映射

1. 配置资产与运行就绪分离：新增 `configured`、`assetPresent`、`configuredModel*`；资产存在但尚未推理时为 `pending/probing`，检测器、ReID、OCR、车牌检测和 tracker 只有真实执行成功后才为 `ready`，异常与回退均保留原因。
2. backend/provider 独立：每个 ReID 后端状态同时暴露实现后端和执行 provider；Youtu 保留真实 `youtu-reid-opencv`/`youtu-reid-onnxruntime` 语义，测试使用实际 extractor 元数据结构而非伪造扁平字段。
3. 多相机模型不再“最后写入获胜”：运行态以 `byCamera` 为事实源，并输出复数键/版本/backend/provider/输入/维度；仅所有相机一致时保留顶层标量，前端对 mixed 状态逐相机展示。
4. 预算语义完整：`considered/eligible/queued/consumed/budgetSkipped/samplerSkipped` 全链路累计；纯 eligibility 检查没有预留副作用，采样器拒绝单独计数，预算为 0 时仅对真正 eligible 的候选计 `budgetSkipped`。
5. 长期关联 margin 可追溯：LONG_TERM 的 `AssocEvidence.extra` 写入 `bestScore/secondBestScore/matchMargin/minMatchMargin`；回归通过真实 SQLite 持久化和路由格式化验证正 margin，没有预填自证字段。
6. 缺失拓扑策略不再伪造：前端仅在 `directed`、`missingEdgePolicy` 和 `edges` 快照完整时描述策略，否则明确显示“等待策略快照”。
7. 四类现场回归走真实边界：确定性外部 stub 驱动实际 `_process_frame/_process_frame_locked`、`_resolve_overlay_global`、collector/claimed 互斥和 tracker release；覆盖错误复用、静态局部 ID 切换、合法 non-overlap 续接和延迟帧振荡，没有复制 `peek_sticky` 算法。

自审额外发现并修复：分离的人/车检测器逐个执行时，后执行模型失败不能覆盖前一个模型已记录的成功状态；共享模型仍会对两个角色记录同一次成功或失败。

### GREEN 与最终验证

```text
focused 后端：25 passed, 11 warnings in 41.02s
前端纯函数：11 passed, 0 failed
完整 MTMC：177 passed, 46 warnings in 142.24s
Python py_compile：exit code 0
git diff --check：exit code 0（仅 LF→CRLF 提示）
```

前端生产构建：

```text
npm run build
2731 modules transformed
built in 25.70s
exit code 0
```

### 本轮变更文件 SHA-256

```text
0c0c0a9f6c646e821c751f69ca5e36944297e32b41e675c613ebdd1fb2e97bd4  backend/person_reid_dnn.py
d57af7fe6636a8703aa02a489d15e6c9a9c6d05ae97feea8b93401fa302f4e87  backend/routes/mtmc.py
85b02b402ef4f6b850230fa295a8ba933910ccf854bcf34953ee14ff8b4eb809  backend/services/mtmc_associator.py
38d3fb1c7865ca5c78eee9371cf087e0b2b9ccb7c7b821e0ccb347b945b08a07  backend/services/mtmc_engine.py
cc111fcf3287ac9c6bc2e7389f79edadf959dabdb35dd5727417aa5eae5c19b9  backend/services/mtmc_tracklet.py
6b00bafeb51c3a39123da688db2cbad85f99f687f6ed1f543f0ed78b4d04ede3  backend/services/strong_reid.py
f535e91f2619ac76faa94295f1f2152e75282e122a8339dc706377c9fb8be26e  backend/unittests/test_mtmc_reid_runtime.py
d0b441ec83239729269f327e458cb3f27ba5d8afecea284df397496d75d1af35  backend/unittests/test_mtmc_runtime_status.py
2c59a21f26117481dd58339b02315c599ee213ddec755d6bd91f777d11f0ad83  backend/unittests/test_mtmc_stream_regressions.py
a6a0963a7eb69a469c6f0077fdbec5a0c10babd901b648599cd218f901740cb0  frontend/frontend_admin/src/utils/mtmcRuntimeStatus.js
fc13627bec2feb5d3b6212612e8fadf97d22c3db1f3648d47dec319dd5c6891f  frontend/frontend_admin/src/utils/mtmcRuntimeStatus.test.js
6f24cf13d419d3e63b96ebdd69a216f5b7fe21ffb42a700e15c8ebe698a01c18  frontend/frontend_admin/src/views/ai/mtmc/index.vue
```

### 自审与关注项

- 模型硬件边界：CI 未加载生产 GPU、摄像头和真实模型资产；backend/provider/输入/维度要在部署环境完成首帧后才能得到硬件实测值，首帧前 UI 会保持等待状态。
- 告警：完整套件的 46 条 warning 为 42 条既有 `datetime.utcnow()` 弃用提示、2 条 SQLAlchemy `Query.get()` 弃用提示和 2 条受限 `.pytest_cache` 写入提示；不影响退出码。Vite 仍有第三方 PURE 注释及既有大 chunk 警告。
- 清理：本轮创建的 10 个 `.pytest-task6-r1-*` 临时目录均在验证绝对路径属于工作区后删除；未触碰既有且权限受限的 `.pytest_cache`。

---

## 审查修复轮次 2/5

### 状态与基线

- 状态：`DONE_WITH_CONCERNS`
- 审查基线：`b4cffb66784d8ef6c08be07d769ca349b0d1ceef`（`fix: report truthful MTMC runtime state`）
- 本轮提交主题：`fix: surface MTMC execution failures`
- 范围：只处理本轮 6 项 Important；没有新增外部 API、数据库字段或模型配置入口。

### RED 证据

每项在生产代码修改前独立观察到预期失败：

```text
真实 plate detector / OCR callable 与 legacy detector helper：3 failed
tracker 构造、首次 update、update 异常：3 failed
仅 Youtu 尝试失败的 backend 归因：1 failed
同模型跨相机执行状态不一致：1 failed
车辆 ReID 异常路径预算快照：1 failed
前端 plateOcr/localTracker 可见性：1 failed, 12 passed
```

失败原因分别是：plate/OCR helper 把推理异常转换为空结果；tracker 构造即写 ready 且 update 没有观察点；无 active person ReID 错落入 strong 默认分支；mixed 签名不比较执行健康；车辆 ReID 异常在帧末预算写入前退出；前端角色白名单漏项。

### 六项修复映射

1. `vehicle_track` 的 plate detection 与 OCR helper 不再吞掉推理异常。MTMC engine 在真实 `_plate_candidates`/`_ocr_plate` 边界捕获异常，分别记录 `plateDetection` 或 `plateOcr` failed/degraded；测试使用会真实抛错的 predictor/ocr callable。
2. `localTracker` 构造只记录 `ready=null/runtimeState=pending`，包括回退后的实际 backend；`_tracks_or_raw` 在第一次真实 `update()` 成功后写 ready，update 异常先写 failed/degraded 再按既有帧处理策略向上抛出，由 worker 记录错误并处理下一帧。
3. 前端运行态角色加入 `plateOcr`（“车牌 OCR”）和 `localTracker`（“本地跟踪器”）；两者进入模型卡片、风险摘要和 `runtimeOverallTone` 的既有统一计算，失败会显示并令总状态为 danger。
4. person ReID 只按 `activeBackend` 选择顶层 backend/provider；仅 Youtu 尝试失败且无 active 时，顶层字段保持空，`backendReadiness.youtu` 保留实际尝试的 `youtu-reid-opencv/opencv-dnn-cpu` 与 Youtu 错误，不再伪装为 strong。
5. 多相机 mixed 判定新增 `ready/runtimeState/degraded/degradedReason/backendReadiness`，并把 `None` 也作为事实差异；相同模型在两个相机一成一败时 `mixed=true`，前端展开为逐相机成功/失败行。
6. 车辆 ReID eligibility、采样预留及 queued/consumed 在推理前完成；推理异常的 `finally` 路径立即持久化本帧预算，避免 early exit 留下全零快照。`consumed` 表示已发起并消耗预算的推理尝试，因此失败尝试仍计入。

### GREEN 与最终验证

```text
plate/OCR focused：3 passed
tracker focused：3 passed
Youtu-only focused：1 passed
mixed-health focused：1 passed
vehicle ReID exception budget：1 passed
MTMC runtime/ReID/真实流 focused：66 passed, 11 warnings
vehicle plate/speed：64 passed, 2 warnings
前端纯函数：13 passed, 0 failed
完整 MTMC：183 passed, 46 warnings in 151.37s
Python py_compile：exit code 0
git diff --check：exit code 0（仅 LF→CRLF 提示）
```

前端生产构建：

```text
npm run build
2731 modules transformed
built in 26.36s
exit code 0
```

### 本轮变更文件 SHA-256

```text
fc5d47893db1fdc77b0df7a68143ec0a89ec75f2dd9ed59d474d5c903ce6a90a  backend/services/mtmc_engine.py
0c7c964a08a64935c1c1364aac66b944796559b9084280dcaa2553228ac9c66a  backend/services/vehicle_track.py
233daf69ecfa0094b9ad23bef90e03567e3a1c1f2226f0332068a3c815d010f8  backend/unittests/test_mtmc_runtime_status.py
e619c4029a6c048410634dc60203ddd532bedf974a95cfdb82065df4f81bf424  frontend/frontend_admin/src/utils/mtmcRuntimeStatus.js
884b1e999f2b59086a1f190ab3e2427bc43562b50fd5bbd08f4ac298d1f1e348  frontend/frontend_admin/src/utils/mtmcRuntimeStatus.test.js
```

### 自审与关注项

- plate/OCR 异常不再伪装成“无候选/空文本”；MTMC 仍会继续当前帧的其余安全路径。非 MTMC 的 vehicle track 调用会收到 helper 异常并交由其既有上层策略处理，相关 vehicle zone/speed 64 项回归通过。
- tracker update 异常仍按既有策略终止当前帧并由静态图、文件或流 worker 捕获；本轮只保证异常前先写真实 runtime 状态，没有静默改成 raw fallback。
- 完整套件 46 条 warning 仍为 42 条既有 `datetime.utcnow()`、2 条 SQLAlchemy `Query.get()` 和 2 条受限 `.pytest_cache` 写入提示；Vite 仍有第三方 PURE 注释及既有大 chunk 警告。
- 本轮创建的 3 个残留 `.pytest-task6-r2-*` 目录已在确认绝对路径属于工作区后删除；单项 pytest 的临时目录由 pytest 自行清理。
