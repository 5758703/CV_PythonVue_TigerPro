"""水位尺 YOLOv8 目标检测训练脚本。

用法（在 backend 目录下运行）:
    python train_water_gauge.py

输入:
    ../docs/Data/*.jpg + *.xml  (Pascal VOC 格式，类别 WaterGuage)

输出:
    weights/water_gauge_yolo.pt  (训练完成的最佳权重)

流程:
    1. VOC XML → YOLO TXT 标注
    2. 80/20 划分 train/val
    3. 创建 data.yaml
    4. weights/yolov8n.pt 预训练权重微调 (100 epochs)
    5. 拷贝 best.pt → weights/water_gauge_yolo.pt
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"   # fix Windows OMP conflict

import shutil
import random
import xml.etree.ElementTree as ET
from pathlib import Path

# ── 路径配置 ──────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR.parent / "docs" / "Data"
WORK_DIR  = BASE_DIR / "yolo_dataset"        # 临时训练目录
OUT_PT         = BASE_DIR / "weights" / "water_gauge_yolo.pt"
PRETRAINED_PT  = BASE_DIR / "weights" / "yolov8n.pt"

CLASS_NAMES = ["WaterGuage"]   # 与 XML <name> 对应（保留原始拼写）
SPLIT_RATIO = 0.8              # 训练集比例
EPOCHS      = 100
IMG_SIZE    = 640
BATCH       = 8                # CPU 训练建议 4-8


# ── 1. 解析 VOC XML ───────────────────────────────────

def parse_voc(xml_path: Path):
    """返回 (img_w, img_h, [(class_id, xmin, ymin, xmax, ymax), ...])。"""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    size  = root.find("size")
    img_w = int(float(size.find("width").text))
    img_h = int(float(size.find("height").text))
    boxes = []
    for obj in root.iter("object"):
        cls_name = obj.find("name").text.strip()
        cls_id   = CLASS_NAMES.index(cls_name) if cls_name in CLASS_NAMES else -1
        if cls_id < 0:
            continue
        bb = obj.find("bndbox")
        xmin = float(bb.find("xmin").text)
        ymin = float(bb.find("ymin").text)
        xmax = float(bb.find("xmax").text)
        ymax = float(bb.find("ymax").text)
        boxes.append((cls_id, xmin, ymin, xmax, ymax))
    return img_w, img_h, boxes


def voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h):
    """Pascal VOC 绝对坐标 → YOLO 归一化中心点 + 宽高。"""
    cx = ((xmin + xmax) / 2) / img_w
    cy = ((ymin + ymax) / 2) / img_h
    bw = (xmax - xmin) / img_w
    bh = (ymax - ymin) / img_h
    return cx, cy, bw, bh


# ── 2. 生成 YOLO 数据集目录 ───────────────────────────

def build_dataset():
    for split in ("train", "val"):
        (WORK_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
        (WORK_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)

    xml_files = sorted(DATA_DIR.glob("*.xml"))
    random.seed(42)
    random.shuffle(xml_files)

    n_train = int(len(xml_files) * SPLIT_RATIO)
    splits  = {"train": xml_files[:n_train], "val": xml_files[n_train:]}

    ok, skip = 0, 0
    for split, files in splits.items():
        for xml_path in files:
            # 找对应图片（同前缀不同扩展名）
            stem    = xml_path.stem          # e.g. Ehance01-VID-10-107
            img_src = DATA_DIR / f"{stem}.jpg"
            if not img_src.exists():
                skip += 1
                continue

            img_w, img_h, boxes = parse_voc(xml_path)
            if not boxes:
                skip += 1
                continue

            # 复制图片
            img_dst = WORK_DIR / "images" / split / img_src.name
            shutil.copy2(img_src, img_dst)

            # 写 YOLO txt 标注
            lbl_dst = WORK_DIR / "labels" / split / f"{stem}.txt"
            with open(lbl_dst, "w") as f:
                for cls_id, xmin, ymin, xmax, ymax in boxes:
                    cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            ok += 1

    print(f"数据集构建完成: {ok} 张图片 ({n_train} 训练 / {len(xml_files)-n_train} 验证)，跳过 {skip}")
    return ok


# ── 3. 生成 data.yaml ─────────────────────────────────

def write_yaml():
    yaml_path = WORK_DIR / "data.yaml"
    content = f"""path: {WORK_DIR.as_posix()}
train: images/train
val: images/val

nc: {len(CLASS_NAMES)}
names: {CLASS_NAMES}
"""
    yaml_path.write_text(content, encoding="utf-8")
    print(f"data.yaml -> {yaml_path}")
    return str(yaml_path)


# ── 4. 训练 ──────────────────────────────────────────

def train(yaml_path):
    from ultralytics import YOLO

    weight = str(PRETRAINED_PT) if PRETRAINED_PT.is_file() else "yolov8n.pt"
    model = YOLO(weight)
    results = model.train(
        data     = yaml_path,
        epochs   = EPOCHS,
        imgsz    = IMG_SIZE,
        batch    = BATCH,
        device   = "cpu",        # CPU 训练；有 GPU 改 "0"
        project  = str(WORK_DIR / "runs"),
        name     = "water_gauge",
        patience   = 20,          # 20 轮无提升提前停止
        workers    = 0,           # Windows 多进程 DataLoader 须为 0
        exist_ok   = True,        # 允许覆盖之前的训练目录
        verbose    = True,
    )

    # 找 best.pt
    best_pt = Path(results.save_dir) / "weights" / "best.pt"
    if best_pt.exists():
        OUT_PT.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best_pt, OUT_PT)
        print(f"\n训练完成！最佳权重 -> {OUT_PT}")
    else:
        print(f"警告：未找到 best.pt，请检查 {results.save_dir}")

    return str(OUT_PT)


# ── 主程序 ────────────────────────────────────────────

if __name__ == "__main__":
    print("=== 水位尺 YOLOv8 训练 ===")
    print(f"数据目录 : {DATA_DIR}")
    print(f"工作目录 : {WORK_DIR}")
    print(f"输出权重 : {OUT_PT}")
    print(f"类别列表 : {CLASS_NAMES}")
    print(f"训练轮数 : {EPOCHS}")
    print()

    n = build_dataset()
    if n == 0:
        print("错误：无有效图片，请检查 docs/Data 目录")
        exit(1)

    yaml_path = write_yaml()
    train(yaml_path)
