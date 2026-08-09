"""命令行入口"""
import argparse
import json
import logging
import sys
import os
from pathlib import Path

from docmask import __version__
from docmask.config import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_FORMATS,
    DESENSITIZED_SUFFIX,
    RESTORED_SUFFIX,
)
from docmask.core.codebook import Codebook, CodebookError
from docmask.core.masker import Masker, MaskConflictError
from docmask.core.restorer import Restorer
from docmask.services.file_service import collect_files, get_handler
from docmask.utils.logger import setup_logging
from docmask.utils.file_utils import resolve_output_path

logger = logging.getLogger(__name__)


def _load_codebook(codebook_path: str) -> Codebook:
    """加载并校验密码本，出错时打印友好提示并退出"""
    if not os.path.exists(codebook_path):
        print(f"错误: 密码本文件未找到：{codebook_path}")
        sys.exit(1)

    try:
        cb = Codebook(codebook_path)
        cb.load()
    except CodebookError as e:
        print(f"错误: {e}")
        sys.exit(1)

    messages = cb.validate()
    has_error = False
    for msg in messages:
        print(msg)
        if msg.startswith("ERROR"):
            has_error = True
    if has_error:
        print("密码本存在错误，无法继续操作。")
        sys.exit(1)

    return cb


def cmd_check(args) -> int:
    """校验密码本"""
    try:
        cb = Codebook(args.codebook)
        cb.load()
    except CodebookError as e:
        print(f"错误: {e}")
        return 1

    messages = cb.validate()
    has_error = False
    for msg in messages:
        print(msg)
        if msg.startswith("ERROR"):
            has_error = True

    if not messages:
        print("密码本校验通过。")
        print(f"  精确规则: {cb.exact_rule_count} 条")
        print(f"  正则规则: {cb.regex_rule_count} 条")
    else:
        if has_error:
            print("密码本存在错误，请修正后重试。")
        else:
            print("密码本存在警告，请检查。")

    return 1 if has_error else 0


def cmd_mask(args) -> int:
    """执行脱敏"""
    cb = _load_codebook(args.codebook)

    # 解析格式过滤
    formats = args.format.split(",") if args.format else DEFAULT_FORMATS

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"错误: 输入文件/目录未找到：{input_path}")
        return 1

    files, scan_errors = collect_files(input_path, formats)
    for err in scan_errors:
        print(f"[WARN] 目录访问错误: {err}")
    if not files:
        print(f"未找到可处理的文件（格式: {', '.join(formats)}）")
        return 0 if args.allow_empty else 2

    masker = Masker(cb)
    success_count = 0
    fail_count = 0
    total_replacements = 0
    all_hits: dict[str, int] = {}
    failures: list[tuple[str, str]] = []
    interrupted = False
    batch_mode = Path(input_path).is_dir() or len(files) > 1

    if batch_mode and args.output and Path(args.output).exists() and not Path(args.output).is_dir():
        print("错误: 批量处理时 --output 必须是目录，不能是文件")
        return 1

    for filepath in files:
        try:
            handler, fmt = get_handler(filepath)
            if handler is None:
                print(f"跳过: 不支持的文件格式 '{fmt}' — {filepath}")
                fail_count += 1
                continue

            resolved_output = resolve_output_path(
                filepath,
                args.output,
                suffix=DESENSITIZED_SUFFIX,
                batch_mode=batch_mode,
                output_extension=".docx" if Path(filepath).suffix.lower() == ".doc" else None,
            )
            output_path, count, coverage = handler.mask(
                filepath, masker, output_path=resolved_output
            )
            print(f"[OK] {filepath} -> {Path(output_path).name} (替换 {count} 处)")
            for warning in getattr(handler, "last_warnings", []):
                print(f"[WARN] {filepath}: {warning}")
            total_replacements += count
            for k, v in coverage.items():
                all_hits[k] = all_hits.get(k, 0) + v
            success_count += 1

        except KeyboardInterrupt:
            print("\n用户中断操作。")
            interrupted = True
            break
        except MaskConflictError as e:
            print(f"[冲突] {filepath}:")
            print(str(e))
            fail_count += 1
            failures.append((filepath, "脱敏词冲突"))
        except Exception as e:
            print(f"[FAIL] {filepath}: {e}")
            logger.error(f"脱敏失败: {filepath} - {e}")
            fail_count += 1
            failures.append((filepath, str(e)))

    # 汇总
    print()
    if interrupted:
        unprocessed = len(files) - success_count - fail_count
        print(f"脱敏已中断: 成功 {success_count} 个, 失败 {fail_count} 个, "
              f"未处理 {unprocessed} 个, 共替换 {total_replacements} 处")
    else:
        print(f"脱敏完成: 成功 {success_count} 个, 失败 {fail_count} 个, 共替换 {total_replacements} 处")
    if failures:
        print("失败详情:")
        for fp, err in failures:
            print(f"  {fp}: {err}")

    # 覆盖率报告
    if args.report and all_hits:
        report = masker.generate_coverage_summary(all_hits)
        print()
        print("隐私安全覆盖率报告（不含原文、替换值和正则内容）:")
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if interrupted:
        return 130
    return 1 if fail_count > 0 else 0


