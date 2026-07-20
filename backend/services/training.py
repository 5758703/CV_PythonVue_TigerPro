"""YOLOv8 模型训练服务（参照 train_water_gauge.py）。"""
import csv
import json
import os
import random
import shutil
import threading
import zipfile
from datetime import datetime
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

IMG_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".webp")
LABEL_EXT = ".txt"
XML_EXT = ".xml"

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
PRETRAINED_WEIGHTS_DIR = _BACKEND_ROOT / "weights"

DATASET_FORMATS = {
    "auto": "自动检测",
    "voc": "Pascal VOC（图片 + 同名 XML）",
    "voc_standard": "Pascal VOC 标准目录（Annotations + JPEGImages）",
    "yolo": "YOLO 原生（images/labels 含 train/val 子目录）",
    "yolo_flat": "YOLO 扁平（images/ + labels/ 无划分，构建时按比例切分）",
    "coco": "COCO JSON（instances_*.json + images/）",
    "labelme": "LabelMe JSON（每张图配套 .json 标注）",
    "import": "导入本地已有数据集目录",
}

# 各格式详细说明（供 API / 前端展示）
FORMAT_SPECS = {
    "auto": {
        "label": "自动检测",
        "summary": "上传后由系统扫描目录结构，自动识别 VOC / YOLO / COCO / LabelMe 等格式。",
        "directoryTree": "任意符合下列任一格式的目录结构",
        "requiredFiles": "无固定要求，系统自动识别",
        "classNames": "依检测到的格式：YOLO 可从 data.yaml 读取，COCO/LabelMe 可从 JSON 推断",
        "splitRatio": "仅对需切分的格式生效（VOC、YOLO 扁平、单文件 COCO、LabelMe）",
        "uploadTypes": ".jpg .jpeg .png .bmp .xml .txt .json .yaml .zip",
        "example": "将完整数据集文件夹打成 zip 上传，格式选 auto 后构建",
        "notes": [
            "推荐不熟悉格式细节时使用",
            "若检测失败，请改用明确格式并检查目录结构",
        ],
    },
    "voc": {
        "label": "Pascal VOC（扁平）",
        "summary": "每张图片对应一个同名 XML 标注文件，全部放在同一目录（raw/）。",
        "directoryTree": (
            "raw/\n"
            "├── image001.jpg\n"
            "├── image001.xml\n"
            "├── image002.png\n"
            "└── image002.xml"
        ),
        "requiredFiles": "图片（.jpg/.png/.bmp）+ 同名 .xml",
        "classNames": "必填；须与 XML 中 <name> 完全一致（区分大小写）",
        "splitRatio": "构建时按比例随机划分 train/val",
        "uploadTypes": ".jpg .jpeg .png .bmp .xml .zip",
        "example": "Ehance01-VID-10-107.jpg + Ehance01-VID-10-107.xml",
        "notes": [
            "XML 中 <bndbox> 为 xmin/ymin/xmax/ymax 像素坐标",
            "仅保留 classNames 中列出的类别框",
        ],
    },
    "voc_standard": {
        "label": "Pascal VOC 标准目录",
        "summary": "经典 VOC 数据集目录：Annotations 放 XML，JPEGImages 放图片。",
        "directoryTree": (
            "raw/\n"
            "├── Annotations/\n"
            "│   ├── img001.xml\n"
            "│   └── img002.xml\n"
            "└── JPEGImages/   （或 Images/、images/）\n"
            "    ├── img001.jpg\n"
            "    └── img002.jpg"
        ),
        "requiredFiles": "Annotations/*.xml + JPEGImages/*.{jpg,png}",
        "classNames": "必填；须与 XML <name> 一致",
        "splitRatio": "构建时按比例随机划分 train/val",
        "uploadTypes": ".jpg .jpeg .png .bmp .xml .zip",
        "example": "PASCAL VOC 官方数据集解压后的目录结构",
        "notes": [
            "支持 JPEGImages、Images、images 作为图片目录名",
            "可用 zip 打包整个目录上传",
        ],
    },
    "yolo": {
        "label": "YOLO 原生（已划分）",
        "summary": "Ultralytics/YOLOv5/v8 标准目录，已含 train/val 子目录，可直接用于训练。",
        "directoryTree": (
            "raw/  （或导入目录）\n"
            "├── data.yaml\n"
            "├── images/\n"
            "│   ├── train/\n"
            "│   │   └── *.jpg\n"
            "│   └── val/\n"
            "│       └── *.jpg\n"
            "└── labels/\n"
            "    ├── train/\n"
            "    │   └── *.txt\n"
            "    └── val/\n"
            "        └── *.txt"
        ),
        "requiredFiles": "images/train|val + labels/train|val；data.yaml 可选",
        "classNames": "可选；优先从 data.yaml 的 names 读取",
        "splitRatio": "不生效（已预先划分）",
        "uploadTypes": ".jpg .jpeg .png .txt .yaml .zip",
        "example": "backend/yolo_dataset/ 即此格式",
        "notes": [
            "标签 .txt 每行：class_id cx cy w h（0~1 归一化）",
            "若仅有 train 无 val，构建时自动切 20% 作验证集",
            "支持 Roboflow 导出结构：train/images + train/labels、valid/images + valid/labels",
            "构建后统一输出到 uploads/datasets/<id>/yolo/",
        ],
    },
    "yolo_flat": {
        "label": "YOLO 扁平（未划分）",
        "summary": "图片与 YOLO 标签分目录存放，但尚未划分 train/val，构建时自动切分。",
        "directoryTree": (
            "raw/\n"
            "├── images/\n"
            "│   ├── a.jpg\n"
            "│   └── b.jpg\n"
            "└── labels/\n"
            "    ├── a.txt\n"
            "    └── b.txt"
        ),
        "requiredFiles": "images/* + labels/*.txt（stem 同名配对）",
        "classNames": "必填，或构建后从标签 id 推断为 class_0、class_1…",
        "splitRatio": "构建时按此比例划分 train/val",
        "uploadTypes": ".jpg .jpeg .png .txt .zip",
        "example": "images/frame001.jpg + labels/frame001.txt",
        "notes": [
            "也支持图片与 txt 同目录（扁平混合放 raw/）",
            "标签格式同 YOLO 原生",
            "若上传的是 Roboflow 等已划分数据集，构建时会自动按 YOLO 原生处理",
        ],
    },
    "coco": {
        "label": "COCO JSON",
        "summary": "MS COCO 目标检测标注格式，单文件或多文件 instances JSON + 图片目录。",
        "directoryTree": (
            "raw/\n"
            "├── images/              （或 train/、val/）\n"
            "│   └── *.jpg\n"
            "└── annotations/\n"
            "    ├── instances_train.json\n"
            "    ├── instances_val.json\n"
            "    └── instances.json     （单文件时构建阶段切分）\n"
            "\n"
            "也支持：annotations.json、_annotations.coco.json 放根目录"
        ),
        "requiredFiles": "COCO instances JSON（含 images、annotations、categories）+ 图片",
        "classNames": "可选；不填则使用 JSON categories 全部类别",
        "splitRatio": "单 JSON 时按图片随机切分；已有 train/val JSON 时不生效",
        "uploadTypes": ".jpg .jpeg .png .json .zip",
        "example": (
            "Roboflow/CVAT 导出的 COCO JSON；\n"
            'bbox 为 [x, y, width, height] 左上角像素坐标'
        ),
        "notes": [
            "仅转换 bbox 类标注（category_id + bbox）",
            "忽略 segmentation、iscrowd 等字段",
            "若指定 classNames，仅保留这些类别（名称匹配 categories.name）",
            "图片路径按 file_name 字段在 images/ 及子目录中查找",
        ],
    },
    "labelme": {
        "label": "LabelMe JSON",
        "summary": "LabelMe / labelme 标注工具导出的每图一个 JSON，含矩形或多边形框。",
        "directoryTree": (
            "raw/\n"
            "├── photo001.jpg\n"
            "├── photo001.json\n"
            "├── photo002.jpg\n"
            "└── photo002.json"
        ),
        "requiredFiles": "图片 + 同名 .json（含 shapes 数组）",
        "classNames": "可选；不填则汇总所有 shapes[].label",
        "splitRatio": "构建时按图片随机划分 train/val",
        "uploadTypes": ".jpg .jpeg .png .json .zip",
        "example": (
            'JSON 中 shapes[].label="猫"，shape_type 为 rectangle 或 polygon\n'
            "polygon 将自动转为外接矩形"
        ),
        "notes": [
            "支持 shape_type: rectangle、polygon",
            "忽略 line、point、circle 等非框类型",
            "imagePath 字段可用于辅助定位图片",
        ],
    },
    "import": {
        "label": "本地目录导入",
        "summary": "直接引用服务器上已有的数据集目录，无需上传，支持上述所有可识别格式。",
        "directoryTree": (
            "填写绝对路径，例如：\n"
            "F:/python_project/.../backend/yolo_dataset"
        ),
        "requiredFiles": "项目目录内的合法数据集路径",
        "classNames": "依路径内格式自动推断或手动填写",
        "splitRatio": "依检测到的格式决定",
        "uploadTypes": "无需上传",
        "example": "F:/python_project/CV_PyhonVue_Tigerpro/backend/yolo_dataset",
        "notes": [
            "仅允许项目根目录及 backend/uploads 下的路径",
            "保存后点击「构建」即可复制/转换为 YOLO 训练目录",
            "适合复用 yolo_dataset 等大型本地数据集",
        ],
    },
}


