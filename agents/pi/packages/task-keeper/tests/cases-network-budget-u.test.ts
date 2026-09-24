import { test, assert } from "./recorded-test.ts";
import { networkFailureBudget } from "../src/reliability/network-budget.ts";
import { configured } from "./fixtures/config.ts";

test("[U REC-005] unlimited quota waiting does not make the network failure budget unlimited", () => {
  const config=configured();assert.equal(config.recovery.maxWaitMs,null);assert.equal(config.recovery.maxNetworkAttempts,2);
  assert.deepEqual(networkFailureBudget(0,config.recovery.maxNetworkAttempts),{attempts:1,exhausted:false});
  assert.deepEqual(networkFailureBudget(1,config.recovery.maxNetworkAttempts),{attempts:2,exhausted:false});
  assert.deepEqual(networkFailureBudget(2,config.recovery.maxNetworkAttempts),{attempts:3,exhausted:true});
  assert.deepEqual(networkFailureBudget(0,0),{attempts:1,exhausted:true});
  assert.deepEqual(networkFailureBudget(0,1),{attempts:1,exhausted:false});
  assert.deepEqual(networkFailureBudget(1,1),{attempts:2,exhausted:true});
  assert.equal(config.recovery.maxWaitMs,null);assert.equal(config.recovery.maxNetworkAttempts,2);
});
