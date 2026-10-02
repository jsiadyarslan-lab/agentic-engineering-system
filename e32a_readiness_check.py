"""
E32A - Safe Readiness Check (No Network)
Checks provider readiness without making any network model calls
"""

import sys
sys.path.insert(0, 'src')

import json
import sqlite3
from pathlib import Path

def safe_readiness_check():
    results = {}
    
    # 1. Check database provider registry
    conn = sqlite3.connect('runtime/agent_hub_v2.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT id, name, type, auth_type, enabled FROM providers')
    providers = cursor.fetchall()
    
    cursor.execute('SELECT id, provider_id, name, base_url, default_model, enabled FROM provider_configurations')
    configs = cursor.fetchall()
    
    cursor.execute('SELECT role, provider, configuration, model FROM role_provider_mappings')
    mappings = cursor.fetchall()
    
    results["provider_registry"] = {
        "providers": [
            {"id": p[0], "name": p[1], "type": p[2], "auth_type": p[3], "enabled": bool(p[4])}
            for p in providers
        ],
        "configurations": [
            {"id": c[0], "provider_id": c[1], "name": c[2], "base_url": c[3], "default_model": c[4], "enabled": bool(c[5])}
            for c in configs
        ],
        "role_mappings": [
            {"role": m[0], "provider": m[1], "config": m[2], "model": m[3]}
            for m in mappings
        ]
    }
    
    # 2. Check secrets store
    from src.secrets_store.store import stored_providers, has_key, mask
    secret_providers = stored_providers()
    results["secrets_store"] = {
        "providers_with_keys": secret_providers,
        "key_status": {
            p: {"has_key": has_key(p), "masked": mask("****") if has_key(p) else "N/A"}
            for p in ["nvidia", "openai_compatible", "anthropic", "google", "zai_internal"]
        }
    }
    
    # 3. Provider readiness assessment (NO NETWORK CALLS)
    provider_status = {}
    for p in providers:
        p_name = p[1]
        p_type = p[2]
        p_auth = p[3]
        
        # Check config
        p_configs = [c for c in configs if c[1] == p[0] and c[5]]
        # Check roles
        p_roles = [m[0] for m in mappings if m[1] == p_name]
        # Check secret
        secret_present = has_key(p_name)
        
        if not p_configs:
            state = "PROVIDER_UNCONFIGURED"
        elif not secret_present and p_auth != "config_file":
            state = "PROVIDER_CONFIGURED"
        else:
            state = "PROVIDER_CREDENTIALED"
        
        provider_status[p_name] = {
            "provider_type": p_type,
            "auth_type": p_auth,
            "configurations": len(p_configs),
            "roles_mapped": p_roles,
            "credential_present": secret_present,
            "readiness_state": state,
            "network_probe": "NOT EXECUTED (E32A scope)",
            "model_call": "NOT EXECUTED (E32A scope)"
        }
    
    results["readiness_assessment"] = provider_status
    
    # 4. Gateway readiness (config only, no initialization)
    from src.unified.llm_gateway import GatewayConfig
    gateway_config = GatewayConfig()
    results["gateway_config"] = {
        "provider_type": gateway_config.provider_type,
        "model": gateway_config.model,
        "api_key_configured": gateway_config.api_key is not None,
        "base_url": gateway_config.base_url,
        "note": "Gateway not initialized - no network calls"
    }
    
    # 5. Providers.py auto-detect check (no network)
    from src.llm.providers import ProviderType
    env_check = {}
    for pt in ProviderType:
        env_var = f"{pt.value.upper()}_API_KEY"
        import os
        env_check[env_var] = "PRESENT" if os.getenv(env_var) else "ABSENT"
    results["env_auto_detect"] = env_check
    
    # Save results
    with open('docs/evidence/e32a/E32A_SAFE_READINESS_CHECK.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    return results

if __name__ == "__main__":
    print("Running safe readiness check (NO NETWORK CALLS)...")
    results = safe_readiness_check()
    
    print("\n=== PROVIDER REGISTRY ===")
    for p in results["provider_registry"]["providers"]:
        print(f"  {p['name']} (type={p['type']}, auth={p['auth_type']}, enabled={p['enabled']})")
    
    print("\n=== SECRETS STORE ===")
    print(f"  Providers with keys: {results['secrets_store']['providers_with_keys']}")
    
    print("\n=== READINESS ASSESSMENT ===")
    for name, status in results["readiness_assessment"].items():
        print(f"  {name}: {status['readiness_state']} (cred={status['credential_present']}, roles={status['roles_mapped']})")
    
    print("\n=== GATEWAY CONFIG ===")
    print(f"  provider_type: {results['gateway_config']['provider_type']}")
    print(f"  model: {results['gateway_config']['model']}")
    print(f"  api_key_configured: {results['gateway_config']['api_key_configured']}")
    
    print("\n=== ENV AUTO-DETECT ===")
    for k, v in results["env_auto_detect"].items():
        print(f"  {k}: {v}")
    
    print("\nResults saved to docs/evidence/e32a/E32A_SAFE_READINESS_CHECK.json")