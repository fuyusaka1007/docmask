"""文件编码检测工具"""
import chardet


def detect_encoding(filepath: str, read_bytes: int = 4096) -> str:
    """
    检测文件编码
    返回编码名称，如 'utf-8', 'gbk' 等
    """
    with open(filepath, "rb") as f:
        raw = f.read(read_bytes)
    result = chardet.detect(raw)
    encoding = result.get("encoding", "utf-8")
    if encoding is None:
        encoding = "utf-8"
    # 统一常见编码别名
    encoding_lower = encoding.lower()
    if encoding_lower in ("gb2312", "gb18030"):
        return "gbk"
    return encoding