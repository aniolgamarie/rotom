"""只在已准备的私有快照执行原candidate producer和detached npm开发安装。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import traceback

run=Path(sys.argv[1]).resolve();mode=sys.argv[2];preparation=json.loads((run/'preparation.json').read_text());repository=Path(preparation['repository']);stage=Path(preparation['stage'])
sys.path.insert(0,str(repository/'src'))
from agentcfg.pi_dependencies import PiBackend
from agentcfg.pi_vendor import read_inputs,build_archive,npm_environment
from agentcfg.pi_license_bundle import projection
from agentcfg.deployment import json_bytes
from agentcfg.storage import ensure_private
from agentcfg.process import checked


def write(path,value):
  path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n');path.chmod(0o600)


def registry(lock):
  return projection(lock)


def limit_tree(path):
  total=count=0
  for directory,dirs,files in os.walk(path,followlinks=False):
    assert len(Path(directory).relative_to(path).parts)<=128
    for name in files:
      p=Path(directory)/name
      if p.is_symlink():continue
      total+=p.stat().st_size;count+=1
      assert p.stat().st_size<=64*1024*1024 and total<=512*1024*1024 and count<=65536
  return {'bytes':total,'files':count}

phase='verify-inputs'
try:
  for row in preparation['source_files']:
    p=repository/row['path'];assert p.stat().st_size==row['bytes'] and hashlib.sha256(p.read_bytes()).hexdigest()==row['sha256']
  recipes,inputs=read_inputs(repository,family='modern',current_profiles=())
  assert set(inputs['profiles'])=={'pi-base'} and len(inputs['profiles']['pi-base']['runtime_files'])==120
  assert inputs['capability_bindings']['selections']['pi-base']['state']=='candidate'
  env=npm_environment(Path(preparation['home']))
  for name in ('node','npm'):assert checked([name,'--version'],cwd=repository,env=env)==inputs['toolchains'][name]
  seed_dir=Path(preparation['workspace'])/'seed';ensure_private(seed_dir);ensure_private(seed_dir/'pi-base');ensure_private(seed_dir/'vendor')
  selected={key:inputs['sources'][key] for key in inputs['profiles']['pi-base']['source_ids'] if inputs['sources'][key]['kind'] in ('npm','local','git')};sources={};archives={}
  for key,row in selected.items():
    if row['kind']=='npm':continue
    raw,record=build_archive(repository,recipes['sources'][key]);record['vendor_path']='vendor/'+key+'-'+record['archive_digest']+'.tgz';sources[key]=record;archives[record['vendor_path']]=raw
    p=seed_dir/record['vendor_path'];p.write_bytes(raw);p.chmod(0o600)
  dependencies={row['package']:row['version'] if row['kind']=='npm' else 'file:../'+sources[key]['vendor_path'] for key,row in selected.items()}
  package={'name':'agentcfg-pi-base','version':'1.0.0','private':True,'dependencies':dependencies,'overrides':inputs['profiles']['pi-base']['npm_dependency_overrides']}
  seed_path=repository/inputs['profiles']['pi-base']['npm_resolution_seed']['source'];before=seed_path.read_bytes();old=json.loads(before)
  (seed_dir/'pi-base/package.json').write_bytes(json_bytes(package));(seed_dir/'pi-base/package-lock.json').write_bytes(before)
  phase='local-npm-relock'
  checked(['npm','install','--package-lock-only','--ignore-scripts','--no-audit','--no-fund'],cwd=seed_dir/'pi-base',env=env)
  raw=(seed_dir/'pi-base/package-lock.json').read_bytes();new=json.loads(raw)
  assert len(registry(old))==145 and registry(old)==registry(new)
  assert [(p,r) for p,r in old['packages'].items() if r.get('resolved','').startswith('https://registry.npmjs.org/')] == [(p,r) for p,r in new['packages'].items() if r.get('resolved','').startswith('https://registry.npmjs.org/')]
  changes=[p for p in old['packages'] if old['packages'][p]!=new['packages'].get(p)]
  assert set(changes)<= {''}|{'node_modules/'+row['package'] for row in selected.values() if row['kind'] in ('local','git')}
  # 公共npm重锁输出，不手写local integrity；原load_seed接着完整验证。
  seed_path.write_bytes(raw);doc=repository/'agents/pi/dependencies-modern.json';declaration=json.loads(doc.read_bytes());declaration['profiles']['pi-base']['npm_resolution_seed']['sha256']=hashlib.sha256(raw).hexdigest();doc.write_bytes(json_bytes(declaration))
  write(run/(mode+'-seed-diff.json'),{'changed_package_rows':changes,'registry_nine_field_rows_unchanged':len(registry(old)),'all_registry_fields_ordered_rows_unchanged':True,'old_sha256':hashlib.sha256(before).hexdigest(),'new_sha256':hashlib.sha256(raw).hexdigest(),'local_archives':sources})
  phase='original-resolve-lock'
  backend=PiBackend(profile='pi-base');lock=backend.resolve_lock(repository,current_profiles=());read=backend.read_lock(repository);assert read.identity==lock.identity
  assert read.validated_bindings['pi-base'].state=='candidate'
  spec=importlib.util.spec_from_file_location('own_development',Path(__file__).with_name('development.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  phase='original-development-install'
  result=module.development_steps(repository,stage,read,run,env)
  write(run/'result.json',{**result,'runtime_file_rows':120,'registry_nine_field_rows':145,'snapshot_lock_identity':lock.identity,'profile_slice_identity':lock.metadata['profile_slices']['pi-base']['identity'],'candidate_bindings':lock.metadata['capability_bindings']['selections']['pi-base'],'source_records':lock.metadata['sources'],'stage_inventory':limit_tree(stage),'workspace_inventory':limit_tree(Path(preparation['workspace']))})
  print(json.dumps({'status':'candidate-development-installed','identity':lock.identity,'formal_current':False}))
except BaseException as error:
  write(run/(mode+'-failure.json'),{'phase':phase,'error_type':type(error).__name__,'code':getattr(error,'code',None),'exit_code':getattr(error,'exit_code',None)})
  traceback.print_exc();sys.exit(2)
