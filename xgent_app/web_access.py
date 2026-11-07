"""Persistent Web access limits, device sessions, and owner-managed IP rules."""
from __future__ import annotations
import hashlib
import ipaddress
import json
import math
import secrets
import time

from . import web_auth

POLICY_KEY='web_access_policy'
DEFAULT_POLICY={'enabled':True,'wait_after':5,'wait_seconds':180,'ban_after':8,'proxy_header':'none'}


async def rows(conn,sql,args=()):
    cursor=await conn.execute(sql,args)
    try:return [dict(zip([c[0] for c in cursor.description],row)) for row in await cursor.fetchall()]
    finally:await cursor.close()


def address(value):
    try:
        ip=ipaddress.ip_address(str(value));return str(ip.ipv4_mapped or ip) if isinstance(ip,ipaddress.IPv6Address) else str(ip)
    except ValueError:raise ValueError('请输入有效的 IP 地址') from None


def resolve_ip(peer,headers,policy):
    peer=address(peer)
    # Explicit proxy selection: remote clients cannot enable trust using headers.
    if ipaddress.ip_address(peer).is_loopback:
        name={'cloudflare':'cf-connecting-ip','real-ip':'x-real-ip'}.get(policy.get('proxy_header'))
        if name:
            value={k.lower():v for k,v in headers.items()}.get(name)
            if value:
                try:return address(value)
                except ValueError:pass
    return peer


def device_cookie(secret,value):
    device,_,signature=str(value or '').partition('.')
    if len(device)==32 and all(c in '0123456789abcdef' for c in device):
        expected=web_auth._sign(secret,'device:'+device)
        if signature.isascii() and secrets.compare_digest(signature,expected):return device,None
    device=secrets.token_hex(16)
    return device,device+'.'+web_auth._sign(secret,'device:'+device)


