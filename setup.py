"""DocMask setup"""
from setuptools import setup, find_packages

setup(
    name="docmask",
    version="0.1.0-beta.2",
    description="文档脱敏工具 - 离线可逆的文档敏感信息替换工具",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "python-docx>=1.0",
        "chardet>=5.0",
        "lxml>=4.9",
    ],
    extras_require={
        "ui": [
            "customtkinter>=6.0.0",
            "darkdetect>=0.8.0",
            "tkinterdnd2>=0.4.2",
        ],
        "doc": [
            'pywin32>=306; sys_platform == "win32"',
        ],
        "dev": [
            "pytest>=7.0",
            "pyinstaller>=6.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "docmask=docmask.cli:main",
        ],
    },
)
