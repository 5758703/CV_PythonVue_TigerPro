# MTMC 跨镜重识别可靠性升级设计

## 1. 背景与目标

当前 MTMC 已具备多路取流、目标检测、单镜跟踪、Tracklet、人员/车辆 ReID、在线 Global ID、拓扑、候选复核和证据落库，但现场拉流测试仍出现：

1. 不同车辆错误复用同一 Global ID；
2. 静止车辆的 Local ID 和 Global ID 频繁切换；
3. 配置拓扑后，非重叠摄像头仍很难续接原 Global ID；
4. Global ID 延迟匹配、反复切换，且恢复后可能不是原 ID。

本设计将 MTMC 从“外观相似度加固定时间窗”的在线原型升级为可测量、可解释、可拒识的跨镜追踪系统。实施采用四个独立阶段；每个阶段必须形成可运行、可回归、可单独提交的增量。

## 2. 范围与非目标

### 2.1 范围

- 人员和车辆共用的 Tracklet、拓扑、全局关联和证据基础设施；
- 人员 OSNet/CLIP-ReID/Youtu 与车辆 TransReID/CLIP-ReID 的正确接入；
- 重叠摄像头的同步、标定和 BEV/世界坐标关联；
- 无重叠摄像头的入口/出口、有向拓扑、转移时间模型和 Tracklet 图关联；
- 实际模型、降级状态、关联证据与端到端指标的可观测性；
- 现有候选晋升/驳回、事件、轨迹、监控墙的兼容迁移。

### 2.2 非目标

- 不承诺在图像证据缺失、完全同外观或严重遮挡时 100% 自动认出真实身份；此时必须返回 candidate 或 new；
- 第一阶段不引入新的训练框架和大型 GPU 依赖；
- 未提供相机标定数据前，第四阶段只交付标定能力和降级路径，不伪造世界坐标；
- 不以单纯降低阈值作为提升召回率的手段；
- 不把未经人工或高置信规则确认的 Global ID 直接回灌训练。

## 3. 总体架构

```text
视频源 + 源时间戳
        │
        ▼
检测 → 单镜跟踪 → Tracklet 生命周期与质量评估 → 多关键帧特征
                                                        │
                    ┌───────────────────────────────────┴─────────────────────────────┐
                    │                                                                 │
              重叠相机组                                                         无重叠相机图
       同步帧组 → 标定 → BEV/世界检测                                      Exit → Entry 有向边
       位置/速度/极线几何门控                                             转移时间概率/方向门控
                    │                                                                 │
                    └───────────────────────候选边────────────────────────────────────┘
                                                │
                                                ▼
                                多模型分数级融合 + 全局约束求解
                                                │
                              Confirm / Candidate / New / Reject
                                                │
                              Global Identity + 原子证据 + 事件/轨迹
```

重叠和无重叠场景不再共用一套简单时间阈值：重叠场景以几何连续性为主，非重叠场景以有向时空可达性为主；ReID 是两条路径共享的判别信号。

## 4. 阶段一：正确性基线修复

### 4.1 强 ReID 正确接入

- 从 ONNX 首输入直接解析 NCHW 高宽，不再用 `max(h, w)` 猜测模型类型；
- 项目现有 OSNet 和 CLIP-ReID Person 必须按 `256×128` 输入运行；
- 模型加载阶段执行输入、输出维度自检；不兼容时会话返回明确 degraded 状态；
- Youtu、OSNet、CLIP-ReID 各自保留独立 embedding 空间和模型版本；
- 禁止不同模型 embedding 通过 pad/trim 后逐元素相加；
- 多模型融合改为独立余弦分数经校准后加权，某一路不可用时重新归一化有效权重；
- 已登记人员 Gallery 只与相同模型空间比较。

### 4.2 Tracklet 生命周期与静止目标稳定性

