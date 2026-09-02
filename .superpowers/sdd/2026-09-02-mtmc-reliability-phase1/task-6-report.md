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
