import pytest
from datetime import datetime, timezone

from unified.domain_model import Mission, MissionState, Task, TaskState, AgentType

class TestMissionSummary:
    """Unit tests for Mission.to_summary_dict() method."""
    
    def test_to_summary_dict_exists(self):
        """Mission should have to_summary_dict method."""
        mission = Mission(
            mission_id="test-mission",
            user_request="Test goal",
            state=MissionState.PLANNING
        )
        assert hasattr(mission, 'to_summary_dict')
        assert callable(getattr(mission, 'to_summary_dict'))
    
    def test_to_summary_dict_returns_dict(self):
        """to_summary_dict should return a dictionary."""
        mission = Mission(
            mission_id="test-mission",
            user_request="Test goal",
            state=MissionState.PLANNING
        )
        result = mission.to_summary_dict()
        assert isinstance(result, dict)
    
    def test_to_summary_dict_has_required_fields(self):
        """Summary dict should have required fields."""
        mission = Mission(
            mission_id="test-mission-123",
            user_request="Test goal",
            state=MissionState.EXECUTING
        )
        result = mission.to_summary_dict()
        
        required_fields = ['mission_id', 'state', 'user_request', 'created_at', 'task_count', 'task_counts']
        for field in required_fields:
            assert field in result, f"Missing field: {field}"
    
    def test_to_summary_dict_values(self):
        """Summary dict should have correct values."""
        mission = Mission(
            mission_id="mission-abc",
            user_request="Test goal",
            state=MissionState.EXECUTING
        )
        result = mission.to_summary_dict()
        
        assert result['mission_id'] == "mission-abc"
        assert result['user_request'] == "Test goal"
        assert result['state'] == "EXECUTING"
        assert result['task_count'] == 0
        assert result['task_counts'] == {}
    
    def test_to_summary_dict_created_at(self):
        """Summary dict should include created_at."""
        mission = Mission(
            mission_id="test-mission",
            user_request="Test goal",
            state=MissionState.PLANNING
        )
        result = mission.to_summary_dict()
        
        assert result['created_at'] is not None
        # Should be valid ISO format
        assert 'T' in result['created_at']