- 单帧 tracker 未输出不立即 finalize；Tracklet 进入 grace/lost 状态，等待 tracker `max_age` 或按秒计算的丢失期限；
- tracker 明确移除、超时、会话停止或源结束时才 finalize；
- 静止目标不得因速度接近零、轨迹点不变化而释放 Local/Global 绑定；
- local ID 重建时，优先在同镜 lost Global 中按位置、类别、外观和时间做恢复；
- 同镜仍活跃的 Global 是硬占用资源，不允许另一个 local track 抢占；
- 每帧保持 object-to-Global 一对一约束。

### 4.3 真正的多关键帧表征

- 每个 Tracklet 不只在首帧提取 ReID；在生命周期内按质量和时间间隔补充关键帧；
- 至少支持首帧、质量显著提升帧、视角变化帧、离场前帧；
- 人员和车辆分别设置预算，避免人员先遍历耗尽车辆预算；
- 预算调度优先级：未获得 embedding 的新生目标、即将离场目标、candidate、质量提升目标、普通刷新；
- 保留 Top-K、medoid 和离群过滤；低质量帧不得覆盖稳定 prototype；
- Global 按模型、相机、视角保存多个 prototype，并记录质量与时间。

### 4.4 有向拓扑与时间评分

- `fromCameraId → toCameraId` 严格有向，不自动生成反向边；
- 未配置边默认不可达；仅显式设置 fallback 的场景允许软可达；
- 重叠边必须显式标记 `overlap`，允许最短时间为 0；
- 时间适配度必须参与最终关联分和三档决策；
- 拓扑 `weight` 必须参与评分；
- confirm 使用融合后的 final score，而不是绕开拓扑的 raw ReID；
- 人员与车辆允许不同的时空权重和阈值。

### 4.5 Global ID 防误复用

- Global 保存每个相机的 active/lost 区间和最后观测，不再只依赖单个 `camera_id/last_seen`；
- 长时匹配必须同时满足物理可达、类别/身份无硬冲突、外观阈值和候选 margin；
- 增加第一与第二候选分差及 mutual-best 检查；
- 低 margin、低质量或证据冲突进入 candidate，不自动复用旧 Global；
- 可靠车牌相同是强证据，但仍需通过可达性检查；可靠车牌冲突继续硬拒绝；
- Global prototype 更新采用质量感知 EMA；candidate 和低质量 sticky 不得污染长期模板。

### 4.6 车辆证据修正

- 禁止使用同一 embedding 与自身比较生成 `visualScore=1`；
- `visualScore` 表示当前 Tracklet 与候选 Global prototype 的相似度；
- 多帧车牌通过规范化、字符置信度和投票形成 Tracklet 车牌；
- `identityKey` 不再依赖浮点 embedding 的精确 SHA1 作为跨帧身份；
- 页面事件分与 association 分明确分栏，不再混用 Gallery 分、车辆融合分和跨镜关联分。

### 4.7 并发和停止语义

- `associate()` 原子返回 Global 与本次 `AssocEvidence`，不通过共享 `last_evidence` 跨线程读取；
- 会话停止先通知 worker，再 join，最后 finalize 仍活跃 Tracklet；
- 上传临时目录必须在 worker 退出后清理；
- candidate 晋升后统一重写相关 Tracklet、事件、跨镜事件、关联边、过车记录和 Global；
- reject 同步更新内存与数据库候选状态。

### 4.8 第一阶段现场验收

必须建立以下自动回归场景：

1. 两辆不同静止车辆持续存在，不得共享或交换 Global ID；
2. 静止车辆连续若干采样帧漏检后恢复，保留原 Global ID；
3. local ID 因跟踪器重建改变时，同镜恢复到原 Global；
4. 旧车辆离场、新车辆随后进入时，不得仅因外观相似复用旧 Global；
5. A→B 可达、B→A 不可达或时间不同，方向必须生效；
6. 未配置拓扑的非重叠相机不得自动合并；
7. 非重叠目标在正确 Exit/Entry 和时间窗内续接原 Global；
8. candidate 不得更新被怀疑 Global 的 prototype；
9. 多摄像头并发关联时每条证据对应正确 Tracklet；
10. OSNet、CLIP-ReID Person、Youtu 和车辆 ONNX 的真实输入输出冒烟测试通过；
11. 人员密集时车辆仍能获得自己的 ReID 预算；
12. 停止会话后所有活跃 Tracklet 已 finalize，worker 和临时资源已释放。

