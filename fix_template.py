import re

p = 'trading/templates/trading/detalhe_estrutura.html'
with open(p, 'r', encoding='utf-8') as f:
    text = f.read()

# Fix split tags
fixed_text = re.sub(r'\{%\s*else\s*%\}(\s*)-(\s*)\{%\s*\r?\n\s*endif\s*%\}', '{% else %}-{% endif %}', text)
fixed_text = re.sub(r'\{%\s*endif\s*\r?\n\s*%\}(\s*)</h5>', '{% endif %}</h5>', fixed_text)

if fixed_text != text:
    with open(p, 'w', encoding='utf-8') as f:
        f.write(fixed_text)
    print("Tags fixed!")
else:
    print("Pattern not found, nothing changed.")
