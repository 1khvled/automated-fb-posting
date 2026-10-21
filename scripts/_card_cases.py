import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath("post_bot.py")), "scripts"))
import card_design as cd

CASES = [
    ("ethan", "stocks", """BREAKING: President Trump is set to highlight overseas CRYPTO abuses at an upcoming White House event.

The administration is turning its focus to international digital asset illicit activity and regulatory enforcement."""),
    ("ethan", "crypto", """JUST IN: JPMorgan just DOUBLED its SpaceX ($SPCX) price target to $500.

Old target: $240
New target: $500
Increase: +108%"""),
    ("market", "crypto", """💬 "المستثمرين بيتاكل حقهم بره".. ترامب بيفتح ملف تجاوزات الكريبتو في البيت الأبيض

🏛️ ترامب هيجمع القيادات في البيت الأبيض عشان يناقش tema التشفير."""),
    ("ethan", "ai", """OpenAI models helped researchers discover critical security flaws in popular open-source projects.

The models found 14 vulnerabilities that human reviewers had missed."""),
]

for br, cat, txt in CASES:
    b = cd.design_card(txt, [cat], "Reuters", br)
    fn = f"_t_{br}_{cat}.jpg"
    open(fn, "wb").write(b)
    print("wrote", fn, len(b))
