import asyncio, sys, hashlib
from pathlib import Path
sys.path.insert(0, '.')
from src.factory.tools import ReadFileTool, ReadFileInput

async def main():
    tool = ReadFileTool()
    root = Path('.').resolve()

    # اختبار 1: اقرأ pyproject.toml
    args = ReadFileInput(path="pyproject.toml")
    result = await tool.run(args, workspace_root=root)
    print("ok:", result.ok)
    print("error:", result.error)
    print("output_len:", len(result.output))
    print("hash_len:", len(result.evidence_hash))
    expected = hashlib.sha256(result.output.encode()).hexdigest()
    print("hash_matches:", result.evidence_hash == expected)

    # اختبار 2: ملف غير موجود
    r2 = await tool.run(ReadFileInput(path="does_not_exist.xyz"), workspace_root=root)
    print("missing_ok:", r2.ok, "| error:", r2.error)

    # اختبار 3: محاولة escape
    r3 = await tool.run(ReadFileInput(path="../../etc/passwd"), workspace_root=root)
    print("escape_ok:", r3.ok, "| error:", r3.error)

asyncio.run(main())
