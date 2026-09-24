# Pi委托使用固定SDK worker的V2语义事件，不解释原生私密消息正文。
if .schema_version == 2 and (.kind == "ready" or .kind == "checkpoint" or .kind == "completed" or .kind == "failed" or .kind == "canceled" or .kind == "timeout")
then {schema_version,run_id,seq,timestamp,kind,phase,artifact_id}
else error("DELEGATE_EVENT_VERSION") end
