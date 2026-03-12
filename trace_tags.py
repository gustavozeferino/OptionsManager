import re

template_path = 'trading/templates/trading/detalhe_estrutura.html'
with open(template_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

stack = []
for i, line in enumerate(lines, start=1):
    # Find all if/endif/for/endfor/block/endblock tags on this line
    tags = re.findall(r'{%\s*(if|endif|elif|else|for|empty|endfor|block|endblock)', line)
    for tag in tags:
        if tag in ['if', 'for', 'block']:
            stack.append((tag, i))
            print(f"L{i}: OPEN {tag}")
        elif tag == 'endif':
            if not stack or stack[-1][0] != 'if':
                print(f"L{i}: ERROR! Found endif but stack is {stack}")
            else:
                stack.pop()
                print(f"L{i}: CLOSE if")
        elif tag == 'endfor':
            if not stack or stack[-1][0] != 'for':
                print(f"L{i}: ERROR! Found endfor but stack is {stack}")
            else:
                stack.pop()
                print(f"L{i}: CLOSE for")
        elif tag == 'endblock':
            if not stack or stack[-1][0] != 'block':
                print(f"L{i}: ERROR! Found endblock but stack is {stack}")
            else:
                stack.pop()
                print(f"L{i}: CLOSE block")

if stack:
    print(f"ERROR! Stack not empty at end: {stack}")
else:
    print("All tags balanced!")
