import { test, assert, evidence } from "./recorded-test.ts";
import { evaluateVerification, type VerificationFacts } from "../src/verification/runner.ts";
const build = {kind:"build" as const,parser:"exit-code" as const,minimumTests:1};
const complete: VerificationFacts = {stdout:"",truncated:false,timedOut:false,cancelled:false,spawnFailed:false,exitCode:0,
  terminationConfirmed:true,admissionError:null,lingering:0,launcherExitCode:0,started:true,terminalObserved:true};

test("[U EXE-013 T16] silence alone is neither failure nor completion; timeout still requires termination evidence", () => {
  const cases: Array<[Partial<VerificationFacts>,string,string]> = [
    [{terminationConfirmed:false,terminalObserved:false,exitCode:null},"unknown","external_processes_not_confirmed_stopped"],
    [{terminationConfirmed:false,terminalObserved:false,exitCode:null,stdout:"still working"},"unknown","external_processes_not_confirmed_stopped"],
    [{terminationConfirmed:false,terminalObserved:false,exitCode:null,timedOut:true},"unknown","external_processes_not_confirmed_stopped"],
    [{timedOut:true,exitCode:null},"failed","timeout"],
    [{terminalObserved:false},"unknown","command_terminal_not_observed"],
    [{},"passed","verified"],
  ];
  for (const id of ["EXE-013", "T16"]) evidence(id, () => {
    for (const [patch,status,reason] of cases) {const input={...complete,...patch},before=structuredClone(input),result=evaluateVerification(build,input);
      assert.equal(result.status,status);assert.equal(result.reason,reason);assert.equal(result.counts,null);assert.deepEqual(input,before);}
    const tests=evaluateVerification({...build,kind:"tests",parser:"json"},complete);
    assert.equal(tests.status,"unknown");assert.equal(tests.reason,"test_count_unknown");
  });
});