def get_format_specs_list():
    """返回前端用的格式说明列表。"""
    items = []
    for key, short in DATASET_FORMATS.items():
        spec = FORMAT_SPECS.get(key, {})
        items.append({
            "value": key,
            "label": spec.get("label") or short,
            "shortLabel": short,
            "summary": spec.get("summary", ""),
            "directoryTree": spec.get("directoryTree", ""),
            "requiredFiles": spec.get("requiredFiles", ""),
            "classNames": spec.get("classNames", ""),
            "splitRatio": spec.get("splitRatio", ""),
            "uploadTypes": spec.get("uploadTypes", ""),
            "example": spec.get("example", ""),
            "notes": spec.get("notes", []),
        })
    return items

_cancel_flags = {}
_cancel_lock = threading.Lock()


def _cancel_flag_path(job_id, upload_root: Path | None = None) -> Path:
    """跨进程取消标记文件（Flask debug reloader / 多进程下内存标志不可靠）。"""
    root = Path(upload_root) if upload_root else Path(__file__).resolve().parent.parent / "uploads"
    return root / "training" / "cancel" / f"{int(job_id)}.flag"


def request_cancel(job_id, upload_root: Path | None = None):
    """请求取消：内存标志 + 落盘标志。"""
    jid = int(job_id)
    with _cancel_lock:
        _cancel_flags[jid] = True
    try:
        p = _cancel_flag_path(jid, upload_root)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("1", encoding="utf-8")
    except OSError:
        pass


def is_cancelled(job_id, upload_root: Path | None = None):
    """是否已请求取消（内存或磁盘标志任一为真）。"""
    jid = int(job_id)
    with _cancel_lock:
        if _cancel_flags.get(jid, False):
            return True
    try:
        return _cancel_flag_path(jid, upload_root).is_file()
    except OSError:
        return False


def clear_cancel(job_id, upload_root: Path | None = None):
    jid = int(job_id)
    with _cancel_lock:
        _cancel_flags.pop(jid, None)
    try:
        p = _cancel_flag_path(jid, upload_root)
        if p.is_file():
            p.unlink()
    except OSError:
        pass


# ── VOC → YOLO ────────────────────────────────────────

def parse_voc(xml_path: Path, class_names):
    """解析 VOC XML。

    Returns:
        (img_w, img_h, boxes, found_classes)
        - boxes: 只包含 class_names 内的目标
        - found_classes: xml 中出现过的所有类别名（用于诊断）
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    size = root.find("size")
    if size is None:
        raise ValueError("VOC XML 缺少 <size> 节点")
    w_node = size.find("width")
    h_node = size.find("height")
    if w_node is None or h_node is None:
        raise ValueError("VOC XML <size> 缺少 width/height")
    img_w = int(float(w_node.text))
    img_h = int(float(h_node.text))

    boxes = []
    found = set()
    for obj in root.iter("object"):
        name_node = obj.find("name")
        if name_node is None or not (name_node.text or "").strip():
            continue
        cls_name = name_node.text.strip()
        found.add(cls_name)
        cls_id = class_names.index(cls_name) if cls_name in class_names else -1
        if cls_id < 0:
            continue
        bb = obj.find("bndbox")
        if bb is None:
            continue
        xmin_n, ymin_n = bb.find("xmin"), bb.find("ymin")
        xmax_n, ymax_n = bb.find("xmax"), bb.find("ymax")
        if None in (xmin_n, ymin_n, xmax_n, ymax_n):
            continue
        xmin = float(xmin_n.text)
        ymin = float(ymin_n.text)
        xmax = float(xmax_n.text)
        ymax = float(ymax_n.text)
        boxes.append((cls_id, xmin, ymin, xmax, ymax))
    return img_w, img_h, boxes, sorted(found)


def voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h):
    cx = ((xmin + xmax) / 2) / img_w
    cy = ((ymin + ymax) / 2) / img_h
    bw = (xmax - xmin) / img_w
    bh = (ymax - ymin) / img_h
    return cx, cy, bw, bh


def build_yolo_dataset(raw_dir: Path, yolo_dir: Path, class_names, split_ratio=0.8, seed=42):
    """将 raw_dir 中的 VOC(jpg+xml) 转为 YOLO 目录结构。"""
    for split in ("train", "val"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    xml_files = sorted(raw_dir.glob("*.xml"))
    random.seed(seed)
    random.shuffle(xml_files)
    n_train = int(len(xml_files) * split_ratio)
    splits = {"train": xml_files[:n_train], "val": xml_files[n_train:]}

    ok, skip = 0, 0
    skip_no_image = 0
    skip_no_boxes = 0
    skip_parse_error = 0
    found_classes = set()
    train_n, val_n = 0, 0
    for split, files in splits.items():
        for xml_path in files:
            stem = xml_path.stem
            img_src = None
            for ext in (".jpg", ".jpeg", ".png", ".bmp"):
                p = raw_dir / f"{stem}{ext}"
                if p.exists():
                    img_src = p
                    break
            if img_src is None:
                skip += 1
                skip_no_image += 1
                continue
            try:
                img_w, img_h, boxes, found = parse_voc(xml_path, class_names)
                found_classes.update(found)
            except Exception:  # noqa: BLE001
                skip += 1
                skip_parse_error += 1
                continue
            if not boxes:
                skip += 1
                skip_no_boxes += 1
                continue
            img_dst = yolo_dir / "images" / split / img_src.name
            shutil.copy2(img_src, img_dst)
            lbl_dst = yolo_dir / "labels" / split / f"{stem}.txt"
            with open(lbl_dst, "w", encoding="utf-8") as f:
                for cls_id, xmin, ymin, xmax, ymax in boxes:
                    cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            ok += 1
            if split == "train":
                train_n += 1
            else:
                val_n += 1
    diag = {
        "xmlTotal": len(xml_files),
        "ok": ok,
        "skip": skip,
        "skipNoImage": skip_no_image,
        "skipNoBoxes": skip_no_boxes,
        "skipParseError": skip_parse_error,
        "foundClasses": sorted(found_classes),
    }
    return ok, skip, train_n, val_n, diag


def write_data_yaml(yolo_dir: Path, class_names):
    yaml_path = yolo_dir / "data.yaml"
    content = (
        f"path: {yolo_dir.as_posix()}\n"
        f"train: images/train\n"
        f"val: images/val\n\n"
        f"nc: {len(class_names)}\n"
        f"names: {class_names}\n"
    )
    yaml_path.write_text(content, encoding="utf-8")
    return yaml_path


# ── 多格式数据集：检测 / 解析 / 构建 ─────────────────

def _find_image(stem: str, *dirs: Path):
    """在若干目录中按 stem 查找图片。"""
    for d in dirs:
        if not d or not d.exists():
            continue
        for ext in IMG_EXTENSIONS:
            p = d / f"{stem}{ext}"
            if p.exists():
                return p
    return None


def _count_split(yolo_dir: Path):
    train_n = len(list((yolo_dir / "images" / "train").glob("*"))) if (yolo_dir / "images" / "train").exists() else 0
    val_n = len(list((yolo_dir / "images" / "val").glob("*"))) if (yolo_dir / "images" / "val").exists() else 0
    return train_n, val_n


def _is_roboflow_yolo_layout(source_dir: Path) -> bool:
    """Roboflow 导出：train/images + train/labels（valid/ 作 val）。"""
    return (
        (source_dir / "train" / "images").is_dir()
        and (source_dir / "train" / "labels").is_dir()
    )


def _is_standard_yolo_layout(source_dir: Path) -> bool:
    """标准 YOLO：images/train + labels/train。"""
    return (
        (source_dir / "images" / "train").is_dir()
        and (source_dir / "labels" / "train").is_dir()
    )


def _copy_roboflow_yolo_splits(source_dir: Path, yolo_dir: Path):
    """将 Roboflow 目录复制为标准 YOLO images/train|val + labels/train|val。"""
    split_map = (("train", "train"), ("valid", "val"), ("val", "val"))
    copied = set()
    for src_split, dst_split in split_map:
        if dst_split in copied:
            continue
        img_src = source_dir / src_split / "images"
        lbl_src = source_dir / src_split / "labels"
        if not img_src.is_dir() or not lbl_src.is_dir():
            continue
        img_dst = yolo_dir / "images" / dst_split
        lbl_dst = yolo_dir / "labels" / dst_split
        img_dst.mkdir(parents=True, exist_ok=True)
        lbl_dst.mkdir(parents=True, exist_ok=True)
        for img in sorted(img_src.iterdir()):
            if not img.is_file() or img.suffix.lower() not in IMG_EXTENSIONS:
                continue
            lbl = lbl_src / f"{img.stem}.txt"
            if not lbl.exists():
                continue
            shutil.copy2(img, img_dst / img.name)
            shutil.copy2(lbl, lbl_dst / lbl.name)
        copied.add(dst_split)


def parse_data_yaml(yaml_path: Path):
    """解析 YOLO data.yaml，返回 {path, train, val, nc, names}。"""
    if not yaml_path.exists():
        return {}
    names = []
    nc = 0
    data = {"path": "", "train": "images/train", "val": "images/val"}
    for line in yaml_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        if key == "names":
            if val.startswith("["):
                try:
                    names = json.loads(val.replace("'", '"'))
                except json.JSONDecodeError:
                    names = [x.strip().strip("'\"") for x in val.strip("[]").split(",") if x.strip()]
            else:
                names = [val.strip("'\"")]
        elif key == "nc":
            try:
                nc = int(val)
            except ValueError:
                pass
        else:
            data[key] = val
    if names:
        data["names"] = names
        data["nc"] = nc or len(names)
    return data


def detect_dataset_format(source_dir: Path):
    """自动检测数据集目录格式。返回格式名或 None。"""
    if not source_dir.exists():
        return None

    source_dir = unwrap_dataset_root(source_dir)

    if _is_roboflow_yolo_layout(source_dir):
        return "yolo"

    yaml_path = source_dir / "data.yaml"
    if yaml_path.exists():
        if (source_dir / "images" / "train").is_dir() and (source_dir / "labels" / "train").is_dir():
            return "yolo"
        yaml_data = parse_data_yaml(yaml_path)
        base = Path(yaml_data.get("path") or source_dir)
        train_rel = yaml_data.get("train", "images/train")
        if (base / train_rel).exists() or (source_dir / train_rel).exists():
            return "yolo"

    if (source_dir / "images" / "train").is_dir() and (source_dir / "labels" / "train").is_dir():
        return "yolo"
    if (source_dir / "images" / "val").is_dir() and (source_dir / "labels" / "val").is_dir():
        return "yolo"

    if (source_dir / "images").is_dir() and (source_dir / "labels").is_dir():
        img_files = [p for p in (source_dir / "images").iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
        if img_files:
            return "yolo_flat"

    ann_dir = source_dir / "Annotations"
    img_dir = None
    for name in ("JPEGImages", "Images", "images"):
        if (source_dir / name).is_dir():
            img_dir = source_dir / name
            break
    if ann_dir.is_dir() and img_dir and list(ann_dir.glob("*.xml")):
        return "voc_standard"

    if list(source_dir.glob("*.xml")):
        return "voc"

    txt_files = list(source_dir.glob("*.txt"))
    img_files = [p for p in source_dir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
    if txt_files and img_files:
        return "yolo_flat"

    if _find_coco_json_files(source_dir):
        return "coco"

    if _detect_labelme_dataset(source_dir):
        return "labelme"

    return None


def _is_coco_json(path: Path):
    """判断 JSON 是否为 COCO instances 格式。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            isinstance(data, dict)
            and isinstance(data.get("images"), list)
            and isinstance(data.get("annotations"), list)
        )
    except (OSError, json.JSONDecodeError, TypeError):
        return False


