"""更新获准的一生产源，原producer重派生candidate及完整launcher；不activate/seal。"""
import json,hashlib,shutil,sys,os,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[4];base=root/'.cache/pi-two-profiles/run-20261004/base-current-candidate-development-review01';run=base/'complete02';run.mkdir(mode=0o700)
private=Path(tempfile.mkdtemp(prefix='pi-base-complete-',dir='/tmp'));private.chmod(0o700);source=private/'source-snapshot';shutil.copytree(base/'final-stable/source-snapshot',source,symlinks=True);stage=private/'candidate-with-launcher';shutil.copytree(base/'final-stable/developer-installed-tree',stage,symlinks=True)
(run/'paths.json').write_text(json.dumps({'source':str(source),'stage':str(stage),'private':str(private)})+'\n')
current=root/'src/agentcfg/pi_dependencies.py';shutil.copyfile(current,source/'src/agentcfg/pi_dependencies.py');(source/'src/agentcfg/pi_dependencies.py').chmod(0o600)
assert hashlib.sha256(current.read_bytes()).hexdigest()==hashlib.sha256((source/'src/agentcfg/pi_dependencies.py').read_bytes()).hexdigest()
sys.path.insert(0,str(source/'src'))
from agentcfg.pi_dependencies import PiBackend,platform_id
from agentcfg.pi_vendor import install_launcher
from agentcfg.pi_assets import install_assets
from agentcfg.pi_runtime_files import validate_files
from agentcfg.pi_modern_launcher import validate_profile
from agentcfg.config import SourceInputs,AdapterSources,LocalConfig,load_sources,resolve_config
from agentcfg.pi import PiAdapter
from agentcfg.workspace import Workspace
from agentcfg.secrets import SecretStore
from agentcfg.pi_license_bundle import validate_source,validate_installed,projection
from agentcfg.pi_capabilities import source_identity
phase='original-resolve'
try:
 backend=PiBackend(profile='pi-base');lock=backend.resolve_lock(source,current_profiles=());read=backend.read_lock(source);assert lock.identity==read.identity;piece=lock.metadata['profile_slices']['pi-base']
 old=json.loads((base/'final-stable/source-snapshot/locks/pi-modern/manifest.json').read_bytes());old_piece=old['profile_slices']['pi-base']
 assert (source/'locks/pi-modern'/piece['package_path']).read_bytes()==(base/'final-stable/source-snapshot/locks/pi-modern'/old_piece['package_path']).read_bytes()
 assert (source/'locks/pi-modern'/piece['lock_path']).read_bytes()==(base/'final-stable/source-snapshot/locks/pi-modern'/old_piece['lock_path']).read_bytes()
 assert piece['package_path']==old_piece['package_path']
 adapter=PiAdapter(source);schemas=adapter.schemas();inputs=SourceInputs(tuple(sorted((source/'shared').glob('*.toml')))+(source/'agents/pi/content.toml',),tuple(sorted((source/'profiles').glob('pi-*.toml'))),{'pi':AdapterSources(*(source/'agents/pi'/f'{kind}.toml' for kind in ('agent','bindings','plugins')))},source/'shared/defaults/models.toml')
 resolved=resolve_config(load_sources(inputs,adapter_schemas=schemas),LocalConfig({'schema_version':1,'machine':{'id':'candidate-probe'}}),profile_id='pi-base',adapter_schemas=schemas)
 workspace=Workspace(source,run/'synthetic-local.toml',resolved,adapter,schemas,SecretStore({}))
 phase='original-runtime-identity';identity=backend.runtime_identity(workspace,read)
 phase='original-fixed-assets';install_assets(source,stage,piece,lock.metadata,platform_id(),lock_family='modern')
 phase='original-install-launcher';install_launcher(source,stage,piece,lock.metadata,runtime_identity=identity)
 phase='original-complete-validation';validate_files(stage,piece['runtime_files']);validate_profile(stage,piece,identity=identity,lock_identity=lock.identity,toolchains=lock.metadata['toolchains'],profile_id='pi-base')
 resolution=json.loads(lock.pairs['pi-base'][1]);src=validate_source(source,piece,resolution,allow_unresolved=False);installed=validate_installed(stage,piece,resolution)
 assert len(projection(resolution))==145 and read.validated_bindings['pi-base'].state=='candidate'
 assert all(not (stage/name).exists() for name in ('.agentcfg-ready','.agentcfg-receipt.json','current'))
 facts=[]
 for row in lock.metadata['capability_bindings']['selections']['pi-base']['bindings']:
  provider=lock.metadata['capability_bindings']['providers'][row['provider_id']]
  assert source_identity(lock.metadata['sources'][provider['source_id']])==provider['source_identity']
  for support in provider.get('support_sources',[]):assert source_identity(lock.metadata['sources'][support['source_id']])==support['source_identity']
  facts.append(provider)
 result={'status':'candidate-complete-launcher-generated','lock_identity':lock.identity,'slice_identity':piece['identity'],'runtime_identity':identity,'state':'candidate','runtime_file_rows':len(piece['runtime_files']),'installed_license_rows':len(installed['packages']),'registry_rows':145,'package_pair_unchanged_from_detached':True,'updated_source':{'path':'src/agentcfg/pi_dependencies.py','bytes':current.stat().st_size,'sha256':hashlib.sha256(current.read_bytes()).hexdigest()},'capability_bindings':facts,'generated_profile':json.loads((stage/'runtime/profile.json').read_bytes()),'generated_commands':json.loads((stage/'runtime/commands.json').read_bytes()),'sync_seal_activate_current_called':False}
 (run/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ('capability_bindings','generated_profile','generated_commands')}))
except BaseException as error:
 (run/'failure.json').write_text(json.dumps({'phase':phase,'error_type':type(error).__name__,'code':getattr(error,'code',None),'exit_code':getattr(error,'exit_code',None)},indent=2)+'\n');raise
