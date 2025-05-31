#!/usr/bin/env python3
"""
YuttoPlus 安装配置
"""

from setuptools import setup, find_packages
from pathlib import Path

# 读取README文件
readme_file = Path(__file__).parent / "docs" / "README.md"
long_description = ""
if readme_file.exists():
    with open(readme_file, "r", encoding="utf-8") as f:
        long_description = f.read()

# 读取requirements文件
requirements_file = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_file.exists():
    with open(requirements_file, "r", encoding="utf-8") as f:
        requirements = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="yutto-plus",
    version="2.0.0",
    author="YuttoPlus Team",
    author_email="yutto-plus@example.com",
    description="Modern Bilibili Video Downloader with Parallel Downloads",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yutto-plus/yutto-plus",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Multimedia :: Video",
        "Topic :: Internet :: WWW/HTTP",
    ],
    python_requires=">=3.8",
    install_requires=requirements,
    extras_require={
        "webui": ["flask", "flask-socketio"],
        "dev": ["pytest", "black", "flake8"],
    },
    entry_points={
        "console_scripts": [
            "yutto-plus=yutto_plus.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "": ["*.yaml", "*.yml", "*.json"],
    },
    zip_safe=False,
) 