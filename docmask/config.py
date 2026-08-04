"""全局配置常量"""

from docmask.utils.file_utils import user_data_dir

# 输出文件后缀
DESENSITIZED_SUFFIX = "_desensitized"
RESTORED_SUFFIX = "_restored"

# 日志：保存在用户数据目录的 Logs 子目录中
LOG_FILE = str(user_data_dir() / "Logs" / "docmask.log")
DEFAULT_LOG_LEVEL = "INFO"

# 默认支持的文件格式
DEFAULT_FORMATS = ["docx", "doc", "txt"]

# 密码本
CODEBOOK_SEPARATOR = "==>"
REGEX_PREFIX = "regex:"
COMMENT_PREFIX = "#"