class WebAccess:
    def __init__(self,database,notify=None):self.database=database;self.notify=notify

    async def initialize(self):
        db=await self.database()
        async with db._transaction() as conn:
            await conn.execute('''CREATE TABLE IF NOT EXISTS web_access_clients (
                kind TEXT NOT NULL,id TEXT NOT NULL,visits INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0,streak INTEGER NOT NULL DEFAULT 0,
                wait_until REAL NOT NULL DEFAULT 0,blocked INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT '',first_seen REAL NOT NULL,last_seen REAL NOT NULL,
                last_ip TEXT NOT NULL,agent TEXT NOT NULL,PRIMARY KEY(kind,id))''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS web_login_sessions (
                id TEXT PRIMARY KEY,device TEXT NOT NULL,ip TEXT NOT NULL,agent TEXT NOT NULL,
                created_at REAL NOT NULL,last_seen REAL NOT NULL,expires_at REAL NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,key_version TEXT NOT NULL)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS web_ip_rules (
                id TEXT PRIMARY KEY,network TEXT NOT NULL UNIQUE,mode TEXT NOT NULL,note TEXT NOT NULL,created_at REAL NOT NULL)''')
            await conn.execute('''CREATE TABLE IF NOT EXISTS web_access_incidents (
                id TEXT PRIMARY KEY,ip TEXT NOT NULL,device TEXT NOT NULL,agent TEXT NOT NULL,
                failures INTEGER NOT NULL,created_at REAL NOT NULL,resolved INTEGER NOT NULL DEFAULT 0)''')
            await conn.execute('CREATE INDEX IF NOT EXISTS web_sessions_device ON web_login_sessions(device)')
            await conn.execute('CREATE TABLE IF NOT EXISTS web_session_migrations (token_hash TEXT PRIMARY KEY,session_id TEXT NOT NULL)')

    async def policy(self):
        db=await self.database();value=await db.get_config_fresh(POLICY_KEY,{})
        return {**DEFAULT_POLICY,**(value if isinstance(value,dict) else {})}

    async def _clients(self,conn,ip,device,agent,now):
        for kind,value in [('ip',ip),('device',device)]:
            await conn.execute('''INSERT INTO web_access_clients(kind,id,first_seen,last_seen,last_ip,agent)
                VALUES(?,?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET last_seen=excluded.last_seen,last_ip=excluded.last_ip,agent=excluded.agent''',
                (kind,value,now,now,ip,agent))
        return await rows(conn,'SELECT * FROM web_access_clients WHERE (kind=? AND id=?) OR (kind=? AND id=?)',('ip',ip,'device',device))

    async def _rule(self,conn,ip):
        matched=[]
        for row in await rows(conn,'SELECT network,mode FROM web_ip_rules'):
            if ipaddress.ip_address(ip) in ipaddress.ip_network(row['network']):matched.append(row['mode'])
        return 'black' if 'black' in matched else 'white' if 'white' in matched else ''

    async def handle(self,action,data):
        db=await self.database();now=time.time()
        if action=='gate':
            policy=await self.policy();ip=resolve_ip(data['peer'],data.get('headers',{}),policy);device=data['device'];agent=data.get('agent','')[:512]
            async with db._transaction() as conn:
                clients=await self._clients(conn,ip,device,agent,now)
                await conn.execute('UPDATE web_access_clients SET visits=visits+1 WHERE (kind=? AND id=?) OR (kind=? AND id=?)',('ip',ip,'device',device))
                rule=await self._rule(conn,ip)
            wait=math.ceil(max([0,*[c['wait_until']-now for c in clients]]))
            blocked=rule=='black' or any(c['blocked'] for c in clients)
            return {'ip':ip,'device':device,'blocked':blocked,'wait':wait if rule!='white' and policy['enabled'] else 0,'rule':rule}
        if action=='failure':
            policy=await self.policy();ip=data['ip'];device=data['device'];incident=None
            async with db._transaction() as conn:
                clients=await self._clients(conn,ip,device,data.get('agent','')[:512],now)
                rule=await self._rule(conn,ip)
                if any(c['blocked'] for c in clients):return {'blocked':True,'wait':0}
                for c in clients:
                    streak=c['streak']+1;wait=c['wait_until'];blocked=0
                    if policy['enabled'] and rule!='white':
                        if streak>=policy['ban_after']:blocked=1
                        elif streak==policy['wait_after']:wait=now+policy['wait_seconds']
                    await conn.execute('UPDATE web_access_clients SET failures=failures+1,streak=?,wait_until=?,blocked=?,reason=? WHERE kind=? AND id=?',
                        (streak,wait,blocked,'连续登录失败' if blocked else '',c['kind'],c['id']))
                clients=await self._clients(conn,ip,device,data.get('agent','')[:512],now)
                if any(c['blocked'] for c in clients):
                    # A device changing IP or cookies changing on the same IP cannot evade the counter.
                    await conn.execute('UPDATE web_access_clients SET blocked=1,reason=? WHERE (kind=? AND id=?) OR (kind=? AND id=?)',('连续登录失败','ip',ip,'device',device))
                    await conn.execute('UPDATE web_login_sessions SET revoked=1 WHERE ip=? OR device=?',(ip,device))
                    incident={'id':secrets.token_hex(16),'ip':ip,'device':device,'agent':data.get('agent','')[:512],
                              'failures':max(c['streak'] for c in clients),'created_at':now,'resolved':0}
                    await conn.execute('INSERT INTO web_access_incidents VALUES(?,?,?,?,?,?,?)',tuple(incident.values()))
            if incident and self.notify:
                # Blocking is already committed; notification cannot roll it back.
                try:await self.notify(incident)
                except Exception:
                    import logging;logging.getLogger(__name__).exception('网页访问封禁已生效，告警投递失败')
            return {'blocked':bool(incident),'wait':math.ceil(max([0,*[c['wait_until']-now for c in clients]])) if rule!='white' else 0}
        if action in {'create_session','migrate_session'}:
            sid=secrets.token_hex(16)
            async with db._transaction() as conn:
                if action=='migrate_session':
                    found=await rows(conn,'SELECT s.* FROM web_session_migrations m JOIN web_login_sessions s ON s.id=m.session_id WHERE m.token_hash=?',(data['token_hash'],))
                    if found:
                        s=found[0];valid=not s['revoked'] and s['expires_at']>now and s['device']==data['device'] and s['key_version']==data['key_version']
                        return {'id':s['id'] if valid else ''}
                await conn.execute('UPDATE web_login_sessions SET revoked=1 WHERE device=?',(data['device'],))
                await conn.execute('UPDATE web_access_clients SET streak=0,wait_until=0 WHERE (kind=? AND id=?) OR (kind=? AND id=?)',('ip',data['ip'],'device',data['device']))
                await conn.execute('INSERT INTO web_login_sessions VALUES(?,?,?,?,?,?,?,0,?)',
                    (sid,data['device'],data['ip'],data.get('agent','')[:512],now,now,now+web_auth.SESSION_TTL_SECONDS,data['key_version']))
                if action=='migrate_session':await conn.execute('INSERT INTO web_session_migrations VALUES(?,?)',(data['token_hash'],sid))
            return {'id':sid}
        if action=='session':
            async with db._transaction() as conn:
                found=await rows(conn,'SELECT * FROM web_login_sessions WHERE id=?',(data['id'],))
                valid=bool(found and not found[0]['revoked'] and found[0]['expires_at']>now and found[0]['device']==data['device'] and found[0]['key_version']==data['key_version'])
                if valid:await conn.execute('UPDATE web_login_sessions SET last_seen=?,ip=? WHERE id=?',(now,data['ip'],data['id']))
            return {'valid':valid}
        if action=='logout':
            async with db._transaction() as conn:await conn.execute('UPDATE web_login_sessions SET revoked=1 WHERE id=?',(data.get('id',''),))
            return {'ok':True}
        if action=='overview':
            async with db._transaction() as conn:
                clients=await rows(conn,'SELECT * FROM web_access_clients ORDER BY last_seen DESC LIMIT 500')
                known={(client['kind'],client['id']) for client in clients}
                clients.extend(client for client in await rows(conn,'SELECT * FROM web_access_clients WHERE blocked=1 ORDER BY last_seen DESC')
                               if (client['kind'],client['id']) not in known)
                sessions=await rows(conn,'SELECT * FROM web_login_sessions WHERE revoked=0 AND expires_at>? AND key_version=? ORDER BY last_seen DESC LIMIT 200',(now,data['key_version']))
                rules=await rows(conn,'SELECT * FROM web_ip_rules ORDER BY created_at DESC')
                incidents=await rows(conn,'SELECT * FROM web_access_incidents ORDER BY created_at DESC LIMIT 100')
            for session in sessions:
                session.pop('key_version',None);session['current']=session['id']==data.get('session_id')
            return {'policy':await self.policy(),'clients':clients,'sessions':sessions,'rules':rules,'incidents':incidents}
        if action in {'unblock','block','rule','delete_rule','policy','revoke','revoke_others'}:
            if data.get('confirm') is not True:raise ValueError('请确认访问安全操作')
            async with db._transaction() as conn:
                if action=='unblock':
                    if data.get('incident'):
                        found=await rows(conn,'SELECT * FROM web_access_incidents WHERE id=?',(data['incident'],))
                        if not found:raise ValueError('封禁记录不存在')
                        data={**data,**found[0]}
                    if data.get('ip'):await conn.execute('UPDATE web_access_clients SET blocked=0,streak=0,wait_until=0,reason=? WHERE kind=? AND id=?',('','ip',address(data['ip'])))
                    if data.get('device'):await conn.execute('UPDATE web_access_clients SET blocked=0,streak=0,wait_until=0,reason=? WHERE kind=? AND id=?',('','device',data['device']))
                    await conn.execute('UPDATE web_access_incidents SET resolved=1 WHERE ip=? AND device=?',(data.get('ip',''),data.get('device','')))
                    if data.get('incident'):
                        try:found=await rows(conn,'SELECT id,metadata FROM global_messages WHERE metadata LIKE ?',('%'+data['incident']+'%',))
                        except Exception:found=[]  # Standalone auth embeds may have no chat history.
                        for row in found:
                            metadata=json.loads(row['metadata'] or '{}');notice=metadata.get('security_notice') or {}
                            if notice.get('incident_id')==data['incident']:
                                notice['resolved']=True;await conn.execute('UPDATE global_messages SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),row['id']))
                elif action=='block':
                    kind=data.get('kind');value=data.get('id')
                    if kind not in {'ip','device'}:raise ValueError('无效的封禁目标')
                    if kind=='ip':value=address(value)
                    await conn.execute('UPDATE web_access_clients SET blocked=1,reason=? WHERE kind=? AND id=?',('手动封禁',kind,value))
                    await conn.execute('UPDATE web_login_sessions SET revoked=1 WHERE '+('ip' if kind=='ip' else 'device')+'=?',(value,))
                elif action=='rule':
                    try:network=str(ipaddress.ip_network(str(data.get('network','')),strict=False))
                    except ValueError:raise ValueError('请输入有效 IP 或 CIDR 网段') from None
                    if data.get('mode') not in {'black','white'}:raise ValueError('无效的名单类型')
                    await conn.execute('INSERT INTO web_ip_rules VALUES(?,?,?,?,?) ON CONFLICT(network) DO UPDATE SET mode=excluded.mode,note=excluded.note',
                        (secrets.token_hex(16),network,data['mode'],str(data.get('note',''))[:200],now))
                elif action=='delete_rule':await conn.execute('DELETE FROM web_ip_rules WHERE id=?',(data.get('id',''),))
                elif action=='policy':
                    policy={**DEFAULT_POLICY,**{k:data[k] for k in DEFAULT_POLICY if k in data}}
                    if type(policy['enabled']) is not bool or policy['proxy_header'] not in {'none','cloudflare','real-ip'}:raise ValueError('无效的访问策略')
                    if any(type(policy[k]) is not int or not 1<=policy[k]<=3600 for k in ('wait_after','wait_seconds','ban_after')) or policy['ban_after']<=policy['wait_after']:raise ValueError('封禁次数必须大于等待次数，数值须为 1–3600')
                    await conn.execute('INSERT OR REPLACE INTO config VALUES(?,?)',(POLICY_KEY,json.dumps(policy)))
                elif action=='revoke':await conn.execute('UPDATE web_login_sessions SET revoked=1 WHERE id=?',(data.get('id',''),))
                elif action=='revoke_others':await conn.execute('UPDATE web_login_sessions SET revoked=1 WHERE id<>?',(data.get('session_id',''),))
            return {'ok':True}
        raise ValueError('未知访问安全操作')
