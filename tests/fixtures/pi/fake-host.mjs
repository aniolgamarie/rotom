// 不默认返回成功；调用方必须安排每个宿主结果。
export class FakeHost {
  constructor() { this.responses = []; this.calls = []; }
  queue(response) { this.responses.push(structuredClone(response)); }
  async invoke(request) {
    if (!this.responses.length) throw new Error("fake host requires a queued result");
    this.calls.push(structuredClone(request));
    return this.responses.shift();
  }
}