## 5. 阶段二：可信评测与可观测性

### 5.1 真实状态展示

会话快照增加：

- 实际检测、人员 ReID、车辆 ReID、车牌/OCR 模型及版本；
- 模型输入尺寸、embedding 维度和运行 provider；
- strong/youtu/vehicle backend 是否 ready；
- degraded 原因；
- ReID 队列深度、跳过原因、各类预算使用量；
- 每次关联的 appearance、topology、time、geometry、plate、margin 和 final 分。

### 5.2 标注与指标

- 建立项目自有的同步多摄像头验证集和身份真值格式；
- 按人员/车辆、camera pair、昼夜、目标尺寸、遮挡程度分桶；
- 输出 IDP、IDR、IDF1、HOTA、DetA、AssA、ID Switch、fragmentation；
- 增加 false merge、false split、handoff precision/recall、candidate 命中率；
- ReID 层输出 mAP、Rank-1/5、TPR@固定 FAR；
- 在线输出首次确认延迟、handoff 延迟和 p95 推理/关联时延；
- 现有“跨镜 Global 数量”只作为运行统计，不再作为成功率。

### 5.3 阈值校准

- 阈值按 object type、camera pair、昼夜和质量桶配置；
- 以目标 FAR 和 handoff precision 为约束选择 confirm 阈值；
- candidate 阈值必须低于 confirm，且配合 margin；
- 所有阈值版本写入证据，支持回放比较。

## 6. 阶段三：无重叠区域增强

### 6.1 数据模型

为每条有向拓扑边增加：

- From exit zone 与 To entry zone；
- 边类型 `non_overlap`；
- 最短/最长通行时间；
- 可选经验分布参数或直方图；
- 方向、车道、对象类型和时段；
- ReID/时空融合权重与阈值版本。

### 6.2 真实时间轴

- 文件源使用视频 PTS，并支持配置各文件起始时间或同步偏移；
- RTSP 优先使用源时间戳，缺失时记录接收时刻及估计偏移；
- 暴露每路时钟健康状态；时钟不可信时扩大窗口但降低自动确认权限；
- 本地多视频不得默认假设全部重叠和同时开始。

### 6.3 Tracklet 图关联

- 节点是 finalized 或稳定 Tracklet；
- 先通过有向拓扑、Exit/Entry、时间和方向稀疏候选边；
- 边分融合 appearance、plate/person identity、时间概率、区域和属性；
- 在线使用重叠滑动窗口，允许短暂延迟提交；
- 求解必须满足同镜冲突、不可达和传递一致性；
- 第一版采用约束层次聚类或最小代价流，不引入研究级 GNN；
- 高置信解自动 confirm，中间态保留 candidate，低置信 new。

### 6.4 拓扑学习

- 从人工确认和高置信 handoff 累积转移时间样本；
- 新分布以影子模式评估，不直接覆盖生产配置；
- 数据不足时使用人工 min/max；数据充分后再启用经验分布；
- 人员方向为软约束，车辆道路方向可配置为硬约束。

## 7. 阶段四：重叠区域增强

### 7.1 标定与同步

- 相机保存内参、畸变、外参或地面单应矩阵及版本；
- 提供地面点对标定和重投影误差验证；
- 相机移动或误差超过阈值时自动禁用硬几何并降级；
- 重叠组按可配置时间容差组成同步帧组。

### 7.2 世界坐标关联

- 人员使用 bbox 脚点或分割接地点，车辆使用地面接触点/3D 中心；
- 投影到共同 BEV/世界坐标；
- 用世界距离、速度连续性、可行加速度和视锥一致性生成候选；
- 同时刻多视图检测先融合为 world observation，再进入 world tracker；
- ReID 只处理多个几何候选或遮挡恢复，不取代几何门控；
- 无标定或标定失效时自动回退到阶段一的外观/拓扑路径，并显示 degraded 状态。

