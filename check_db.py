import sqlite3
conn = sqlite3.connect('runtime/agent_hub_v2.db')
cursor = conn.cursor()

# List all tables
cursor.execute('SELECT name FROM sqlite_master WHERE type="table"')
tables = cursor.fetchall()
print('TABLES:')
for t in tables:
    print(t[0])

print()

# Check providers
cursor.execute('SELECT * FROM providers')
providers = cursor.fetchall()
print('PROVIDERS:')
for p in providers:
    print(p)

print()

# Check provider_configurations
cursor.execute('SELECT * FROM provider_configurations')
configs = cursor.fetchall()
print('CONFIGURATIONS:')
for c in configs:
    print(c)

print()

# Check role_provider_mappings
cursor.execute('SELECT * FROM role_provider_mappings')
mappings = cursor.fetchall()
print('ROLE MAPPINGS:')
for m in mappings:
    print(m)