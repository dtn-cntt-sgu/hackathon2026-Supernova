// Unit-only secrets and mocked backend responses; no production OAuth verification claim.
import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import { signedIdentityHeaders, signedClientHeaders } from '../src/lib/server-identity.ts';

test('server signatures bind identity and timestamp without a fixed fallback', t => {
  const old = process.env.AUTH_SECRET, alias = process.env.NEXTAUTH_SECRET;
  t.after(() => { if (old === undefined) delete process.env.AUTH_SECRET; else process.env.AUTH_SECRET=old; if (alias === undefined) delete process.env.NEXTAUTH_SECRET; else process.env.NEXTAUTH_SECRET=alias; });
  delete process.env.AUTH_SECRET; delete process.env.NEXTAUTH_SECRET;
  assert.throws(() => signedIdentityHeaders('owner@example.com','provider'), /not configured/);
  process.env.AUTH_SECRET='unit-only-signature-secret';
  const headers=signedIdentityHeaders(' Owner@Example.com ','provider');
  assert.equal(headers['X-Auth-Signature'],crypto.createHmac('sha256',process.env.AUTH_SECRET).update(`owner@example.com:provider:${headers['X-Auth-Timestamp']}`).digest('hex'));
  assert.equal(headers['X-Auth-User-Email'],'owner@example.com');
  const client=signedClientHeaders('192.0.2.1');
  assert.equal(client['X-Proxy-Signature'],crypto.createHmac('sha256',process.env.AUTH_SECRET).update(`client:192.0.2.1:${client['X-Proxy-Timestamp']}`).digest('hex'));
  assert.notEqual(client['X-Proxy-Signature'],headers['X-Auth-Signature']);
});

test('OAuth sync signs identity and denies login when backend sync fails', async t => {
  const oldSecret=process.env.AUTH_SECRET, originalFetch=global.fetch;
  process.env.AUTH_SECRET='unit-only-oauth-secret';
  t.after(()=>{ global.fetch=originalFetch; if(oldSecret===undefined) delete process.env.AUTH_SECRET; else process.env.AUTH_SECRET=oldSecret; });
  const { authOptions }=await import('../src/auth.ts');
  const credentials={ user:{email:'owner@example.com',name:'Owner'}, account:{provider:'google',providerAccountId:'provider'},profile:{email_verified:true} };
  global.fetch=async (url,init)=>{ assert.ok(init.headers['X-Auth-Signature']); assert.equal(JSON.parse(init.body).provider_account_id,'provider'); return new Response(JSON.stringify({id:'unit-user',is_active:true}),{status:200}); };
  assert.equal(await authOptions.callbacks.signIn(credentials),true);
  assert.equal(credentials.user.id,'unit-user');
  global.fetch=async ()=>new Response('{}',{status:401});
  assert.equal(await authOptions.callbacks.signIn(credentials),false);
  assert.equal(await authOptions.callbacks.signIn({...credentials,profile:{email_verified:false}}),false);
  assert.equal(await authOptions.callbacks.signIn({...credentials,profile:{}}),false);
  global.fetch=async ()=>new Response(JSON.stringify({id:'unit-user',is_active:false}),{status:200});
  assert.equal(await authOptions.callbacks.signIn(credentials),false);
});
