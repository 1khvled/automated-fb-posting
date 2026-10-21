"""Give the English repo the same writer chain as the Arabic one.

The English repo had only Gemini + OpenRouter. The Arabic repo also had
Groq and NVIDIA. When Gemini's quota ran out on 21 Oct 2026, the English
page had a two-model chain and the Arabic page had four - and the
English one published an English fallback while the Arabic one was
protected by the language guard. Equal chains, equal protection.

Groq is also the model that WORKS when Gemini is quota'd, once the token
budget is big enough: gpt-oss are reasoning models and max_tokens=1000
truncated them before they emitted anything.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(sys.argv[1])
bot = REPO / "post_bot.py"
src = bot.read_text(encoding="utf-8")
changed = []

GROQ_FN = '''
def gen_groq(model: str, system: str, user: str) -> str:
    """Groq free tier. The gpt-oss models are REASONING models: they spend
    the token budget thinking before they emit the post, so the budget has
    to be big (4000) and an answer truncated with an empty body is retried
    with a much bigger one (12000). Without this the model looked broken
    when it was only truncated."""
    import json as _json
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("No GROQ_API_KEY set")

    def call(mx):
        return requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "max_tokens": mx, "temperature": 0.5,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=120).json()

    d = call(4000)
    if d.get("error"):
        raise RuntimeError(f"Groq {model} HTTP error: {_json.dumps(d)[:200]}")
    try:
        text = (d["choices"][0]["message"].get("content") or "").strip()
    except Exception:
        text = ""
    if text:
        return text
    if d["choices"][0].get("finish_reason") == "length":
        d2 = call(12000)
        try:
            text = (d2["choices"][0]["message"].get("content") or "").strip()
        except Exception:
            text = ""
        if text:
            return text
    raise RuntimeError(
        f"Groq {model} returned no text "
        f"(finish_reason={d['choices'][0].get('finish_reason')})")


'''

if "def gen_groq(" not in src:
    # put it right before gen_openrouter so the order reads naturally
    anchor = "def gen_openrouter("
    if anchor in src:
        src = src.replace(anchor, GROQ_FN.lstrip("\n") + anchor, 1)
        changed.append("gen_groq added")
    else:
        print("  !! gen_openrouter anchor not found")

# put Groq in the chain, before the OpenRouter fallback
old_chain = """    if os.getenv("OPENROUTER_API_KEY", "").strip():
        chain += [("openrouter", m) for m in
                  _model_list("OPENROUTER_", "MODEL", OPENROUTER_MODELS_DEFAULT)]"""
new_chain = """    if os.getenv("GROQ_API_KEY", "").strip():
        chain += [("groq", m) for m in
                  _model_list("GROQ_", "MODEL", GROQ_MODELS_DEFAULT)]
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        chain += [("openrouter", m) for m in
                  _model_list("OPENROUTER_", "MODEL", OPENROUTER_MODELS_DEFAULT)]"""
if old_chain in src and "GROQ_API_KEY" not in src:
    src = src.replace(old_chain, new_chain, 1)
    changed.append("Groq added to the chain")

# the dispatcher needs a groq entry
if '"groq": gen_groq' not in src:
    src = src.replace('_GEN = {"gemini": gen_gemini, "openrouter": gen_openrouter',
                      '_GEN = {"gemini": gen_gemini, "openrouter": gen_openrouter,\n'
                      '            "groq": gen_groq', 1)
    changed.append("groq added to the dispatcher")

bot.write_text(src, encoding="utf-8")

# ---- the Groq key + model list, from the Arabic repo's .env
src_env = Path(r"C:\Users\Abdelli\Documents\soq-alyoum-fb-bot\.env")
if src_env.exists():
    txt = src_env.read_text(encoding="utf-8")
    m = re.search(r"(?m)^GROQ_API_KEY=(.*)$", txt)
    if m and m.group(1).strip():
        dst = REPO / ".env"
        t2 = dst.read_text(encoding="utf-8")
        if "GROQ_API_KEY" not in t2:
            t2 = t2.rstrip("\n") + "\nGROQ_API_KEY=" + m.group(1).strip() + "\n"
            dst.write_text(t2, encoding="utf-8")
            changed.append("GROQ_API_KEY copied into .env")
        r = subprocess.run(["gh", "secret", "set", "GROQ_API_KEY", "--repo",
                            "1khvled/automated-fb-posting", "--body",
                            m.group(1).strip()], capture_output=True, text=True)
        if r.returncode == 0:
            changed.append("GROQ_API_KEY set as a GitHub secret")

print(f"[{REPO.name}]")
for c in changed:
    print("  -", c)
if not changed:
    print("  (nothing to do)")
