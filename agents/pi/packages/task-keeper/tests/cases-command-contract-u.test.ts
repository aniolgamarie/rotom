import { test, assert } from "./recorded-test.ts";
import { Ajv } from "ajv";
import { kernelTaskParameters } from "../src/contracts/commands.ts";

test("[U SCH-002] model tool parameters reject every independent scope, budget and binding override", () => {
  const schema = kernelTaskParameters(), before = JSON.stringify(schema), validate = new Ajv().compile(schema);
  for (const input of [{action:"fix",goal:"Implement the bounded task"},{action:"inspect",goal:"Inspect evidence"},{action:"status"},{action:"pause",jobId:"job"},{action:"resume",jobId:"job"},{action:"stop",jobId:"job"}]) {
    assert.equal(validate(input),true,JSON.stringify(validate.errors));
    for (const [key,value] of Object.entries({workScope:"fresh",scopeId:"fresh",reset:true,resetBudget:true,budget:{ceiling:1000},route:"unapproved",provider:"other",model:"other",storagePath:"other.db",policyDigest:"forged"})) {
      const rejected = {...input,[key]:value}; assert.equal(validate(rejected),false,key);
      assert.ok(validate.errors?.some(error=>error.keyword==="additionalProperties"&&(error.params as {additionalProperty:string}).additionalProperty===key));
      assert.deepEqual(rejected,{...input,[key]:value});
    }
  }
  assert.equal(validate({action:"reset",jobId:"job"}),false); assert.equal(validate({action:"fix",goal:"x".repeat(65537)}),false);
  assert.equal(validate({action:"resume",jobId:"x".repeat(201)}),false); assert.equal(JSON.stringify(schema),before);
  const independent = kernelTaskParameters(); assert.notEqual(independent,schema); assert.equal(JSON.stringify(independent),before);
});
