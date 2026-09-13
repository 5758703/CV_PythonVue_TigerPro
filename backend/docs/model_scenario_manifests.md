# 生产模型清单

`efficient-sam` 与 `yolo26n-p2-plate` 只有在权重同目录存在可信的 `production-manifest.json` 时才会进入 ready 状态。就绪检查和推理入口共用同一契约；检查不会导入模型、加载权重、下载文件或写磁盘。

```json
{
  "modelKey": "efficient-sam",
  "task": "interactive-segmentation",
  "artifactFile": "image_segmentation_efficientsam_ti_2025april.onnx",
  "artifactSha256": "64位十六进制SHA256",
  "runtimeContract": "opencv-sam/effective-sam-v1"
}
```

P2 车牌模型还必须包含训练完成证明和车牌类别：

```json
{
  "modelKey": "yolo26n-p2-plate",
  "task": "object-detection",
  "artifactFile": "p2-plate.pt",
  "artifactSha256": "64位十六进制SHA256",
  "trainingComplete": true,
  "classes": ["license_plate"]
}
```

约束：

- `artifactFile` 必须只是文件 basename，不得包含目录、`..` 或路径分隔符，并必须与当前配置选择的权重文件名完全一致。
- `artifactSha256` 必须是 64 位十六进制；大小写均接受，校验时与权重文件实际 SHA256 常量时间比较。
- 权重目录出现多个兼容候选时视为歧义并保持 not ready；应把 `AiModel.file_path` 精确指向单个制品。
- 清单缺失、字段缺失、hash 错误、模型键或任务不匹配时均保持 not ready，并在 `reason` 返回可操作原因。

PowerShell 生成 hash：

```powershell
(Get-FileHash -Algorithm SHA256 .\p2-plate.pt).Hash.ToLower()
```

Linux/macOS 生成 hash：

```bash
sha256sum ./p2-plate.pt
```
