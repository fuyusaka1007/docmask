"""DocMask UI 主题：色板、字体、间距、控件尺寸

颜色以 (light, dark) 元组定义，CustomTkinter 自动按当前模式选择。
"""
import platform

# ======================== 色板 (light, dark) ========================

# 品牌主色
PRIMARY = ("#168AAD", "#38A6C7")
PRIMARY_HOVER = ("#11728F", "#2E8BA8")
PRIMARY_FG = ("#FFFFFF", "#FFFFFF")

# 页面背景
BG_PAGE = ("#F4F7FA", "#0F1722")
BG_CARD = ("#FFFFFF", "#172230")
BG_INPUT = ("#F9FAFB", "#1E2A38")

# 导航
BG_SIDEBAR = ("#0F1B2D", "#09111E")
FG_SIDEBAR = ("#DCE3EA", "#9AA8B8")
BG_SIDEBAR_ACTIVE = ("#168AAD", "#168AAD")
FG_SIDEBAR_ACTIVE = ("#FFFFFF", "#FFFFFF")

# 文字
FG_MAIN = ("#172033", "#F1F5F9")
FG_MUTED = ("#667085", "#9AA8B8")
FG_SUBTLE = ("#9CA3AF", "#6B7280")

# 边框
BORDER = ("#DCE3EA", "#2B3949")
BORDER_LIGHT = ("#EEF1F5", "#1E2A38")

# 状态色（两种模式一致）
SUCCESS = ("#168A5B", "#2DBA7E")
WARNING = ("#D68B16", "#E8A540")
ERROR = ("#D94A4A", "#E85A5A")
INFO = ("#3B82C4", "#5B9AE0")

# 状态背景色（浅底）
BG_SUCCESS = ("#E8F7F0", "#0D2B20")
BG_WARNING = ("#FDF4E6", "#2B2010")
BG_ERROR = ("#FCEAEA", "#2B1010")
BG_INFO = ("#E8F2FC", "#0D1E2B")

# 格式标签
TAG_DOCX = ("#3B82C4", "#5B9AE0")
TAG_DOC = ("#667085", "#9AA8B8")
TAG_TXT = ("#168A5B", "#2DBA7E")
BG_TAG_DOCX = ("#E8F2FC", "#0D1E2B")
BG_TAG_DOC = ("#EEF1F5", "#1E2A38")
BG_TAG_TXT = ("#E8F7F0", "#0D2B20")

# ======================== 字体 ========================

_SYS = platform.system()
if _SYS == "Windows":
    _FONT_FAMILY = "Microsoft YaHei UI"
elif _SYS == "Darwin":
    _FONT_FAMILY = "PingFang SC"
else:
    _FONT_FAMILY = "Noto Sans CJK SC"

FONT_FAMILY = _FONT_FAMILY

# 字号
FS_TITLE = 24        # 页面标题
FS_SECTION = 16      # 卡片标题
FS_BODY = 14         # 正文
FS_LABEL = 13        # 分区标签、状态和次按钮
FS_SMALL = 12        # 辅助文本
FS_BUTTON = 14       # 按钮
FS_STAT = 28         # 统计数字

# 字重
FW_NORMAL = "normal"
# Tk 字体仅支持有限的标准样式；用 normal 表示中等字重以兼容 macOS。
FW_MEDIUM = "normal"
FW_SEMIBOLD = "bold"

# ======================== 间距 ========================

S_1 = 4
S_2 = 8
S_3 = 12
S_4 = 16
S_5 = 24
S_6 = 32

# ======================== 控件尺寸 ========================

BTN_HEIGHT = 42       # 主按钮
BTN_HEIGHT_SM = 36    # 次按钮
INPUT_HEIGHT = 40     # 输入框
NAV_ITEM_HEIGHT = 44  # 导航项
ROW_HEIGHT = 48       # 表格行
RADIUS_CARD = 12      # 卡片圆角
RADIUS_BTN = 8        # 按钮圆角
RADIUS_INPUT = 8      # 输入框圆角
RADIUS_PILL = 999     # 徽章圆角
RADIUS_SM = 4         # 小圆角（标签、小按钮）

# 内容宽度
MAX_WIDTH_WORKBENCH = 860
MAX_WIDTH_CODEBOOK = 860
MAX_WIDTH_RESULTS = 860
MAX_WIDTH_SETTINGS = 860

# 窗口
WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 760
WINDOW_MIN_WIDTH = 980
WINDOW_MIN_HEIGHT = 640
SIDEBAR_WIDTH = 220


def font(size=FS_BODY, weight=FW_NORMAL):
    """生成字体元组"""
    return (FONT_FAMILY, size, weight)
