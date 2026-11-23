"""S3ObjectLockVault tests against an in-memory fake S3 client (no AWS). The fake enforces what S3 Object
Lock does: conditional writes (IfNoneMatch), COMPLIANCE-mode retention that can't be shortened, and SHA-256
checksums. It also paginates list results to exercise continuation tokens. AI-assisted (Claude)."""
import base64
import hashlib
import io
from datetime import timedelta

import pytest

pytest.importorskip("botocore")
from botocore.exceptions import ClientError  # noqa: E402

from mwia.common.timeutil import parse_utc  # noqa: E402
from mwia.vault import ObjectExists, RetentionError  # noqa: E402
from mwia.vault.s3 import S3ObjectLockVault  # noqa: E402


def _err(code, op):
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class FakeS3:
    def __init__(self, page_size=3):
        self.objects: dict[str, dict] = {}
        self.page_size = page_size
        self.calls: list[str] = []

    def put_object(self, *, Bucket, Key, Body, IfNoneMatch, ChecksumSHA256, ObjectLockMode, ObjectLockRetainUntilDate):
        self.calls.append("put_object")
        assert IfNoneMatch == "*" and ObjectLockMode == "COMPLIANCE"
        assert ChecksumSHA256 == base64.b64encode(hashlib.sha256(Body).digest()).decode()
        if Key in self.objects:
            raise _err("PreconditionFailed", "PutObject")
        self.objects[Key] = {"Body": Body, "Until": ObjectLockRetainUntilDate, "Mode": ObjectLockMode}

    def get_object(self, *, Bucket, Key):
        if Key not in self.objects:
            raise _err("NoSuchKey", "GetObject")
        return {"Body": io.BytesIO(self.objects[Key]["Body"])}

    def list_objects_v2(self, *, Bucket, Prefix, ContinuationToken=None, StartAfter=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))
        start = int(ContinuationToken) if ContinuationToken else 0
        if StartAfter and not ContinuationToken:
            keys = [k for k in keys if k > StartAfter]
        page = keys[start:start + self.page_size]
        more = start + self.page_size < len(keys)
        resp = {"Contents": [{"Key": k} for k in page], "IsTruncated": more}
        if more:
            resp["NextContinuationToken"] = str(start + self.page_size)
        return resp

    def get_object_retention(self, *, Bucket, Key):
        o = self.objects[Key]
        return {"Retention": {"Mode": o["Mode"], "RetainUntilDate": o["Until"]}}

    def put_object_retention(self, *, Bucket, Key, Retention):
        self.calls.append("put_object_retention")
        o = self.objects[Key]
        if Retention["RetainUntilDate"] < o["Until"]:
            raise _err("AccessDenied", "PutObjectRetention")  # COMPLIANCE: cannot shorten
        o["Until"] = Retention["RetainUntilDate"]


@pytest.fixture
def s3():
    return FakeS3()


@pytest.fixture
def v(s3):
    return S3ObjectLockVault(s3, "bucket", prefix="mwia/test")


def test_put_get_and_ledger_objects(v, s3):
    for i in range(5):
        v.put_json(f"runs/d/r/{i}-x.json", {"i": i})
    assert v.get("runs/d/r/3-x.json") == b'{"i":3}'
    ledger = sorted(k for k in s3.objects if k.startswith("mwia/test/ledger/"))
    assert ledger == [f"mwia/test/ledger/{i:012d}.json" for i in range(5)]
    assert all(o["Mode"] == "COMPLIANCE" for o in s3.objects.values())
    assert v.verify() == []
    # a fresh instance replays the paginated ledger
    assert S3ObjectLockVault(s3, "bucket", prefix="mwia/test").list_keys() == [f"runs/d/r/{i}-x.json" for i in range(5)]


def test_overwrite_refused(v, s3):
    v.put("runs/a.json", b"one")
    with pytest.raises(ObjectExists):
        v.put("runs/a.json", b"two")
    with pytest.raises(ObjectExists):  # refused by the storage layer even if the ledger cache is bypassed
        S3ObjectLockVault(s3, "bucket", prefix="mwia/test")._write_once("runs/a.json", b"two", "2030-01-01T00:00:00Z")
    assert v.get("runs/a.json") == b"one"


def test_retention_extension_and_shortening(v, s3):
    info = v.put("runs/a.json", b"one")
    later = parse_utc(info.retain_until) + timedelta(days=10)
    v.extend_retention("runs/a.json", later)
    assert s3.objects["mwia/test/runs/a.json"]["Until"] == later
    assert "put_object_retention" in s3.calls
    with pytest.raises(RetentionError):
        v.extend_retention("runs/a.json", later - timedelta(days=1))
    assert v.verify() == []


def test_tampered_ledger_object_detected(v, s3):
    for i in range(3):
        v.put(f"runs/{i}.json", b"x%d" % i)
    s3.objects["mwia/test/ledger/000000000001.json"]["Body"] = b'{"forged":true}'  # e.g. a GOVERNANCE bypass
    assert "ledger_malformed" in {p.code for p in S3ObjectLockVault(s3, "bucket", prefix="mwia/test").verify()}


def test_tampered_object_detected(v, s3):
    v.put("runs/a.json", b"one")
    s3.objects["mwia/test/runs/a.json"]["Body"] = b"evil"
    assert [p.code for p in v.verify()] == ["object_hash_mismatch"]
