"""Streaming ZIP / Zstd / XZ backups and legacy Gzip; no extractall or shell tools."""
from __future__ import annotations

import gzip
import hashlib
import io
import lzma
import math
import stat
import tarfile
import time
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

try:
    import zstandard
except ImportError:
    zstandard = None  # Standalone ZIP/XZ migration helpers work without site-packages.


def zstd_codec():
    if zstandard is None:
        raise ValueError('Zstd 压缩需要安装 requirements.txt 中的 zstandard 依赖')
    return zstandard


ARCHIVE_ERRORS = (tarfile.TarError, zipfile.BadZipFile, lzma.LZMAError, EOFError) + (
    (zstandard.ZstdError,) if zstandard is not None else ())

FORMATS = {
    "zip": {"label": "ZIP · 通用", "extension": ".zip", "description": "通用兼容，均衡压缩"},
    "tar.zst": {"label": "Zstd · 快速", "extension": ".tar.zst", "description": "快速流式压缩，优先速度"},
    "tar.xz": {"label": "XZ · 高压缩", "extension": ".tar.xz", "description": "高压缩级别，优先体积，耗时更长"},
    "tar.gz": {"label": "TAR.GZ · 旧格式", "extension": ".tar.gz", "description": "兼容已有备份", "legacy": True},
}
MAX_MANIFEST = 16 * 1024 * 1024
MAX_MEMBERS = 200_000
CHUNK = 1024 * 1024
XZ_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME, "dict_size": 8 * 1024 * 1024}]


def normalize_format(value="zip"):
    if value not in FORMATS:
        raise ValueError("请选择 ZIP、Zstd 或 XZ 压缩格式")
    return value


def archive_format(filename):
    name = str(filename).lower()
    return next((key for key in FORMATS if name.endswith(FORMATS[key]["extension"])), None)


@dataclass(frozen=True)
class Member:
    name: str
    size: int
    mode: int
    regular: bool
    source: object


class ZstdReader(io.RawIOBase):
    """Seek over a Zstd stream by reopening only for backward reads; bounded memory."""
    def __init__(self, filename):
        self.source = self.reader = None
        codec = zstd_codec()
        self.source = Path(filename).open('rb')
        self.decoder = codec.ZstdDecompressor(max_window_size=128 * 1024 * 1024)
        self.reader = self.decoder.stream_reader(self.source, read_across_frames=True, closefd=False)
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def read(self, size=-1):
        data = self.reader.read(size)
        self.position += len(data)
        return data

    def seek(self, offset, whence=io.SEEK_SET):
        if whence == io.SEEK_END:
            for _ in iter(lambda: self.read(CHUNK), b''):
                pass
            offset += self.position
        elif whence == io.SEEK_CUR:
            offset += self.position
        elif whence != io.SEEK_SET:
            raise ValueError('无效的备份读取位置')
        if offset < 0:
            raise ValueError('无效的备份读取位置')
        if offset < self.position:
            self.reader.close()
            self.source.seek(0)
            self.reader = self.decoder.stream_reader(self.source, read_across_frames=True, closefd=False)
            self.position = 0
        while self.position < offset:
            if not self.read(min(CHUNK, offset - self.position)):
                break
        return self.position

    def close(self):
        if not self.closed:
            try:
                if self.reader is not None:
                    self.reader.close()
            finally:
                if self.source is not None:
                    self.source.close()
                super().close()


class ArchiveReader:
    def __init__(self, filename):
        self.archive = None
        self.stream = None
        try:
            if zipfile.is_zipfile(filename):
                self.format = "zip"
                self.archive = zipfile.ZipFile(filename)
                self.members = [Member(info.filename, info.file_size, info.external_attr >> 16,
                    not info.is_dir() and not (info.flag_bits & 1) and
                    stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG), info)
                    for info in self.archive.infolist()]
            else:
                with Path(filename).open("rb") as source:
                    magic = source.read(6)
                self.format = ("tar.gz" if magic.startswith(b"\x1f\x8b") else "tar.xz" if magic == b"\xfd7zXZ\x00"
                               else "tar.zst" if magic.startswith(b'\x28\xb5\x2f\xfd') else None)
                if self.format is None:
                    raise ValueError("不是支持的 ZIP、Zstd、XZ 或旧 TAR.GZ 备份")
                if self.format == 'tar.zst':
                    self.stream = ZstdReader(filename)
                    self.archive = tarfile.open(fileobj=self.stream, mode='r:')
                else:
                    self.archive = tarfile.open(filename, "r:gz" if self.format == "tar.gz" else "r:xz")
                self.members = []
                for info in self.archive:
                    if len(self.members) >= MAX_MEMBERS:
                        raise ValueError("备份包含过多文件")
                    self.members.append(Member(info.name, info.size, stat.S_IFREG | info.mode,
                        info.isreg() and not info.issparse(), info))
                if self.stream is not None:
                    for _ in iter(lambda: self.stream.read(CHUNK), b''):
                        pass  # Consume the checksum even after TAR's end marker.
            if len(self.members) > MAX_MEMBERS:
                raise ValueError("备份包含过多文件")
            self.by_name = {member.name: member for member in self.members}
        except BaseException as exc:
            if self.archive is not None:
                self.archive.close()
            if self.stream is not None:
                self.stream.close()
            if isinstance(exc, ARCHIVE_ERRORS):
                raise ValueError("备份压缩流损坏：" + str(exc)) from exc
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.archive.close()
        if self.stream is not None:
            self.stream.close()

    def open(self, member):
        return self.archive.open(member.source) if self.format == "zip" else self.archive.extractfile(member.source)

    def read_manifest(self):
        member = self.by_name.get("manifest.json")
        if member is None or not member.regular or member.size > MAX_MANIFEST:
            raise ValueError("备份缺少有效清单或清单过大")
        try:
            with self.open(member) as source:
                data = source.read(MAX_MANIFEST + 1)
        except ARCHIVE_ERRORS as exc:
            raise ValueError("备份清单无法读取：" + str(exc)) from exc
        if len(data) > MAX_MANIFEST:
            raise ValueError("备份清单过大，无法安全校验")
        return data


