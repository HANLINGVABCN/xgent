"""Updates retain valid Web sessions; credential changes still revoke them."""
import asyncio
import contextlib
import http.client
import json
import threading
import time

import aiosqlite
import pytest

from xgent_app import web_auth
from xgent_app.data_parts import config_part
from xgent_app.web_server import WebChatConfig, WebChatServer
from xgent_app.web_two_factor import PASSWORD_KEY, WebTwoFactor, totp
from tests.test_web_two_factor import Database


def test_instance_secret_survives_database_reopen_and_concurrent_load(tmp_path):
    class Store:
        @contextlib.asynccontextmanager
        async def _transaction(self):
            async with self.lock:
                await self.connection.execute('BEGIN IMMEDIATE')
                try:
                    yield self.connection
                    await self.connection.commit()
                except BaseException:
                    await self.connection.rollback()
                    raise
    async def exercise():
        store=Store();store.lock=asyncio.Lock()
        store.connection=await aiosqlite.connect(tmp_path/'memory.db',isolation_level=None)
        await store.connection.execute('CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        values=await asyncio.gather(*(web_auth.load_session_secret(store) for _ in range(8)))
        assert len(set(values))==1 and len(values[0])==32
        await store.connection.close()
        store.connection=await aiosqlite.connect(tmp_path/'memory.db',isolation_level=None)
        try:
            assert await web_auth.load_session_secret(store)==values[0]
            await store.connection.execute('UPDATE config SET value=?',('"corrupt"',))
            with pytest.raises(ValueError,match='配置异常'):await web_auth.load_session_secret(store)
            assert (await (await store.connection.execute('SELECT value FROM config')).fetchone())[0]=='"corrupt"'
        finally:await store.connection.close()
    asyncio.run(exercise())
    assert config_part(web_auth.SESSION_SECRET_CONFIG_KEY)=='secrets'


@pytest.fixture
def instance_server():
    loop=asyncio.new_event_loop();thread=threading.Thread(target=loop.run_forever,daemon=True);thread.start()
    run=lambda coro:asyncio.run_coroutine_threadsafe(coro,loop).result(10)
    db=run(Database().open())
    async def database():return db
    async def empty(*args):return []
    secret=run(web_auth.load_session_secret(db))
    class Instance:
        def start(self):
            self.service=WebTwoFactor(database)
            self.server=WebChatServer(WebChatConfig(host='127.0.0.1',port=0,
                password_hash=run(db.get_config_fresh(PASSWORD_KEY)),bot_token='fixture-token',authorized_user_id=1,
                loop=loop,submit_message=empty,read_history=empty,read_settings=empty,write_setting=empty,
                request_stop=lambda:None,is_busy=lambda:False,security_api=self.service.handle,session_secret=secret))
            self.server.start()
        def restart(self):self.server.stop();self.start()
        def request(self,path,data=None,cookie=''):
            connection=http.client.HTTPConnection('127.0.0.1',self.server._httpd.server_address[1],timeout=5)
            connection.request('POST' if data is not None else 'GET',path,
                body=json.dumps(data) if data is not None else None,
                headers={'Cookie':cookie,'Content-Type':'application/json'})
            response=connection.getresponse();result=response.status,json.loads(response.read()),response.getheader('Set-Cookie')
            connection.close();return result
        def login(self,password='test-password'):
            status,_,cookie=self.request('/api/login',{'password':password});assert status==200
            return cookie.split(';',1)[0]
    instance=Instance();instance.start();instance.db=db;instance.run=run
    try:yield instance
    finally:
        instance.server.stop();run(db.close());loop.call_soon_threadsafe(loop.stop);thread.join(5);loop.close()


def test_restart_retains_cookie_password_change_and_logout_do_not(instance_server):
    instance=instance_server;cookie=instance.login();old_key=instance.server._httpd.session_key
    instance.restart()
    assert instance.server._httpd.session_key==old_key
    assert instance.request('/api/session',cookie=cookie)[1]['authenticated']
    assert instance.request('/api/history',cookie=cookie)[0]==200
    instance.run(instance.db.set(PASSWORD_KEY,web_auth.hash_password('changed-password')))
    instance.restart()
    assert instance.server._httpd.session_key!=old_key
    assert not instance.request('/api/session',cookie=cookie)[1]['authenticated']
    assert instance.request('/api/history',cookie=cookie)[0]==401
    new=instance.login('changed-password')
    assert instance.request('/api/session',cookie=new)[1]['authenticated']
    assert 'Max-Age=0' in instance.request('/api/logout',{},new)[2]


def test_shutdown_is_temporary_unavailability_instead_of_login_expiry(instance_server):
    instance=instance_server;cookie=instance.login()
    instance.server.shutdown_event.set()
    try:
        for path,data in [('/api/session',None),('/api/history',None),('/api/login',{'password':'test-password'})]:
            status,body,new_cookie=instance.request(path,data,cookie)
            assert status==503 and 'authenticated' not in body and new_cookie is None
    finally:instance.server.shutdown_event.clear()
    assert instance.request('/api/session',cookie=cookie)[1]['authenticated']


def test_two_factor_cookie_survives_restart_but_security_version_changes_revoke_it(instance_server):
    instance=instance_server;old=instance.login()
    status,setup,_=instance.request('/api/security/2fa/setup',{'password':'test-password'},old);assert status==200
    status,result,cookie=instance.request('/api/security/2fa/confirm',
        {'setup_id':setup['setup_id'],'code':totp(setup['secret'],int(time.time())//30)},old)
    assert status==200;cookie=cookie.split(';',1)[0]
    instance.restart()
    assert instance.request('/api/session',cookie=cookie)[1]['authenticated']
    assert not instance.request('/api/session',cookie=old)[1]['authenticated']
    status,start,no_cookie=instance.request('/api/login',{'password':'test-password'})
    assert status==200 and start['requires_2fa'] and no_cookie is None
    instance.restart()
    assert instance.request('/api/login',{'challenge_id':start['challenge_id'],'code':result['recovery_codes'][0]})[0]==410
    status,_,refreshed=instance.request('/api/security/2fa/disable',
        {'password':'test-password','code':result['recovery_codes'][1]},cookie)
    assert status==200;refreshed=refreshed.split(';',1)[0]
    instance.restart()
    assert not instance.request('/api/session',cookie=cookie)[1]['authenticated']
    assert instance.request('/api/session',cookie=refreshed)[1]['authenticated']


def test_instance_credential_identity_and_cookie_ttl_remain_enforced():
    secret=b'a'*32;key=web_auth.instance_session_key(secret,'hash','bot',1)
    cookie=web_auth.make_session_cookie_value(key,issued_at=100)
    assert web_auth.verify_session_cookie(key,cookie,now=101)
    for password,bot,user in [('new-hash','bot',1),('hash','new-bot',1),('hash','bot',2)]:
        assert not web_auth.verify_session_cookie(web_auth.instance_session_key(secret,password,bot,user),cookie,now=101)
    assert not web_auth.verify_session_cookie(key,cookie,now=101+web_auth.SESSION_TTL_SECONDS)
