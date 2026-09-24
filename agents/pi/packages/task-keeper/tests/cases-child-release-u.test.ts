import { test, assert, evidence } from "./recorded-test.ts";
import { childTerminationConfirmed } from "../src/adapters/child-contract.ts";
const process = {pid:42,bootId:"boot",startTicks:"10",pidNamespace:"pid:[42]"};

test("[U T42 TK14] expired ownership or a completed native result cannot release an unresolved external writer", () => {
  for (const id of ["T42", "TK14"]) evidence(id, () => {
    const cases: Array<[boolean|null,string[]|undefined,boolean]> = [
      [false,undefined,false],[false,[],false],[false,["find-running"],false],[false,["grep-running"],false],
      [null,undefined,false],[null,[],false],[null,["find-running"],false],[null,["grep-running"],false],
      [true,undefined,false],[true,[],true],[true,["find-running"],false],[true,["grep-running"],false],
    ];
    for (const [processStopped,externalWork,expected] of cases) {
      const observation = {process,externalWork,ready:true,settled:true,stopReason:"stop",leaseExpired:true,ownerActive:false};
      const before=structuredClone(observation);
      assert.equal(childTerminationConfirmed(observation,processStopped),expected);
      assert.deepEqual(observation,before);
    }
    assert.equal(childTerminationConfirmed({process:null,externalWork:[]},true),false);
    assert.equal(childTerminationConfirmed({process,externalWork:[]},null),false);
    assert.equal(childTerminationConfirmed({process,externalWork:["writer"]},true),false);
    assert.equal(childTerminationConfirmed({process,externalWork:[]},true),true);
  });
});