def cmd_restore(args) -> int:
    """执行恢复"""
    cb = _load_codebook(args.codebook)

    formats = args.format.split(",") if args.format else DEFAULT_FORMATS

    input_path = args.input
    if not os.path.exists(input_path):
        print(f"错误: 输入文件/目录未找到：{input_path}")
        return 1

    files, scan_errors = collect_files(input_path, formats)
    for err in scan_errors:
        print(f"[WARN] 目录访问错误: {err}")
    if not files:
        print(f"未找到可处理的文件（格式: {', '.join(formats)}）")
        return 0 if args.allow_empty else 2

    restorer = Restorer(cb)
    success_count = 0
    fail_count = 0
    total_replacements = 0
    failures: list[tuple[str, str]] = []
    interrupted = False
    batch_mode = Path(input_path).is_dir() or len(files) > 1

    if batch_mode and args.output and Path(args.output).exists() and not Path(args.output).is_dir():
        print("错误: 批量处理时 --output 必须是目录，不能是文件")
        return 1

    for filepath in files:
        try:
            handler, fmt = get_handler(filepath)
            if handler is None:
                print(f"跳过: 不支持的文件格式 '{fmt}' - {filepath}")
                fail_count += 1
                continue

            resolved_output = resolve_output_path(
                filepath,
                args.output,
                suffix=RESTORED_SUFFIX,
                batch_mode=batch_mode,
                output_extension=".docx" if Path(filepath).suffix.lower() == ".doc" else None,
            )
            output_path, count = handler.restore(
                filepath, restorer, output_path=resolved_output
            )
            print(f"[OK] {filepath} -> {Path(output_path).name} (替换 {count} 处)")
            total_replacements += count
            success_count += 1

        except KeyboardInterrupt:
            print("\n用户中断操作。")
            interrupted = True
            break
        except Exception as e:
            print(f"[FAIL] {filepath}: {e}")
            logger.error(f"恢复失败: {filepath} - {e}")
            fail_count += 1
            failures.append((filepath, str(e)))

    print()
    if interrupted:
        unprocessed = len(files) - success_count - fail_count
        print(f"恢复已中断: 成功 {success_count} 个, 失败 {fail_count} 个, "
              f"未处理 {unprocessed} 个, 共替换 {total_replacements} 处")
    else:
        print(f"恢复完成: 成功 {success_count} 个, 失败 {fail_count} 个, 共替换 {total_replacements} 处")
    if failures:
        print("失败详情:")
        for fp, err in failures:
            print(f"  {fp}: {err}")

    if interrupted:
        return 130
    return 1 if fail_count > 0 else 0


def main() -> None:
    """主入口"""
    parser = argparse.ArgumentParser(
        description="DocMask - 文档脱敏工具",
        prog="docmask",
    )
    parser.add_argument(
        "--version", "-V", action="version", version=f"docmask {__version__}"
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # check 子命令
    check_parser = subparsers.add_parser("check", help="校验密码本")
    check_parser.add_argument("--codebook", "-c", required=True, help="密码本文件路径")
    check_parser.add_argument(
        "--log-level", "-l", default=DEFAULT_LOG_LEVEL, help="日志级别"
    )

    # mask 子命令
    mask_parser = subparsers.add_parser("mask", help="脱敏文档")
    mask_parser.add_argument("--codebook", "-c", required=True, help="密码本文件路径")
    mask_parser.add_argument("--input", "-i", required=True, help="输入文件或目录路径")
    mask_parser.add_argument("--output", "-o", default=None, help="输出文件或目录路径")
    mask_parser.add_argument(
        "--format", "-f", default=",".join(DEFAULT_FORMATS),
        help="限定处理的文件格式，逗号分隔（默认 docx,doc,txt）"
    )
    mask_parser.add_argument(
        "--log-level", "-l", default=DEFAULT_LOG_LEVEL, help="日志级别"
    )
    mask_parser.add_argument(
        "--report", "-r", action="store_true", help="输出脱敏覆盖率报告"
    )
    mask_parser.add_argument(
        "--allow-empty", action="store_true",
        help="未找到文件时返回成功码 0（默认返回 2）",
    )

    # restore 子命令
    restore_parser = subparsers.add_parser("restore", help="恢复脱敏文档")
    restore_parser.add_argument("--codebook", "-c", required=True, help="密码本文件路径")
    restore_parser.add_argument("--input", "-i", required=True, help="输入文件或目录路径")
    restore_parser.add_argument("--output", "-o", default=None, help="输出文件或目录路径")
    restore_parser.add_argument(
        "--format", "-f", default=",".join(DEFAULT_FORMATS),
        help="限定处理的文件格式，逗号分隔（默认 docx,doc,txt）"
    )
    restore_parser.add_argument(
        "--log-level", "-l", default=DEFAULT_LOG_LEVEL, help="日志级别"
    )
    restore_parser.add_argument(
        "--verify", action="store_true", help=argparse.SUPPRESS
    )
    restore_parser.add_argument(
        "--allow-empty", action="store_true",
        help="未找到文件时返回成功码 0（默认返回 2）",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    setup_logging(args.log_level)

    if args.command == "check":
        sys.exit(cmd_check(args))
    elif args.command == "mask":
        sys.exit(cmd_mask(args))
    elif args.command == "restore":
        sys.exit(cmd_restore(args))


if __name__ == "__main__":
    main()
