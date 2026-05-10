import re

with open("agent.py") as f:
    code = f.read()

old = '''    try:
        result = json.loads(raw)
        # Validate schema
        assert "reply" in result
        assert "recommendations" in result
        assert "end_of_conversation" in result
        assert isinstance(result["recommendations"], list)
        # Validate each recommendation has required fields
        valid_recs = []
        for rec in result["recommendations"]:
            if all(k in rec for k in ["name", "url", "test_type"]):
                # Ensure URL is from catalog (basic check)
                if "shl.com" in rec["url"]:
                    valid_recs.append({
                        "name": rec["name"],
                        "url": rec["url"],
                        "test_type": rec["test_type"]
                    })
        result["recommendations"] = valid_recs[:10]  # cap at 10
        return result
    except Exception as e:
        # Fallback: extract reply text and return empty recs
        return {
            "reply": raw if raw else "I encountered an issue. Could you please rephrase your request?",
            "recommendations": [],
            "end_of_conversation": False,
        }'''

new = '''    try:
        result = json.loads(raw)
    except Exception:
        # Try to extract JSON block from response
        match = re.search(r"\\{.*\\}", raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except Exception:
                return {
                    "reply": re.sub(r"\\{.*\\}", "", raw, flags=re.DOTALL).strip() or raw,
                    "recommendations": [],
                    "end_of_conversation": False,
                }
        else:
            return {
                "reply": raw,
                "recommendations": [],
                "end_of_conversation": False,
            }

    # Clean reply: strip embedded JSON if LLM leaks it
    reply_text = result.get("reply", "")
    reply_text = re.sub(r"\\{[\\s\\S]*\\}", "", reply_text).strip()
    result["reply"] = reply_text

    # Validate schema
    if "recommendations" not in result:
        result["recommendations"] = []
    if "end_of_conversation" not in result:
        result["end_of_conversation"] = False

    # Validate each recommendation
    valid_recs = []
    for rec in result.get("recommendations", []):
        if all(k in rec for k in ["name", "url", "test_type"]):
            if "shl.com" in rec["url"]:
                valid_recs.append({
                    "name": rec["name"],
                    "url": rec["url"],
                    "test_type": rec["test_type"]
                })
    result["recommendations"] = valid_recs[:10]
    return result'''

code = code.replace(old, new)
with open("agent.py", "w") as f:
    f.write(code)
print("✓ agent.py patched")
