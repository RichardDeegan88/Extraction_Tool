"""Tests for DAF core components, repositories, cache, algorithm, and services."""

from __future__ import annotations

import pytest

from extraction_tool.algorithms.dynamic_programming import FibonacciDP
from extraction_tool.cache.memory import MemoryCache
from extraction_tool.contracts.extraction import ExtractionRequest
from extraction_tool.contracts.query import (
    DeleteInfo,
    PostInfo,
    PutInfo,
    QueryInfo,
)
from extraction_tool.core.access import DataAccess
from extraction_tool.core.factory import DataAccessFactory
from extraction_tool.repositories.filesystem import FilesystemRepository
from extraction_tool.repositories.http import HttpReadingRepository
from extraction_tool.repositories.memory import MemoryRepository
from extraction_tool.services.extraction_service import ExtractionService
from extraction_tool.services.reading_service import ReadingService

# ── DataAccessFactory ────────────────────────────────────────────────

class TestDataAccessFactory:
    def test_creates_data_access_with_repo_and_cache(self):
        factory = DataAccessFactory(
            repository=MemoryRepository(),
            cache=MemoryCache(),
        )
        daf = factory.create()
        assert isinstance(daf, DataAccess)

    def test_create_requires_repository(self):
        with pytest.raises((TypeError, ValueError)):
            DataAccessFactory(cache=MemoryCache()).create()

    def test_create_requires_cache(self):
        with pytest.raises((TypeError, ValueError)):
            DataAccessFactory(repository=MemoryRepository()).create()

    def test_factory_is_deterministic(self):
        repo = MemoryRepository()
        cache = MemoryCache()
        f1 = DataAccessFactory(repository=repo, cache=cache)
        f2 = DataAccessFactory(repository=repo, cache=cache)
        assert f1.create()._repository is f2.create()._repository


# ── DataAccess ───────────────────────────────────────────────────────

class TestDataAccessQuery:
    @pytest.fixture
    def daf(self):
        repo = MemoryRepository()
        cache = MemoryCache()
        return DataAccessFactory(repository=repo, cache=cache).create()

    @pytest.mark.asyncio
    async def test_cache_miss_fetches_from_repository(self, daf):
        repo = daf._repository
        await repo.save("key1", {"value": "hello"})
        info = QueryInfo(resource_id="key1")
        result = await daf.query(info)
        assert result.success is True
        assert result.data == {"value": "hello"}
        assert result.cache_hit is False

    @pytest.mark.asyncio
    async def test_cache_hit_skips_repository(self, daf):
        repo = daf._repository
        await repo.save("key2", {"value": "world"})
        info = QueryInfo(resource_id="key2")
        result1 = await daf.query(info)
        assert result1.cache_hit is False
        result2 = await daf.query(info)
        assert result2.cache_hit is True
        assert result2.data == {"value": "world"}

    @pytest.mark.asyncio
    async def test_query_not_found_returns_failure(self, daf):
        info = QueryInfo(resource_id="nonexistent")
        result = await daf.query(info)
        assert result.success is False
        assert result.error is not None


class TestDataAccessMutations:
    @pytest.fixture
    def daf(self):
        repo = MemoryRepository()
        cache = MemoryCache()
        return DataAccessFactory(repository=repo, cache=cache).create()

    @pytest.mark.asyncio
    async def test_post_creates_resource(self, daf):
        info = PostInfo(resource_type="item", data={"name": "test"})
        result = await daf.post(info)
        assert result.success is True
        assert result.resource_id is not None

    @pytest.mark.asyncio
    async def test_put_updates_existing(self, daf):
        post_info = PostInfo(resource_type="item", data={"name": "old"})
        post_result = await daf.post(post_info)
        rid = post_result.resource_id
        put_info = PutInfo(resource_id=rid, data={"name": "new"})
        put_result = await daf.put(put_info)
        assert put_result.success is True

    @pytest.mark.asyncio
    async def test_delete_removes_resource(self, daf):
        post_info = PostInfo(resource_type="item", data={"name": "del"})
        post_result = await daf.post(post_info)
        rid = post_result.resource_id
        del_info = DeleteInfo(resource_id=rid)
        del_result = await daf.delete(del_info)
        assert del_result.success is True


# ── MemoryCache ──────────────────────────────────────────────────────

class TestMemoryCache:
    @pytest.fixture
    def cache(self):
        return MemoryCache()

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache):
        await cache.set("k", "v")
        assert await cache.get("k") == "v"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, cache):
        assert await cache.get("missing") is None

    @pytest.mark.asyncio
    async def test_delete_removes_key(self, cache):
        await cache.set("k", "v")
        await cache.delete("k")
        assert await cache.get("k") is None

    @pytest.mark.asyncio
    async def test_clear_empties_cache(self, cache):
        await cache.set("a", "1")
        await cache.set("b", "2")
        await cache.clear()
        assert await cache.get("a") is None


# ── MemoryRepository ─────────────────────────────────────────────────

