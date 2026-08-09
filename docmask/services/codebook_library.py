"""密码本库：多密码本管理 + 版本控制

所有数据存储在 user_data_dir()/codebooks/ 下，纯本地，不上传。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from docmask.core.codebook import Codebook, CodebookError
from docmask.utils.file_utils import user_data_dir, staged_output_path

logger = logging.getLogger(__name__)


@dataclass
class CodebookMeta:
    """密码本元数据（索引项）"""
    id: str
    name: str
    description: str = ""
    created_at: str = ""
    updated_at: str = ""
    current_version: str = ""
    version_count: int = 0
    exact_rule_count: int = 0
    regex_rule_count: int = 0


@dataclass
class VersionInfo:
    """版本快照信息"""
    version_id: str
    created_at: str
    exact_rule_count: int
    regex_rule_count: int
    change_summary: str


class CodebookLibrary:
    """密码本库：多密码本管理 + 版本控制

    存储结构::

        <base_dir>/index.json
        <base_dir>/<codebook_id>/current.txt
        <base_dir>/<codebook_id>/meta.json
        <base_dir>/<codebook_id>/versions/v-<timestamp>.txt
    """

    MAX_VERSIONS = 20

    # A-19: ID 格式校验，防止路径遍历
    _CODEBOOK_ID_RE = re.compile(r"^cb-[0-9a-f]{8}$")
    _VERSION_ID_RE = re.compile(r"^v-\d{8}_\d{6}_[0-9a-f]{6}$")

    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = base_dir or (user_data_dir() / "codebooks")
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base_dir / "index.json"
        self._ensure_index()

    # ======================== 索引读写 ========================

    @classmethod
    def _validate_codebook_id(cls, codebook_id: str) -> None:
        """A-19: 校验密码本 ID 格式，防止路径遍历攻击。"""
        if not isinstance(codebook_id, str) or not cls._CODEBOOK_ID_RE.match(codebook_id):
            raise CodebookError(f"无效的密码本 ID：{codebook_id}")

    @classmethod
    def _validate_version_id(cls, version_id: str) -> None:
        """A-19: 校验版本 ID 格式，防止路径遍历攻击。"""
        if not isinstance(version_id, str) or not cls._VERSION_ID_RE.match(version_id):
            raise CodebookError(f"无效的版本 ID：{version_id}")

    def _ensure_index(self) -> None:
        if not self._index_path.exists():
            # A-19: 索引不存在时从子目录重建，而非直接创建空索引
            self._rebuild_index()
        # A-08: 检测并恢复中断的保存操作
        self._recover_interrupted_saves()

    def _recover_interrupted_saves(self) -> None:
        """A-08: 检测并恢复中断的保存操作。

        如果发现 commit marker，说明上次保存被中断。
        使用 commit marker 中的 meta 数据恢复一致性。
        """
        if not self._base_dir.exists():
            return
        for cb_dir in self._base_dir.iterdir():
            if not cb_dir.is_dir() or cb_dir.name.startswith("."):
                continue
            # A-19: 跳过不符合 ID 格式的目录
            if not self._CODEBOOK_ID_RE.match(cb_dir.name):
                continue
            commit_marker = cb_dir / ".commit"
            if not commit_marker.exists():
                continue
            codebook_id = cb_dir.name
            try:
                new_meta = json.loads(
                    commit_marker.read_text(encoding="utf-8")
                )
                version_id = new_meta.get("current_version", "")
                version_path = cb_dir / "versions" / f"{version_id}.txt"
                if version_path.exists():
                    # 版本文件已写入 -> 确保其余文件一致
                    current_path = cb_dir / "current.txt"
                    if not current_path.exists() or \
                            current_path.read_text(encoding="utf-8") != \
                            version_path.read_text(encoding="utf-8"):
                        shutil.copy2(version_path, current_path)
                    self._write_meta(codebook_id, new_meta)
                    versions = new_meta.get("versions", [])
                    last_v = versions[-1] if versions else {}
                    meta_obj = CodebookMeta(
                        id=codebook_id,
                        name=new_meta.get("name", ""),
                        description=new_meta.get("description", ""),
                        created_at=new_meta.get("created_at", ""),
                        updated_at=new_meta.get("updated_at", ""),
                        current_version=version_id,
                        version_count=len(versions),
                        exact_rule_count=last_v.get("exact_rule_count", 0),
                        regex_rule_count=last_v.get("regex_rule_count", 0),
                    )
                    self._update_index_entry(meta_obj)
                # 版本文件不存在 -> 保存中断极早，旧状态完好，无需操作
                commit_marker.unlink()
            except (json.JSONDecodeError, OSError):
                try:
                    commit_marker.unlink()
                except FileNotFoundError:
                    pass

    def _read_index(self) -> dict:
        """A-19: 读取索引并校验结构；损坏时从子目录重建。"""
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning("索引文件损坏或不存在，尝试从子目录重建")
            return self._rebuild_index()
        if not isinstance(data, dict) or not isinstance(data.get("codebooks"), list):
            logger.warning("索引结构无效，尝试从子目录重建")
            return self._rebuild_index()
        return data

    def _rebuild_index(self) -> dict:
        """A-19: 从子目录重建索引。不静默返回空库。"""
        codebooks: list[dict] = []
        if self._base_dir.exists():
            for cb_dir in sorted(self._base_dir.iterdir()):
                if not cb_dir.is_dir() or cb_dir.name.startswith("."):
                    continue
                cb_id = cb_dir.name
                if not self._CODEBOOK_ID_RE.match(cb_id):
                    continue
                meta = self._read_meta(cb_id)
                if not meta:
                    continue
                meta_obj = self._meta_to_obj(cb_id, meta)
                codebooks.append({
                    "id": meta_obj.id,
                    "name": meta_obj.name,
                    "description": meta_obj.description,
                    "created_at": meta_obj.created_at,
                    "updated_at": meta_obj.updated_at,
                    "current_version": meta_obj.current_version,
                    "version_count": meta_obj.version_count,
                    "exact_rule_count": meta_obj.exact_rule_count,
                    "regex_rule_count": meta_obj.regex_rule_count,
                })
        data = {"codebooks": codebooks}
        self._write_index(data)
        return data

    def _write_index(self, data: dict) -> None:
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".index.", suffix=".tmp", dir=str(self._base_dir)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp_name, self._index_path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _update_index_entry(self, meta: CodebookMeta) -> None:
        data = self._read_index()
        entry = {
            "id": meta.id,
            "name": meta.name,
            "description": meta.description,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "current_version": meta.current_version,
            "version_count": meta.version_count,
            "exact_rule_count": meta.exact_rule_count,
            "regex_rule_count": meta.regex_rule_count,
        }
        found = False
        for i, cb in enumerate(data["codebooks"]):
            if cb["id"] == meta.id:
                data["codebooks"][i] = entry
                found = True
                break
        if not found:
            data["codebooks"].append(entry)
        self._write_index(data)

    def _remove_index_entry(self, codebook_id: str) -> None:
        data = self._read_index()
        data["codebooks"] = [cb for cb in data["codebooks"] if cb["id"] != codebook_id]
        self._write_index(data)

    # ======================== 元数据读写 ========================

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _version_id() -> str:
        return f"v-{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def _codebook_dir(self, codebook_id: str) -> Path:
        # A-19: ID 校验 + 路径安全检查
        self._validate_codebook_id(codebook_id)
        path = self._base_dir / codebook_id
        resolved = path.resolve()
        base_resolved = self._base_dir.resolve()
        if resolved != base_resolved and base_resolved not in resolved.parents:
            raise CodebookError(f"路径越界：{codebook_id}")
        return path

    def _current_path(self, codebook_id: str) -> Path:
        return self._codebook_dir(codebook_id) / "current.txt"

    def _meta_path(self, codebook_id: str) -> Path:
        return self._codebook_dir(codebook_id) / "meta.json"

    def _versions_dir(self, codebook_id: str) -> Path:
        return self._codebook_dir(codebook_id) / "versions"

    def _read_meta(self, codebook_id: str) -> dict:
        path = self._meta_path(codebook_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_meta(self, codebook_id: str, meta: dict) -> None:
        path = self._meta_path(codebook_id)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".meta.", suffix=".tmp", dir=str(self._codebook_dir(codebook_id))
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(json.dumps(meta, ensure_ascii=False, indent=2))
            os.replace(tmp_name, path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # ======================== 辅助方法 ========================

    @staticmethod
    def _count_rules(codebook: Codebook) -> tuple[int, int]:
        return codebook.exact_rule_count, codebook.regex_rule_count

    def _make_change_summary(
        self, old_exact: int, old_regex: int, new_exact: int, new_regex: int
    ) -> str:
        parts = []
        diff_exact = new_exact - old_exact
        diff_regex = new_regex - old_regex
        if diff_exact > 0:
            parts.append(f"+{diff_exact} 精确规则")
        elif diff_exact < 0:
            parts.append(f"{diff_exact} 精确规则")
        if diff_regex > 0:
            parts.append(f"+{diff_regex} 正则规则")
        elif diff_regex < 0:
            parts.append(f"{diff_regex} 正则规则")
        if not parts:
            return "无变更"
        return ", ".join(parts)

    def _write_current(self, codebook_id: str, content: str) -> None:
        """原子写入 current.txt（内部管理文件，允许覆盖）。"""
        cb_dir = self._codebook_dir(codebook_id)
        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=".current.", suffix=".tmp", dir=str(cb_dir)
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp_name, self._current_path(codebook_id))
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def _meta_to_obj(self, codebook_id: str, meta: dict) -> CodebookMeta:
        versions = meta.get("versions", [])
        last_v = versions[-1] if versions else {}
        return CodebookMeta(
            id=codebook_id,
            name=meta.get("name", ""),
            description=meta.get("description", ""),
            created_at=meta.get("created_at", ""),
            updated_at=meta.get("updated_at", ""),
            current_version=meta.get("current_version", ""),
            version_count=len(versions),
            exact_rule_count=last_v.get("exact_rule_count", 0),
            regex_rule_count=last_v.get("regex_rule_count", 0),
        )

    # ======================== 密码本 CRUD ========================

    def list_codebooks(self) -> list[CodebookMeta]:
        """列出所有密码本元数据。"""
        data = self._read_index()
        result = []
        for cb in data.get("codebooks", []):
            result.append(CodebookMeta(
                id=cb["id"],
                name=cb["name"],
                description=cb.get("description", ""),
                created_at=cb.get("created_at", ""),
                updated_at=cb.get("updated_at", ""),
                current_version=cb.get("current_version", ""),
                version_count=cb.get("version_count", 0),
                exact_rule_count=cb.get("exact_rule_count", 0),
                regex_rule_count=cb.get("regex_rule_count", 0),
            ))
        return result

    def create(self, name: str, description: str = "") -> CodebookMeta:
        """创建新密码本（空规则），返回元数据。"""
        codebook_id = f"cb-{uuid.uuid4().hex[:8]}"
        now = self._now()
        cb_dir = self._codebook_dir(codebook_id)
        cb_dir.mkdir(parents=True, exist_ok=True)
        self._versions_dir(codebook_id).mkdir(parents=True, exist_ok=True)

        self._current_path(codebook_id).write_text("", encoding="utf-8")

        meta = {
            "id": codebook_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "versions": [],
        }
        self._write_meta(codebook_id, meta)

        meta_obj = CodebookMeta(
            id=codebook_id, name=name, description=description,
            created_at=now, updated_at=now,
        )
        self._update_index_entry(meta_obj)
        return meta_obj

    def load(self, codebook_id: str) -> Codebook:
        """加载密码本当前版本，返回 Codebook 实例。"""
        path = str(self._current_path(codebook_id))
        if not os.path.exists(path):
            raise CodebookError(f"密码本不存在：{codebook_id}")
        cb = Codebook(path)
        cb.load()
        return cb

    def save(self, codebook_id: str, codebook: Codebook) -> VersionInfo:
        """保存密码本并自动生成版本快照。

        A-08: 使用 commit marker 实现事务性保存。
        版本快照先写入，然后写入 commit marker 记录目标 meta 状态，
        最后依次更新 current.txt / meta.json / index.json。
        中断后启动时通过 commit marker 恢复一致性。
        """
        now = self._now()
        version_id = self._version_id()

        old_meta = self._read_meta(codebook_id)
        old_versions = old_meta.get("versions", [])
        old_exact = old_versions[-1]["exact_rule_count"] if old_versions else 0
        old_regex = old_versions[-1]["regex_rule_count"] if old_versions else 0

        new_exact, new_regex = self._count_rules(codebook)
        summary = self._make_change_summary(old_exact, old_regex, new_exact, new_regex)

        content = codebook.render()

        version_info = {
            "version_id": version_id,
            "created_at": now,
            "exact_rule_count": new_exact,
            "regex_rule_count": new_regex,
            "change_summary": summary,
        }
        new_versions = list(old_versions)
        new_versions.append(version_info)

        # 清理超出 MAX_VERSIONS 的旧版本
        removed_versions: list[dict] = []
        if len(new_versions) > self.MAX_VERSIONS:
            removed_versions = new_versions[: len(new_versions) - self.MAX_VERSIONS]
            new_versions = new_versions[len(new_versions) - self.MAX_VERSIONS:]

        new_meta = dict(old_meta)
        new_meta["updated_at"] = now
        new_meta["current_version"] = version_id
        new_meta["versions"] = new_versions

        cb_dir = self._codebook_dir(codebook_id)
        versions_dir = self._versions_dir(codebook_id)

        # A-08: 先写版本快照（作为备份），再写 commit marker
        version_path = versions_dir / f"{version_id}.txt"
        version_path.write_text(content, encoding="utf-8")

        commit_marker = cb_dir / ".commit"
        commit_marker.write_text(
            json.dumps(new_meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        try:
            # 依次更新各文件（每个文件本身通过 temp+os.replace 原子写入）
            self._write_current(codebook_id, content)

            # 删除超出上限的旧版本
            for v in removed_versions:
                v_path = versions_dir / f"{v['version_id']}.txt"
                try:
                    v_path.unlink()
                except FileNotFoundError:
                    pass

            self._write_meta(codebook_id, new_meta)

            # 更新索引
            meta_obj = CodebookMeta(
                id=codebook_id,
                name=new_meta.get("name", ""),
                description=new_meta.get("description", ""),
                created_at=new_meta.get("created_at", ""),
                updated_at=now,
                current_version=version_id,
                version_count=len(new_versions),
                exact_rule_count=new_exact,
                regex_rule_count=new_regex,
            )
            self._update_index_entry(meta_obj)

            # 事务完成 — 删除 commit marker
            commit_marker.unlink()
        except Exception:
            try:
                commit_marker.unlink()
            except FileNotFoundError:
                pass
            raise

        return VersionInfo(
            version_id=version_id,
            created_at=now,
            exact_rule_count=new_exact,
            regex_rule_count=new_regex,
            change_summary=summary,
        )

    def rename(self, codebook_id: str, new_name: str) -> None:
        """重命名密码本。"""
        meta = self._read_meta(codebook_id)
        meta["name"] = new_name
        meta["updated_at"] = self._now()
        self._write_meta(codebook_id, meta)
        meta_obj = self._meta_to_obj(codebook_id, meta)
        self._update_index_entry(meta_obj)

    def delete(self, codebook_id: str) -> None:
        """删除密码本及其所有版本。"""
        cb_dir = self._codebook_dir(codebook_id)
        if cb_dir.exists():
            shutil.rmtree(cb_dir)
        self._remove_index_entry(codebook_id)

    def duplicate(self, codebook_id: str, new_name: str) -> CodebookMeta:
        """复制密码本（含当前规则，不复制版本历史）。"""
        source_cb = self.load(codebook_id)
        new_meta = self.create(new_name)
        content = source_cb.render()
        if content.strip():
            self._write_current(new_meta.id, content)
            new_cb = Codebook(str(self._current_path(new_meta.id)))
            new_cb.load()
            self.save(new_meta.id, new_cb)
        # 返回更新后的元数据
        for m in self.list_codebooks():
            if m.id == new_meta.id:
                return m
        return new_meta

    def import_file(self, src_path: str, name: str) -> CodebookMeta:
        """从外部 .txt 文件导入密码本。"""
        cb = Codebook(src_path)
        cb.load()
        new_meta = self.create(name)
        content = cb.render()
        if content.strip():
            self._write_current(new_meta.id, content)
            new_cb = Codebook(str(self._current_path(new_meta.id)))
            new_cb.load()
            self.save(new_meta.id, new_cb)
        for m in self.list_codebooks():
            if m.id == new_meta.id:
                return m
        return new_meta

    def export_file(self, codebook_id: str, dest_path: str) -> None:
        """导出密码本当前版本到外部文件（原子不覆盖）。"""
        cb = self.load(codebook_id)
        content = cb.render()
        with staged_output_path(dest_path) as temp_path:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(content)

    # ======================== 版本管理 ========================

    def list_versions(self, codebook_id: str) -> list[VersionInfo]:
        """列出密码本的所有版本（最近在前）。"""
        meta = self._read_meta(codebook_id)
        versions = meta.get("versions", [])
        return [
            VersionInfo(
                version_id=v["version_id"],
                created_at=v["created_at"],
                exact_rule_count=v["exact_rule_count"],
                regex_rule_count=v["regex_rule_count"],
                change_summary=v["change_summary"],
            )
            for v in reversed(versions)
        ]

    def load_version(self, codebook_id: str, version_id: str) -> Codebook:
        """加载指定历史版本，返回 Codebook 实例。"""
        # A-19: 版本 ID 校验
        self._validate_version_id(version_id)
        version_path = self._versions_dir(codebook_id) / f"{version_id}.txt"
        if not version_path.exists():
            raise CodebookError(f"版本不存在：{version_id}")
        cb = Codebook(str(version_path))
        cb.load()
        return cb

    def restore_version(self, codebook_id: str, version_id: str) -> VersionInfo:
        """将指定历史版本恢复为当前版本（生成新快照）。"""
        cb = self.load_version(codebook_id, version_id)
        return self.save(codebook_id, cb)
