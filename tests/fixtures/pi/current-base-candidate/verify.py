"""对原生成/开发安装的独立只读复核；不重复npm，不运行SDK/host。"""
import hashlib
import json
import os
from pathlib import Path
import sys

run=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(mode=0o700)
preparation=json.loads((run/'preparation.json').read_text());repository=Path(preparation['repository']);stage=Path(preparation['stage'])
sys.path.insert(0,str(repository/'src'))
from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi_runtime_files import validate_files,verify_sources
from agentcfg.pi_license_bundle import validate_source,validate_installed,projection
from agentcfg.workspace import load_workspace
from agentcfg.config import load_sources,SourceInputs,AdapterSources,resolve_config,LocalConfig
from agentcfg.pi import PiAdapter
from agentcfg.pi_capabilities import source_identity
from agentcfg.schema import AdapterSchemas


def inventory(path,tool=None):
  total=count=0;rows=[]
  for directory,dirs,files in os.walk(path,followlinks=False):
    assert len(Path(directory).relative_to(path).parts)<=128
    for name in files:
      p=Path(directory)/name
      if p.is_symlink():continue
      size=p.stat().st_size
      if tool and p==tool:
        assert size==122466960 and size<=128*1024*1024 and hashlib.sha256(p.read_bytes()).hexdigest()=='e237a2839d0cbdc9a9a2adda1a184afc0f5b20306ffbe923af5686550472d8a8'
      else:assert size<=64*1024*1024
      total+=size;count+=1;assert total<=512*1024*1024 and count<=65536
      rows.append({'path':str(p.relative_to(path)),'bytes':size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
  return {'bytes':total,'files':count,'rows':rows}

lock=PiBackend(profile='pi-base').read_lock(repository);piece=lock.metadata['profile_slices']['pi-base'];resolution=json.loads(lock.pairs['pi-base'][1]);source=validate_source(repository,piece,resolution,allow_unresolved=False);installed=validate_installed(stage,piece,resolution)
assert lock.validated_bindings['pi-base'].state=='candidate';assert len(piece['runtime_files'])==120
validate_files(stage,piece['runtime_files'],generated=());verify_sources(repository,piece['runtime_files'])
old=json.loads((Path(__file__).resolve().parents[4]/'agents/pi/build/resolutions/pi-base.package-lock.json').read_bytes());assert projection(old)==projection(resolution) and len(projection(old))==145
# 原正常catalog/resolve/render，纯配置视图；不调用runtime/sync/seal/activate。
adapter=PiAdapter(repository);schemas=adapter.schemas();inputs=SourceInputs(tuple(sorted((repository/'shared').glob('*.toml')))+(repository/'agents/pi/content.toml',),tuple(sorted((repository/'profiles').glob('pi-*.toml'))),{'pi':AdapterSources(*(repository/'agents/pi'/f'{kind}.toml' for kind in ('agent','bindings','plugins')))},repository/'shared/defaults/models.toml')
# 全局默认模型声明并非recipe_digest的资源目录，但正常resolve必须使用原固定文件。
resolved=resolve_config(load_sources(inputs,adapter_schemas=schemas),LocalConfig({'schema_version':1,'machine':{'id':'candidate-probe'}}),profile_id='pi-base',adapter_schemas=schemas)
artifacts=adapter.render(resolved.data);manifest=json.loads(next(row.content for row in artifacts if row.target.path.endswith('manifest.json')))
assert manifest['profile_id']=='pi-base' and set(manifest['plugins'])=={'pi-todo','loop-guard','colorful-footer'}
assert 'subagents' not in manifest['plugins'] and not resolved.data['profile'].get('mcp')
bindings=lock.metadata['capability_bindings'];providers=bindings['providers'];selected=bindings['selections']['pi-base']['bindings'];assert len(selected)==6
facts=[]
for row in selected:
 p=providers[row['provider_id']];assert source_identity(lock.metadata['sources'][p['source_id']])==p['source_identity']
 for support in p.get('support_sources',[]):assert source_identity(lock.metadata['sources'][support['source_id']])==support['source_identity']
 facts.append({'capability_id':row['capability_id'],'provider_id':row['provider_id'],'source_identity':p['source_identity'],'source_id':p['source_id'],'support_sources':p.get('support_sources',[])})
result={'status':'candidate-development-installed-verified','identity':lock.identity,'profile_slice_identity':piece['identity'],'state':'candidate','runtime_file_rows':120,'registry_nine_fields_unchanged':145,'source_license_rows':len(source['packages']),'installed_license_rows':len(installed['packages']),'capability_bindings':facts,'render_plugins':manifest['plugins'],'render_plugin_capabilities':manifest['plugin_capabilities'],'formal_current':False,'npm_or_sdk_repeated':False}
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
(out/'installed-inventory.json').write_text(json.dumps(inventory(stage),indent=2)+'\n');(out/'workspace-inventory.json').write_text(json.dumps(inventory(Path(preparation['workspace']),Path(preparation['bindir'])/'node'),indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('capability_bindings','render_plugin_capabilities')}))