class TestMemoryRepository:
    @pytest.fixture
    def repo(self):
        return MemoryRepository()

    @pytest.mark.asyncio
    async def test_save_and_get(self, repo):
        await repo.save("r1", {"name": "a"})
        assert await repo.get("r1") == {"name": "a"}

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, repo):
        assert await repo.get("missing") is None

    @pytest.mark.asyncio
    async def test_list_all(self, repo):
        await repo.save("r1", {"name": "a"})
        await repo.save("r2", {"name": "b"})
        assert len(await repo.list_all()) == 2

    @pytest.mark.asyncio
    async def test_delete(self, repo):
        await repo.save("r1", {"name": "a"})
        await repo.delete("r1")
        assert await repo.get("r1") is None


# ── FilesystemRepository ─────────────────────────────────────────────

class TestFilesystemRepository:
    @pytest.fixture
    def repo(self):
        return FilesystemRepository()

    def test_resolve_single_pdf(self, repo, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        results = repo.resolve_pdf_inputs([str(pdf)])
        assert len(results) == 1
        assert results[0] == pdf

    def test_extract_pdf_metadata_returns_dict(self, repo, tmp_path):
        pdf = tmp_path / "doc.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        meta = repo.extract_pdf_metadata(str(pdf))
        assert isinstance(meta, dict)
        assert "title" in meta
        assert "author" in meta

    def test_atomic_write_text_creates_file(self, repo, tmp_path):
        target = tmp_path / "out.txt"
        repo.atomic_write_text(target, "hello")
        assert target.read_text() == "hello"

    def test_atomic_write_cleans_temp_on_failure(self, repo, tmp_path):
        target = tmp_path / "missing_dir" / "out.txt"
        with pytest.raises(OSError):
            repo.atomic_write_text(target, "data")
        assert not target.exists()


# ── HttpReadingRepository ─────────────────────────────────────────────

class TestHttpReadingRepository:
    @pytest.fixture
    def repo(self):
        return HttpReadingRepository()

    def test_categorise_pdf(self, repo):
        assert repo.categorise("http://example.com/doc.pdf") == "pdf"

    def test_categorise_html(self, repo):
        assert repo.categorise("http://example.com/page.html") == "article"

    def test_categorise_video(self, repo):
        assert repo.categorise("https://youtube.com/watch?v=1") == "video"

    def test_categorise_article_fallback(self, repo):
        assert repo.categorise("http://example.com/unknown") == "article"

    def test_is_public_host_blocks_loopback(self, repo):
        ok, reason = repo._is_public_host("127.0.0.1")
        assert ok is False
        assert "loopback" in reason.lower()

    def test_is_public_host_blocks_link_local(self, repo):
        ok, reason = repo._is_public_host("169.254.169.254")
        assert ok is False
        assert "reserved" in reason.lower() or "link-local" in reason.lower()

    def test_is_public_host_allows_public(self, repo):
        ok, reason = repo._is_public_host("93.184.216.34")
        assert ok is True


# ── FibonacciDP ──────────────────────────────────────────────────────

class TestFibonacciDP:
    @pytest.fixture
    def solver(self):
        return FibonacciDP()

    @pytest.mark.asyncio
    async def test_fib_zero(self, solver):
        result = await solver.execute(0)
        assert result == 0

    @pytest.mark.asyncio
    async def test_fib_one(self, solver):
        result = await solver.execute(1)
        assert result == 1

    @pytest.mark.asyncio
    async def test_fib_ten(self, solver):
        result = await solver.execute(10)
        assert result == 55

    @pytest.mark.asyncio
    async def test_memoization_stats(self, solver):
        await solver.execute(10)
        stats = await solver.get_stats()
        assert "iterations" in stats
        assert "cache_hits" in stats
        assert stats["cache_hits"] > 0

    @pytest.mark.asyncio
    async def test_negative_input_raises(self, solver):
        with pytest.raises(ValueError):
            await solver.execute(-1)


# ── ExtractionService ────────────────────────────────────────────────

class TestExtractionService:
    @pytest.fixture
    def service(self):
        return ExtractionService(FilesystemRepository())

    def test_nonexistent_pdf_returns_error(self, service):
        request = ExtractionRequest(pdf_path="/nonexistent.pdf")
        result = service.extract_pdf(request)
        assert result.success is False
        assert len(result.errors) > 0


# ── ReadingService ───────────────────────────────────────────────────

class TestReadingService:
    @pytest.fixture
    def service(self):
        return ReadingService(HttpReadingRepository())

    def test_page_looks_gated_detects_login_form(self, service):
        html = "<html><body><form><input name='login'></form>short text</body></html>"
        reason = ReadingService._page_looks_gated(html, "short text", 10)
        assert "login form" in reason

    def test_page_looks_gated_clean_page(self, service):
        reason = ReadingService._page_looks_gated(
            "<html></html>", "normal article text here", 200
        )
        assert reason == ""

    def test_trim_url_strips_trailing_punct(self, service):
        assert ReadingService._trim_url("http://example.com/page.") == "http://example.com/page"
        assert ReadingService._trim_url("http://example.com/page,") == "http://example.com/page"

    def test_decode_body_utf8(self, service):
        raw = b"Hello World"
        assert ReadingService._decode_body(raw) == "Hello World"

    def test_decode_body_fallback_on_bad_charset(self, service):
        raw = b"Hello World"
        result = ReadingService._decode_body(
            raw, content_type="text/html; charset=invalid"
        )
        assert result == "Hello World"
