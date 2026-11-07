import asyncio
import json
import time
from unittest.mock import patch

import pytest

from tests.test_web_two_factor import Database
from xgent_app.web_access import WebAccess,device_cookie,resolve_ip,DEFAULT_POLICY
from xgent_app import web_auth
from xgent_app.web_server import WebChatConfig,WebChatServer


def test_http_failure_limits_managed_sessions_and_unblock():
    import threading,http.client
    loop=asyncio.new_event_loop();thread=threading.Thread(target=loop.run_forever,daemon=True);thread.start()
    run=lambda coro:asyncio.run_coroutine_threadsafe(coro,loop).result(10)
    db=run(Database().open())
    async def database():return db
    async def empty(*args):return []
    access=WebAccess(database);run(access.initialize())
    run(db.set('web_access_policy',{**DEFAULT_POLICY,'proxy_header':'real-ip'}))
    server=WebChatServer(WebChatConfig(host='127.0.0.1',port=0,password_hash=run(db.get_config_fresh('web_password_hash')),
        bot_token='',authorized_user_id=1,loop=loop,submit_message=empty,read_history=empty,read_settings=empty,
        write_setting=empty,request_stop=lambda:None,is_busy=lambda:False,session_secret=run(web_auth.load_session_secret(db)),access_api=access.handle))
    server.start();cookies={'owner':{},'stranger':{}}
    def request(path,data=None,client='owner'):
        connection=http.client.HTTPConnection('127.0.0.1',server._httpd.server_address[1],timeout=10)
        connection.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,
            {'Cookie':'; '.join(k+'='+v for k,v in cookies[client].items()),'X-Real-IP':'198.51.100.1' if client=='owner' else '198.51.100.2','Content-Type':'application/json'})
        response=connection.getresponse();body=json.loads(response.read())
        for header,value in response.getheaders():
            if header.lower()=='set-cookie':cookies[client].update(web_auth.parse_cookie_header(value.split(';')[0]))
        connection.close();return response.status,body
    try:
        assert request('/api/login',{'password':'test-password'})[0]==200
        assert request('/api/session')[1]['authenticated']
        assert request('/api/security/access')[0]==200
        for i in range(5):status,_=request('/api/login',{'password':'wrong'},'stranger')
        assert status==429
        assert request('/api/login',{'password':'test-password'},'stranger')[0]==429
        async def expire_wait():
            async with db._transaction() as conn:await conn.execute('UPDATE web_access_clients SET wait_until=0')
        run(expire_wait())
        for i in range(3):status,_=request('/api/login',{'password':'wrong'},'stranger')
        assert status==403
        assert request('/api/login',{'password':'test-password'},'stranger')[0]==403
        data=request('/api/security/access')[1];assert len(data['incidents'])==1
        assert request('/api/security/access/unblock',{'incident':data['incidents'][0]['id'],'confirm':True})[0]==200
        assert request('/api/login',{'password':'test-password'},'stranger')[0]==200
        state=request('/api/security/access')[1];assert len(state['sessions'])==2
        target=next(s for s in state['sessions'] if not s['current'])
        assert request('/api/security/access/revoke',{'id':target['id'],'confirm':True})[0]==200
        assert not request('/api/session',client='stranger')[1]['authenticated']
        assert request('/api/history',client='stranger')[0]==401
        assert request('/api/session')[1]['authenticated']
    finally:
        server.stop();run(db.close());loop.call_soon_threadsafe(loop.stop);thread.join(5);loop.close()


