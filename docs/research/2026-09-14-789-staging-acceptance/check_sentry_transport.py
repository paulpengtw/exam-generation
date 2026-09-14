import asyncio
import json
import os
import tempfile
from pathlib import Path
import sentry_sdk
from sentry_sdk.transport import Transport
from server import observability
from server.generate import persistence
from tests.server.test_exchange_persistence_integration import exchange_store, delayed_exchange

class MemoryTransport(Transport):
    events=[]
    def capture_envelope(self,envelope):
        for item in envelope.items:
            if item.headers.get('type')=='event':
                self.events.append(json.loads(item.get_bytes()))

real_init=sentry_sdk.init
transport=MemoryTransport()
def isolated_init(**kwargs):
    kwargs['transport']=transport
    return real_init(**kwargs)
sentry_sdk.init=isolated_init
os.environ['SENTRY_DSN']='https://public@example.invalid/1'
os.environ['SENTRY_ENVIRONMENT']='local-acceptance'
observability.init_sentry()
persistence.EXCHANGE_WRITE_TIMEOUT_SECONDS=0.05
async def run():
    with tempfile.TemporaryDirectory() as directory:
        async with exchange_store(Path(directory)) as store:
            await delayed_exchange(store)
asyncio.run(run())
sentry_sdk.flush()
results=[]
for event in transport.events:
    if event.get('logger')!='server.generate.persistence': continue
    extra=event.get('extra',{})
    safe={k:extra.get(k) for k in ['generation_log_id','agent','exchange_order','outcome','error_type','error_module']}
    assert safe['generation_log_id'] and safe['agent']=='sub_generator#1' and safe['exchange_order']==7
    assert 'PRIVATE_' not in json.dumps(event)
    assert not event.get('exception')
    results.append({'metadata':safe,'has_exception':bool(event.get('exception')),'contains_synthetic_content':False})
assert [r['metadata']['outcome'] for r in results]==['pending','committed']
print(json.dumps({'transport':'in-memory; no telemetry sent','events':results},indent=2))
