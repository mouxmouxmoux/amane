from pathlib import Path

import pytest

from amane.config import ColdSettings, ConfigManager, HotSettings
from amane.db import MediaFileStatus
from amane.db.repository import Repository
from amane.handlers import RefreshHandler, RefreshPayload, ScanMode
from amane.handlers.file import apply_file_operations
from amane.library import build_footprint
from amane.media import ResourceStore
from amane.organize import PlaceOutcome
from amane.parsing import FileMarkerRules, Mosaic


@pytest.mark.asyncio
async def test_refresh_marker_rules(repo: Repository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = ConfigManager(cold=ColdSettings(data_dir=tmp_path / "data"), hot=HotSettings())
    monkeypatch.setattr(repo, "_get_marker_rules", lambda: config.hot.parsing.to_marker_rules())
    root = tmp_path / "lib"
    root.mkdir()
    child = root / "child"
    child.mkdir()
    library = await repo.create_library(name="markers", path=str(root), subtitle_extensions=[])
    assert library.id is not None
    metadata = await repo.upsert_metadata(number="MIDV-123")
    video = child / "MIDV-123-XYZ.mp4"
    video.touch()
    existing = await repo.create_media_file(
        library.id, path=str(video), metadata_id=metadata.id, status=MediaFileStatus.SCRAPED
    )
    outside = await repo.create_media_file(library.id, path=str(root / "MIDV-456-XYZ.mp4"))
    Path(outside.path).touch()
    assert existing.id is not None
    assert outside.id is not None
    config.update({"parsing": {"cracked_suffixes": ["XYZ"], "subtitle_suffixes": ["XYZ"]}})
    fresh = await repo.create_media_file(library.id, path=str(root / "MIDV-789-XYZ.mp4"))
    Path(fresh.path).touch()
    assert fresh.mosaic is Mosaic.CRACKED
    assert fresh.has_subtitle_in_name
    assert existing.mosaic is None

    handler = RefreshHandler(repo)
    for scan in (set(), {ScanMode.remove}, {ScanMode.add}):
        result = await handler.handle(RefreshPayload(library_id=library.id, path=str(child), scan=scan, scrape=set()))
        assert result.success
        current = await repo.get_media_file(existing.id)
        assert current is not None
        assert current.mosaic is (Mosaic.CRACKED if ScanMode.add in scan else None)
        assert current.has_subtitle_in_name is (ScanMode.add in scan)
        assert current.metadata_id == metadata.id
        assert current.status is MediaFileStatus.SCRAPED
    untouched = await repo.get_media_file(outside.id)
    assert untouched is not None and untouched.mosaic is None

    current = await repo.get_media_file(existing.id)
    assert current is not None
    unchanged_at = current.updated_at
    await handler.handle(RefreshPayload(library_id=library.id, path=str(child), scrape=set()))
    current = await repo.get_media_file(existing.id)
    assert current is not None and current.updated_at == unchanged_at
    config.update({"parsing": {"cracked_suffixes": [], "subtitle_suffixes": []}})
    await handler.handle(RefreshPayload(library_id=library.id, path=str(child), scrape=set()))
    current = await repo.get_media_file(existing.id)
    assert current is not None and current.mosaic is None and not current.has_subtitle_in_name


@pytest.mark.asyncio
async def test_reprojection_preserves_renamed_path(repo: Repository) -> None:
    media = await repo.create_media_file(1, path="MIDV-123-XYZ.mp4", has_external_subtitle=True)
    assert media.id is not None
    await repo.update_media_file(media.id, path="MIDV-123-LTX.mp4")
    await repo.reproject_media_file_phases([media], marker_rules=FileMarkerRules(cracked_suffixes=()))
    current = await repo.get_media_file(media.id)
    assert current is not None
    assert current.path == "MIDV-123-LTX.mp4"
    assert current.mosaic is Mosaic.CRACKED
    assert current.has_external_subtitle
    disabled = FileMarkerRules(cracked_suffixes=())
    updated = await repo.update_media_file(media.id, path="MIDV-123-LTX-4K.mp4", marker_rules=disabled)
    assert updated is not None and updated.mosaic is None and updated.definition == "4K"


@pytest.mark.asyncio
async def test_organize_and_footprint_share_rules(
    repo: Repository, resource_store: ResourceStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = FileMarkerRules(cracked_suffixes=("XYZ",), subtitle_suffixes=("XYZ",))
    monkeypatch.setattr(repo, "_get_marker_rules", lambda: rules)
    root = tmp_path / "lib"
    root.mkdir()
    video = root / "MIDV-123-XYZ.mp4"
    video.touch()
    library = await repo.create_library(
        name="markers",
        path=str(root),
        video_template="{number}[-{mosaic?|cracked=XYZ}].{ext}",
        nfo_template="{number}[-{mosaic?}][-{sub?}].nfo",
    )
    assert library.id is not None
    metadata = await repo.upsert_metadata(number="MIDV-123")
    assert metadata.id is not None
    media = await repo.create_media_file(library.id, path=str(video), metadata_id=metadata.id)
    result = await apply_file_operations(repo, media.id, metadata, HotSettings(), resource_store)
    assert result is not None and result.outcome is PlaceOutcome.PLACED
    nfo = root / "MIDV-123-cracked-C.nfo"
    assert nfo.is_file()
    outcome = await build_footprint(
        library=library,
        items=[media],
        indexed=[media],
        metas={metadata.id: metadata},
        include_work_dir=False,
        marker_rules=repo.marker_rules(),
    )
    assert nfo in [entry.path for entry in outcome.inventory.entries]