def test_wait_then_ban_both_identifiers_persist_and_unblock_together():
    async def exercise():
        db=await Database().open();notifications=[]
        async def database():return db
        async def notify(incident):notifications.append(incident)
        access=WebAccess(database,notify);await access.initialize()
        peer={'peer':'198.51.100.7','device':'d'*32,'agent':'Browser'}
        clock=1700000000
        with patch('xgent_app.web_access.time.time',lambda:clock):
            for i in range(5):
                gate=await access.handle('gate',peer);assert not gate['blocked'] and gate['wait']==0
                result=await access.handle('failure',{**peer,'ip':gate['ip']})
            assert result['wait']==180 and not notifications
            restarted=WebAccess(database,notify);await restarted.initialize()
            assert (await restarted.handle('gate',peer))['wait']==180
            clock+=181
            for i in range(3):
                assert not (await restarted.handle('gate',peer))['blocked']
                result=await restarted.handle('failure',{**peer,'ip':peer['peer']})
            assert result['blocked'] and len(notifications)==1
            assert (await restarted.handle('gate',{**peer,'peer':'203.0.113.8'}))['blocked']
            assert (await restarted.handle('gate',{**peer,'device':'a'*32}))['blocked']
            await restarted.handle('unblock',{'incident':notifications[0]['id'],'confirm':True})
            assert not (await restarted.handle('gate',peer))['blocked']
            state=await restarted.handle('overview',{'key_version':'key'})
            assert all(c['streak']==0 and c['failures']==8 for c in state['clients'] if c['id'] in {peer['peer'],peer['device']})
        await db.close()
    asyncio.run(exercise())


def test_sessions_revoked_individually_logout_and_white_black_precedence():
    async def exercise():
        db=await Database().open()
        async def database():return db
        access=WebAccess(database);await access.initialize()
        common={'ip':'198.51.100.8','device':'a'*32,'key_version':'k','agent':'Browser'}
        first=(await access.handle('create_session',common))['id']
        second=(await access.handle('create_session',{**common,'device':'b'*32}))['id']
        assert (await access.handle('session',{**common,'id':first}))['valid']
        assert not (await access.handle('session',{**common,'id':second}))['valid']
        await access.handle('revoke_others',{'session_id':first,'confirm':True})
        assert not (await access.handle('session',{**common,'device':'b'*32,'id':second}))['valid']
        await access.handle('logout',{'id':first})
        assert not (await access.handle('session',{**common,'id':first}))['valid']
        migrated=(await access.handle('migrate_session',{**common,'token_hash':'legacy'}))['id']
        assert (await access.handle('migrate_session',{**common,'token_hash':'legacy'}))['id']==migrated
        await access.handle('revoke',{'id':migrated,'confirm':True})
        assert not (await access.handle('migrate_session',{**common,'token_hash':'legacy'}))['id']
        await access.handle('rule',{'network':'198.51.100.8','mode':'white','confirm':True})
        for i in range(10):assert not (await access.handle('failure',common))['blocked']
        await access.handle('rule',{'network':'198.51.100.0/24','mode':'black','confirm':True})
        assert (await access.handle('gate',{'peer':common['ip'],'device':common['device']}))['blocked']
        assert (await access.handle('overview',{'key_version':'k'}))['sessions']==[]
        await db.close()
    asyncio.run(exercise())


def test_proxy_headers_not_trusted_until_explicitly_enabled_and_device_signed():
    header={'CF-Connecting-IP':'198.51.100.9'}
    assert resolve_ip('127.0.0.1',header,DEFAULT_POLICY)=='127.0.0.1'
    assert resolve_ip('203.0.113.1',header,{**DEFAULT_POLICY,'proxy_header':'cloudflare'})=='203.0.113.1'
    assert resolve_ip('127.0.0.1',header,{**DEFAULT_POLICY,'proxy_header':'cloudflare'})=='198.51.100.9'
    secret=web_auth.generate_session_secret();device,cookie=device_cookie(secret,'')
    assert device_cookie(secret,cookie)==(device,None)
    assert device_cookie(secret,cookie+'bad')[0]!=device


def test_notice_matches_existing_context_and_sync_without_duplicate_cards(tmp_path):
    from tests.test_thinking_params import run_in_app
    result=run_in_app('import asyncio\nfrom tests.web_access_notice_probe import exercise\n'+
        f'print(json.dumps(asyncio.run(exercise(bot,{str(tmp_path)!r}))))')
    assert all(result.values()),result
