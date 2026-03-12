import os
import django
from django.conf import settings
from django.template import Template, Context, Engine

# Minimal Django setup
if not settings.configured:
    settings.configure(
        TEMPLATES=[{
            'BACKEND': 'django.template.backends.django.DjangoTemplates',
            'DIRS': [os.path.join(os.getcwd(), 'trading', 'templates')],
            'APP_DIRS': True,
        }],
        INSTALLED_APPS=['django.contrib.humanize'],
    )
    django.setup()

template_path = 'trading/templates/trading/detalhe_estrutura.html'
with open(template_path, 'r', encoding='utf-8') as f:
    template_content = f.read()

try:
    # Try to compile the template
    Template(template_content)
    print("Template compiled successfully!")
except Exception as e:
    print(f"Template compilation failed: {e}")
    
    import re
    ifs = len(re.findall(r'{%\s*if', template_content))
    elifs = len(re.findall(r'{%\s*elif', template_content))
    elses = len(re.findall(r'{%\s*else', template_content))
    endifs = len(re.findall(r'{%\s*endif', template_content))
    fors = len(re.findall(r'{%\s*for', template_content))
    endfors = len(re.findall(r'{%\s*endfor', template_content))
    blocks = len(re.findall(r'{%\s*block', template_content))
    endblocks = len(re.findall(r'{%\s*endblock', template_content))
    
    print(f"Stats:")
    print(f"  IF: {ifs}, ELIF: {elifs}, ELSE: {elses}, ENDIF: {endifs}")
    print(f"  FOR: {fors}, ENDFOR: {endfors}")
    print(f"  BLOCK: {blocks}, ENDBLOCK: {endblocks}")
    
    if ifs > endifs:
        print(f"MISSING {ifs - endifs} endif tag(s)!")
    elif endifs > ifs:
        print(f"EXTRA {endifs - ifs} endif tag(s)!")

    if fors > endfors:
        print(f"MISSING {fors - endfors} endfor tag(s)!")
    elif endfors > fors:
        print(f"EXTRA {endfors - fors} endfor tag(s)!")

    if blocks > endblocks:
        print(f"MISSING {blocks - endblocks} endblock tag(s)!")
    elif endblocks > blocks:
        print(f"EXTRA {endblocks - blocks} endblock tag(s)!")

    import traceback
    traceback.print_exc()
