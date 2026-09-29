"""CreatorHub owns D2Y intents; the source manifest is a replayable projection."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from ..db import get_session
from ..models import DouyinAccount, PublishTask, D2YImportRequest


def default_batch_size() -> int:
    value = int(os.environ.get('D2Y_DAILY_BATCH_SIZE', '10'))
    if not 1 <= value <= 100:
        raise ValueError('D2Y_DAILY_BATCH_SIZE must be between 1 and 100')
    return value


def source_adapter():
    """Legacy cross-repository bridge used only by /import-batch compatibility."""
    root = Path(os.environ.get('D2Y_ROOT', str(Path(__file__).resolve().parents[3] / '自媒体自动化')))
    if not (root / 'src/douyin_to_youtube/d2y_to_creatorhub.py').is_file():
        raise RuntimeError('D2Y source module missing; configure D2Y_ROOT')
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return importlib.import_module('src.douyin_to_youtube.d2y_to_creatorhub')


def _account(account_id=None):
    with get_session() as s:
        if account_id is not None:
            account = s.get(DouyinAccount, account_id)
        else:
            account = s.exec(select(DouyinAccount).where(
                DouyinAccount.platform == 'youtube', DouyinAccount.status == 'active',
                DouyinAccount.credential_ref != '').order_by(DouyinAccount.id.desc())).first()
        if not account or account.platform != 'youtube' or account.status != 'active' or not account.credential_ref:
            raise ValueError('未找到已授权的活跃 YouTube 账号')
        return account.model_dump()


def _record(task, account):
    return dict(task_id=task.id, d2y_video_id=task.source_content_id,
                title=task.title, scheduled_at=task.scheduled_at.isoformat() if task.scheduled_at else None,
                file_path=json.loads(task.media_json)[0], channel_id=account['sec_uid'],
                status=task.status, youtube_video_id=task.platform_result_id,
                error=task.error, intent_key=task.source_intent_key, revision=task.source_revision)


def _manifest_fingerprint(account_id, video, *, visibility, intent_id, manifest_version):
    payload = {
        'manifest_version': int(manifest_version),
        'account_id': int(account_id),
        'source_id': int(video['id']),
        'processed_path': str(Path(video['processed_path']).resolve()),
        'title_en': str(video.get('title_en') or ''),
        'desc_en': str(video.get('desc_en') or ''),
        'tags_en': str(video.get('tags_en') or ''),
        'visibility': str(visibility),
        'intent_id': str(intent_id),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def enqueue_d2y(account_id, videos, *, visibility='public', interval_seconds=150,
                start_time=None, intent_id='initial', manifest_version=1):
    if manifest_version != 1:
        raise ValueError('Unsupported D2Y manifest_version; supported version is 1')
    if visibility not in {'public', 'unlisted', 'private'} or not 0 <= interval_seconds <= 86400:
        raise ValueError('Invalid visibility or interval_seconds')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', intent_id):
        raise ValueError('Invalid intent_id')
    if len(videos) > 100:
        raise ValueError('A batch may contain at most 100 videos')
    account = _account(account_id)
    now = datetime.utcnow()
    start = start_time or now
    if start.tzinfo is not None:
        start = start.astimezone(timezone.utc).replace(tzinfo=None)
    tasks=[]; created=0
    # Validate the whole request before creating any task.
    for video in videos:
        if int(video['id']) <= 0 or not Path(video['processed_path']).is_file():
            raise ValueError('Invalid source id or missing media file')
    for index, video in enumerate(videos):
        key=f"d2y:{account['id']}:{int(video['id'])}:upload:{intent_id}"
        fingerprint = _manifest_fingerprint(
            account['id'], video, visibility=visibility,
            intent_id=intent_id, manifest_version=manifest_version)
        legacy_fingerprint = hashlib.sha256(key.encode()).hexdigest()
        with get_session() as s:
            task=s.exec(select(PublishTask).where(PublishTask.source_intent_key==key)).first()
            if task is not None and task.content_fingerprint not in {'', None, legacy_fingerprint, fingerprint}:
                raise ValueError(
                    f'D2Y intent conflict for source id {int(video["id"])}: '
                    'same intent_id was already used with different manifest content')
            if task is None:
                task=PublishTask(platform='youtube', account_id=account['id'],media_type='video',
                    title=(video.get('title_en') or 'Douyin Shorts').strip()[:100],
                    desc=(video.get('desc_en') or '').strip()[:4500],topics=video.get('tags_en') or '',
                    media_json=json.dumps([video['processed_path']]),visibility=visibility,operation='upload',
                    scheduled_at=start+timedelta(seconds=index*interval_seconds),
                    source_platform='d2y',source_content_id=int(video['id']),source_intent_key=key,
                    content_fingerprint=fingerprint)
                s.add(task)
                try:
                    s.commit();s.refresh(task);created+=1
                except IntegrityError:
                    s.rollback()
                    task=s.exec(select(PublishTask).where(PublishTask.source_intent_key==key)).first()
                    if task is None:raise
            tasks.append(_record(task,account))
    return dict(ok=True,manifest_version=manifest_version,count=len(tasks),created_count=created,
                account=account['nickname'],tasks=tasks,
                message=f'已确认 {len(tasks)} 条任务，新建 {created} 条')


def reconcile_d2y(*, projector=None):
    """Replay latest committed states; no external publication or account mutation."""
    with get_session() as s:
        rows=s.exec(select(PublishTask).where(PublishTask.source_platform=='d2y').order_by(PublishTask.id)).all()
        latest={}
        for t in rows:
            account=s.get(DouyinAccount,t.account_id)
            if account and t.source_content_id:
                latest[t.source_content_id]=_record(t,account.model_dump())
    records=list(latest.values())
    if records and projector is not None:
        projector(records)
    return len(records)


def import_batch(*, batch_size=None, visibility='public',interval_seconds=150,account_id=None,start_time=None,request_id=None):
    count=default_batch_size() if batch_size is None else batch_size
    if not 1 <= count <= 100:raise ValueError('batch_size must be between 1 and 100')
    account=_account(account_id)
    source=source_adapter()
    reconcile_d2y(projector=source.apply_task_results)
    if request_id is not None and not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',request_id):
        raise ValueError('Invalid request_id')
    options=json.dumps(dict(batch_size=count,visibility=visibility,interval_seconds=interval_seconds,account_id=account['id']),sort_keys=True)
    batch=None
    if request_id:
        with get_session() as s:batch=s.get(D2YImportRequest,request_id)
    if batch is None:
        videos=source.prepare_d2y_batch(count)
        if request_id:
            with get_session() as s:
                batch=D2YImportRequest(request_id=request_id,account_id=account['id'],options_json=options,
                                      videos_json=json.dumps(videos),start_time=start_time or datetime.utcnow())
                s.add(batch)
                try:s.commit();s.refresh(batch)
                except IntegrityError:
                    s.rollback();batch=s.get(D2YImportRequest,request_id)
                    if batch is None:raise
    if batch:
        if batch.options_json != options:
            raise ValueError('request_id was already used with different batch options')
        videos=json.loads(batch.videos_json);start_time=batch.start_time
    result=enqueue_d2y(account['id'],videos,visibility=visibility,interval_seconds=interval_seconds,start_time=start_time)
    result['request_id']=request_id
    result['legacy_adapter']=True
    result['deprecated']=True
    result['replacement']='/api/youtube/d2y/enqueue'
    # A failure here leaves committed intents which the next legacy run can replay.
    reconcile_d2y(projector=source.apply_task_results)
    return result