class HashingReader:
    def __init__(self, source, progress):
        self.source, self.progress = source, progress
        self.size = 0
        self.sha = hashlib.sha256()

    def read(self, size=-1):
        chunk = self.source.read(size)
        self.size += len(chunk)
        self.sha.update(chunk)
        if chunk:
            self.progress(len(chunk))
        return chunk


class ArchiveWriter:
    def __init__(self, filename, format="zip"):
        self.format = normalize_format(format)
        self.stream = None
        self.raw = None
        if format == "zip":
            self.archive = zipfile.ZipFile(filename, "x", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True)
        elif format == "tar.gz":
            self.archive = tarfile.open(filename, "x:gz", compresslevel=1)
        elif format == 'tar.zst':
            codec = zstd_codec()
            self.raw = Path(filename).open('xb')
            try:
                self.stream = codec.ZstdCompressor(level=1, write_checksum=True).stream_writer(self.raw, closefd=False)
                self.archive = tarfile.open(fileobj=self.stream, mode='w|')
            except BaseException:
                if self.stream:
                    self.stream.close()
                self.raw.close()
                raise
        else:
            self.stream = lzma.LZMAFile(filename, 'x', filters=XZ_FILTERS)
            try:
                self.archive = tarfile.open(fileobj=self.stream, mode='w|')
            except BaseException:
                self.stream.close()
                raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            self.archive.close()
        finally:
            try:
                if self.stream is not None:
                    self.stream.close()
            finally:
                if self.raw is not None:
                    self.raw.close()

    def write_file(self, name, source, mode, progress):
        with Path(source).open("rb") as incoming:
            reader = HashingReader(incoming, progress)
            if self.format == "zip":
                info = zipfile.ZipInfo(name)
                info.compress_type = zipfile.ZIP_DEFLATED
                info._compresslevel = 6
                info.external_attr = (stat.S_IFREG | mode) << 16
                with self.archive.open(info, "w", force_zip64=True) as outgoing:
                    for chunk in iter(lambda: reader.read(CHUNK), b""):
                        outgoing.write(chunk)
            else:
                info = tarfile.TarInfo(name)
                info.size, info.mode = Path(source).stat().st_size, mode
                self.archive.addfile(info, reader)
            return reader.size, reader.sha.hexdigest()

    def write_bytes(self, name, data):
        if self.format == "zip":
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info._compresslevel = 6
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            self.archive.writestr(info, data)
        else:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o600
            self.archive.addfile(info, io.BytesIO(data))


def estimate_formats(entries, total, count, *, samples=()):
    """Bounded, real compression samples; estimates are never promises."""
    budget = 1024 * 1024
    fragments = []
    # Spread the sample across files and positions rather than only zero-filled
    # database headers. Never retain more than 1 MiB of source content.
    candidates = sorted(entries, key=lambda entry: entry[1].stat().st_size, reverse=True)[:32]
    remaining = budget
    for sample in samples:
        chunk = sample[:min(65536, remaining)]
        fragments.append(chunk)
        remaining -= len(chunk)
        if remaining <= 0:
            break
    for _, filename in candidates:
        if remaining <= 0:
            break
        size = filename.stat().st_size
        allowance = min(size, remaining, max(4096, budget // max(1, len(candidates))))
        if not allowance:
            continue
        piece = max(1, allowance // 3)
        with filename.open("rb") as source:
            for offset in sorted({0, max(0, size // 2 - piece // 2), max(0, size - piece)}):
                source.seek(offset)
                chunk = source.read(min(piece, remaining))
                fragments.append(chunk)
                remaining -= len(chunk)
    sample = b"".join(fragments)
    compressors = {"zip": lambda: zlib.compress(sample, 6),
                   "tar.zst": lambda: zstd_codec().ZstdCompressor(level=1).compress(sample),
                   "tar.xz": lambda: lzma.compress(sample, filters=XZ_FILTERS)}
    results = []
    for key, spec in FORMATS.items():
        if spec.get('legacy'):
            continue
        if key == 'tar.zst' and zstandard is None:
            results.append({'id': key, **spec, 'available': False, 'error': 'Zstd 依赖未安装',
                            'estimated_size': None, 'estimated_seconds': None, 'is_estimate': True})
            continue
        started = time.perf_counter()
        packed = compressors[key]()
        elapsed = time.perf_counter() - started
        ratio = min(1.05, len(packed) / max(1, len(sample)))
        overhead = 1024 + count * (120 if key == "zip" else 80)
        seconds = 0.1 + count * 0.001 + total / (80 * CHUNK) * 3
        if sample:
            seconds += elapsed * total / len(sample)
        results.append({"id": key, **spec, "estimated_size": math.ceil(total * ratio + overhead),
                        "estimated_seconds": round(max(0.1, seconds), 2),
                        "sample_bytes": len(sample), "is_estimate": True})
    return results
