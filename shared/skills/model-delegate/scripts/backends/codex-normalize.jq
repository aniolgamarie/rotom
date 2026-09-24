# 离线公开进度投影；正式执行由固定版本 Python parser 核验顺序和终态。
if .type == "thread.started" then {kind:"ready",phase:"started"}
elif .type == "turn.completed" then {kind:"completed",phase:"turn-completed"}
elif .type == "turn.failed" or .type == "error" then {kind:"failed",phase:"terminated"}
elif .type == "item.completed" and (.item.type == "command_execution" or .item.type == "file_change" or .item.type == "web_search") then {kind:"checkpoint",phase:"tool-completed"}
else empty end
