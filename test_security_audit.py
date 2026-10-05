import asyncio
import sys
sys.path.insert(0, 'src')
from unified.operational import OperationalSecurityAgent

async def test():
    agent = OperationalSecurityAgent()
    
    class MockContext:
        def __init__(self):
            self.sandbox_manager = None
            self.sandbox_id = None
            self.evidence_store = None
            self.grants = []
            self.task = type('Task', (), {'context': {}})()
    
    result = await agent._run_security_audit('.', ['sast', 'secrets'], 'medium', [], MockContext())
    print(f'vulnerabilities_found: {result.get("vulnerabilities_found")}')
    print(f'secrets_found: {result.get("secrets_found")}')
    print(f'sast_issues: {result.get("sast_issues")[:3]}')
    print(f'secret_details: {result.get("secret_details")[:3]}')
    if "error" in result:
        print(f'error: {result["error"]}')

asyncio.run(test())