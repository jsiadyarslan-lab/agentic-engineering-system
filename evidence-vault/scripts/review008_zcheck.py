import re, subprocess, sys
files = subprocess.run(['git','-C','/home/z/my-project/ui007','ls-tree','-r','--name-only','56e42ba','--','src/ui/'],capture_output=True,text=True).stdout.split()
css = [f for f in files if f.endswith('.css')]
total_literal = 0
for f in sorted(css):
    text = subprocess.run(['git','-C','/home/z/my-project/ui007','show',f'56e42ba:{f}'],capture_output=True,text=True).stdout
    stripped = re.sub(r'/\*.*?\*/', '', text, flags=re.S)  # strip comments
    # find z-index declarations
    for m in re.finditer(r'z-index\s*:\s*([^;]+);', stripped):
        val = m.group(1).strip()
        if not val.startswith('var('):
            total_literal += 1
            print(f"LITERAL {f}: z-index: {val}")
print(f"CSS files checked: {len(css)}")
print(f"Total literal z-index declarations (after comment strip): {total_literal}")
# also count z-index var usages
var_count = 0
for f in sorted(css):
    text = subprocess.run(['git','-C','/home/z/my-project/ui007','show',f'56e42ba:{f}'],capture_output=True,text=True).stdout
    stripped = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    var_count += len(re.findall(r'z-index\s*:\s*var\(', stripped))
print(f"z-index: var(--...) usages: {var_count}")
