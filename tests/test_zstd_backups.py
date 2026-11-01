import io
import json
import tarfile

import pytest
import zstandard

from tests.test_backup_options import instance
from xgent_app.data_archives import ArchiveReader
from xgent_app.data_bundles import BundleError


def test_zstd_checksum_is_checked_and_corruption_does_not_touch_instance(tmp_path):
    paths, service = instance(tmp_path)
    exported = service.export(categories=['memory'], archive_format='tar.zst')
    damaged = tmp_path/'damaged.tar.zst'
    body = bytearray(open(exported['path'], 'rb').read())
    body[-1] ^= 1
    damaged.write_bytes(body)
    before = (paths.memory/'note.md').read_bytes()
    with pytest.raises(BundleError):
        service.prepare_import(damaged)
    assert (paths.memory/'note.md').read_bytes() == before


def test_zstd_archive_members_support_backward_reads_and_keep_exact_bytes(tmp_path):
    paths, service = instance(tmp_path)
    exported = service.export(categories=['memory', 'uploads'], archive_format='tar.zst')
    with ArchiveReader(exported['path']) as archive:
        manifest = json.loads(archive.read_manifest())
        for member in reversed(archive.members):
            if member.name != 'manifest.json':
                with archive.open(member) as source:
                    assert source.read() == (paths.root/member.name).read_bytes()
        assert manifest['archive_format'] == 'tar.zst'


@pytest.mark.parametrize('name', ['../outside.txt', '/outside.txt'])
def test_zstd_does_not_bypass_member_path_validation(tmp_path, name):
    _, service = instance(tmp_path)
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode='w') as archive:
        data = b'not a valid backup'
        member = tarfile.TarInfo(name)
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    bad = tmp_path/'bad.tar.zst'
    bad.write_bytes(zstandard.ZstdCompressor().compress(tar.getvalue()))
    with pytest.raises(BundleError):
        service.prepare_import(bad)
