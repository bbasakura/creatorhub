import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
from app.platforms.youtube import client


class UploadTests(unittest.IsolatedAsyncioTestCase):
    async def test_resumable_upload_and_completed_retry_do_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(client, 'ROOT', Path(temp)), patch.dict('os.environ', {'YOUTUBE_CLIENT_ID':'id','YOUTUBE_CLIENT_SECRET':'secret'}):
            video = Path(temp) / 'video.mp4'
            video.write_bytes(b'video')
            client.store('credential', {'channel_id':'channel','refresh_token':'refresh'})
            initiated = []
            chunks = []
            def handle(request):
                path = request.url.path
                if path == '/token':
                    return httpx.Response(200, json={'access_token':'access'})
                if path.endswith('/channels'):
                    return httpx.Response(200, json={'items':[{'id':'channel'}]})
                if path.startswith('/upload/'):
                    initiated.append(1)
                    return httpx.Response(200, headers={'location':'https://www.googleapis.com/session'})
                if path == '/session':
                    if request.headers.get('content-range') == 'bytes */5':
                        return httpx.Response(308)
                    chunks.append(request.content)
                    return httpx.Response(200, json={'id':'video-id'})
                if path.endswith('/videos'):
                    return httpx.Response(200, json={'items':[{'snippet':{'channelId':'channel'},'status':{'privacyStatus':'private'},'processingDetails':{'processingStatus':'processing'}}]})
                raise AssertionError(str(request.url))
            factory = httpx.AsyncClient
            with patch.object(client.httpx, 'AsyncClient', side_effect=lambda **kw: factory(transport=httpx.MockTransport(handle), **kw)):
                args = (1,'credential','channel',str(video),'Title','Description',[])
                first = await client.upload_video(*args)
                second = await client.upload_video(*args)
            self.assertTrue(first[0]); self.assertTrue(second[0])
            self.assertEqual(len(initiated),1)
            self.assertEqual(chunks,[b'video'])
            self.assertEqual(client.load('upload_1')['processing'],'processing')

    async def test_invalid_visibility_does_not_upload(self):
        ok, _, error = await client.upload_video(1,'ref','channel','missing','title','',[],visibility='friends')
        self.assertFalse(ok)
        self.assertEqual(error,'invalid_visibility')

    async def test_expired_oauth_state_is_consumed(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(client,'ROOT',Path(temp)):
            client.store('state_test', {'expires':0,'verifier':'test'})
            with self.assertRaises(ValueError):
                await client.finish_oauth('code','test')
            self.assertFalse((Path(temp)/'state_test.json').exists())