def _find_coco_json_files(source_dir: Path):
    """查找目录中的 COCO JSON 文件。"""
    found = []
    search_dirs = [source_dir]
    ann = source_dir / "annotations"
    if ann.is_dir():
        search_dirs.insert(0, ann)
    for d in search_dirs:
        for p in sorted(d.glob("*.json")):
            if _is_coco_json(p):
                found.append(p)
    return found


def _detect_labelme_dataset(source_dir: Path):
    """是否存在 LabelMe 风格的 json+图片配对。"""
    count = 0
    for jp in source_dir.rglob("*.json"):
        if jp.name == "data.yaml":
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "shapes" not in data:
            continue
        stem = jp.stem
        if _find_image(stem, source_dir, source_dir / "images"):
            count += 1
        if count >= 1:
            return True
    return False


def _resolve_coco_image(file_name: str, source_dir: Path):
    """根据 COCO file_name 查找图片路径。"""
    fn = file_name.replace("\\", "/")
    candidates = [
        source_dir / fn,
        source_dir / "images" / Path(fn).name,
        source_dir / "images" / fn,
        source_dir / "train" / Path(fn).name,
        source_dir / "val" / Path(fn).name,
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    # 递归按文件名搜索
    base = Path(fn).name
    for p in source_dir.rglob(base):
        if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS:
            return p
    return None


def _coco_bbox_to_yolo(bbox, img_w, img_h):
    """COCO [x,y,w,h] -> YOLO normalized cx,cy,w,h。"""
    x, y, bw, bh = bbox
    xmin, ymin = float(x), float(y)
    xmax, ymax = xmin + float(bw), ymin + float(bh)
    return voc_to_yolo(0, xmin, ymin, xmax, ymax, img_w, img_h)


def _parse_coco_categories(coco_data, class_names=None):
    """解析 COCO categories，返回 (class_names_ordered, cat_id_to_cls_id, found_names)。"""
    cats = coco_data.get("categories") or []
    id_to_name = {}
    for c in cats:
        cid = c.get("id")
        name = (c.get("name") or "").strip()
        if cid is not None and name:
            id_to_name[int(cid)] = name

    found_names = sorted(set(id_to_name.values()))
    if not class_names:
        # 按 category id 排序
        ordered = [id_to_name[i] for i in sorted(id_to_name.keys())]
        class_names = ordered or found_names
    else:
        class_names = list(class_names)

    cat_id_to_cls = {}
    for cat_id, name in id_to_name.items():
        if name in class_names:
            cat_id_to_cls[cat_id] = class_names.index(name)

    return class_names, cat_id_to_cls, found_names


def _write_yolo_label(lbl_path: Path, boxes):
    """boxes: list of (cls_id, cx, cy, bw, bh)"""
    with open(lbl_path, "w", encoding="utf-8") as f:
        for cls_id, cx, cy, bw, bh in boxes:
            f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")


def _process_coco_json(json_path: Path, source_dir: Path, yolo_dir: Path, split: str,
                       class_names, cat_id_to_cls, img_root: Path = None):
    """处理单个 COCO JSON，写入指定 split。返回 (ok, skip, found_classes)。"""
    coco = json.loads(json_path.read_text(encoding="utf-8"))
    img_root = img_root or source_dir

    img_map = {}
    for im in coco.get("images") or []:
        iid = im.get("id")
        if iid is None:
            continue
        img_map[int(iid)] = im

    ann_by_img = {}
    found_classes = set()
    for ann in coco.get("annotations") or []:
        if ann.get("iscrowd"):
            continue
        bbox = ann.get("bbox")
        if not bbox or len(bbox) < 4:
            continue
        cat_id = ann.get("category_id")
        if cat_id is None or int(cat_id) not in cat_id_to_cls:
            continue
        iid = int(ann.get("image_id", -1))
        cls_id = cat_id_to_cls[int(cat_id)]
        ann_by_img.setdefault(iid, []).append((cls_id, bbox))

    ok, skip = 0, 0
    out_img = yolo_dir / "images" / split
    out_lbl = yolo_dir / "labels" / split
    out_img.mkdir(parents=True, exist_ok=True)
    out_lbl.mkdir(parents=True, exist_ok=True)

    for iid, boxes_raw in ann_by_img.items():
        im = img_map.get(iid)
        if not im:
            skip += 1
            continue
        file_name = im.get("file_name") or ""
        img_w = int(im.get("width") or 0)
        img_h = int(im.get("height") or 0)
        img_src = _resolve_coco_image(file_name, img_root)
        if img_src is None:
            skip += 1
            continue
        if img_w <= 0 or img_h <= 0:
            import cv2  # noqa: lazy
            arr = cv2.imread(str(img_src))
            if arr is None:
                skip += 1
                continue
            img_h, img_w = arr.shape[:2]

        yolo_boxes = []
        for cls_id, bbox in boxes_raw:
            cx, cy, bw, bh = _coco_bbox_to_yolo(bbox, img_w, img_h)
            if bw <= 0 or bh <= 0:
                continue
            yolo_boxes.append((cls_id, cx, cy, bw, bh))

        if not yolo_boxes:
            skip += 1
            continue

        stem = Path(file_name).stem or img_src.stem
        dst_name = img_src.name
        shutil.copy2(img_src, out_img / dst_name)
        _write_yolo_label(out_lbl / f"{stem}.txt", yolo_boxes)
        ok += 1

    return ok, skip


def build_from_coco(source_dir: Path, yolo_dir: Path, class_names=None, split_ratio=0.8, seed=42):
    """COCO instances JSON → YOLO。"""
    if yolo_dir.exists():
        shutil.rmtree(yolo_dir, ignore_errors=True)

    json_files = _find_coco_json_files(source_dir)
    if not json_files:
        raise ValueError("未找到 COCO instances JSON（需含 images、annotations 字段）")

    # 尝试 train/val 分文件
    train_json = val_json = None
    for p in json_files:
        low = p.stem.lower()
        if "train" in low:
            train_json = p
        elif "val" in low or "valid" in low:
            val_json = p

    # 读取 categories 确定类别
    sample = json.loads(json_files[0].read_text(encoding="utf-8"))
    class_names, cat_id_to_cls, found_names = _parse_coco_categories(sample, class_names)
    if not cat_id_to_cls:
        hint = f"；JSON 中类别={found_names}" if found_names else ""
        raise ValueError(f"无有效类别，请填写 classNames{hint}")

    train_n, val_n = 0, 0
    total_skip = 0

    if train_json and val_json:
        ok_t, skip_t = _process_coco_json(train_json, source_dir, yolo_dir, "train", class_names, cat_id_to_cls)
        ok_v, skip_v = _process_coco_json(val_json, source_dir, yolo_dir, "val", class_names, cat_id_to_cls)
        train_n, val_n = ok_t, ok_v
        total_skip = skip_t + skip_v
    else:
        # 单文件：按 image id 随机切分
        json_path = json_files[0]
        coco = json.loads(json_path.read_text(encoding="utf-8"))
        images = coco.get("images") or []
        random.seed(seed)
        random.shuffle(images)
        n_train = max(1, int(len(images) * split_ratio))
        train_ids = {int(im["id"]) for im in images[:n_train] if im.get("id") is not None}
        val_ids = {int(im["id"]) for im in images[n_train:] if im.get("id") is not None}
        if not val_ids and train_ids:
            last = images[n_train - 1]["id"]
            train_ids.discard(int(last))
            val_ids.add(int(last))
        if not train_ids and val_ids:
            # 仅 1 张图时保证 train 非空
            vid = next(iter(val_ids))
            val_ids.discard(vid)
            train_ids.add(vid)

        for split, id_set in (("train", train_ids), ("val", val_ids)):
            if not id_set:
                continue
            sub = {
                "images": [im for im in images if int(im.get("id", -1)) in id_set],
                "annotations": [
                    a for a in (coco.get("annotations") or [])
                    if int(a.get("image_id", -1)) in id_set
                ],
                "categories": coco.get("categories") or [],
            }
            tmp_json = yolo_dir.parent / f"_coco_tmp_{split}.json"
            tmp_json.write_text(json.dumps(sub), encoding="utf-8")
            try:
                ok, skip = _process_coco_json(tmp_json, source_dir, yolo_dir, split, class_names, cat_id_to_cls)
            finally:
                tmp_json.unlink(missing_ok=True)
            if split == "train":
                train_n = ok
            else:
                val_n = ok
            total_skip += skip

    if train_n + val_n == 0:
        diag = {"format": "coco", "jsonFiles": [p.name for p in json_files], "foundClasses": found_names, "skip": total_skip}
        return 0, 0, diag

    write_data_yaml(yolo_dir, class_names)
    diag = {
        "format": "coco",
        "jsonFiles": [p.name for p in json_files],
        "train": train_n,
        "val": val_n,
        "skip": total_skip,
        "classNames": class_names,
        "foundClasses": found_names,
    }
    return train_n, val_n, diag


def _labelme_points_to_bbox(points):
    """LabelMe points → xmin,ymin,xmax,ymax。"""
    if not points or len(points) < 2:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def parse_labelme(json_path: Path, class_names):
    """解析 LabelMe JSON。返回 (img_w, img_h, boxes, found_labels)。"""
    data = json.loads(json_path.read_text(encoding="utf-8"))
    img_w = int(data.get("imageWidth") or 0)
    img_h = int(data.get("imageHeight") or 0)
    boxes = []
    found = set()
    for shape in data.get("shapes") or []:
        st = (shape.get("shape_type") or "").lower()
        if st not in ("rectangle", "polygon"):
            continue
        label = (shape.get("label") or "").strip()
        if not label:
            continue
        found.add(label)
        cls_id = class_names.index(label) if label in class_names else -1
        if cls_id < 0:
            continue
        bb = _labelme_points_to_bbox(shape.get("points"))
        if not bb:
            continue
        xmin, ymin, xmax, ymax = bb
        boxes.append((cls_id, xmin, ymin, xmax, ymax))
    return img_w, img_h, boxes, sorted(found)


def _collect_labelme_pairs(source_dir: Path):
    """收集 LabelMe 图片-json 配对。"""
    pairs = []
    seen = set()
    for jp in sorted(source_dir.rglob("*.json")):
        if _is_coco_json(jp):
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "shapes" not in data:
            continue
        stem = jp.stem
        if stem in seen:
            continue
        img_path = None
        image_path = data.get("imagePath") or data.get("image_path")
        if image_path:
            for cand in (source_dir / image_path, source_dir / Path(image_path).name,
                         source_dir / "images" / Path(image_path).name):
                if cand.exists():
                    img_path = cand
                    break
        if img_path is None:
            img_path = _find_image(stem, source_dir, source_dir / "images")
        if img_path:
            pairs.append((img_path, jp))
            seen.add(stem)
    return pairs


def build_from_labelme(source_dir: Path, yolo_dir: Path, class_names=None, split_ratio=0.8, seed=42):
    """LabelMe JSON + 图片 → YOLO。"""
    pairs = _collect_labelme_pairs(source_dir)
    if not pairs:
        raise ValueError("未找到 LabelMe 配对（图片 + 含 shapes 的 .json）")

    # 汇总全部 label
    all_labels = set()
    for _, jp in pairs:
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            for s in data.get("shapes") or []:
                lb = (s.get("label") or "").strip()
                if lb:
                    all_labels.add(lb)
        except (OSError, json.JSONDecodeError):
            pass

    if not class_names:
        class_names = sorted(all_labels)
    if not class_names:
        raise ValueError("无法确定类别，请填写 classNames")

    if yolo_dir.exists():
        shutil.rmtree(yolo_dir, ignore_errors=True)
    for split in ("train", "val"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    random.shuffle(pairs)
    n_train = max(1, int(len(pairs) * split_ratio))
    splits = {"train": pairs[:n_train], "val": pairs[n_train:]}
    if not splits["val"]:
        if len(pairs) == 1:
            splits = {"train": pairs, "val": pairs}
        else:
            splits["val"] = splits["train"][-1:]
            splits["train"] = splits["train"][:-1]

    ok, skip = 0, 0
    skip_no_boxes = 0
    train_n, val_n = 0, 0
    found_classes = set(all_labels)

    for split, items in splits.items():
        for img_src, json_path in items:
            try:
                img_w, img_h, boxes, found = parse_labelme(json_path, class_names)
                found_classes.update(found)
            except (OSError, json.JSONDecodeError):
                skip += 1
                continue
            if img_w <= 0 or img_h <= 0:
                import cv2
                arr = cv2.imread(str(img_src))
                if arr is None:
                    skip += 1
                    continue
                img_h, img_w = arr.shape[:2]
            if not boxes:
                skip += 1
                skip_no_boxes += 1
                continue
            stem = img_src.stem
            shutil.copy2(img_src, yolo_dir / "images" / split / img_src.name)
            lbl_dst = yolo_dir / "labels" / split / f"{stem}.txt"
            with open(lbl_dst, "w", encoding="utf-8") as f:
                for cls_id, xmin, ymin, xmax, ymax in boxes:
                    cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            ok += 1
            if split == "train":
                train_n += 1
            else:
                val_n += 1

    diag = {
        "format": "labelme",
        "pairs": len(pairs),
        "ok": ok,
        "skip": skip,
        "skipNoBoxes": skip_no_boxes,
        "foundClasses": sorted(found_classes),
        "classNames": class_names,
    }
    if ok == 0:
        return 0, 0, diag
    write_data_yaml(yolo_dir, class_names)
    return train_n, val_n, diag


def is_allowed_import_path(path: Path, app_base_dir: Path):
    """限制可导入的本地路径在项目目录内。"""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    project_root = app_base_dir.parent.resolve()
    allowed_roots = [
        project_root,
        app_base_dir.resolve(),
        (app_base_dir / "uploads").resolve(),
    ]
    return any(str(resolved).startswith(str(root)) for root in allowed_roots)


def extract_zip_dataset(zip_path: Path, dest_dir: Path):
    """解压 zip 到目标目录，返回解压的文件数。

    兼容 Roboflow 常见结构：顶层项目目录 / train|valid / images|labels / …
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [info.filename.replace("\\", "/") for info in zf.infolist() if not info.is_dir()]
        # 若所有文件共有唯一顶层目录，则剥掉（Roboflow / GitHub 导出常见）
        tops = {n.split("/", 1)[0] for n in names if n and not n.startswith("..")}
        strip_root = None
        if len(tops) == 1:
            root = next(iter(tops))
            # 顶层不是 train/images/labels 本身时才剥离
            if root.lower() not in ("train", "valid", "val", "test", "images", "labels"):
                strip_root = root

        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if ".." in name or name.startswith("/"):
                continue
            if strip_root and name.startswith(strip_root + "/"):
                rel = name[len(strip_root) + 1 :]
            else:
                rel = name
            if not rel:
                continue
            target = dest_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            count += 1
    return count


def unwrap_dataset_root(source_dir: Path) -> Path:
    """若 raw 下仅有一层包裹目录且内含 YOLO/Roboflow 结构，则返回内层路径。"""
    if not source_dir.is_dir():
        return source_dir
    if _is_roboflow_yolo_layout(source_dir) or _is_standard_yolo_layout(source_dir):
        return source_dir
    if (source_dir / "data.yaml").exists():
        return source_dir
    children = [p for p in source_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if len(children) == 1:
        inner = children[0]
        if (
            _is_roboflow_yolo_layout(inner)
            or _is_standard_yolo_layout(inner)
            or (inner / "data.yaml").exists()
        ):
            return inner
    return source_dir


def list_base_models(upload_root: Path | None = None):
    """训练基座模型选项（含 YOLO11 与本地羽毛球权重）。"""
    opts = [
        {
            "value": "yolo11n.pt",
            "label": "YOLO11n（推荐轻量，羽毛球自训）",
            "group": "yolo11",
            "hint": "backend/weights/yolo11n.pt；无本地文件时由 Ultralytics 自动下载",
        },
        {
            "value": "yolo11s.pt",
            "label": "YOLO11s（精度优先）",
            "group": "yolo11",
            "hint": "比 n 更准、稍慢",
        },
        {
            "value": "yolov8n.pt",
            "label": "YOLOv8n（轻量）",
            "group": "yolov8",
            "hint": "backend/weights/yolov8n.pt；无本地文件时由 Ultralytics 自动下载",
        },
        {
            "value": "yolov8s.pt",
            "label": "YOLOv8s",
            "group": "yolov8",
        },
        {
            "value": "yolov8m.pt",
            "label": "YOLOv8m",
            "group": "yolov8",
        },
    ]
    # 本地 Good-Badminton / 已部署羽毛球权重可作为微调起点
    if upload_root:
        root = Path(upload_root)
        candidates = [
            ("local:yolo11s-ball", root / "models" / "yolo11s-ball" / "yolo11s-ball.pt",
             "YOLO11s-ball（Good-Badminton，微调推荐）"),
        ]
        # 已部署的自定义羽毛球权重
        models_dir = root / "models"
        if models_dir.is_dir():
            for sub in sorted(models_dir.iterdir()):
                if not sub.is_dir():
                    continue
                key = sub.name.lower()
                if "badminton" not in key and "ball" not in key and "shuttle" not in key:
                    continue
                for pt in sorted(sub.glob("*.pt")):
                    val = f"local:{sub.name}/{pt.name}"
                    if any(o["value"] == val for o in opts):
                        continue
                    if pt.name == "yolo11s-ball.pt":
                        continue
                    opts.append({
                        "value": val,
                        "label": f"微调自 {sub.name}/{pt.name}",
                        "group": "finetune",
                        "hint": "基于已部署权重继续训练",
                    })
        for value, path, label in candidates:
            if path.is_file():
                opts.insert(2, {
                    "value": value,
                    "label": label,
                    "group": "finetune",
                    "hint": str(path),
                    "available": True,
                })
    return opts


def _resolve_official_pretrained(name: str) -> str:
    """官方短名优先解析为 backend/weights 下本地权重，不存在则回退 Ultralytics 自动下载。"""
    path = PRETRAINED_WEIGHTS_DIR / name
    if path.is_file():
        return str(path)
    return name


def resolve_base_model(base_model: str, upload_root: Path | None = None) -> str:
    """将 baseModel 解析为 Ultralytics YOLO() 可加载的路径或官方权重名。"""
    name = (base_model or "yolo11n.pt").strip()
    if not name:
        name = "yolo11n.pt"
    # 官方短名 -> backend/weights/*.pt（本地有则用之，否则由 Ultralytics 下载）
    if name.endswith(".pt") and "/" not in name and "\\" not in name and not name.startswith("local:"):
        return _resolve_official_pretrained(name)
    if name.startswith("local:"):
        rel = name[len("local:"):].replace("\\", "/").lstrip("/")
        if upload_root:
            # yolo11s-ball → models/yolo11s-ball/yolo11s-ball.pt
            if "/" not in rel and not rel.endswith(".pt"):
                cand = Path(upload_root) / "models" / rel / f"{rel}.pt"
                if cand.is_file():
                    return str(cand)
            path = Path(upload_root) / "models" / rel
            if path.is_file():
                return str(path)
            # models/<key>/best.pt
            if not rel.endswith(".pt"):
                for fname in ("best.pt", f"{Path(rel).name}.pt"):
                    p2 = Path(upload_root) / "models" / rel / fname
                    if p2.is_file():
                        return str(p2)
        raise ValueError(f"本地基座权重不存在: {name}")
    # 绝对路径
    p = Path(name)
    if p.is_file():
        return str(p)
    if upload_root:
        rel = Path(upload_root) / name
        if rel.is_file():
            return str(rel)
    return name


def badminton_deploy_defaults(job):
    """羽毛球检测部署到模型管理的默认字段。"""
    jid = getattr(job, "id", 0) or 0
    base = (getattr(job, "base_model", "") or "").lower()
    size = "s" if "yolo11s" in base or "yolov8s" in base else "n"
    return {
        "modelName": f"自训羽毛球 YOLO11{size}",
        "modelKey": f"badminton-yolo11{size}-{jid}",
        "category": "目标检测",
        "task": "object-detection",
        "library": "ultralytics",
        "version": "v11",
        "description": (
            f"训练任务 #{jid} 产出的羽毛球（shuttlecock）检测权重。"
            "可在「羽毛球分析」页作为羽毛球模型选用；可由 Roboflow 导出集 + 自有比赛抽帧微调。"
        ),
    }


def build_from_native_yolo(source_dir: Path, yolo_dir: Path, class_names=None):
    """复制/校验已划分好的 YOLO 数据集（images/train|val + labels/train|val）。"""
    if yolo_dir.exists():
        shutil.rmtree(yolo_dir, ignore_errors=True)

    source_dir = unwrap_dataset_root(source_dir)

    yaml_src = source_dir / "data.yaml"
    yaml_names = []
    if yaml_src.exists():
        yaml_data = parse_data_yaml(yaml_src)
        yaml_names = yaml_data.get("names") or []

    if not class_names and yaml_names:
        class_names = yaml_names
    if not class_names:
        class_names = _infer_class_names_from_labels(source_dir)
    if not class_names:
        raise ValueError("无法确定类别：请在 data.yaml 或表单中填写 classNames")

    if _is_roboflow_yolo_layout(source_dir):
        _copy_roboflow_yolo_splits(source_dir, yolo_dir)
    else:
        # 复制标准 images/labels 结构
        for sub in ("images", "labels"):
            for split in ("train", "val"):
                src = source_dir / sub / split
                if src.exists():
                    dst = yolo_dir / sub / split
                    shutil.copytree(src, dst)

    # 若只有 train 无 val，从 train 切 20% 作 val
    train_imgs = list((yolo_dir / "images" / "train").glob("*")) if (yolo_dir / "images" / "train").exists() else []
    val_imgs = list((yolo_dir / "images" / "val").glob("*")) if (yolo_dir / "images" / "val").exists() else []
    if train_imgs and not val_imgs:
        _split_train_to_val(yolo_dir, ratio=0.2, seed=42)

    train_n, val_n = _count_split(yolo_dir)
    if train_n + val_n == 0:
        raise ValueError("YOLO 数据集中未找到有效图片")

    yaml_path = write_data_yaml(yolo_dir, class_names)
    diag = {
        "format": "yolo",
        "train": train_n,
        "val": val_n,
        "classNames": class_names,
        "fromYaml": bool(yaml_names),
    }
    return train_n, val_n, diag


def _infer_class_names_from_labels(source_dir: Path):
    """从标签文件推断最大 class_id，生成占位类别名。"""
    max_id = -1
    label_dirs = [
        source_dir / "labels" / "train",
        source_dir / "labels" / "val",
        source_dir / "labels",
    ]
    for d in label_dirs:
        if not d.exists():
            continue
        for txt in d.glob("*.txt"):
            try:
                for line in txt.read_text(encoding="utf-8").splitlines():
                    parts = line.strip().split()
                    if parts:
                        max_id = max(max_id, int(parts[0]))
            except (OSError, ValueError):
                continue
    if max_id < 0:
        return []
    return [f"class_{i}" for i in range(max_id + 1)]


def _split_train_to_val(yolo_dir: Path, ratio=0.2, seed=42):
    """从 train 随机切分一部分到 val。"""
    train_img_dir = yolo_dir / "images" / "train"
    train_lbl_dir = yolo_dir / "labels" / "train"
    val_img_dir = yolo_dir / "images" / "val"
    val_lbl_dir = yolo_dir / "labels" / "val"
    val_img_dir.mkdir(parents=True, exist_ok=True)
    val_lbl_dir.mkdir(parents=True, exist_ok=True)

    imgs = [p for p in train_img_dir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
    random.seed(seed)
    random.shuffle(imgs)
    n_val = max(1, int(len(imgs) * ratio))
    for img in imgs[:n_val]:
        stem = img.stem
        lbl = train_lbl_dir / f"{stem}.txt"
        shutil.move(str(img), str(val_img_dir / img.name))
        if lbl.exists():
            shutil.move(str(lbl), str(val_lbl_dir / lbl.name))


def build_from_yolo_flat(source_dir: Path, yolo_dir: Path, class_names, split_ratio=0.8, seed=42):
    """将扁平 YOLO（images/ + labels/ 或同目录 jpg+txt）切分为 train/val。"""
    if yolo_dir.exists():
        shutil.rmtree(yolo_dir, ignore_errors=True)
    for split in ("train", "val"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    img_dir = source_dir / "images" if (source_dir / "images").is_dir() else source_dir
    lbl_dir = source_dir / "labels" if (source_dir / "labels").is_dir() else source_dir

    pairs = []
    for img in sorted(img_dir.iterdir()):
        if not img.is_file() or img.suffix.lower() not in IMG_EXTENSIONS:
            continue
        lbl = lbl_dir / f"{img.stem}.txt"
        if not lbl.exists():
            continue
        pairs.append((img, lbl))

    if not pairs:
        if _is_roboflow_yolo_layout(source_dir) or _is_standard_yolo_layout(source_dir):
            return build_from_native_yolo(source_dir, yolo_dir, class_names)
        raise ValueError(
            "未找到配对的图片与 .txt 标签；"
            "若为 Roboflow 等已划分 YOLO 数据集，请选择「YOLO 原生」或「自动检测」"
        )

    random.seed(seed)
    random.shuffle(pairs)
    n_train = max(1, int(len(pairs) * split_ratio))
    splits = {"train": pairs[:n_train], "val": pairs[n_train:]}
    if not splits["val"]:
        if len(pairs) == 1:
            splits = {"train": pairs, "val": pairs}
        else:
            splits["val"] = splits["train"][-1:]
            splits["train"] = splits["train"][:-1]

    ok = 0
    train_n, val_n = 0, 0
    for split, items in splits.items():
        for img, lbl in items:
            shutil.copy2(img, yolo_dir / "images" / split / img.name)
            shutil.copy2(lbl, yolo_dir / "labels" / split / lbl.name)
            ok += 1
            if split == "train":
                train_n += 1
            else:
                val_n += 1

    if not class_names:
        class_names = _infer_class_names_from_labels(yolo_dir)
    if not class_names:
        raise ValueError("请填写类别名称 classNames")

    yaml_path = write_data_yaml(yolo_dir, class_names)
    diag = {"format": "yolo_flat", "pairs": len(pairs), "ok": ok, "train": train_n, "val": val_n}
    return train_n, val_n, diag


def build_from_voc_standard(source_dir: Path, yolo_dir: Path, class_names, split_ratio=0.8, seed=42):
    """Pascal VOC 标准目录：Annotations/ + JPEGImages|Images/。"""
    ann_dir = source_dir / "Annotations"
    img_dir = None
    for name in ("JPEGImages", "Images", "images"):
        if (source_dir / name).is_dir():
            img_dir = source_dir / name
            break
    if not ann_dir.is_dir() or not img_dir:
        raise ValueError("未找到 Annotations/ 与 JPEGImages|Images/ 目录")

    if yolo_dir.exists():
        shutil.rmtree(yolo_dir, ignore_errors=True)
    for split in ("train", "val"):
        (yolo_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (yolo_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    xml_files = sorted(ann_dir.glob("*.xml"))
    random.seed(seed)
    random.shuffle(xml_files)
    n_train = int(len(xml_files) * split_ratio)
    splits = {"train": xml_files[:n_train], "val": xml_files[n_train:]}

    ok, skip = 0, 0
    skip_no_image = skip_no_boxes = skip_parse_error = 0
    found_classes = set()
    train_n, val_n = 0, 0

    for split, files in splits.items():
        for xml_path in files:
            stem = xml_path.stem
            img_src = _find_image(stem, img_dir)
            if img_src is None:
                skip += 1
                skip_no_image += 1
                continue
            try:
                img_w, img_h, boxes, found = parse_voc(xml_path, class_names)
                found_classes.update(found)
            except Exception:  # noqa: BLE001
                skip += 1
                skip_parse_error += 1
                continue
            if not boxes:
                skip += 1
                skip_no_boxes += 1
                continue
            shutil.copy2(img_src, yolo_dir / "images" / split / img_src.name)
            lbl_dst = yolo_dir / "labels" / split / f"{stem}.txt"
            with open(lbl_dst, "w", encoding="utf-8") as f:
                for cls_id, xmin, ymin, xmax, ymax in boxes:
                    cx, cy, bw, bh = voc_to_yolo(cls_id, xmin, ymin, xmax, ymax, img_w, img_h)
                    f.write(f"{cls_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n")
            ok += 1
            if split == "train":
                train_n += 1
            else:
                val_n += 1

    diag = {
        "format": "voc_standard",
        "xmlTotal": len(xml_files),
        "ok": ok,
        "skip": skip,
        "skipNoImage": skip_no_image,
        "skipNoBoxes": skip_no_boxes,
        "skipParseError": skip_parse_error,
        "foundClasses": sorted(found_classes),
    }
    if ok == 0:
        return 0, 0, diag
    write_data_yaml(yolo_dir, class_names)
    return train_n, val_n, diag


def import_external_dataset(source_path: Path, yolo_dir: Path, class_names=None, app_base_dir=None):
    """从本地已有目录导入（如 backend/yolo_dataset）。"""
    if not source_path.exists():
        raise ValueError(f"源路径不存在: {source_path}")
    if app_base_dir and not is_allowed_import_path(source_path, app_base_dir):
        raise ValueError("仅允许导入项目目录内的数据集路径")

    detected = detect_dataset_format(source_path)
    if detected is None:
        raise ValueError("无法识别源目录的数据集格式，请确认包含 YOLO、VOC、COCO 或 LabelMe 结构")

    if detected == "yolo":
        return build_from_native_yolo(source_path, yolo_dir, class_names)
    if detected == "yolo_flat":
        return build_from_yolo_flat(source_path, yolo_dir, class_names or [])
    if detected == "voc_standard":
        if not class_names:
            raise ValueError("VOC 标准格式导入需填写 classNames")
        return build_from_voc_standard(source_path, yolo_dir, class_names)
    if detected == "voc":
        if not class_names:
            raise ValueError("VOC 格式导入需填写 classNames")
        ok, skip, train_n, val_n, diag = build_yolo_dataset(source_path, yolo_dir, class_names)
        if ok == 0:
            return 0, 0, diag
        write_data_yaml(yolo_dir, class_names)
        diag["format"] = "voc"
        return train_n, val_n, diag

    if detected == "coco":
        return build_from_coco(source_path, yolo_dir, class_names)

    if detected == "labelme":
        return build_from_labelme(source_path, yolo_dir, class_names)

    raise ValueError(f"不支持的源格式: {detected}")


def build_dataset_unified(
    fmt: str,
    source_dir: Path,
    yolo_dir: Path,
    class_names,
    split_ratio=0.8,
    source_path: Path = None,
    app_base_dir: Path = None,
):
    """统一数据集构建入口。

    Args:
        fmt: auto/voc/voc_standard/yolo/yolo_flat/import
        source_dir: uploads/datasets/<id>/raw 或工作目录
        yolo_dir: 输出 YOLO 目录
        class_names: 类别列表
        split_ratio: 训练集比例
        source_path: import 格式的本地绝对路径
        app_base_dir: backend 目录，用于路径安全校验

    Returns:
        (train_n, val_n, diag)
    """
    if yolo_dir.exists():
        shutil.rmtree(yolo_dir, ignore_errors=True)

    if fmt == "import":
        if not source_path:
            raise ValueError("import 格式需提供 sourcePath")
        return import_external_dataset(source_path, yolo_dir, class_names, app_base_dir)

    work_dir = unwrap_dataset_root(Path(source_dir)) if source_dir else source_dir
    if fmt == "auto":
        detected = detect_dataset_format(work_dir)
        if not detected:
            raise ValueError(
                "自动检测失败：请确认目录包含 VOC、YOLO、COCO JSON 或 LabelMe JSON 结构"
                "（Roboflow 导出请选 YOLOv8/YOLO11 格式 zip）"
            )
        fmt = detected

    if fmt == "voc":
        ok, skip, train_n, val_n, diag = build_yolo_dataset(
            work_dir, yolo_dir, class_names, split_ratio=split_ratio,
        )
        if ok == 0:
            return 0, 0, diag
        write_data_yaml(yolo_dir, class_names)
        diag["format"] = "voc"
        return train_n, val_n, diag

    if fmt == "voc_standard":
        train_n, val_n, diag = build_from_voc_standard(
            work_dir, yolo_dir, class_names, split_ratio=split_ratio,
        )
        if train_n + val_n == 0:
            return 0, 0, diag
        return train_n, val_n, diag

    if fmt == "yolo":
        return build_from_native_yolo(work_dir, yolo_dir, class_names)

    if fmt == "yolo_flat":
        return build_from_yolo_flat(work_dir, yolo_dir, class_names, split_ratio=split_ratio)

    if fmt == "coco":
        return build_from_coco(work_dir, yolo_dir, class_names, split_ratio=split_ratio)

    if fmt == "labelme":
        return build_from_labelme(work_dir, yolo_dir, class_names, split_ratio=split_ratio)

    raise ValueError(f"不支持的数据集格式: {fmt}")


def scan_dataset_structure(source_dir: Path):
    """扫描目录结构，返回预览信息。"""
    if not source_dir.exists():
        return {"exists": False, "files": [], "detectedFormat": None}

    detected = detect_dataset_format(source_dir)
    files = []
    for p in sorted(source_dir.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(source_dir)).replace("\\", "/")
            files.append({"name": rel, "size": p.stat().st_size})
            if len(files) >= 200:
                break

    summary = {
        "exists": True,
        "detectedFormat": detected,
        "formatLabel": DATASET_FORMATS.get(detected, detected),
        "fileCount": len(files),
        "files": files[:50],
        "hasDataYaml": (source_dir / "data.yaml").exists(),
        "hasImagesTrain": (source_dir / "images" / "train").is_dir(),
        "hasLabelsTrain": (source_dir / "labels" / "train").is_dir(),
        "cocoJsonCount": len(_find_coco_json_files(source_dir)),
        "labelmePairs": len(_collect_labelme_pairs(source_dir)),
        "xmlCount": len(list(source_dir.glob("*.xml"))) + (
            len(list((source_dir / "Annotations").glob("*.xml")))
            if (source_dir / "Annotations").exists() else 0
        ),
    }
    if (source_dir / "data.yaml").exists():
        yaml_data = parse_data_yaml(source_dir / "data.yaml")
        summary["yamlNames"] = yaml_data.get("names", [])
    return summary

def parse_results_csv(results_csv: Path):
    """解析 Ultralytics results.csv 最后一行指标。"""
    if not results_csv.exists():
        return {}
    try:
        with open(results_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        if not rows:
            return {}
        last = rows[-1]
        out = {}
        for k, v in last.items():
            key = k.strip()
            try:
                out[key] = round(float(v), 6)
            except (ValueError, TypeError):
                out[key] = v
        return out
    except OSError:
        return {}


def read_metrics_history(results_csv: Path, max_rows=200):
    if not results_csv.exists():
        return []
    try:
        with open(results_csv, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        history = []
        for row in rows[-max_rows:]:
            item = {}
            for k, v in row.items():
                key = k.strip()
                try:
                    item[key] = round(float(v), 6)
                except (ValueError, TypeError):
                    item[key] = v
            history.append(item)
        return history
    except OSError:
        return []


def _update_job_metrics(job, save_dir):
    results_csv = Path(save_dir) / "results.csv"
    latest = parse_results_csv(results_csv)
    history = read_metrics_history(results_csv)
    job.set_metrics({"latest": latest, "history": history})
    if latest:
        for key in ("metrics/mAP50(B)", "metrics/mAP50-95(B)", "mAP50", "mAP50-95"):
            if key in latest:
                job.progress = min(99, job.progress)
                break


def run_training_worker(app, job_id):
    """后台训练线程。"""
    with app.app_context():
        from extensions import db
        from models.training import TrainingJob, TrainingDataset

        job = TrainingJob.query.get(job_id)
        if not job:
            return

        upload_root = Path(app.config["UPLOAD_FOLDER"])

        # 启动前若已取消（pending 被取消 / 残留标志），直接退出
        if job.status in ("cancelled", "cancelling") or is_cancelled(job_id, upload_root):
            job.status = "cancelled"
            job.error_message = "用户取消训练"
            db.session.commit()
            clear_cancel(job_id, upload_root)
            return

        ds = TrainingDataset.query.get(job.dataset_id)
        if not ds or ds.status != "ready" or not ds.yaml_path:
            job.status = "failed"
            job.error_message = "数据集未就绪，请先构建数据集"
            db.session.commit()
            return

        yaml_abs = upload_root / ds.yaml_path
        if not yaml_abs.exists():
            job.status = "failed"
            job.error_message = f"data.yaml 不存在: {ds.yaml_path}"
            db.session.commit()
            return

        hp = job.hyperparams_dict()
        epochs = int(hp.get("epochs", job.total_epochs or 100))
        batch = int(hp.get("batch", 8))
        imgsz = int(hp.get("imgsz", 640))
        device = str(hp.get("device", "cpu"))
        patience = int(hp.get("patience", 20))

        runs_root = upload_root / "training" / "runs" / str(job_id)
        runs_root.mkdir(parents=True, exist_ok=True)
        run_name = job.run_name or f"train_{job_id}"

        log_root = upload_root / "training" / "logs" / str(job_id)
        log_root.mkdir(parents=True, exist_ok=True)
        train_log = log_root / "train.log"

        def _log(line: str):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                train_log.open("a", encoding="utf-8").write(f"[{ts}] {line}\n")
            except OSError:
                pass

        def _mark_cancelled(reason="用户取消训练"):
            j = TrainingJob.query.get(job_id)
            if j is None:
                return
            j.status = "cancelled"
            j.error_message = reason
            db.session.commit()

        def _stop_trainer(trainer, reason="收到取消请求，正在停止…"):
            try:
                trainer.stop = True
            except Exception:  # noqa: BLE001
                pass
            try:
                # 部分版本用此属性
                if hasattr(trainer, "stopper"):
                    trainer.stopper.possible_stop = True
            except Exception:  # noqa: BLE001
                pass
            _log(reason)

        # 仅清理「上一轮残留」标志；若此刻已取消则退出
        if is_cancelled(job_id, upload_root):
            _mark_cancelled()
            clear_cancel(job_id, upload_root)
            _log("启动前检测到取消，退出")
            return
        clear_cancel(job_id, upload_root)

        job.status = "running"
        job.total_epochs = epochs
        job.current_epoch = 0
        job.progress = 0
        job.error_message = None
        job.log_dir = str(runs_root.relative_to(upload_root)).replace("\\", "/")
        db.session.commit()

        _log(f"训练开始: job={job_id} base={job.base_model} epochs={epochs} batch={batch} imgsz={imgsz} device={device}")
        _log(f"data.yaml: {ds.yaml_path}")

        def _check_stop(trainer, where=""):
            if not is_cancelled(job_id, upload_root):
                # 同步读库状态（cancelling）
                try:
                    with app.app_context():
                        j = TrainingJob.query.get(job_id)
                        if j and j.status == "cancelling":
                            request_cancel(job_id, upload_root)
                except Exception:  # noqa: BLE001
                    pass
            if is_cancelled(job_id, upload_root):
                _stop_trainer(trainer, f"收到取消请求（{where}），正在停止…")
                return True
            return False

        def on_train_batch_end(trainer):
            _check_stop(trainer, "batch")

        def on_train_epoch_end(trainer):
            if _check_stop(trainer, "epoch"):
                return
            with app.app_context():
                j = TrainingJob.query.get(job_id)
                if j is None:
                    return
                j.current_epoch = int(trainer.epoch) + 1
                j.progress = min(99, int(j.current_epoch / max(epochs, 1) * 100))
                _update_job_metrics(j, trainer.save_dir)
                db.session.commit()
                latest = j.metrics_dict().get("latest") or {}
                m50 = latest.get("metrics/mAP50(B)", latest.get("mAP50"))
                lbox = latest.get("train/box_loss")
                _log(f"Epoch {j.current_epoch}/{epochs} progress={j.progress}% mAP50={m50} box_loss={lbox}")

        def on_fit_epoch_end(trainer):
            _check_stop(trainer, "fit_epoch")

        try:
            from ultralytics import YOLO

            if is_cancelled(job_id, upload_root):
                _mark_cancelled()
                _log("加载基座前已取消")
                return

            try:
                base_resolved = resolve_base_model(job.base_model or "yolo11n.pt", upload_root)
            except ValueError as e:
                job.status = "failed"
                job.error_message = str(e)
                db.session.commit()
                _log(str(e))
                return

            if is_cancelled(job_id, upload_root):
                _mark_cancelled()
                _log("解析基座后已取消")
                return

            _log(f"加载基座: {base_resolved}")
            model = YOLO(base_resolved)
            model.add_callback("on_train_batch_end", on_train_batch_end)
            model.add_callback("on_train_epoch_end", on_train_epoch_end)
            model.add_callback("on_fit_epoch_end", on_fit_epoch_end)

            if is_cancelled(job_id, upload_root):
                _mark_cancelled()
                _log("train() 前已取消")
                return

            results = model.train(
                data=str(yaml_abs),
                epochs=epochs,
                imgsz=imgsz,
                batch=batch,
                device=device,
                project=str(runs_root),
                name=run_name,
                patience=patience,
                workers=0,
                exist_ok=True,
                verbose=True,
            )

            job = TrainingJob.query.get(job_id)
            if job is None:
                return

            if is_cancelled(job_id, upload_root) or job.status == "cancelling":
                job.status = "cancelled"
                job.error_message = "用户取消训练"
                _log("训练取消完成")
            else:
                save_dir = Path(results.save_dir) if results else runs_root / run_name
                best_pt = save_dir / "weights" / "best.pt"
                if best_pt.exists():
                    out_dir = upload_root / "training" / "weights" / str(job_id)
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_pt = out_dir / "best.pt"
                    shutil.copy2(best_pt, out_pt)
                    job.output_weight_path = str(out_pt.relative_to(upload_root)).replace("\\", "/")
                    job.status = "done"
                    job.progress = 100
                    job.current_epoch = epochs
                    _update_job_metrics(job, save_dir)
                    _log(f"训练完成，best.pt 已保存: {job.output_weight_path}")
                else:
                    job.status = "failed"
                    job.error_message = f"未找到 best.pt: {save_dir}"
                    _log(f"训练失败：未找到 best.pt: {save_dir}")
        except Exception as e:  # noqa: BLE001
            job = TrainingJob.query.get(job_id)
            if job:
                if is_cancelled(job_id, upload_root) or job.status == "cancelling":
                    job.status = "cancelled"
                    job.error_message = "用户取消训练"
                    _log("训练取消（异常路径）")
                else:
                    job.status = "failed"
                    job.error_message = str(e)
                    _log(f"训练异常：{e}")
        finally:
            db.session.commit()
            clear_cancel(job_id, upload_root)
            j = TrainingJob.query.get(job_id)
            _log(f"训练线程结束: status={j.status if j else 'unknown'}")


def run_validate_worker(app, job_id):
    """后台验证线程：写入 logs/<job_id>/val.log，并返回 metrics。"""
    with app.app_context():
        from extensions import db
        from models.training import TrainingJob, TrainingDataset

        upload_root = Path(app.config["UPLOAD_FOLDER"])
        log_root = upload_root / "training" / "logs" / str(job_id)
        log_root.mkdir(parents=True, exist_ok=True)
        val_log = log_root / "val.log"

        def _log(line: str):
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                val_log.open("a", encoding="utf-8").write(f"[{ts}] {line}\n")
            except OSError:
                pass

        job = TrainingJob.query.get(job_id)
        if not job:
            _log("任务不存在")
            return None
        if not job.output_weight_path:
            _log("任务无训练权重，无法验证")
            return None
        ds = TrainingDataset.query.get(job.dataset_id)
        if not ds or not ds.yaml_path:
            _log("数据集 yaml 不可用")
            return None

        hp = job.hyperparams_dict()
        device = str(hp.get("device", "cpu"))
        weight_abs = upload_root / job.output_weight_path
        yaml_abs = upload_root / ds.yaml_path
        _log(f"验证开始: job={job_id} weight={job.output_weight_path} device={device}")
        try:
            metrics = validate_model(weight_abs, yaml_abs, device=device)
            _log(f"验证完成: metrics_keys={list(metrics.keys())}")
            return metrics
        except Exception as e:  # noqa: BLE001
            _log(f"验证异常：{e}")
            return None


def validate_model(weight_abs: Path, yaml_abs: Path, device="cpu"):
    from ultralytics import YOLO

    model = YOLO(str(weight_abs))
    metrics = model.val(data=str(yaml_abs), device=device, verbose=False)
    result = {}
    if hasattr(metrics, "results_dict"):
        for k, v in metrics.results_dict.items():
            try:
                result[k] = round(float(v), 6)
            except (TypeError, ValueError):
                result[k] = v
    elif hasattr(metrics, "box"):
        result["mAP50"] = round(float(metrics.box.map50), 6)
        result["mAP50-95"] = round(float(metrics.box.map), 6)
    return result


def test_predict(weight_abs: Path, image_bytes, conf=0.25):
    import base64

    import cv2
    import numpy as np
    from ultralytics import YOLO

    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("无法解析图片")

    model = YOLO(str(weight_abs))
    results = model(img, conf=conf, verbose=False)
    annotated = results[0].plot()
    ok, buf = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 92])
    img_b64 = base64.b64encode(buf.tobytes()).decode() if ok else None

    detections = []
    if results and results[0].boxes is not None:
        names = results[0].names or {}
        for box in results[0].boxes:
            cls_id = int(box.cls.item())
            detections.append({
                "className": names.get(cls_id, str(cls_id)),
                "confidence": round(float(box.conf.item()), 4),
                "bbox": [round(float(x), 1) for x in box.xyxy[0].tolist()],
            })
    return {"imageBase64": img_b64, "detections": detections, "count": len(detections)}


def export_model(weight_abs: Path, out_dir: Path, fmt="onnx"):
    from ultralytics import YOLO

    out_dir.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(weight_abs))
    path = model.export(format=fmt)
    if path and Path(path).exists():
        dest = out_dir / Path(path).name
        if Path(path).resolve() != dest.resolve():
            shutil.copy2(path, dest)
        return dest
    raise FileNotFoundError(f"导出失败: {fmt}")


def deploy_to_ai_model(app, job, model_name, model_key, category, description="",
                       task="object-detection", library="ultralytics", version="v11"):
    """将训练权重注册到 ai_model 表。"""
    from extensions import db
    from models import AiModel

    if not job.output_weight_path:
        raise ValueError("训练任务尚无可用权重")

    upload_root = Path(app.config["UPLOAD_FOLDER"])
    src = upload_root / job.output_weight_path
    if not src.exists():
        raise ValueError("权重文件不存在")

    if AiModel.query.filter_by(model_key=model_key).first():
        raise ValueError(f"模型标识 {model_key} 已存在")

    dest_dir = Path(app.config["MODEL_FOLDER"]) / model_key
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "best.pt"
    shutil.copy2(src, dest)

    rel = str(dest.relative_to(upload_root)).replace("\\", "/")
    m = AiModel(
        model_name=model_name,
        model_key=model_key,
        category=category or "目标检测",
        task=task or "object-detection",
        library=library or "ultralytics",
        version=version or "v11",
        file_path=rel,
        file_size=dest.stat().st_size,
        description=description or f"训练任务 #{job.id} 产出",
        status="0",
    )
    db.session.add(m)
    db.session.flush()
    job.output_model_id = m.id
    db.session.commit()
    return m
