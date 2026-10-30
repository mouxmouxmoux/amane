from collections.abc import Iterable
from pathlib import Path

import pytest

from amane.aggregate import CrawlerLike
from amane.config import HotSettings
from amane.db import MediaFileStatus
from amane.db.repository import Repository
from amane.handlers import ScrapeHandler, ScrapePayload
from amane.media import ResourceStore
from amane.parsing import ContentType, FileMarkerRules, Mosaic


@pytest.mark.asyncio
async def test_scrape_reprojects_existing_file_marker(
    repo: Repository, resource_store: ResourceStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "MIDV-123-LTX.mp4"
    video.touch()
    media = await repo.create_media_file(1, path=str(video), status=MediaFileStatus.SCRAPED)
    assert media.id is not None
    monkeypatch.setattr(repo, "_get_marker_rules", lambda: FileMarkerRules(cracked_suffixes=("LTX",)))

    class _Factory:
        async def get_crawlers(self, names: Iterable[str]) -> dict[str, CrawlerLike]:
            return {}

    handler = ScrapeHandler(
        repo=repo,
        factory=_Factory(),
        resource_store=resource_store,
        pipeline_config=HotSettings(),
    )
    # 任务在没有可用来源时提前失败, 但旧文件的相位应已完成当前规则投影.
    result = await handler.handle(
        ScrapePayload(media_file_id=media.id, number="MIDV-123", content_type=ContentType.CENSORED, use_cache=set())
    )
    assert result.success is False
    updated = await repo.get_media_file(media.id)
    assert updated is not None and updated.mosaic is Mosaic.CRACKED
