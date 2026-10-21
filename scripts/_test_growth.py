import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath("post_bot.py")), "scripts"))
import growth
import no_llm

print("growth OK:", hasattr(growth, "after_publish"),
      "| reply_backlog:", hasattr(growth, "reply_backlog"))
print("no_llm OK:", hasattr(no_llm, "build_post"))

cand = {
    "title": "JPMorgan doubles SpaceX target to $500",
    "summary": "The bank raised its target from $240 to $500, an increase of 108%.",
    "keywords": ["stocks", "ai"],
    "feed": "X @WatcherGuru",
}
print("\n--- no-LLM fallback post (EN) ---")
print(no_llm.build_post(cand, "en"))

cand_ar = {
    "title": "JPMorgan doubles SpaceX target to $500",
    "summary": "The bank raised its target from $240 to $500.",
    "keywords": ["stocks"],
    "feed": "Reuters",
}
print("\n--- no-LLM fallback post (AR) ---")
print(no_llm.build_post(cand_ar, "ar"))

print("\n--- share kit (EN) ---")
v = growth.share_variants(
    "JPMorgan doubles SpaceX target to $500",
    "JUST IN: JPMorgan just DOUBLED its SpaceX price target to $500.\n"
    "Old target: $240\nNew target: $500\nIncrease: +108%",
    ["stocks"], "Full breakdown on the page.")
for x in v:
    print(f"\n[{x['angle']}] -> {x['group_type']}")
    print(x["text"][:200])
