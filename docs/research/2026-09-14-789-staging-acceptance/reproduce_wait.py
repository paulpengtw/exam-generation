import asyncio
import json
import logging
import subprocess
import tempfile
import time
from pathlib import Path
from tests.server.test_exchange_persistence_integration import exchange_store, delayed_exchange
from server.generate import persistence

original_source = subprocess.check_output(['git', 'show', '850c455f79b804d0cb84f8ef44efdfa8fde952f9:server/generate/persistence.py'], text=True)
original_namespace = {'__name__': 'old_exchange_persistence'}
exec(original_source, original_namespace)
new_factory = persistence.make_exchange_recorder
class Collect(logging.Handler):
    def __init__(self):
        super().__init__(); self.rows=[]
    def emit(self, record):
        if record.name not in {'old_exchange_persistence', 'server.generate.persistence'}: return
        safe = {key:getattr(record,key) for key in ['generation_log_id','agent','exchange_order','outcome','error_type','error_module'] if hasattr(record,key)}
        self.rows.append({'message':record.getMessage(),'metadata':safe,'has_exception':bool(record.exc_info),'contains_synthetic_content':'PRIVATE_' in repr(record.__dict__)})
handler=Collect(); logging.getLogger().addHandler(handler)
async def run():
    result=[]
    for name, factory in [('before',original_namespace['make_exchange_recorder']),('after',new_factory)]:
        persistence.make_exchange_recorder=factory
        handler.rows=[]
        with tempfile.TemporaryDirectory(prefix='examgen-789-') as directory:
            async with exchange_store(Path(directory)) as store:
                started=time.monotonic()
                await delayed_exchange(store)
                rows=await store.exchanges()
                elapsed=time.monotonic()-started
                assert len(rows)==1 and elapsed>=10
                result.append({'revision':name,'elapsed_seconds':round(elapsed,3),'eventual_rows':len(rows),'diagnostics':handler.rows})
    persistence.make_exchange_recorder=new_factory
    return result
print(json.dumps(asyncio.run(run()),indent=2))
