from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, cast

import structlog
from fastapi import APIRouter, HTTPException, Query, Response

from ...db.models import Library, MediaFile, MediaFileStatus, MediaSortField, Metadata, SortOrder
from ...organize import resolve_paths
from ...parsing import DEFINITION_VALUES, ContentType, Mosaic, parse_file_info
from ..deps import RepoDep
from ..models import (
    MediaBatchDeleteRequest,
    MediaBatchDeleteResponse,
    MediaFileResponse,
    MediaFileUpdateRequest,
    MediaListResponse,
    to_media_file_response,
)

if TYPE_CHECKING:
    from ...db.repo_types import MediaFileUpdates
    from ...db.repository import Repository

logger = structlog.get_logger()

router = APIRouter(prefix="/media", tags=["media"])


def _require_known_definition(definition: str | None) -> str | None:
    if definition is None:
        return None
    if definition not in DEFINITION_VALUES:
        raise HTTPException(status_code=422, detail=f"未知分辨率: {definition}")
    return definition


async def _organized_paths(
    repo: Repository, items: Sequence[MediaFile], metadata_by_id: Mapping[int, Metadata]
) -> dict[int, str | None]:
    libraries: dict[int, Library | None] = {}
    result: dict[int, str | None] = {}
    marker_rules = repo.marker_rules()
    actor_names = sorted({name for metadata in metadata_by_id.values() for name in metadata.actors})
    actor_genders = {actor.name: actor.gender for actor in await repo.get_actors_by_names(actor_names)}
    for media in items:
        media_id = media.id
        if media_id is None or media.metadata_id is None:
            continue
        if media.library_id not in libraries:
            libraries[media.library_id] = await repo.get_library(media.library_id)
        library = libraries[media.library_id]
        metadata = metadata_by_id.get(media.metadata_id)
        if library is None or metadata is None:
            continue
        try:
            file_info = parse_file_info(
                media.path,
                has_external_subtitle=media.has_external_subtitle,
                marker_rules=marker_rules,
            )
            paths = resolve_paths(
                library,
                metadata,
                ext=Path(media.path).suffix.lstrip("."),
                file_info=file_info,
                source_path=Path(media.path),
                safe_dirs=None,
                actor_genders=actor_genders,
                marker_rules=marker_rules,
            )
        except ValueError:
            continue
        result[media_id] = str(paths.video)
    return result


async def _phase_responses(repo: Repository, items: Sequence[MediaFile]) -> list[MediaFileResponse]:
    """批量读取所属条目, 同时用于文件相位与整理路径."""
    metadata_by_id = {
        metadata.id: metadata
        for metadata in await repo.get_metadata_by_ids({m.metadata_id for m in items if m.metadata_id is not None})
        if metadata.id is not None
    }
    types = {metadata_id: metadata.content_type for metadata_id, metadata in metadata_by_id.items()}
    organized_paths = await _organized_paths(repo, items, metadata_by_id)
    return [
        to_media_file_response(m, types.get(m.metadata_id) if m.metadata_id is not None else None).model_copy(
            update={"organized_path": organized_paths.get(m.id) if m.id is not None else None}
        )
        for m in items
    ]


@router.get("")
async def list_media(
    repo: RepoDep,
    status: Annotated[MediaFileStatus | None, Query(description="Filter by media file status")] = None,
    search: Annotated[str | None, Query(description="Search by path or number")] = None,
    library_id: Annotated[int | None, Query(description="Filter by owning library")] = None,
    has_subtitle: Annotated[bool | None, Query(description="Filter by subtitle marker")] = None,
    mosaic: Annotated[Mosaic | None, Query(description="Filter by mosaic marker")] = None,
    uncensored: Annotated[
        bool | None, Query(description="Filter by uncensored (own marker or uncensored number content type)")
    ] = None,
    definition: Annotated[str | None, Query(description="Filter by definition (8K/4K/1080p/…)")] = None,
    content_type: Annotated[ContentType | None, Query(description="Filter by owning number content type")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_by: Annotated[MediaSortField, Query(description="Sort field")] = MediaSortField.UPDATED_AT,
    order: Annotated[SortOrder, Query(description="Sort order")] = SortOrder.DESC,
) -> MediaListResponse:
    definition = _require_known_definition(definition)
    status_filter = [status] if status is not None else None
    items = await repo.list_media_files(
        status_filter,
        limit,
        offset,
        search,
        library_id,
        sort_by,
        order,
        has_subtitle=has_subtitle,
        mosaic=mosaic,
        uncensored=uncensored,
        definition=definition,
        content_type=content_type,
    )
    total = await repo.count_media_files(
        status=status_filter,
        search=search,
        library_id=library_id,
        has_subtitle=has_subtitle,
        mosaic=mosaic,
        uncensored=uncensored,
        definition=definition,
        content_type=content_type,
    )
    return MediaListResponse(items=await _phase_responses(repo, items), total=total)


@router.post("/batch/delete")
async def batch_delete_media(req: MediaBatchDeleteRequest, repo: RepoDep) -> MediaBatchDeleteResponse:
    """批量删除媒体文件记录; 不存在的 id 计入 missing 而不是报错."""
    deleted, missing = await repo.batch_delete_media_files(req.ids)
    logger.info("media files batch deleted", deleted=deleted, missing=missing)
    return MediaBatchDeleteResponse(deleted=deleted, missing=missing)


@router.get("/{media_id}")
async def get_media(media_id: int, repo: RepoDep) -> MediaFileResponse:
    media = await repo.get_media_file(media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    return (await _phase_responses(repo, [media]))[0]


@router.patch("/{media_id}")
async def update_media(media_id: int, req: MediaFileUpdateRequest, repo: RepoDep) -> MediaFileResponse:
    updates = cast("MediaFileUpdates", req.model_dump(exclude_unset=True))
    if not updates:
        raise HTTPException(status_code=422, detail="没有需要修改的字段")
    media = await repo.update_media_file(media_id, **updates)
    if media is None:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    logger.info("media file updated", media_id=media_id, fields=list(updates.keys()))
    return (await _phase_responses(repo, [media]))[0]


@router.delete("/{media_id}", status_code=204)
async def delete_media(media_id: int, repo: RepoDep):
    deleted = await repo.delete_media_file(media_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    logger.info("media file deleted", media_id=media_id)
    return Response(status_code=204)
