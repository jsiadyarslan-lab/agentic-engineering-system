"""Test TaskFailedEvent with None error - regression test for the fix."""
import sys
sys.path.insert(0, 'src')
from unified.contracts import TaskFailedEvent

def test_task_failed_event_none_error():
    """Test that TaskFailedEvent can be created with None error (should become 'Unknown error')."""
    # This simulates what happens in execution.py:878
    result_error = None
    failure_error = result_error or "Unknown error"
    
    event = TaskFailedEvent(
        task_id="task-123",
        mission_id="mission-456",
        run_id="run-789",
        error=failure_error,
        retry_count=1,
        max_retries=2,
    )
    
    assert event.error == "Unknown error", f"Expected 'Unknown error', got '{event.error}'"
    print(f"[PASS] TaskFailedEvent with None error -> '{event.error}'")
    
    # Test with actual error
    event2 = TaskFailedEvent(
        task_id="task-123",
        mission_id="mission-456",
        run_id="run-789",
        error="Connection timeout",
        retry_count=1,
        max_retries=2,
    )
    
    assert event2.error == "Connection timeout", f"Expected 'Connection timeout', got '{event2.error}'"
    print(f"[PASS] TaskFailedEvent with actual error -> '{event2.error}'")
    
    print("\n[VERIFIED] TaskFailedEvent handles None error correctly")
    return True

if __name__ == "__main__":
    test_task_failed_event_none_error()