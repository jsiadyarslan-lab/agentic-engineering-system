
import sys
sys.path.insert(0, 'src')
from unified.domain_model import Mission, MissionState, Task, TaskState, AgentType

# Test the method works
m = Mission(mission_id="verify-test", user_request="Verify goal", state=MissionState.EXECUTING)
summary = m.to_summary_dict()
assert summary["mission_id"] == "verify-test"
assert summary["user_request"] == "Verify goal"
assert summary["state"] == "EXECUTING"
assert summary["task_count"] == 0
print("VERIFICATION PASSED")
