import json
from pathlib import Path
from types import SimpleNamespace
import sys
run=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(mode=0o700)
preparation=json.loads((run/'preparation.json').read_text());repository=Path(preparation['repository']);sys.path.insert(0,str(repository/'src'))
from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi import PiAdapter
from agentcfg.config import SourceInputs,AdapterSources,LocalConfig,load_sources,resolve_config
adapter=PiAdapter(repository);schemas=adapter.schemas();inputs=SourceInputs(tuple(sorted((repository/'shared').glob('*.toml')))+(repository/'agents/pi/content.toml',),tuple(sorted((repository/'profiles').glob('pi-*.toml'))),{'pi':AdapterSources(*(repository/'agents/pi'/f'{kind}.toml' for kind in ('agent','bindings','plugins')))},repository/'shared/defaults/models.toml')
resolved=resolve_config(load_sources(inputs,adapter_schemas=schemas),LocalConfig({'schema_version':1,'machine':{'id':'candidate-probe'}}),profile_id='pi-base',adapter_schemas=schemas)
backend=PiBackend(profile='pi-base');lock=backend.read_lock(repository)
result={'profile_plugins':resolved.data['profile']['plugins'],'piece_capability_ids':lock.metadata['profile_slices']['pi-base']['capability_ids'],'state':lock.validated_bindings['pi-base'].state,'uses_original_resolved_config':True,'has_resolved_not_omitted':True}
try:
 result['runtime_identity']=backend.runtime_identity(SimpleNamespace(profile='pi-base',repository=repository,resolved=resolved),lock)
except Exception as error:
 result.update(error_type=type(error).__name__,code=getattr(error,'code',None),exit_code=getattr(error,'exit_code',None));(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');raise
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