### 7.3 依赖条件

交付真实重叠区效果前，需要每个相机组至少提供：

- 同步或可估计偏移的视频；
- 相机内参，或足够的地面对应点；
- 重叠区域和可行地面范围；
- 少量跨视角身份与位置真值用于验证。

## 8. 前端工作台设计

沿用现有 MTMC 页面，不新增重复入口：

- “基础配置”默认只显示摄像头、对象类型和场景类型；
- 根据相机关系显示“重叠几何”或“非重叠拓扑”状态；
- 模型默认自动推荐，但必须显示实际选择、ready/degraded 和回退原因；
- 高级参数按人员、车辆、时空和性能分组；
- 候选表展示第一/第二候选、margin 和分项证据；
- Global 详情展示各相机 active/lost 区间和 prototype 数量；
- 增加 ID 切换、误合并风险、ReID 队列和时钟/标定健康卡片；
- 拓扑编辑器保持有向语义，并支持 Exit/Entry 区域与边类型；
- 页面不允许把未配置拓扑描述成已具备跨镜可达性。

## 9. 数据兼容与迁移

- 现有 `camera_topology`、Global、Tracklet、Association、Candidate 和 Event 表保留；
- 新字段采用可空或独立版本表，旧数据按 legacy 策略读取；
- 旧拓扑边不自动复制反向边；迁移后由用户显式确认方向；
- embedding 必须携带 model key、model version 和 dimension；不同空间禁止比较；
- 旧证据缺少新分项时显示 `legacy/unknown`，不得伪造零分；
- 数据库迁移必须可回滚，服务升级期间保持旧查询 API 可用。

## 10. 错误处理与降级

- 强 ReID 不可用：回退 Youtu，但降低自动确认权限并展示原因；
- 车辆 ReID 不可用：颜色直方图只能生成 candidate，不得在无车牌时单独 auto-confirm；
- 拓扑缺失：非重叠 camera pair 不可自动关联；
- 时间戳不可信：标记证据并限制自动确认；
- 标定失效：重叠场景回退外观路径；
- FAISS 不可用：允许精确矩阵检索，结果语义不变；
- ReID 队列积压：优先即将离场和新生 Tracklet，并报告跳过量；
- 任一降级不得静默发生。

## 11. 测试策略

### 11.1 单元测试

- ONNX shape、模型空间隔离、分数融合；
- Tracklet grace/finalize、多关键帧、prototype 更新；
- 有向拓扑、缺边不可达、时间概率、margin；
- Global 占用、同镜恢复、车牌冲突、candidate 污染防护；
- 原子 evidence、停止 finalize、晋升数据一致性。

### 11.2 集成测试

- 两路模拟流复现四个现场问题；
- 多线程交错关联和短暂断流；
- 文件 PTS 与偏移；
- 人员/车辆拥挤预算；
- pipeline 和独立 MTMC API 使用同一拓扑语义；
- 页面显示实际模型、降级和真实分项分数。

### 11.3 数据集回归

- 固定小型 canary 数据集用于每次提交；
- 完整标注集用于阶段验收；
- 所有优化同时报告精度、召回、错误合并和延迟，禁止只报告成功匹配数量。

## 12. 交付和提交边界

每个阶段单独编写实施计划。阶段一内部再按以下可审查任务拆分：

1. ReID 模型输入和空间隔离；
2. Tracklet 生命周期和多关键帧调度；
3. 有向拓扑与最终评分；
4. Global 状态、margin 和 prototype 防污染；
5. 车辆证据、并发证据和停止一致性；
6. 前端真实状态与现场场景回归。

每个任务遵循测试先行、独立提交、独立代码复审。阶段一通过现场四类问题的自动回归后，才进入阶段二；阶段二建立可信指标后，阶段三和阶段四的效果提升才有可验证依据。

